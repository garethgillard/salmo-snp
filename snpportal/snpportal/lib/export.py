"""Exports (P6.4, P1.4, P6.5): provenance header lines, a methods paragraph with references, vendor submission files
(Illumina-style, Axiom-style, KASP), BED, TSV, Parquet, a zip bundle and a genomic-prediction priors zip (BayesRC
classes, GFBLUP/MultiBLUP SNP sets, LDAK partitions, an annotation matrix). TSV and BED start with '#' provenance lines
(plain=True drops them); a SYNTHETIC line is added whenever synthetic data contributes. Vendor files never hold comment
lines (no vendor accepts them): their provenance goes in a <file>.provenance.txt sidecar and their extra columns (your
ids, TOP/BOT, assay status) in a <file>.lookup.tsv sidecar. Vendor column headers are kept per template version in
TEMPLATES, each 'layout to confirm against the vendor's current template'. Vendor rules: docs/RESEARCH.md section 5."""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

import duckdb
import yaml

from snpscore import assay
from snpscore.annotate import genome_location, write_in_order
from snpscore.fasta import Fasta
from snpscore.formats import InputError, lit, q
from snpscore import score as snp_score
from snpscore.score import preset_conditions

from .panel import _open, _tier_cols, vendor_checks

LAYOUT_NOTE = "layout to confirm against the vendor's current template"
_ILLUMINA = ["Locus_Name", "Target_Type", "Sequence", "Chromosome", "Coordinate", "Genome_Build_Version", "Source",
             "Source_Version", "Sequence_Orientation", "Plus_Minus"]
TEMPLATES = {  # vendor -> template version -> column headers
    "illumina": {
        "designstudio-2026": _ILLUMINA + ["Species", "Force_Infinium_I", "Replication_Count"],  # DesignStudio help, 2026-10-06
        "iselect-2016": _ILLUMINA + ["Force_Infinium_I", "Species"],  # iSelect tech note 370-2007-021-B, Table 4
    },
    "axiom": {"houston-2014": ["SNP_ID", "Chromosome", "Position", "Strand", "Sequence"]},  # 71-mer; Thermo's columns unverified
    "kasp": {"lgc-v10.0": ["SNP ID", "Sequence", "Position"]},  # LGC SNP submission template v10.0, 'SNPs' sheet
    "agena": {"ads-unverified": ["SNP_ID", "Sequence"]},  # I14: Assay Design Suite sequence input; not checked against Agena
    "primer3": {"boulder-io": ["SEQUENCE_ID", "SEQUENCE_TEMPLATE", "SEQUENCE_TARGET"]},  # I14: amplicon and GT-seq panels
}
VENDORS = {  # flank: default bases either side of the SNP and the allowed range; template: default TEMPLATES version
    "illumina": {"flank": 60, "range": (60, 200), "template": "designstudio-2026", "ext": "csv"},  # > 50 bp a side
    "axiom": {"flank": 35, "range": (35, 35), "template": "houston-2014", "ext": "csv"},  # 35 + [A/B] + 35
    "kasp": {"flank": 50, "range": (50, 100), "template": "lgc-v10.0", "ext": "csv"},  # >= 50; up to 100 helps design
    "agena": {"flank": 100, "range": (50, 250), "template": "ads-unverified", "ext": "csv"},  # PROVISIONAL, to confirm
    "primer3": {"flank": 150, "range": (50, 500), "template": "boulder-io", "ext": "txt"},  # room for both primers
}
# Primer3's settings for amplicon panels (GT-seq: short products, one multiplex PCR). PROVISIONAL: the lab's to set;
# written into the file's first record, so the file runs as `primer3_core < file`.
PRIMER3 = {"PRIMER_TASK": "generic", "PRIMER_PICK_LEFT_PRIMER": 1, "PRIMER_PICK_RIGHT_PRIMER": 1,
           "PRIMER_PICK_INTERNAL_OLIGO": 0, "PRIMER_PRODUCT_SIZE_RANGE": "70-120", "PRIMER_NUM_RETURN": 1,
           "PRIMER_MAX_NS_ACCEPTED": 0}
ACCESSIONS = {"Ssal_v3.1": "GenBank GCA_905237065.2, RefSeq GCF_905237065.1"}
LOOKUP = ["locus_name", "id", "chrom", "pos", "ref", "alt", "topbot", "allele_a", "allele_b", "two_probes",
          "assay_status", "assay_reasons", "export_notes"]
FORMATS = ("tsv", "parquet", "bed", *VENDORS, "priors")
REFERENCES = {  # DOIs only where certain; the others are marked 'DOI to add'
    "gerp": "Davydov EV et al. (2010) Identifying a high fraction of the human genome to be under selective constraint "
            "using GERP++. PLoS Comput Biol 6: e1001025. doi:10.1371/journal.pcbi.1001025",
    "wakefield": "Wakefield J (2009) Bayes factors for genome-wide association studies: comparison with P-values. "
                 "Genet Epidemiol 33: 79-86. doi:10.1002/gepi.20359",
}
FLIP = str.maketrans("ACGT", "TGCA")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load(manifest, weights):
    """(manifest dict, weights dict, manifest sha256, weights sha256) from dicts or file paths."""
    m_sha = w_sha = None
    if not isinstance(manifest, dict):
        m_sha, manifest = sha256(manifest), json.loads(Path(manifest).read_text())
    if weights is not None and not isinstance(weights, dict):
        w_sha, weights = sha256(weights), yaml.safe_load(Path(weights).read_text())
    return manifest, weights or {}, m_sha, w_sha


def is_synthetic(manifest, meta=None):
    return bool((meta or {}).get("synthetic")) or any(l.get("synthetic") for l in manifest.get("layers", []))


def installed():
    """{name: version} of the installed salmo-snp, snpscore and DuckDB (I4: every export names them)."""
    from importlib.metadata import PackageNotFoundError, version
    out = {}
    for name in ("salmo-snp", "snpscore"):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "unknown"
    return {**out, "duckdb": duckdb.__version__}


def provenance(manifest, weights, meta=None):
    """'# ' header lines: release, hashes, versions, preset and filters, PROVISIONAL rules, a SYNTHETIC line when
    synthetic data contributes, the UTC time and the equivalent snpscore command. `manifest` and `weights` are dicts
    or file paths (then their sha256 is computed). meta (all optional): tool, preset, filters {name: value}, panel
    (hash), synthetic, input_sha256, created_utc, manifest_sha256, weights_sha256, command, vendor (adds the layout
    note). Never includes SNPs or file names."""
    manifest, weights, m_sha, w_sha = _load(manifest, weights)
    meta = meta or {}
    preset = meta.get("preset", "all")
    conditions = ", ".join((weights.get("presets") or {}).get(preset) or []) or "all conditions"
    filters = ", ".join(f"{k}={v}" for k, v in (meta.get("filters") or {}).items()) or "none"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"{meta.get('tool', 'snpscore')} export, {now}",
        f"release {manifest.get('version')} ({manifest.get('assembly')}, built {manifest.get('created')}); "
        f"manifest sha256 {meta.get('manifest_sha256') or m_sha or 'n/a'}; weights sha256 {meta.get('weights_sha256') or w_sha or 'n/a'}",
        "installed " + ", ".join(f"{k} {v}" for k, v in installed().items())
        + f"; release built with snpscore {manifest.get('snpscore_version')}, duckdb {manifest.get('duckdb_version')}"
        + (f"; job created {meta['created_utc']}" if meta.get("created_utc") else "")
        + (f"; input sha256 {meta['input_sha256']}" if meta.get("input_sha256") else ""),
        f"preset {preset} ({conditions}); filters: {filters}" + (f"; panel {meta['panel']}" if meta.get("panel") else "")
        + (f" ({meta['panel_params']})" if meta.get("panel_params") else ""),
        "PROVISIONAL rules (prototype values, under review): " + ", ".join((manifest.get("provisional") or []) + (weights.get("provisional") or []) or ["tiers"]),
    ]
    if meta.get("vendor"):
        lines.append(f"{meta['vendor']} submission file: {LAYOUT_NOTE}")
    if is_synthetic(manifest, meta):
        lines.append("SYNTHETIC: built from synthetic test data, not real results")
    lines.append("equivalent command: " + meta.get("command", f"snpscore annotate <your list> --release "
                                                              f"<release {manifest.get('version')}> --trait {preset}"))
    return ["# " + line for line in lines]


def methods_text(manifest, weights, preset="all", release_dir=None, finemap=None):
    """Paste-ready methods paragraphs (annotation layers, tiers, assay QC; with `finemap`, the GWAS settings used as
    gwas.settings() returns them and gwas.json 'finemap' records them, a loci and fine-mapping paragraph) and the
    references: layer citations (each '; '-separated part once, 'DOI to add' where it has no doi:), GERP++, Wakefield
    2009 (with `finemap`) and the DOIs of the known-loci catalogue (read from release_dir when given). PROVISIONAL
    rules are named as such."""
    manifest, weights, _, _ = _load(manifest, weights)
    layers = [l for l in manifest.get("layers", []) if l.get("type") != "features"]
    syn = [l["name"] for l in layers if l.get("synthetic")]
    text = [
        f"SNPs were annotated with snpscore {manifest.get('snpscore_version')} (DuckDB {manifest.get('duckdb_version')}) "
        f"against release {manifest.get('version')} of the salmobase functional SNP annotation (assembly "
        f"{manifest.get('assembly')}, built {manifest.get('created')}). Annotation layers: "
        + "; ".join(f"{l['name']}: {l.get('description', '').rstrip('.')}" for l in layers) + "."
        + (f" Layers {', '.join(syn)} are SYNTHETIC stand-ins and did not count towards tiers." if syn else ""),
    ]
    if weights.get("weights"):
        w, presets = weights["weights"], weights.get("presets") or {}
        conds = ", ".join(presets.get(preset) or [])
        some = bool(conds) and preset != "all"  # a subset of the conditions; else all of them, so nothing is active elsewhere
        text.append(
            "Each SNP was given a functional tier (1 best to 4) "
            + (f"for the '{preset}' preset ({conds})" if some else "counting all AQUA-FAANG conditions") + ". tier_score adds "
            f"the weights of the evidence it has: an active chromatin state ({', '.join(weights.get('active_states', []))}) "
            + (f"in a preset condition ({w.get('active')}), active only in other conditions ({w.get('active_elsewhere')}), "
               if some else f"in any condition ({w.get('active')}), ")
            + f"a weak state ({w.get('weak')}), a CDS change to the protein or of unknown effect ({w.get('coding')}), a "
            f"synonymous CDS change ({w.get('synonymous', w.get('coding'))}), splice region ({w.get('splice')}), UTR "
            f"({w.get('utr')}), a GERP constrained element ({w.get('constrained')}) and an Ensembl regulatory feature "
            f"outside AQUA-FAANG peaks ({w.get('regbuild')})"
            + (f", and a transcription factor motif changed inside a robust ATAC peak ({w['motif']}: one allele matches a "
               "JASPAR 2024 vertebrate motif at p < 1e-5 and the other does not, at least 4 bits apart)" if w.get("motif") else "")
            + "; tiers 1-3 need a score of at least "
            f"{', '.join(str(t) for t in weights.get('tiers', []))}. These rules are PROVISIONAL.")
    models = next((l for l in manifest.get("layers", []) if l.get("format") == "gff3_transcripts"), None)
    if models and manifest.get("genome"):
        text.append(
            f"Coding consequences (Sequence Ontology terms as Ensembl VEP writes them, with HGVS protein changes) were "
            f"computed from the genome sequence on one transcript per SNP ({models.get('citation') or models['name']}; "
            f"the canonical transcript, else the longest CDS), after turning swapped or strand-flipped alleles to the "
            f"reference; splice donor and acceptor sites are the two intronic bases at internal exon ends.")
    a = assay.rules(weights)
    by_base = ", ".join(f"{b} > {n}" for b, n in sorted((a.get("homopolymer_by_base") or {}).items()))
    text.append(
        f"Assay designability was checked on {a['flank']} bp flanks either side of each SNP from the soft-masked "
        f"{manifest.get('assembly')} genome, with neighbouring public variants written as IUPAC codes. SNPs failed on "
        f"{' or '.join(assay.REF_CHECK.get(c, c) for c in a['fail_ref_check'])} or any N in the flanks, and were flagged (warn) for GC "
        f"outside {a['gc'][0]}-{a['gc'][1]}, a soft-masked share above {a['max_repeat']}, a single-base run longer "
        f"than {a['max_homopolymer']}" + (f" (or runs by base: {by_base})" if by_base else "") + ", more than "
        f"{a['max_flank_variants']} public variants " + ("on both sides of the SNP (one clean flank is enough)"
                                                          if a.get("flank_variants_per_side") else "in the two flanks")
        + f", an A/T or C/G SNP whose Illumina TOP/BOT strand cannot be determined from the flanks, or "
        f"{', '.join(a['warn_flags'])}. These thresholds are PROVISIONAL, to confirm with the genotyping provider.")
    if finemap:
        f = finemap
        text.append(
            f"GWAS summary statistics were turned to the {manifest.get('assembly')} reference alleles, and loci formed "
            f"by greedy distance clumping: the strongest SNP with p < {f['suggestive']:g} leads a locus of all SNPs within "
            f"{f['window'] / 1000:g} kb (genome-wide significance p < {f['significant']:g}). Each locus was fine-mapped "
            f"with Wakefield's approximate Bayes factors (Wakefield 2009), assuming one causal variant per locus and "
            f"using no LD reference: V = (se / trait SD)^2, or 1 / (2 N af (1 - af)) without se, with trait SD "
            f"{f['trait_sd']:g}" + (f" ({f['trait_sd_source']})" if f.get("trait_sd_source") else "")
            + f", and prior variance W = {f['prior_sd']:g}^2 = {f['prior_sd'] ** 2:g}. Posterior inclusion "
            f"probabilities were computed under a uniform prior and a functional prior proportional to "
            f"exp({f['functional_lambda']:g} x tier_score), with {f['coverage']:.0%} credible sets. These settings are "
            "PROVISIONAL.")
    parts = {p.strip() for l in layers if l.get("citation") for p in l["citation"].split("; ")}
    refs = [REFERENCES["gerp"] if p.startswith("Ensembl Compara") and "GERP" in p else p if "doi:" in p
            else f"{p} (DOI to add)" for p in parts]
    refs = sorted(set(refs) | ({REFERENCES["gerp"]} if any(l["name"] == "gerp" for l in layers) else set())
                  | ({REFERENCES["wakefield"]} if finemap else set()))
    catalog = Path(release_dir) / manifest["catalog"]["file"] if release_dir and manifest.get("catalog") else None
    if catalog and catalog.exists():
        rows = list(csv.DictReader(io.StringIO(catalog.read_text()), delimiter="\t"))
        dois = sorted({d.strip() for r in rows for d in (r.get("source") or "").split(";") if d.strip()})
        refs += [f"Known loci ({', '.join(sorted({r['locus'] for r in rows}))}): " + "; ".join(f"doi:{d}" for d in dois)]
    return "\n\n".join(text) + "\n\nReferences\n" + "\n".join(f"- {r}" for r in refs) + "\n"


def top_bot(a1, a2, left, right):
    """Illumina strand designation of a SNP as given (alleles a1/a2 and its flanks on that strand): ('TOP' | 'BOT' |
    None, allele A, allele B). A/C and A/G are TOP, T/C and T/G are BOT; for A/T and C/G the flanks are walked outwards
    pair by pair (n-1/n+1, n-2/n+2, ...) to the first pair with one A/T and one C/G base: TOP when the 5' base is A or T,
    BOT when it is C or G (IUPAC codes and N are skipped). Allele A is A (or C) on TOP and T (or G) on BOT. None when
    the flanks run out (Illumina code 103, 'TOP/BOT strand cannot be determined') or a1/a2 is not a SNP."""
    pair = {a1.upper(), a2.upper()}
    if len(pair) != 2 or not pair <= set("ACGT"):
        return None, a1, a2
    if pair in ({"A", "T"}, {"C", "G"}):
        strand = None
        for five, three in zip(reversed(left.upper()), right.upper()):
            if five in "AT" and three in "CG":
                strand = "TOP"
            elif five in "CG" and three in "AT":
                strand = "BOT"
            if strand:
                break
        if not strand:
            return None, a1, a2
    else:
        strand = "TOP" if "A" in pair else "BOT"
    a = ("A" if "A" in pair else "C") if strand == "TOP" else ("T" if "T" in pair else "G")
    return strand, a, (pair - {a}).pop()


def locus_name(chrom, pos, placed):
    """Vendor-safe marker name Ssa<chromosome>p<position>, e.g. Ssa25p28996360: letters and digits only, at most 15
    characters, never starting with rs or cg (Illumina, Axiom and KASP all accept it). Chromosome 0 = unplaced."""
    return f"Ssa{chrom if chrom in placed else 0}p{int(pos)}"


def _placed(manifest):
    """The chromosome names vendors accept (1-29: manifest chrom_sizes); anything else is written as chromosome 0."""
    return set(manifest.get("chrom_sizes") or ()) or {str(i) for i in range(1, 30)}


def vendor_rows(fmt, recs, manifest, template=None):
    """(header, rows) of a vendor file from records (see records()) in the columns of TEMPLATES[fmt][template]
    (default VENDORS[fmt]['template']). Sequence = left + [REF/ALT] + right on the forward strand. Illumina:
    Genome_Build_Version 0 (a number is asked for; the assembly goes in the provenance sidecar), Chromosome and
    Coordinate 0 off chromosomes 1-29 (contig names are rejected), Species Other, Force_Infinium_I FALSE."""
    columns, placed = TEMPLATES[fmt][template or VENDORS[fmt]["template"]], _placed(manifest)
    version = str(manifest.get("version") or "")
    rows = []
    for r in recs:
        on = r["chrom"] in placed
        v = {"Locus_Name": r["locus_name"], "SNP_ID": r["locus_name"], "SNP ID": r["locus_name"], "Target_Type": "SNP",
             "Sequence": f"{r['left']}[{r['ref']}/{r['alt']}]{r['right']}", "Strand": "+",
             "Chromosome": r["chrom"] if on or fmt != "illumina" else "0", "Coordinate": r["pos"] if on else 0,
             "Position": f"{r['chrom']}:{r['pos']}" if fmt == "kasp" else r["pos"], "Genome_Build_Version": 0,
             "Source": "snpscore", "Source_Version": version if re.fullmatch(r"[0-9]+(\.[0-9]+)*", version) else 0,
             "Sequence_Orientation": "Forward", "Plus_Minus": "Plus", "Species": "Other", "Force_Infinium_I": "FALSE",
             "Replication_Count": 1}
        rows.append([v[c] for c in columns])
    return columns, rows


def records(con, rel, columns, fmt, release, manifest, include_failed=False, flank=None):
    """Vendor records of the SNPs in `rel` (with _row), in input order: {locus_name (made unique with v2, v3,
    ...), id, chrom, pos, ref, alt (forward strand: complemented when ref_check says strand_flip; the public alleles
    when the input has none), left, right (`flank` bases, default VENDORS[fmt]['flank'], upper case, neighbouring
    public variants as IUPAC codes, N for indels), topbot, allele_a, allele_b, two_probes, assay_status,
    assay_reasons, export_notes}. Left out: SNPs without known biallelic SNP alleles or a full flank (chromosome end,
    Illumina code 101), and unless include_failed (then kept, noted in export_notes) assay fail and not_checked SNPs
    and, for Illumina, SNPs whose TOP/BOT strand cannot be determined (code 103). Returns (records, {reason: n})."""
    location = genome_location(manifest)
    if not location:
        raise InputError("Vendor exports need the genome sequence, which this release does not have.")
    flank = int(flank or VENDORS[fmt]["flank"])
    col = lambda c: q(c) if c in columns else "NULL"  # noqa: E731
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _export AS SELECT _row AS idx, chrom, pos, {col('id')}::VARCHAR AS id,
                    upper({col('ref')}::VARCHAR) AS ref, upper({col('alt')}::VARCHAR) AS alt,
                    {col('ref_check')}::VARCHAR AS ref_check, {col('assay_status')}::VARCHAR AS assay_status,
                    {col('assay_reasons')}::VARCHAR AS assay_reasons FROM {rel}""")
    point = next((l for l in manifest["layers"] if l["name"] == "public_af"), None)  # public sites with alleles
    flanks = assay.read_flanks(con, Fasta(location), "_export", flank, point and Path(release) / point["file"])
    out, skipped, seen, placed = [], {}, {}, _placed(manifest)
    for idx, chrom, pos, ident, ref, alt, check, status, reasons in con.execute(
            "SELECT * FROM _export ORDER BY idx").fetchall():
        name = locus_name(chrom, pos, placed)
        seen[name] = seen.get(name, 0) + 1
        name += f"v{seen[name]}" if seen[name] > 1 else ""
        why, notes = None, []
        if status in ("fail", "not_checked"):
            why = f"assay {status}"
        if idx not in flanks or not flanks[idx][1]:
            why = "not in the genome"
        else:
            left, base, right, li, ri, pub = flanks[idx]
            if not ref and pub:
                ref, alt = pub.split("/")[:2]
            if not ref or not alt or len(ref) != 1 or len(alt) != 1 or not {ref, alt} <= set("ACGT"):
                why = "not a biallelic SNP with known alleles"
            elif min(len(left), len(right)) < flank:
                why = f"flank shorter than {flank} bp (chromosome end)"
            elif check == "strand_flip":
                ref, alt = ref.translate(FLIP), alt.translate(FLIP)
        if why and (not include_failed or not why.startswith("assay")):
            skipped[why] = skipped.get(why, 0) + 1
            continue
        li, ri = li.upper(), ri.upper()
        strand, a, b = top_bot(ref, alt, li, ri)
        notes += [why] if why else []
        if not strand:
            if fmt == "illumina" and not include_failed:
                skipped[assay.TOPBOT_103] = skipped.get(assay.TOPBOT_103, 0) + 1
                continue
            notes.append(assay.TOPBOT_103)
        if "N" in li + ri:
            notes.append(f"N in the {flank} bp flanks")
        out.append(dict(locus_name=name, id=ident, chrom=chrom, pos=pos, ref=ref, alt=alt, left=li, right=ri, topbot=strand,
                        allele_a=a if strand else None, allele_b=b if strand else None,
                        two_probes="yes" if {ref, alt} in ({"A", "T"}, {"C", "G"}) else "no", assay_status=status,
                        assay_reasons=reasons, export_notes="; ".join(notes) or None))
    return out, skipped


def primer3_input(recs, out):
    """Primer3 Boulder-IO input (I14: amplicon and GT-seq panels) for vendor records: one record per SNP, the
    template its flanks with the reference base (public variants and anything not A, C, G or T as N, so primers avoid
    them), the SNP as the target (0-based start, 1 bp), PRIMER3's settings in the first record. SNPs whose largest
    product could reach another SNP's are noted in export_notes (the lookup), for the multiplex. Returns the records."""
    largest = int(str(PRIMER3["PRIMER_PRODUCT_SIZE_RANGE"]).split("-")[-1])
    ordered = sorted(recs, key=lambda r: (r["chrom"], r["pos"]))
    for a, b in zip(ordered, ordered[1:]):
        if a["chrom"] == b["chrom"] and b["pos"] - a["pos"] < largest:
            for x, y in ((a, b), (b, a)):
                x["export_notes"] = "; ".join(filter(None, [x["export_notes"], f"amplicon may overlap {y['locus_name']}"]))
    clean = lambda seq: "".join(c if c in "ACGT" else "N" for c in seq)  # noqa: E731
    with open(out, "w", newline="\n") as f:
        for i, r in enumerate(recs):
            tags = {**(PRIMER3 if i == 0 else {}), "SEQUENCE_ID": r["locus_name"],
                    "SEQUENCE_TEMPLATE": clean(r["left"]) + r["ref"] + clean(r["right"]), "SEQUENCE_TARGET": f"{len(r['left'])},1"}
            f.write("".join(f"{k}={v}\n" for k, v in tags.items()) + "=\n")
    return recs


def vendor_notes(fmt, template, flank, manifest, written, skipped, warnings, name):
    """The vendor-specific lines of a vendor file's provenance sidecar (without '# ')."""
    template = template or VENDORS[fmt]["template"]
    assembly = manifest.get("assembly")
    lines = [
        f"{name}: {fmt} submission file, {written} SNPs, template {template} (columns: "
        f"{', '.join(TEMPLATES[fmt][template])}); {LAYOUT_NOTE}",
        "The vendor file has no comment lines (no vendor accepts them): this file is its provenance, and "
        f"{name}.lookup.tsv maps each locus name to your id, position, alleles, TOP/BOT strand and assay status",
        f"Sequence: {flank} bp + [REF/ALT] + {flank} bp on the forward (+) strand of {assembly} "
        f"({ACCESSIONS.get(assembly, 'accession to add')}), upper case (the genome's soft-masked repeats are not "
        "marked); neighbouring public variants (504-fish panel) as upper-case IUPAC codes, N for indels",
        "Locus names: Ssa<chromosome>p<position> (letters and digits, at most 20 characters, unique: v2, v3 for a "
        "repeated position); chromosome 0 = not on chromosomes 1-29",
    ]
    if fmt == "illumina":
        lines.append(f"Genome_Build_Version 0: Illumina asks for a version number or 0; the assembly is {assembly}. "
                     "Chromosome 0 and Coordinate 0 off chromosomes 1-29 (Illumina rejects contig names). Source "
                     "snpscore, Source_Version the release when it is a number (else 0), Species Other, "
                     "Force_Infinium_I FALSE, Sequence_Orientation Forward, Plus_Minus Plus")
    if fmt == "kasp":
        lines.append("Paste the rows into the 'SNPs' sheet of LGC's SNP submission template (an Excel workbook)")
    if fmt == "agena":
        lines.append("Agena MassARRAY: SNP_ID and Sequence for Agena's Assay Design Suite. The layout is not yet checked "
                     "against Agena's own template (PROVISIONAL): confirm it with Agena or the lab before ordering")
    if fmt == "primer3":
        lines.append("Primer3 input (Boulder-IO): run `primer3_core < file`; the first record sets "
                     + ", ".join(f"{k}={v}" for k, v in PRIMER3.items())
                     + " (PROVISIONAL: the lab's to set). The SNP is the target, so both primers flank it; neighbouring "
                     "public variants are N, which primers avoid (PRIMER_MAX_NS_ACCEPTED=0). The lookup notes SNPs "
                     "whose amplicons may overlap in one multiplex")
    lines += [f"left out: {n} ({why})" for why, n in sorted(skipped.items())]
    lines += [f"warning: {w}" for w in warnings]
    return lines


def filename(fmt, release, preset="all", tag=None, synthetic=False):
    """snpscore[_SYNTHETIC]_<release>_<preset>[_<tag>][_<vendor> | _priors].<ext>, e.g.
    snpscore_dev_maturation_illumina.csv (SYNTHETIC labels files built from synthetic data, which vendor files can't
    say inside)."""
    ext = VENDORS[fmt]["ext"] if fmt in VENDORS else "zip" if fmt in ("bundle", "priors") else fmt
    parts = (["snpscore"] + (["SYNTHETIC"] if synthetic else []) + [release, preset] + ([tag] if tag else [])
             + ([fmt] if fmt in VENDORS or fmt == "priors" else []))
    return "_".join(re.sub(r"[^A-Za-z0-9.-]", "-", str(p)) for p in parts) + "." + ext


def export(source, fmt, out, release_dir, preset="all", meta=None, include_failed=False, plain=False, table="v",
           manifest=None, weights=None, flank=None, template=None, sidecars=True):
    """Write SNPs (annotate output: a parquet/TSV path, or a DuckDB connection with `table`) as `fmt`: tsv, parquet,
    bed, illumina, axiom, kasp or priors (a zip: see priors()). manifest and weights default to the release's (pass a
    job's snapshots instead). Vendor formats take `flank` (within VENDORS[fmt]['range']) and `template` (a
    TEMPLATES[fmt] version), and with `sidecars` also write <out>.provenance.txt and <out>.lookup.tsv next to `out`
    (plain drops the lookup's '#' lines). Returns {'rows': written, 'skipped': {reason: n}, 'warnings': [panel-level
    vendor checks], 'files': [names]}."""
    if fmt not in FORMATS:
        raise InputError(f"Unknown export format '{fmt}'. Choose from: {', '.join(FORMATS)}")
    if fmt == "priors":
        return priors(source, out, release_dir, preset, meta, table=table, manifest=manifest, weights=weights)
    if fmt in VENDORS:
        lo, hi = VENDORS[fmt]["range"]
        if flank is not None and not lo <= int(flank) <= hi:
            raise InputError(f"{fmt} flanks must be {lo}-{hi} bp either side" if lo < hi else f"{fmt} flanks are {lo} bp")
        if template is not None and template not in TEMPLATES[fmt]:
            raise InputError(f"Unknown {fmt} template '{template}'. Choose from: {', '.join(TEMPLATES[fmt])}")
    release, out = Path(release_dir).resolve(), Path(out).resolve()
    manifest = manifest or release / "manifest.json"
    weights = weights or snp_score.WEIGHTS
    meta = {"preset": preset, **(meta or {}), **({"vendor": fmt} if fmt in VENDORS else {})}
    header = [] if plain else provenance(manifest, weights, meta)
    m, w = _load(manifest, weights)[:2]
    synthetic = [l["name"] for l in m.get("layers", []) if l.get("synthetic")]
    con, rel, columns = _open(source, table, [release], out, preset, w, synthetic)
    hide = ", ".join(c for c in ("_row", "file_row_number") if c == "_row" or c in columns)
    ordered = isinstance(source, (str, Path))  # a file is read in order; a view may not be (a join)
    if fmt in ("tsv", "parquet"):  # I19: the SNPs' positions on the assemblies the release converts to (fSalSal1)
        for name, entry in sorted((m.get("liftover") or {}).items()):
            if entry and entry.get("direction") == "to" and (release / entry["file"]).exists():
                from snpscore.liftover import positions
                rel, ordered = positions(con, rel, release / entry["file"], entry.get("label", name), out=f"_to_{name}"), False
    body = out.with_name(out.name + ".part")
    try:
        if fmt == "parquet":
            kv = "" if plain else f", KV_METADATA {{provenance: {lit(chr(10).join(header))}}}"
            _copy(con, rel, hide, out, f"FORMAT parquet{kv}", ordered)
            return {"rows": con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0], "skipped": {}, "warnings": [],
                    "files": [out.name]}
        if fmt in ("tsv", "bed"):
            if fmt == "tsv":
                _copy(con, rel, hide, body, "HEADER true, DELIMITER '\t'", ordered)
            else:
                name = q("id") if "id" in columns else "chrom || ':' || pos"
                con.execute(f"""COPY (SELECT chrom, pos - 1 AS start, pos AS "end", {name} AS name FROM {rel} ORDER BY _row)
                                TO {lit(body)} (HEADER false, DELIMITER '\t')""")
            n = con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0]
            with open(out, "w") as f, open(body) as b:
                f.write("".join(line + "\n" for line in header))
                for chunk in iter(lambda: b.read(1 << 20), ""):
                    f.write(chunk)
            return {"rows": n, "skipped": {}, "warnings": [], "files": [out.name]}
    finally:  # also DuckDB's own temp file of a COPY that failed (it writes tmp_<name> when <name> exists)
        for path in (body, out.with_name("tmp_" + out.name), body.with_name("tmp_" + body.name)):
            path.unlink(missing_ok=True)
    recs, skipped = records(con, rel, columns, fmt, release, m, include_failed, flank)
    if fmt == "primer3":
        rows = primer3_input(recs, out)
    else:
        head, rows = vendor_rows(fmt, recs, m, template)
        with open(out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(head)
            writer.writerows(rows)
    warnings = vendor_checks([(r["chrom"], r["pos"], r["ref"], r["alt"]) for r in recs])["warnings"]
    files = [out.name]
    if sidecars:
        notes = vendor_notes(fmt, template, flank or VENDORS[fmt]["flank"], m, len(rows), skipped, warnings, out.name)
        side = out.with_name(out.name + ".provenance.txt")
        side.write_text("".join(line + "\n" for line in provenance(manifest, weights, meta) + ["# " + n for n in notes]))
        with open(out.with_name(out.name + ".lookup.tsv"), "w", newline="") as f:
            f.write("".join(line + "\n" for line in header))
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(LOOKUP)
            writer.writerows([r[c] for c in LOOKUP] for r in recs)
        files += [side.name, out.name + ".lookup.tsv"]
    return {"rows": len(rows), "skipped": skipped, "warnings": warnings, "files": files}


def _copy(con, rel, hide, out, options, ordered):
    """COPY `rel` without the `hide` columns to `out` in _row order: as read when `ordered`, else sorted in _row ranges
    (annotate.write_in_order), as one ORDER BY over a wide 1.6M-row result runs out of memory at 2 GB."""
    if ordered:
        con.execute(f"COPY (SELECT * EXCLUDE ({hide}) FROM {rel}) TO {lit(out)} ({options})")
    else:
        write_in_order(con, out, rel, "_row", hide, options)


def bundle_zip(out, source, release_dir, preset="all", meta=None, formats=("tsv", "illumina", "axiom", "kasp", "bed"),
               svgs=None, include_failed=False, table="v", manifest=None, weights=None):
    """A zip with the exports in `formats` (vendor files with their .provenance.txt and .lookup.tsv sidecars),
    manifest.json, weights.yaml, methods.txt (with the fine-mapping paragraph when meta has 'finemap', the GWAS
    settings used), provenance.txt, README.txt and the figure SVGs ({name: svg text}). File names carry SYNTHETIC when
    synthetic data contributes. Returns the zip path."""
    release, out = Path(release_dir).resolve(), Path(out).resolve()
    manifest = manifest or release / "manifest.json"
    weights = weights or snp_score.WEIGHTS
    m, w, _, _ = _load(manifest, weights)
    header = provenance(manifest, weights, {"preset": preset, **(meta or {})})
    synthetic = is_synthetic(m, meta)
    written, notes, warnings = [], [], []
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".bundle-") as tmp:
        for fmt in formats:
            name = filename(fmt, m.get("version"), preset, (meta or {}).get("panel"), synthetic)
            try:
                stats = export(source, fmt, Path(tmp) / name, release, preset, meta, include_failed, table=table,
                               manifest=manifest, weights=weights)
            except (InputError, duckdb.Error) as e:
                notes.append(f"{name}: not written ({e if isinstance(e, InputError) else 'error'})")
                continue
            written += stats["files"]
            warnings += [x for x in stats["warnings"] if x not in warnings]
            notes.append(f"{name}: {stats['rows']} SNPs" + "".join(f"; {n} left out ({why})" for why, n in stats["skipped"].items()))
        readme = [
            "salmobase functional SNP portal / snpscore export bundle", "",
            "Files:", *[f"  {n}" for n in notes],
            "  manifest.json, weights.yaml: the release manifest and the tier, assay and panel rules used",
            "  methods.txt: a methods paragraph with references; provenance.txt: how these files were made",
            *(["  figures/*.svg: the dashboard figures"] if svgs else []), "",
            f"Vendor files (illumina, axiom, kasp): {LAYOUT_NOTE}. They hold no comment lines: <file>.provenance.txt "
            "says how each was made, and <file>.lookup.tsv maps its locus names (Ssa<chromosome>p<position>) to your "
            "ids, alleles, TOP/BOT strand and assay status.",
            *[f"Warning: {x}" for x in warnings],
            "Tier rules, assay thresholds and panel defaults are PROVISIONAL (prototype values, under review).",
        ]
        if synthetic:
            readme += ["", "SYNTHETIC: these files were built from synthetic test data and are not real results."]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in written:
                z.write(Path(tmp) / name, name)
            z.writestr("manifest.json", json.dumps(m, indent=2))
            z.writestr("weights.yaml", yaml.safe_dump(w, sort_keys=False) if isinstance(weights, dict) or not weights
                       else Path(weights).read_text())
            z.writestr("methods.txt", methods_text(m, w, preset, release, (meta or {}).get("finemap")))
            z.writestr("provenance.txt", "\n".join(header) + "\n")
            z.writestr("README.txt", "\n".join(readme) + "\n")
            for name, svg in (svgs or {}).items():
                z.writestr(f"figures/{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.svg", svg)
    return out


# ---- P6.5 genomic-prediction priors ----

PRIOR_ORDER = ["tier1_2", "active", "coding", "constrained", "regulatory"]  # PROVISIONAL: weights.yaml 'priors: order'
NONSYNONYMOUS = ("missense_variant", "stop_gained", "stop_lost", "start_lost")  # coding_consequence (P4.5) for 'coding'
PRIOR_REFERENCES = [  # DOIs checked in PubMed, 2026-10-07
    "Edwards SM et al. (2016) Genomic prediction for quantitative traits is improved by mapping variants to gene "
    "ontology categories in Drosophila melanogaster. Genetics 203: 1871-1883. doi:10.1534/genetics.116.187161",
    "MacLeod IM et al. (2016) Exploiting biological priors and sequence variants enhances QTL discovery and genomic "
    "prediction of complex traits. BMC Genomics 17: 144. doi:10.1186/s12864-016-2443-6",
    "Speed D, Balding DJ (2014) MultiBLUP: improved SNP-based prediction for complex traits. Genome Res 24: 1550-1557. "
    "doi:10.1101/gr.169375.113",
    "Speed D et al. (2012) Improved heritability estimation from genome-wide SNPs. Am J Hum Genet 91: 1011-1021. "
    "doi:10.1016/j.ajhg.2012.10.010",
]


def prior_categories(columns, weights, preset="all", synthetic=(), chosen=None):
    """[(name, SQL condition, definition)] of the genomic-prediction prior categories the annotate `columns` allow, in
    the order of weights.yaml 'priors: order' (PROVISIONAL; default PRIOR_ORDER) and limited to the names in `chosen`:
    tier1_2 (tier 1-2 for the preset), active (an active state in a preset condition), coding (a non-synonymous coding
    consequence when the result has them, else CDS), constrained (GERP element), regulatory (Ensembl regulatory
    feature). Categories from synthetic layers are left out; 'none' (in none of them) is always last."""
    w = weights or {}
    order = list(dict.fromkeys((w.get("priors") or {}).get("order") or PRIOR_ORDER))
    unknown = [str(c) for c in [*order, *(chosen or [])] if c not in PRIOR_ORDER]
    if unknown:
        raise InputError(f"Unknown prior categories: {', '.join(unknown)}. Choose from: {', '.join(PRIOR_ORDER)}")
    tier = _tier_cols(columns, preset)[0]
    states = w.get("active_states") or []
    conds = preset_conditions(w, columns, preset)[0] if w.get("presets") else []
    found = {"tier1_2": (None, f"{tier} <= 2", "functional tier 1 or 2 for the preset"
                         + (f" (tier_score >= {w['tiers'][1]})" if w.get("tiers") else ""))}
    if states and conds:
        where = ", ".join(w["presets"][preset]) or f"any of the {len(conds)} conditions"
        found["active"] = ("chromatin", " OR ".join(f"{q('chromatin_' + c)} IN ({', '.join(map(lit, states))})" for c in conds),
                           f"{' or '.join(states)} in at least one preset condition ({where})")
    if "coding_consequence" in columns:
        found["coding"] = ("region", f"coding_consequence IN ({', '.join(map(lit, NONSYNONYMOUS))})",
                           "a non-synonymous coding SNP (missense, stop gained, stop lost or start lost; not SNPs whose "
                           "alleles are unknown)")
    elif "region_class" in columns:
        found["coding"] = ("region", "region_class = 'CDS'", "in a CDS (amino-acid effect not computed)")
    if "gerp" in columns:
        found["constrained"] = ("gerp", "gerp", "in a GERP constrained element")
    if "regbuild" in columns:
        found["regulatory"] = ("regbuild", "regbuild", "in an Ensembl regulatory feature (with or without an AQUA-FAANG peak)")
    out = [(c, f"coalesce(({found[c][1]}), false)", found[c][2]) for c in order
           if c in found and found[c][0] not in synthetic and (chosen is None or c in chosen)]
    return out + [("none", " AND ".join(f"NOT {sql}" for _, sql, _ in out) or "true", "in none of the categories above")]


def priors(source, out, release_dir, preset="all", meta=None, categories=None, table="v", manifest=None, weights=None):
    """A zip of genomic-prediction prior files (P6.5) for the SNPs of `source` (annotate output: a parquet/TSV path, or
    a DuckDB connection with `table`), every SNP list in input order and no '#' lines in the data files:
    bayesrc_classes.txt (SNP <tab> class, no header; a SNP's class is the first of its prior_categories(), numbered
    over the non-empty ones, 'none' last), sets/<category>.txt (the SNPs of each category, which overlap: GFBLUP or
    MultiBLUP sets), ldak_partitions/partition<k> (the SNPs of class k: disjoint), annot.tsv (CHR, BP, SNP, a 0/1
    column per category, tier_score and active_<condition> 0/1 for every chromatin condition), snp_lookup.tsv (SNPs
    without an id, named Ssa<chromosome>p<position> as vendor files name them), README.txt (provenance, files, the
    PROVISIONAL category definitions with their counts, classes, a methods paragraph and references) and methods.txt.
    SNP names are the list's ids. Returns {'rows', 'skipped', 'warnings', 'files', 'categories': {name: n},
    'classes': [(class, category, n)]}."""
    release, out = Path(release_dir).resolve(), Path(out).resolve()
    manifest = manifest or release / "manifest.json"
    weights = weights or snp_score.WEIGHTS
    m, w = _load(manifest, weights)[:2]
    synthetic = [l["name"] for l in m.get("layers", []) if l.get("synthetic")]
    con, rel, columns = _open(source, table, [release], out, preset, w, synthetic)
    cats = prior_categories(columns, w, preset, synthetic, categories)
    names = [c for c, _, _ in cats]
    states = ", ".join(map(lit, w.get("active_states") or []))
    every = preset_conditions(w, columns, preset)[1] if states and w.get("presets") and "chromatin" not in synthetic else []
    flags = "".join(f", coalesce({q('chromatin_' + c)} IN ({states}), false)::INTEGER AS {q('active_' + c)}" for c in every)
    col = lambda c: f"{q(c)}::VARCHAR" if c in columns else "NULL::VARCHAR"  # noqa: E731
    ident = f"nullif(nullif(trim({q('id')}::VARCHAR), ''), '.')" if "id" in columns else "NULL::VARCHAR"
    placed = ", ".join(map(lit, sorted(_placed(m))))
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _priors AS
        SELECT *, coalesce(_id, _name || CASE WHEN _k > 1 THEN 'v' || _k ELSE '' END) AS SNP,
               CASE {' '.join(f'WHEN {q(c)} THEN {i + 1}' for i, c in enumerate(names))} END AS _class
        FROM (SELECT *, row_number() OVER (PARTITION BY _id IS NULL, _name ORDER BY _row) AS _k
              FROM (SELECT _row, chrom::VARCHAR AS chrom, pos, {col('ref')} AS ref, {col('alt')} AS alt, {ident} AS _id,
                           'Ssa' || CASE WHEN chrom::VARCHAR IN ({placed}) THEN chrom::VARCHAR ELSE '0' END || 'p' || pos::VARCHAR AS _name,
                           {', '.join(f'{sql} AS {q(c)}' for c, sql, _ in cats)}, {_tier_cols(columns, preset)[1]} AS tier_score{flags}
                    FROM {rel}))""")
    try:
        n, made, *counts = con.execute(f"SELECT count(*), count(*) FILTER (_id IS NULL), "
                                       f"{', '.join(f'count(*) FILTER ({q(c)})' for c in names)} FROM _priors").fetchone()
        if not n:
            raise InputError("There are no SNPs to write priors for.")
        by_class = dict(con.execute("SELECT _class, count(*) FROM _priors GROUP BY 1").fetchall())
        kept = [(i + 1, c) for i, c in enumerate(names) if by_class.get(i + 1)]  # classes are numbered without gaps
        classes = [(k + 1, c, by_class[old]) for k, (old, c) in enumerate(kept)]
        renumber = f"CASE _class {' '.join(f'WHEN {old} THEN {k + 1}' for k, (old, _) in enumerate(kept))} END"
        files = ["bayesrc_classes.txt", "annot.tsv", *[f"sets/{c}.txt" for c in names],
                 *[f"ldak_partitions/partition{k}" for k, _, _ in classes], *(["snp_lookup.tsv"] if made else [])]
        command = (f"snpscore annotate <your list> --release <release {m.get('version')}> --trait {preset} -o "
                   f"annotated.parquet; python -m snpportal.lib.cli export annotated.parquet --release <release {m.get('version')}> "
                   f"--preset {preset} --format priors")
        readme = _priors_readme(m, w, preset, cats, counts, classes, n, made,
                                provenance(manifest, weights, {"preset": preset, "command": command, **(meta or {})}))
        with tempfile.TemporaryDirectory(dir=out.parent, prefix=".priors-") as tmp:
            for sub in ("sets", "ldak_partitions"):
                (Path(tmp) / sub).mkdir()

            def copy(sql, name, header=False):
                con.execute(f"COPY ({sql} ORDER BY _row) TO {lit(Path(tmp) / name)} "
                            f"(FORMAT csv, HEADER {'true' if header else 'false'}, DELIMITER '\t')")
            copy(f"SELECT SNP, {renumber} FROM _priors", "bayesrc_classes.txt")
            copy("SELECT chrom AS CHR, pos AS BP, SNP, " + ", ".join(f"{q(c)}::INTEGER AS {q(c)}" for c in names)
                 + ", tier_score" + "".join(f", {q('active_' + c)}" for c in every) + " FROM _priors", "annot.tsv", True)
            for c in names:
                copy(f"SELECT SNP FROM _priors WHERE {q(c)}", f"sets/{c}.txt")
            for k, (old, _) in enumerate(kept):
                copy(f"SELECT SNP FROM _priors WHERE _class = {old}", f"ldak_partitions/partition{k + 1}")
            if made:
                copy("SELECT SNP, chrom, pos, ref, alt FROM _priors WHERE _id IS NULL", "snp_lookup.tsv", True)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("README.txt", readme)
                z.writestr("methods.txt", methods_text(m, w, preset, release))
                for name in files:
                    z.write(Path(tmp) / name, name)
    finally:
        con.execute("DROP TABLE IF EXISTS _priors")
    return {"rows": n, "skipped": {}, "warnings": [], "files": [out.name], "categories": dict(zip(names, counts)),
            "classes": classes}


def _priors_readme(m, w, preset, cats, counts, classes, n, made, header):
    """README.txt of the priors zip: provenance lines, files, categories with counts, classes, methods, references."""
    k, classed = len(classes), {c for _, c, _ in classes}
    where = ", ".join((w.get("presets") or {}).get(preset) or []) or "all conditions"
    unclassed = [f"{c} ({'every SNP in it is in an earlier category' if x else 'no SNPs'})"
                 for (c, _, _), x in zip(cats, counts) if c not in classed]
    lines = [
        "salmobase functional SNP portal / snpscore genomic-prediction priors", "", *header, "",
        f"{n:,} SNPs, preset {preset} ({where}). Every file lists SNPs in the order of your list, without comment lines.",
        "", "Files:",
        f"  bayesrc_classes.txt: each SNP and its class (1-{k}, below), tab-separated, no header (the class column "
        "alone: cut -f2)",
        "  sets/<category>.txt: the SNPs of each category, one per line (categories overlap): GFBLUP feature sets "
        "(a set against the rest) or MultiBLUP classes",
        f"  ldak_partitions/partition1-{k}: the SNPs of each class (no overlap, together all SNPs), e.g. LDAK "
        f"--partition-number {k} --partition-prefix ldak_partitions/partition",
        "  annot.tsv: CHR, BP, SNP, a 0/1 column per category, tier_score and active_<condition> (1 = an active "
        "chromatin state in that condition)",
        *(["  snp_lookup.tsv: the SNPs without an id in your list, named Ssa<chromosome>p<position> (chromosome 0 = not "
           "on 1-29; v2, v3 for a repeated position), with chrom, pos, ref and alt"] if made else []),
        "  methods.txt: how the SNPs were annotated and tiered, with references",
        "SNP names are your ids" + (f" ({made:,} SNPs had none: see snp_lookup.tsv)" if made else "")
        + ". Match them to the SNP names in your genotype files. Layouts follow each program's documented input; "
        "confirm them against the version you run.",
        "", "Categories (PROVISIONAL: definitions and order under review):",
        *[f"  {c}: {x:,} SNPs, {d}" for (c, _, d), x in zip(cats, counts)],
        "", "Classes (BayesRC, LDAK partitions): each SNP takes the first category it is in, in the order above:",
        *[f"  class {i}: {c}, {x:,} SNPs" for i, c, x in classes],
        *([f"  no class of its own: {', '.join(unclassed)}"] if unclassed else []),
        "", "Methods",
        f"SNP categories for genomic prediction were taken from the snpscore annotation (release {m.get('version')}, "
        f"assembly {m.get('assembly')}, '{preset}' preset: {where}): "
        + "; ".join(f"{c}, {d}" for c, _, d in cats[:-1]) + ". Categories overlap. For BayesRC (MacLeod et al. 2016) "
        "and MultiBLUP/LDAK partitions (Speed and Balding 2014; Speed et al. 2012), each SNP was assigned to the first "
        "category it belongs to in that order, and SNPs in none of them formed the last class; GFBLUP (Edwards et al. "
        "2016) feature sets were the SNPs of each category. These category definitions and their order are PROVISIONAL.",
        "", "References", *[f"- {r}" for r in PRIOR_REFERENCES],
    ]
    return "\n".join(lines) + "\n"
