"""Build a release: read every layer in layers.yaml, standardise it, write Parquet files + manifest.json,
plus the chromosome aliases, the known-loci catalogue, the portal's example inputs (demo/) and a copy of tracks.yaml.
A release holds data only: the tier rules (weights.yaml) belong to snpscore, so changing a weight needs no rebuild."""
from __future__ import annotations

import datetime
import gzip
import hashlib
import itertools
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import yaml

from snpscore import motif
from snpscore.bbi import BBIFile
from snpscore.formats import lit, q

GFF3 = ["chrom", "source", "type", "start", "end", "score", "strand", "phase", "attributes"]

# Each reader returns SQL selecting chrom, start, end (BED coordinates) plus the layer's value columns.


def read_bed(path, layer):
    # `columns` names the fields after chrom, start, end; `keep` picks which go into the release (default: all).
    cols = layer.get("columns", [])
    keep = "".join(f", {q(c)}" for c in layer.get("keep", cols))
    return f"""SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end"{keep}
               FROM read_csv({lit(path)}, header=false, names=[{', '.join(lit(c) for c in ["chrom", "start", "end"] + cols)}],
                             types={{'chrom': 'VARCHAR'}}, delim='\t')"""


def read_tsv(path, layer):
    # Header must include chrom, start, end (BED coordinates); `columns` picks what else to keep.
    extra = "".join(f", {q(c)}" for c in layer.get("columns", []))
    return f"""SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end"{extra}
               FROM read_csv({lit(path)}, header=true, all_varchar=true, delim='\t')"""


def read_aquafaang_peaks(path, layer):
    # Column 4 lists "Condition:State" for each condition where the peak is called.
    # Pivot to one column per condition holding its state (NULL = no peak in that condition).
    return f"""SELECT * FROM (
        PIVOT (
            SELECT chrom, start, "end", summary, split_part(cs, ':', 1) AS condition, split_part(cs, ':', 2) AS state
            FROM (SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end", summary,
                         unnest(string_split(states, ',')) AS cs
                  FROM read_csv({lit(path)}, header=false, all_varchar=true, delim='\t',
                                names=['chrom', 'start', 'end', 'states', 'score', 'strand', 'summary']))
        ) ON condition USING first(state) GROUP BY chrom, start, "end", summary)"""


def read_gff3(path, layer):
    # Rows whose type is in `feature_types`. `fields` keeps GFF3 columns (e.g. type, strand); `attributes` maps column -> key.
    fields = "".join(f", {q(f)}" for f in layer.get("fields", []))
    attrs = "".join(f", url_decode(nullif(regexp_extract(attributes, '(?:^|;){key}=([^;]+)', 1), '')) AS {q(col)}"
                    for col, key in layer.get("attributes", {}).items())
    types = ", ".join(lit(t) for t in layer["feature_types"])
    return f"""SELECT chrom, start::BIGINT - 1 AS start, "end"::BIGINT AS "end"{fields}{attrs}
               FROM read_csv({lit(path)}, header=false, names={GFF3}, all_varchar=true, delim='\t', comment='#')
               WHERE type IN ({types})"""


def read_gff3_regions(path, layer):
    # One class per base from exons, CDS and UTRs: splice regions at internal exon ends, introns = rest of the transcript.
    return flatten(f"""
        WITH f AS (SELECT chrom, type, start::BIGINT - 1 AS start, "end"::BIGINT AS "end",
                          regexp_extract(attributes, 'Parent=transcript:([^;]+)', 1) AS tx
                   FROM read_csv({lit(path)}, header=false, names={GFF3}, all_varchar=true, delim='\t', comment='#')
                   WHERE type IN ('exon', 'CDS', 'five_prime_UTR', 'three_prime_UTR')),
        exons AS (SELECT *, row_number() OVER (PARTITION BY tx ORDER BY start) AS i, count(*) OVER (PARTITION BY tx) AS n
                  FROM f WHERE type = 'exon')
        SELECT chrom, start, "end", type AS class FROM f
        UNION ALL SELECT chrom, greatest(start - 8, 0), start + 3, 'splice_region' FROM exons WHERE i > 1
        UNION ALL SELECT chrom, "end" - 3, "end" + 8, 'splice_region' FROM exons WHERE i < n
        UNION ALL SELECT chrom, min(start), max("end"), 'intron' FROM exons GROUP BY chrom, tx""", layer["classes"])


def read_rna_counts(paths, layer):
    # Gene-level read counts (genes x samples, one file per tissue; sample names contain the tissue as 3rd field).
    # Counts per million per sample, then the mean per tissue: one row per gene, one column per tissue.
    return f"""PIVOT (
        SELECT gene_id, split_part(sample, '_', 3) AS tissue, round(avg(cpm), 2) AS cpm FROM (
            SELECT gene_id, sample, n * 1e6 / sum(n) OVER (PARTITION BY sample) AS cpm FROM (
                UNPIVOT (SELECT * EXCLUDE (gene_name) FROM read_csv({[str(p) for p in paths]}, delim='\t', header=true,
                                                                  union_by_name=true))
                ON COLUMNS(* EXCLUDE (gene_id)) INTO NAME sample VALUE n))
        GROUP BY ALL
    ) ON tissue USING first(cpm)"""


def read_vcf(path, layer):
    # Variant sites as 1-bp intervals; genotypes are ignored.
    return f"""SELECT DISTINCT chrom, pos::BIGINT - 1 AS start, pos::BIGINT AS "end"
               FROM read_csv({lit(path)}, header=false, names=['chrom', 'pos'], all_varchar=true, delim='\t', comment='#')"""


def read_gff3_transcripts(path, layer):
    # Exon, CDS and UTR rows of every transcript, with its gene, biotype and Ensembl_canonical tag: for drawing gene models.
    def attr(key):
        return f"regexp_extract(attributes, '(?:^|;){key}([^;]+)', 1)"
    return f"""
        WITH g AS (SELECT * FROM read_csv({lit(path)}, header=false, names={GFF3}, all_varchar=true, delim='\t', comment='#')),
        tx AS (SELECT {attr('ID=transcript:')} AS transcript_id, {attr('Parent=gene:')} AS gene_id,
                      nullif({attr('biotype=')}, '') AS biotype,
                      regexp_matches(attributes, '(?:^|;)tag=[^;]*Ensembl_canonical') AS canonical
               FROM g WHERE regexp_matches(attributes, '(?:^|;)ID=transcript:')),
        genes AS (SELECT {attr('ID=gene:')} AS gene_id, url_decode(nullif({attr('Name=')}, '')) AS gene_name
                  FROM g WHERE regexp_matches(attributes, '(?:^|;)ID=gene:'))
        SELECT g.chrom, g.start::BIGINT - 1 AS start, g."end"::BIGINT AS "end", tx.transcript_id, tx.gene_id,
               genes.gene_name, g.strand, g.type AS part, try_cast(g.phase AS INTEGER) AS phase, tx.canonical, tx.biotype
        FROM g JOIN tx ON {attr('Parent=transcript:')} = tx.transcript_id LEFT JOIN genes USING (gene_id)
        WHERE g.type IN ('exon', 'CDS', 'five_prime_UTR', 'three_prime_UTR')"""


def read_vcf_info(path, layer):
    # Variant sites (1-bp intervals) with ref, alt and numbers from INFO: `info` maps column -> INFO key (integers where
    # the VCF header says Type=Integer). With several `files`, the first gives the sites and each other adds its own
    # `info` columns where chrom, pos, ref and alt match. rename_chrom: true maps other chromosome names (ssa01,
    # HG993260.1, ...) to 1-29 through the alias table; id_as: <column> keeps the VCF ID (e.g. an array probe name).
    def one(p, info):
        types = info_types(p)
        values = "".join(f", try_cast(regexp_extract(info, '(?:^|;){key}=([^;,]+)', 1) AS {types.get(key, 'DOUBLE')}) "
                         f"AS {q(col)}" for col, key in info.items())
        chrom = "coalesce(a.chrom, v.chrom)" if layer.get("rename_chrom") else "v.chrom"
        alias = "LEFT JOIN chrom_alias a ON a.alias = lower(v.chrom)" if layer.get("rename_chrom") else ""
        probe = f", nullif(id, '.') AS {q(layer['id_as'])}" if layer.get("id_as") else ""
        return f"""SELECT {chrom} AS chrom, pos::BIGINT - 1 AS start, pos::BIGINT AS "end", upper(ref) AS ref,
                          upper(alt) AS alt{probe}{values}
                   FROM read_csv({lit(p)}, header=false, all_varchar=true, delim='\t', comment='#', quote='',
                                 names=['chrom', 'pos', 'id', 'ref', 'alt', 'qual', 'filter', 'info']) v {alias}"""
    paths = path if isinstance(path, list) else [path]
    first, *others = [one(p, src.get("info", layer.get("info"))) for p, src in zip(paths, sources(layer))]
    return f"SELECT * FROM ({first})" + "".join(f' LEFT JOIN ({o}) USING (chrom, start, "end", ref, alt)' for o in others)


def info_types(path):
    """{INFO key: 'BIGINT'} for the Integer keys declared in a (gzipped) VCF's header."""
    types = {}
    with (gzip.open if str(path).endswith(".gz") else open)(path, "rt") as f:
        for line in f:
            if not line.startswith("##"):
                break
            if line.startswith("##INFO=<ID=") and "Type=Integer" in line:
                types[line[11:].split(",")[0]] = "BIGINT"
    return types


def read_nfrasqual(paths, layer):
    # nf-RASQUAL eigenMT tables, one per tissue and assay (files named nfrasqual_<Tissue>_<RNA|ATAC>.txt), one row per
    # feature (gene, or ATAC peak 'Interval_N:chrom:start:end:strand:length' in 1-based coordinates) with its lead SNP
    # (chrom_pos_ref_alt). Leads with BF (eigenMT-adjusted p) below max_bf, grouped per SNP. The FDR column is a copy of
    # pvalue, so it is not read; beta is RASQUAL's pi.
    files = "nfrasqual_([A-Za-z]+)_(RNA|ATAC)"
    return f"""
        WITH t AS (SELECT regexp_extract(filename, {lit(files)}, 1) AS tissue,
                          CASE regexp_extract(filename, {lit(files)}, 2) WHEN 'ATAC' THEN 'ca' ELSE 'e' END AS kind,
                          string_split(snps, '_') AS s, gene, try_cast(BF AS DOUBLE) AS bf, try_cast(beta AS DOUBLE) AS pi
                   FROM read_csv({[str(p) for p in paths]}, delim='\t', header=true, all_varchar=true, filename=true)),
        f AS (SELECT s[1] AS chrom, s[2]::BIGINT AS pos, upper(s[3]) AS ref, upper(s[4]) AS alt, tissue, kind, bf, pi,
                     CASE WHEN starts_with(gene, 'Interval_') THEN split_part(gene, ':', 2) || ':'
                          || (split_part(gene, ':', 3)::BIGINT - 1) || '-' || split_part(gene, ':', 4) ELSE gene END AS feature
              FROM t WHERE bf < {float(layer["max_bf"])})
        SELECT chrom, pos - 1 AS start, pos AS "end", ref, alt, count(*) AS n,
               array_to_string(list_sort(list_distinct(list(tissue))), ',') AS tissues,
               array_to_string(list_sort(list_distinct(list(kind))), ',') AS kinds, min(bf) AS best_bf,
               string_agg(tissue || ' ' || kind || ' ' || feature || ' (BF ' || printf('%.2g', bf) || ', pi '
                          || printf('%.2f', pi) || ')', '; ' ORDER BY bf, tissue, feature) AS features
        FROM f GROUP BY chrom, pos, ref, alt"""


def read_genetic_map(path, layer):
    # Space-separated markers with a header: chromosome column `chrom` (default chr), base-pair column `pos`, and the map
    # positions in `columns` (column -> header). Gives one interval per pair of consecutive markers on a chromosome, from
    # the first marker (start) to the next (end), with each value at both ends (<column>, <column>_next), plus a 1-bp
    # interval ending at the first marker: an `interpolate` interval layer. Past the last marker there is no interval.
    cols = layer["columns"]
    values = ", ".join(f"{q(h)}::DOUBLE AS {q(c)}" for c, h in cols.items())
    pairs = ", ".join(f"{q(c)}, lead({q(c)}) OVER w AS {q(c + '_next')}" for c in cols)
    first = ", ".join(f"arg_min({q(c)}, p), arg_min({q(c)}, p)" for c in cols)
    return f"""
        WITH m AS (SELECT {q(layer.get('chrom', 'chr'))} AS chrom, {q(layer.get('pos', 'pos'))}::BIGINT AS p, {values}
                   FROM read_csv({lit(path)}, delim=' ', header=true, all_varchar=true))
        SELECT * FROM (SELECT chrom, p AS start, lead(p) OVER w AS "end", {pairs}
                       FROM m WINDOW w AS (PARTITION BY chrom ORDER BY p)) WHERE "end" IS NOT NULL
        UNION ALL SELECT chrom, min(p) - 1, min(p), {first} FROM m GROUP BY chrom"""


def read_gene_tsv(path, layer):
    # One row per gene from a TSV with a header: `key` is the gene id column, `columns` maps column -> header.
    # Several values for a gene (e.g. one-to-many orthologs) are sorted and joined with commas.
    values = "".join(f", nullif(array_to_string(list_sort(list_distinct(list(nullif({q(h)}, '')))), ','), '') AS {q(c)}"
                     for c, h in layer["columns"].items())
    key = q(layer["key"])
    return f"""SELECT {key} AS gene_id{values} FROM read_csv({lit(path)}, delim='\t', header=true, all_varchar=true, quote='')
               WHERE {key} LIKE 'ENS%' GROUP BY 1"""


def read_ss4r(path, layer):
    # AQUA-FAANG salmon-trout clades (SalmonTroutOrthologs.tsv): a salmon gene's Ss4R duplicates are the other salmon genes
    # of its clade on the paired chromosome of its syntenic quartet ('((Omy03,Ssa25),(Omy22,Ssa21))': 25 <-> 21), or on
    # any other chromosome when the quartet is unknown. class: AORe or LORe (rediploidisation), from the clade or its neighbours.
    return f"""
        WITH t AS (SELECT subOG AS og, geneID AS gene_id, ltrim(replace(chr, 'Ssa', ''), '0') AS chrom,
                          regexp_extract_all(coalesce(nullif(synteny, 'NA'), nullif(proxiSynteny, 'NA'), ''), 'Ssa0*([0-9]+)', 1) AS quartet,
                          CASE WHEN phylogeny IN ('AORe', 'LORe') THEN phylogeny
                               WHEN proxiPhylogeny IN ('AORe', 'LORe') THEN proxiPhylogeny END AS class
                   FROM read_csv({lit(path)}, delim='\t', header=true, all_varchar=true, quote='') WHERE spc = 'Ssal')
        SELECT a.gene_id,
               nullif(array_to_string(list(b.gene_id ORDER BY b.chrom, b.gene_id) FILTER (WHERE b.gene_id IS NOT NULL), ','), '') AS ohnolog,
               nullif(array_to_string(list(b.chrom ORDER BY b.chrom, b.gene_id) FILTER (WHERE b.gene_id IS NOT NULL), ','), '') AS ohnolog_chrom,
               any_value(a.class) AS class
        FROM t a LEFT JOIN t b ON b.og = a.og AND b.chrom <> a.chrom
             AND (NOT list_contains(a.quartet, a.chrom) OR len(a.quartet) <> 2 OR list_contains(a.quartet, b.chrom))
        GROUP BY a.gene_id"""


def read_synteny(path):
    # salmobase synteny.tsv: one row per Ss4R block pair (chromosome_x, begin_x, end_x, chromosome_y, begin_y, end_y,
    # 1-based, begin may be above end). One row per block side: chrom, start, end (BED), partner (the other chromosome),
    # partner_start, partner_end, pairs (anchor gene pairs), aore and lore (their AORe and LORe counts).
    def side(a, b):
        return f"""SELECT chromosome_{a} AS chrom, least(begin_{a}, end_{a}) - 1 AS start, greatest(begin_{a}, end_{a}) AS "end",
                          chromosome_{b} AS partner, least(begin_{b}, end_{b}) - 1 AS partner_start,
                          greatest(begin_{b}, end_{b}) AS partner_end, number_of_anchorpoints AS pairs,
                          aore_count AS aore, lore_count AS lore FROM s"""
    types = {**{f"chromosome_{a}": "VARCHAR" for a in "xy"}, **{f"{k}_{a}": "BIGINT" for k in ("begin", "end") for a in "xy"},
             **{k: "INTEGER" for k in ("number_of_anchorpoints", "aore_count", "lore_count")}}
    return f"""WITH s AS (SELECT * FROM read_csv({lit(path)}, delim='\t', header=true, types={types}))
               {side('x', 'y')} UNION ALL {side('y', 'x')}"""


def read_bgee(paths):
    # Bgee processed RNA-seq values, one file per study (one row per library and gene; the anatomical entity name is
    # in double quotes). Per gene and entity: libraries, libraries called present, median TPM, studies.
    return f"""SELECT "Gene ID" AS gene_id, trim("Anatomical entity name", '"') AS tissue,
                      count(DISTINCT "Library ID")::INTEGER AS libraries,
                      count(DISTINCT "Library ID") FILTER (WHERE "Detection flag" = 'present')::INTEGER AS present,
                      median(TPM::DOUBLE) AS median_tpm, count(DISTINCT "Experiment ID")::INTEGER AS studies
               FROM read_csv({[str(p) for p in paths]}, delim='\t', header=true, all_varchar=true, quote='')
               GROUP BY 1, 2"""


READERS = {"bed": read_bed, "tsv": read_tsv, "aquafaang_peaks": read_aquafaang_peaks, "gff3": read_gff3,
           "gff3_regions": read_gff3_regions, "vcf": read_vcf, "rna_counts": read_rna_counts,
           "gff3_transcripts": read_gff3_transcripts, "vcf_info": read_vcf_info, "gene_tsv": read_gene_tsv,
           "nfrasqual": read_nfrasqual, "genetic_map": read_genetic_map, "ss4r": read_ss4r}
POSITIONAL = ("interval", "nearest", "count", "point", "features")  # layer types with chrom, start, end
UNIQUE = {"point": ["chrom", "end", "ref", "alt"], "count": ["chrom", "end"], "gene": ["gene_id"]}  # annotate's join keys


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def sources(layer):
    """The (file, url) entries of a layer: its `files` list, or the layer itself."""
    return layer.get("files") or [layer]


def bgee_sources(bgee):
    """The (file, url) entries of the layers.yaml `bgee` block: <dir>/<name> for each of its `files`."""
    return [{"file": f"{bgee['dir']}/{name}", "url": bgee["url"] + name} for name in bgee["files"]] if bgee else []


def flatten(features, classes):
    """Overlapping (chrom, start, end, class) rows -> non-overlapping intervals; the first class in `classes` wins."""
    deltas = ", ".join(f"sum(d) FILTER (WHERE class = {lit(c)}) AS d{i}" for i, c in enumerate(classes))
    depths = ", ".join(f"sum(coalesce(d{i}, 0)) OVER w AS n{i}" for i in range(len(classes)))
    winner = " ".join(f"WHEN n{i} > 0 THEN {lit(c)}" for i, c in enumerate(classes))
    return f"""
        WITH feat AS ({features}),
        ev AS (SELECT chrom, start AS pos, class, 1 AS d FROM feat UNION ALL SELECT chrom, "end", class, -1 FROM feat),
        pts AS (SELECT chrom, pos, {deltas} FROM ev GROUP BY chrom, pos),
        seg AS (SELECT chrom, pos AS start, lead(pos) OVER w AS "end", CASE {winner} END AS class
                FROM (SELECT *, {depths} FROM pts WINDOW w AS (PARTITION BY chrom ORDER BY pos))
                WINDOW w AS (PARTITION BY chrom ORDER BY pos)),
        runs AS (SELECT *, sum(CASE WHEN start = prev_end AND class = prev_class THEN 0 ELSE 1 END) OVER w AS run
                 FROM (SELECT *, lag("end") OVER w AS prev_end, lag(class) OVER w AS prev_class
                       FROM seg WHERE class IS NOT NULL WINDOW w AS (PARTITION BY chrom ORDER BY start))
                 WINDOW w AS (PARTITION BY chrom ORDER BY start))
        SELECT chrom, min(start) AS start, max("end") AS "end", class FROM runs GROUP BY chrom, run, class"""


def fetch(layers_yaml, data_dir):
    """Download every `url` in layers.yaml (layers, genome, aliases, rsid, synteny, bgee) that isn't in data_dir yet. A
    bigBed url with a .bed `file` is converted to BED; a `query` is sent as ?query=... (Ensembl BioMart); a source with
    `sites_only` is streamed through sites_only()."""
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    cfg = load_yaml(layers_yaml)
    genome = cfg.get("genome")
    extra = [{"file": genome["file"] + ext, "url": genome["url"] + ext} for ext in (".fai", ".gzi", "")] if genome else []
    extra += [cfg[k] for k in ("aliases", "synteny") if cfg.get(k)]
    extra += cfg["rsid"]["files"] if cfg.get("rsid") else []
    extra += bgee_sources(cfg.get("bgee"))
    for layer in [s for layer in cfg["layers"] for s in sources(layer)] + extra:
        target = data / layer["file"]
        if layer.get("url") and not target.exists():
            url = layer["url"] + ("?query=" + urllib.parse.quote(layer["query"]) if layer.get("query") else "")
            print(f"downloading {layer['url']} -> {target}", flush=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            if layer.get("sites_only"):
                sites_only(url, part, layer["sites_only"], layer.get("count_gt", False))
            elif url.endswith(".bb") and target.suffix == ".bed":
                with tempfile.NamedTemporaryFile(suffix=".bb") as bb:
                    download(url, Path(bb.name))
                    part.write_text("".join(f"{c}\t{s}\t{e}\t{rest}\n" for c, s, e, rest in BBIFile(bb.name).all_entries()))
            else:
                download(url, part)
            part.rename(target)


def download(url, target):
    # Some hosts (bioRxiv) refuse urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "snpdata (salmobase SNP portal build)"})
    with urllib.request.urlopen(request, timeout=120) as r, open(target, "wb") as out:
        shutil.copyfileobj(r, out, 1 << 20)


GT_INFO = {b"AC": b"Integer", b"AN": b"Integer", b"NS": b"Integer", b"AF": b"Float", b"MAF": b"Float"}


def gt_counts(fmt, samples):
    """{AC, AN, NS, AF, MAF} of one biallelic site from its sample columns: ALT alleles, called alleles, samples with a
    call, ALT and minor allele frequency (None without calls)."""
    gts = samples if fmt == b"GT" else b"\t".join(x.split(b":", 1)[0] for x in samples.split(b"\t"))
    ac, an = gts.count(b"1"), gts.count(b"1") + gts.count(b"0")
    af = ac / an if an else None
    return {b"AC": ac, b"AN": an, b"NS": sum(b"." not in g for g in gts.split(b"\t")),
            b"AF": None if af is None else round(af, 6), b"MAF": None if af is None else round(min(af, 1 - af), 6)}


def sites_only(url, target, keys, count_gt=False):
    """Stream a gzipped VCF from `url` into a gzipped sites-only VCF at `target`: the first 8 columns, with only the INFO
    `keys`, and no sample names. The genotype columns are dropped as the file streams in, so they never reach the disk.
    With count_gt, the AC, AN, NS, AF and MAF among `keys` are counted from the genotypes first (gt_counts), replacing
    any the file has: only these per-site numbers are kept."""
    keys = {k.encode() for k in keys}
    counted = {k for k in GT_INFO if k in keys} if count_gt else set()
    request = urllib.request.Request(url, headers={"User-Agent": "snpdata (salmobase SNP portal build)"})
    with urllib.request.urlopen(request, timeout=120) as r, gzip.GzipFile(fileobj=r) as vcf, \
            gzip.open(target, "wb", compresslevel=6) as out:
        out.write(b"##fileformat=VCFv4.2\n##snpdata=sites only (genotypes dropped) from " + url.encode() + b"\n")
        rest, n = b"", 0
        while True:
            chunk = vcf.read(1 << 24)
            lines = (rest + chunk).split(b"\n")
            rest = lines.pop() if chunk else b""
            kept = []
            for line in lines:
                if line.startswith(b"##"):
                    key = line[11:].split(b",")[0]
                    if line.startswith(b"##INFO=<ID=") and key in keys and key not in counted:
                        kept.append(line)
                elif line.startswith(b"#"):
                    kept += [b"##INFO=<ID=%s,Number=1,Type=%s,Description=\"Counted from the genotypes by snpdata fetch\">"
                             % (k, GT_INFO[k]) for k in sorted(counted)]
                    kept.append(b"\t".join(line.split(b"\t", 8)[:8]))
                elif line:
                    f = line.split(b"\t", 9)
                    info = [kv for kv in f[7].split(b";") if kv.split(b"=")[0] in keys - counted]
                    if counted and len(f) > 9:
                        info += [b"%s=%s" % (k, str(v).encode()) for k, v in gt_counts(f[8], f[9]).items()
                                 if k in counted and v is not None]
                    f[7] = b";".join(info) or b"."
                    kept.append(b"\t".join(f[:8]))
                    n += 1
            out.write(b"".join(x + b"\n" for x in kept))
            if not chunk:
                break
    print(f"  {n:,} sites kept", flush=True)


def hashes(paths):
    """(md5, sha256) of the concatenated files."""
    md5, sha = hashlib.md5(), hashlib.sha256()
    for path in paths:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                md5.update(chunk)
                sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def build(layers_yaml, data_dir, out_dir):
    """Write every layer as Parquet, plus alias.parquet, rsid.parquet, catalog/known_loci.tsv, the track registry
    (tracks.yaml next to layers.yaml) and manifest.json, which records versions, hashes,
    chromosome sizes, provisional rules and where the genome is (local path if present, else its URL) for sequence
    checks."""
    cfg = load_yaml(layers_yaml)
    here, data, out = Path(layers_yaml).parent, Path(data_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        from importlib.metadata import version
        snpscore_version = version("snpscore")  # motif scoring and file readers come from snpscore
    except Exception:  # not installed, e.g. run from a source tree
        snpscore_version = "unknown"
    manifest = {
        "version": out.name,
        "assembly": cfg["assembly"],
        "chromosomes": cfg["chromosomes"],
        "created": datetime.date.today().isoformat(),
        "snpscore_version": snpscore_version,
        "duckdb_version": duckdb.__version__,
        "provisional": cfg.get("provisional", []),
        "layers": [],
    }
    genome = cfg.get("genome")
    if genome:
        local = (data / genome["file"]).resolve()
        manifest["genome"] = {"url": genome["url"], "path": str(local) if local.exists() else None}
    aliases = cfg.get("aliases")
    if aliases and (data / aliases["file"]).exists():  # for layers with rename_chrom
        con.execute(f"CREATE TABLE chrom_alias AS {alias_sql(data / aliases['file'], aliases.get('extra', []))}")
    ends = {}  # chrom -> largest end over the positional layers
    for layer in cfg["layers"]:
        paths = [data / s["file"] for s in sources(layer)]
        if layer["format"] == "motif_effects":  # computed from built layers and the genome; annotate reads the motifs
            shutil.copyfile(paths[0], out / "motif.meme")
            layer = dict(layer, meme="motif.meme")
            tmp = out / ".motif-effects.tsv"
            con.execute(f"CREATE OR REPLACE TABLE layer AS {motif.layer_sql(con, paths[0], layer, out, data / genome['file'], tmp)}")
            tmp.unlink()
        else:
            con.execute(f"CREATE OR REPLACE TABLE layer AS {READERS[layer['format']](paths if 'files' in layer else paths[0], layer)}")
        if layer["type"] == "interval":
            check_no_overlap(con, layer["name"])
        if layer["type"] in UNIQUE:
            check_unique(con, layer["name"], UNIQUE[layer["type"]])
        positional = layer["type"] in POSITIONAL
        parquet = out / f"{layer['name']}.parquet"
        con.execute(f"COPY (SELECT * FROM layer ORDER BY {'chrom, start' if positional else 'gene_id'}) TO {lit(parquet)} "
                    "(FORMAT parquet, COMPRESSION zstd)")  # zstd: about half the size of the default for the 7.6M sites
        if positional:
            for chrom, end in con.execute('SELECT chrom, max("end") FROM layer GROUP BY chrom').fetchall():
                ends[chrom] = max(end, ends.get(chrom, 0))
        md5, sha256 = hashes(paths)
        manifest["layers"].append({
            **{k: v for k, v in layer.items() if k not in ("file", "files", "columns", "query", "info")},
            **({"urls": [s.get("url") for s in layer["files"]]} if "files" in layer else {}),
            "synthetic": bool(layer.get("synthetic", False)),
            "citation": layer.get("citation"),
            "source_file": ", ".join(s["file"] for s in sources(layer)),
            "md5": md5,
            "source_sha256": sha256,
            "file": parquet.name,
            "sha256": hashes([parquet])[1],
            "rows": con.execute("SELECT count(*) FROM layer").fetchone()[0],
            "columns": [r[0] for r in con.execute("DESCRIBE layer").fetchall()][3 if positional else 1:],
        })
        print(f"{layer['name']}: {manifest['layers'][-1]['rows']} rows", flush=True)
    fai = data / (genome["file"] + ".fai") if genome else None
    manifest["chrom_sizes"] = chrom_sizes(fai, ends)

    aliases = cfg.get("aliases")
    if aliases and (data / aliases["file"]).exists():
        rows = build_aliases(con, data / aliases["file"], out / "alias.parquet", aliases.get("extra", []))
        manifest["alias"] = {"file": "alias.parquet", "rows": rows, "source_file": aliases["file"],
                             "url": aliases.get("url"), "sha256": hashes([out / "alias.parquet"])[1]}
    rsid = cfg.get("rsid")
    if rsid and all((data / s["file"]).exists() for s in rsid["files"]):
        paths = [data / s["file"] for s in rsid["files"]]
        manifest["rsid"] = {"file": "rsid.parquet", **build_rsid(con, *paths, out / "rsid.parquet"),
                            "source_file": ", ".join(s["file"] for s in rsid["files"]),
                            "urls": [s.get("url") for s in rsid["files"]], "citation": rsid.get("citation"),
                            "source_sha256": hashes(paths)[1], "sha256": hashes([out / "rsid.parquet"])[1]}
        print(f"rsid: {manifest['rsid']['rows']} rows", flush=True)
    for name, block, sql in (("synteny", cfg.get("synteny"), lambda b: read_synteny(data / b["file"])),
                             ("bgee", cfg.get("bgee"), lambda b: read_bgee([data / s["file"] for s in bgee_sources(b)]))):
        paths = [data / block["file"]] if name == "synteny" and block else [data / s["file"] for s in bgee_sources(block)]
        if not block or not all(p.exists() for p in paths):
            continue  # optional extras for the portal, never annotated
        target = out / f"{name}.parquet"
        con.execute(f"COPY ({sql(block)} ORDER BY 1, 2) TO {lit(target)} (FORMAT parquet, COMPRESSION zstd)")
        manifest[name] = {"file": target.name, "rows": con.execute(f"SELECT count(*) FROM read_parquet({lit(target)})").fetchone()[0],
                          "url": block.get("url"), "citation": block.get("citation"), "source_sha256": hashes(paths)[1],
                          "sha256": hashes([target])[1]}
        print(f"{name}: {manifest[name]['rows']} rows", flush=True)
    catalog = cfg.get("catalog")
    if catalog and (here / catalog["file"]).exists():
        (out / "catalog").mkdir(exist_ok=True)
        target = out / "catalog" / Path(catalog["file"]).name
        shutil.copy(here / catalog["file"], target)
        manifest["catalog"] = {**catalog, "file": f"catalog/{target.name}", "sha256": hashes([target])[1],
                               "rows": sum(1 for line in target.read_text().splitlines()[1:] if line.strip())}
    demo = [here / catalog["file"]] if catalog and (here / catalog["file"]).exists() else []
    demo += [data / f for f in cfg.get("demo", []) if (data / f).is_file()]
    if demo:  # example inputs for the portal (SYNTHETIC ones say so in their name)
        (out / "demo").mkdir(exist_ok=True)
        for src in demo:
            shutil.copy(src, out / "demo" / src.name)
        manifest["demo"] = [{"file": f"demo/{src.name}", "sha256": hashes([src])[1], "synthetic": "SYNTHETIC" in src.name}
                            for src in demo]
    manifest["files"] = {}
    for name in ("tracks.yaml",):
        if (here / name).exists():
            shutil.copy(here / name, out / name)
            manifest["files"][name] = hashes([out / name])[1]
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out


def chrom_sizes(fai, ends):
    """Length of each numbered chromosome (Ssal_v3.1 1-29; scaffolds have accession names): from the genome .fai,
    or the layers' largest end where that is larger or the .fai lacks the chromosome (as in the test fixture)."""
    sizes = dict(ends)
    if fai and fai.exists():
        for line in fai.read_text().splitlines():
            name, length = line.split("\t")[:2]
            sizes[name] = max(int(length), sizes.get(name, 0))
    return {c: sizes[c] for c in sorted(sizes, key=lambda c: int(c) if c.isdigit() else 0) if c.isdigit()}


def build_aliases(con, path, target, extra=()):
    """alias.parquet (alias, chrom, warning): alias_sql written out."""
    con.execute(f"COPY ({alias_sql(path, extra)}) TO {lit(target)} (FORMAT parquet)")
    return con.execute(f"SELECT count(*) FROM read_parquet({lit(target)})").fetchone()[0]


def alias_sql(path, extra=()):
    """(alias, chrom, warning) from salmobase alias_filtered.txt (chrom, RefSeq, GenBank, ssaNN; no header), plus the
    accessions without version, chrN, chrNN and ssaN for the numbered chromosomes, and the `extra` names ({alias, chrom,
    warning}) that annotate accepts with a warning. Aliases are lower case."""
    more = " ".join(f"UNION ALL SELECT lower({lit(e['alias'])}), {lit(e['chrom'])}, {lit(e['warning'])}" for e in extra)
    return f"""
        WITH a AS (SELECT * FROM read_csv({lit(path)}, header=false, delim='\t', all_varchar=true,
                                          names=['chrom', 'refseq', 'genbank', 'name'])),
        n AS (SELECT chrom FROM a WHERE regexp_matches(chrom, '^[0-9]+$'))
        SELECT DISTINCT ON (alias) alias, chrom, warning FROM (
            SELECT lower(unnest([chrom, refseq, genbank, name, regexp_replace(refseq, '\\.[0-9]+$', ''),
                                 regexp_replace(genbank, '\\.[0-9]+$', '')])) AS alias, chrom, NULL::VARCHAR AS warning FROM a
            UNION ALL SELECT unnest(['chr' || chrom, 'chr' || lpad(chrom, 2, '0'), 'ssa' || chrom]), chrom, NULL FROM n
            {more})
        WHERE alias IS NOT NULL ORDER BY alias, warning NULLS FIRST, chrom"""


def build_rsid(con, v31, v2, target):
    """rsid.parquet from the EVA rs release VCFs on Ssal_v3.1 and ICSASG_v2 (CHROM ssa01-ssa29; other sequences left
    out): rs (the number), chrom, pos, ref, alt on Ssal_v3.1 and v2_chrom, v2_pos, v2_ref, v2_alt (NULL when the rs is
    not on exactly one ICSASG_v2 line), sorted by rs. rs IDs on more than one Ssal_v3.1 line are left out.
    Returns {rows, left_out}."""
    for name, path in (("v31", v31), ("v2", v2)):
        with gzip.open(path, "rt") as f:  # the ICSASG_v2 header (115k contig lines) is too long for comment='#'
            skip = sum(1 for _ in itertools.takewhile(lambda line: line.startswith("#"), f))
        con.execute(f"""CREATE OR REPLACE TEMP TABLE {name} AS
            SELECT try_cast(substr(id, 3) AS BIGINT) AS rs, any_value(ltrim(substr(chrom, 4), '0')) AS chrom,
                   any_value(pos) AS pos, any_value(ref) AS ref, any_value(alt) AS alt, count(*) AS lines
            FROM read_csv({lit(path)}, header=false, delim='\t', skip={skip}, quote='', auto_detect=false,
                          columns={{'chrom': 'VARCHAR', 'pos': 'BIGINT', 'id': 'VARCHAR', 'ref': 'VARCHAR',
                                   'alt': 'VARCHAR', 'qual': 'VARCHAR', 'filter': 'VARCHAR', 'info': 'VARCHAR'}})
            WHERE regexp_full_match(chrom, 'ssa[0-9]+') AND regexp_full_match(id, 'rs[0-9]+') GROUP BY 1""")
    con.execute(f"""COPY (SELECT a.rs, a.chrom, a.pos, a.ref, a.alt, b.chrom AS v2_chrom, b.pos AS v2_pos, b.ref AS v2_ref,
                                 b.alt AS v2_alt
                          FROM v31 a LEFT JOIN v2 b ON a.rs = b.rs AND b.lines = 1
                          WHERE a.lines = 1 ORDER BY a.rs) TO {lit(target)} (FORMAT parquet, COMPRESSION zstd)""")
    rows, left_out = con.execute(f"""SELECT (SELECT count(*) FROM read_parquet({lit(target)})),
                                            (SELECT count(*) FROM v31 WHERE lines > 1)""").fetchone()
    con.execute("DROP TABLE v31; DROP TABLE v2")
    return {"rows": rows, "left_out": left_out}


def check_no_overlap(con, name):
    n = con.execute("""
        SELECT count(*) FROM (
            SELECT start, max("end") OVER (PARTITION BY chrom ORDER BY start
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
            FROM layer) WHERE start < prev_end""").fetchone()[0]
    if n:
        raise ValueError(f"layer '{name}' has {n} overlapping intervals; merge them before building")


def check_unique(con, name, key):
    group = ", ".join(q(k) for k in key)
    n = con.execute(f"SELECT count(*) FROM (SELECT 1 FROM layer GROUP BY {group} HAVING count(*) > 1)").fetchone()[0]
    if n:
        raise ValueError(f"layer '{name}' repeats {n} keys ({', '.join(key)}); annotate joins on them, so remove duplicates")
