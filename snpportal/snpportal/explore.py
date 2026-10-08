"""Explore without an upload: the landing page, gene pages with candidate public variants, the known-loci catalogue
and candidate jobs from genes or intervals (P5.1-P5.3). Candidates come from the release's public pool
(pool/pool.parquet) or, without one, from the public sites in public_af.parquet annotated on the fly; their tiers are
computed for the chosen preset with snpscore.scored(). The locus browser and variant page live in locus.py; the
guided tour (tour) is P5.11."""
from __future__ import annotations

import csv
import io
import re
import tempfile
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

import snpscore
from snpscore.formats import lit, q

from . import figures, jobs, palette, results, search, views

FLANKS = (0, 10_000, 20_000, 50_000, 100_000, 250_000)  # gene page and candidate-list flank choices (bp)
FLANK, LOCUS_FLANK = 50_000, 20_000  # default flank for candidates; flank of the embedded locus view
SHOW_FIRST, SHOW_ROWS = 10, 200  # gene page rows (best first), and after 'Show all'; TSV and 'Score these' take all
MAX_CANDIDATES = 100_000  # public sites in one job made from genes or intervals
MAX_TARGETS = 200  # genes, positions or intervals in one candidate list
STAGES = ("LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis")
SORTS = {"tier": ("tier", "tier, tier_score DESC, pos"), "pos": ("pos", "pos"),  # ?sort= -> (column it needs, ORDER BY)
         "maf": ("public_af_maf", "public_af_maf DESC NULLS LAST, pos")}
EXAMPLES = ["vgll3", "rs863754587", "25:28996360", "25:28,990,000-29,000,000"]  # landing-page search chips
ENSEMBL_GENE = "https://www.ensembl.org/Salmo_salar/Gene/Summary?g={}"
SALMOBASE_GENE = "https://salmobase.org/genes/id/{}?assembly=Ssal_v3.1"
TRAITS = {"age_at_maturity": "Age at maturity", "flesh_colour": "Flesh colour", "ipn_resistance": "IPN resistance",
          "pd_resistance": "PD resistance", "cms_resistance": "CMS resistance", "sea_lice_resistance": "Sea lice resistance",
          "smoltification": "Smoltification", "sex_determination": "Sex determination"}  # catalogue trait -> heading, in page order
CAVEATS = [  # (word in the catalogue's evidence or caveat, badge): why a row needs care
    ("suggestive", "suggestive"), ("not genome-wide", "suggestive"), ("strain", "strain-specific"),
    ("disputed", "disputed"), ("position", "position inferred"), ("A/B alleles", "A/B alleles only"),
    ("QTL only in", "one challenge group")]
HERO = ("25", 28_978_000, 29_002_000)  # landing thumbnail: vgll3 with its tag SNP, Met54Thr and Asn323Lys (BED start, end)
_hero = {}
JBROWSE = ("https://salmobase.org/jbrowse/?assembly=Ssal_v3.1&loc={}:{}..{}"
           "&tracks=Ssal_v3.1-Ensembl-FeatureTrack,Ssal_v3.1-NCBI-FeatureTrack")


def catalogue():
    """Rows of the release's known-loci catalogue (catalog/known_loci.tsv), or [] before it exists."""
    path = jobs.release() / "catalog" / "known_loci.tsv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t")]
    for r in rows:
        r["dois"] = [d.strip() for d in (r.get("source") or "").split(";") if d.strip().startswith("10.")]
        r["trait_text"] = (r.get("trait") or "").replace("_", " ")
        r["kind"] = evidence_kind(r)
        r["badges"] = badges(r)
    return rows


def aliases():
    """{Ensembl gene id: known-loci catalogue name}, e.g. vgll3 for the chr25 gene Ensembl leaves unnamed (the first
    name when a gene has several): the gene label everywhere, through display_name."""
    path = jobs.release() / "catalog" / "known_loci.tsv"
    return _aliases(str(path), path.stat().st_mtime if path.exists() else 0)


@lru_cache(maxsize=4)
def _aliases(path, mtime):
    out = {}
    for gene, name in sorted({(r["ensembl_gene"], r["locus"]) for r in catalogue() if r.get("ensembl_gene") and r.get("locus")}):
        out.setdefault(gene, name)
    return out


def evidence_kind(row):
    """'missense', 'gwas' (GWAS lead or top SNP), 'marker' (QTL marker or other candidate) or 'region' (not a SNP), from
    the catalogue's evidence text; the published-associations lane and the badges use it."""
    text = (row.get("evidence") or "").lower()
    if "not a snp" in text or text.startswith("gene region"):
        return "region"
    return "missense" if text.startswith("missense") else "gwas" if text.startswith("gwas") else "marker"


def badges(row):
    """[(css class suffix, text, tooltip)] for a catalogue row: its evidence kind, whether the effect allele is stated,
    and caveats (suggestive, strain-specific, inferred position, ...) from its evidence and caveat text."""
    kind = row.get("kind") or evidence_kind(row)
    text = {"missense": "missense", "gwas": "GWAS lead", "marker": "QTL marker", "region": "gene region"}[kind]
    out = [(kind, text, row.get("evidence") or "")]
    if row.get("effect_allele"):
        out.append(("allele", f"effect allele {row['effect_allele']}", row.get("effect") or ""))
    found = (row.get("caveat") or "") + " " + (row.get("evidence") or "")
    for word, label in CAVEATS:
        if word in found and label not in [b[1] for b in out]:
            out.append(("caveat", label, row.get("caveat") or row.get("evidence") or ""))
    return out


def by_trait(rows):
    """[(trait, heading, rows)] in TRAITS order (unknown traits last)."""
    groups = {}
    for r in rows:
        groups.setdefault(r.get("trait") or "other", []).append(r)
    order = list(TRAITS) + sorted(t for t in groups if t not in TRAITS)
    return [(t, TRAITS.get(t, t.replace("_", " ").capitalize()), groups[t]) for t in order if t in groups]


def catalogue_counts(rows=None):
    """The one count of the known-loci catalogue (landing page, Known loci header and intro): {entries, traits, snps,
    regions (gene regions and intervals), alleles (effect allele stated), caveats, window (bp, the known-locus badge)}."""
    rows = catalogue() if rows is None else rows
    regions = sum(1 for r in rows if r["kind"] == "region" or not (r.get("pos") or "").isdecimal())
    return {"entries": len(rows), "traits": len(by_trait(rows)), "snps": len(rows) - regions, "regions": regions,
            "alleles": sum(1 for r in rows if r.get("effect_allele")), "caveats": sum(1 for r in rows if r.get("caveat")),
            "window": (jobs.manifest().get("catalog") or {}).get("window", 50_000)}


def nearby(chrom, pos, window=None):
    """Catalogue rows within `window` (the release's catalog.window) of a position, nearest first, with distance."""
    window = (jobs.manifest().get("catalog") or {}).get("window", 50_000) if window is None else window
    found = [dict(r, dist=abs(int(r["pos"]) - int(pos))) for r in catalogue()
             if r.get("chrom") == str(chrom) and (r.get("pos") or "").isdecimal() and abs(int(r["pos"]) - int(pos)) <= window]
    return sorted(found, key=lambda r: (r["dist"], r.get("id") or ""))


def public_source():
    """Where candidate public variants come from: the release pool's VCF, else the 504-fish panel sites (public_af)."""
    if (jobs.release() / "pool" / "pool.parquet").exists():
        source = jobs.read_json(jobs.release() / "pool" / "background.json").get("source") or ""
        return ("sites of the 12 AQUA-FAANG fish's VCF (release pool)" if source.startswith("12_samples")
                else "sites of the 504-fish reference panel (release pool)" if source.startswith("ALL_chrome")
                else "the release pool of public sites")
    return "sites of the 504-fish reference panel"


UNNAMED_TIP = "Unnamed in Ensembl; named by its human ortholog"  # tooltip of a '~VGLL3' gene label


def display_name(name, alias=None, human=None, gene_id=None):
    """The name a gene is shown under: its Ensembl name, else its known-loci catalogue name, else '~VGLL3' from its
    first human ortholog (tooltip UNNAMED_TIP), else its id."""
    if name or alias:
        return name or alias
    if human:
        return "~" + human.split(",")[0].strip()
    return gene_id or "unnamed"


def layer(name):
    """The manifest entry of a release layer, or {}."""
    return next((x for x in jobs.manifest().get("layers", []) if x["name"] == name), {})


def _file(name):
    """Path of a release parquet when it exists, else None."""
    path = jobs.release() / f"{name}.parquet"
    return path if path.exists() else None


def _aliases_sql():
    """SQL table a(gene_id, alias) of the catalogue's gene names (e.g. vgll3 for the unnamed chr25 copy)."""
    pairs = sorted({(r["ensembl_gene"], r["locus"]) for r in catalogue() if r.get("ensembl_gene") and r.get("locus")})
    if not pairs:
        return "(SELECT NULL::VARCHAR AS gene_id, NULL::VARCHAR AS alias WHERE false) a"
    return "(VALUES " + ", ".join(f"({lit(g)}, {lit(a)})" for g, a in pairs) + ") a(gene_id, alias)"


def tissues():
    """Tissue columns of the release's expression layer."""
    return list(layer("expression").get("columns", [])) if _file("expression") else []


def gene_rows(ids):
    """{gene id: row} for some gene ids: location, names, orthologs (human, zebrafish), expression_<tissue>, the
    catalogue alias and the display label. Missing layers give no columns (orthologs give None)."""
    path = _file("gene")
    if not ids or path is None:
        return {}
    cols, joins = ["NULL::VARCHAR AS human", "NULL::VARCHAR AS zebrafish"], []
    if _file("gene_ortholog"):
        cols, joins = ["o.human", "o.zebrafish"], [f"LEFT JOIN read_parquet({lit(_file('gene_ortholog'))}) o ON o.gene_id = g.id"]
    if tissues():
        cols += [f"e.{q(t)} AS {q('expression_' + t)}" for t in tissues()]
        joins.append(f"LEFT JOIN read_parquet({lit(_file('expression'))}) e ON e.gene_id = g.id")
    cur = jobs.connect([jobs.release()]).execute(
        f"SELECT g.*, {', '.join(cols)} FROM read_parquet({lit(path)}) g {' '.join(joins)} WHERE list_contains($ids, g.id)",
        {"ids": list(ids)})
    names = [d[0] for d in cur.description]
    rows = {r[names.index("id")]: dict(zip(names, r)) for r in cur.fetchall()}
    for g in rows.values():
        g["alias"] = aliases().get(g["id"])
        g["label"] = display_name(g["name"], g["alias"], g["human"], g["id"])
    return rows


def hero():
    """A small locus figure of vgll3 (genes, published associations, molQTL leads, chromatin states, public variants;
    no live signal) for the landing page, drawn once per release and state palette. None without a chromatin layer."""
    from . import locus  # locus imports this module
    info = jobs.release_info()
    key = (info.get("sha256"), palette.states_name())
    if key not in _hero:
        if _file("chromatin") is None:
            return None
        chrom, start, end = HERO
        data = locus.lanes(chrom, start, end)
        svg = locus.locus_svg.locus(data, title="vgll3, chromosome 25", desc="Published associations (diamonds), Ensembl 116 "
                                    "genes, AQUA-FAANG chromatin states in 21 conditions, 504-fish panel variants.",
                                    compact=True, width=locus.COMPACT_WIDTH, gutter=118, synthetic=bool(info.get("synthetic")),
                                    uid="hero", legend_on=False)  # drawn at about its column's width, so its text is not shrunk
        if len(_hero) >= 4:  # one per release and palette
            _hero.clear()
        _hero[key] = svg
    return _hero[key]


def landing(request):
    """/snp/: what the portal does, 'Score your SNPs' and 'Take the tour', a quick search box with example chips and the
    vgll3 thumbnail."""
    figure = hero()
    return render(request, "snpportal/landing.html", {
        "nav": "home", "title": "Functional SNP portal", "hero": mark_safe(figure) if figure else None,
        "examples": EXAMPLES})


def ss4r(ids):
    """{gene id: {"copies": [gene rows of its Ss4R duplicates], "class": AORe or LORe}} from the release's ss4r layer
    (AQUA-FAANG salmon-trout clades); {} without that layer."""
    path = _file("ss4r")
    if not ids or path is None:
        return {}
    rows = jobs.connect([jobs.release()]).execute(
        f"SELECT gene_id, ohnolog, class FROM read_parquet({lit(path)}) WHERE list_contains($ids, gene_id)",
        {"ids": list(ids)}).fetchall()
    copies = gene_rows(sorted({c for _, o, _ in rows for c in (o or "").split(",") if c}))
    return {g: {"copies": [copies[c] for c in (o or "").split(",") if c in copies], "class": cls} for g, o, cls in rows}


def known_loci(request):
    """/snp/known-loci/?tab=<trait>: the published SNPs (and QTL intervals, under review) of the release catalogue, one
    tab per trait, with evidence, effect and caveat, DOIs, gene and its Ss4R duplicate, variant and locus links."""
    rows = catalogue()
    genes = gene_rows(sorted({r["ensembl_gene"] for r in rows if r.get("ensembl_gene")}))
    duplicates = ss4r(genes)
    for r in rows:
        r["gene"] = genes.get(r.get("ensembl_gene"))
        r["ss4r"] = duplicates.get(r.get("ensembl_gene"))
        r["interval"] = r.get("type") == "qtl_interval" or not r.get("pos")
        if r.get("chrom") and (r.get("pos") or "").isdecimal():
            pos = int(r["pos"])
            r["locus_url"] = search.locus_url(r["chrom"], max(1, pos - FLANK), pos + FLANK)
            r["variant_url"] = search.variant_url(r["chrom"], pos)
        elif r.get("chrom") and (r.get("start") or "").isdecimal() and (r.get("end") or "").isdecimal():
            r["locus_url"] = search.locus_url(r["chrom"], int(r["start"]), int(r["end"]))
        r["salmobase"] = SALMOBASE_GENE.format(r["ensembl_gene"]) if r.get("ensembl_gene") else None
        r["flags"] = [b for b in r["badges"] if b[0] == "caveat"]  # the evidence badge leads its cell; caveats get their own
    groups = by_trait(rows)
    tab = request.GET.get("tab")
    return render(request, "snpportal/known_loci.html", {
        "nav": "known", "title": "Known loci", "groups": groups, "has_ss4r": bool(_file("ss4r")),
        "tab": tab if tab in [t for t, _, _ in groups] else groups[0][0] if groups else None,
        "counts": catalogue_counts(rows)})


# ---- candidate public variants ----

def _where(windows, pos="pos"):
    """SQL condition: inside one of the windows [(chrom, start, end)] (1-based, inclusive)."""
    return " OR ".join(f"(chrom = {lit(c)} AND {pos} BETWEEN {int(a)} AND {int(b)})" for c, a, b in windows) or "false"


def public_rows(windows, limit=MAX_CANDIDATES):
    """[(chrom, pos, id, ref, alt)] of the public sites in the windows, from the pool or else public_af.parquet; at
    most limit + 1 rows (so callers can tell when there are too many)."""
    release, pool = jobs.release(), jobs.release() / "pool" / "pool.parquet"
    con = jobs.connect([release])
    if pool.exists():
        cols = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet({lit(pool)}))").fetchall()]
        pick = ", ".join(c if c in cols else f"NULL::VARCHAR AS {c}" for c in ("id", "ref", "alt"))
        sql = f"SELECT DISTINCT chrom, pos, {pick} FROM read_parquet({lit(pool)}) WHERE {_where(windows)}"
    elif _file("public_af"):
        sql = (f"SELECT DISTINCT chrom, \"end\" AS pos, NULL::VARCHAR AS id, ref, alt FROM read_parquet({lit(_file('public_af'))}) "
               f"WHERE {_where(windows, q('end'))}")
    else:
        return []
    return con.execute(f"{sql} ORDER BY try_cast(chrom AS INTEGER), chrom, pos LIMIT {int(limit) + 1}").fetchall()


def candidates(windows, trait="all", sort="pos"):
    """Public sites in the windows, annotated and tiered for `trait`, ordered by ?sort (SORTS): (rows as dicts, column
    names, source). Reads the pool's rows when the release has pool/pool.parquet, else annotates the sites of
    public_af.parquet now (sequence checks off)."""
    release, w = jobs.release(), jobs.weights()
    pool = release / "pool" / "pool.parquet"
    with tempfile.TemporaryDirectory(prefix="snpportal-explore-") as tmp:  # public sites only, never user data
        tmp = Path(tmp).resolve()
        if pool.exists():
            con, source, path = jobs.connect([release]), "pool", pool
        else:
            rows = public_rows(windows)
            if not rows:
                return [], [], "public_af"
            with open(tmp / "sites.tsv", "w") as f:
                f.write("chrom\tpos\tid\tref\talt\n" + "".join("\t".join("" if v is None else str(v) for v in r) + "\n" for r in rows))
            snpscore.annotate(tmp / "sites.tsv", release, tmp / "sites.parquet", sequence=False)
            con, source, path = jobs.connect([release, tmp]), "annotated now", tmp / "sites.parquet"
        cols = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet({lit(path)}))").fetchall()]
        keep = [c for c in cols if not c.startswith("tier")]  # the pool's stored tiers; recomputed for `trait` below
        con.execute(f"CREATE TEMP TABLE w AS SELECT {', '.join(map(q, keep))} FROM read_parquet({lit(path)}) WHERE {_where(windows)}")
    sql = jobs.scored_sql("w", w, keep, trait if trait in w["presets"] else "all", release) if w else "SELECT * FROM w"
    column, order = SORTS.get(sort, SORTS["pos"])
    order = order if column in keep or w and column == "tier" else "pos"
    cur = con.execute(f"SELECT * FROM ({sql}) ORDER BY {order}")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()], names, source


def _tsv(header_lines, names, rows):
    out = io.StringIO()
    out.write("".join(f"{line}\n" for line in header_lines))
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(names)
    for r in rows:
        writer.writerow(["" if r[n] is None else ";".join(f"{t['term']}={t['weight']}" for t in r[n]) if n == "tier_terms"
                         else r[n] for n in names])
    return out.getvalue()


def provenance(what, trait=None):
    """'#' lines for public downloads: what it is, the release and its hashes, the preset, PROVISIONAL and SYNTHETIC."""
    info, weights = jobs.release_info(), jobs.release() / "weights.yaml"
    lines = [f"salmobase functional SNP portal: {what}; exported {jobs.utc()}",
             f"release {info['version']} ({info['assembly']}); manifest sha256 {info['sha256']}; "
             f"weights sha256 {jobs.sha256(weights) if weights.exists() else None}"]
    if trait:
        lines.append(f"preset {trait}; tier rules PROVISIONAL (prototype weights, under review)")
    if info["synthetic"]:
        lines.append(f"SYNTHETIC layers in this release (never counted in tiers): {', '.join(info['synthetic'])}")
    return ["# " + line for line in lines]


def download(text, name, request, header):
    """A text file download; ?plain=1 drops the '#' header lines."""
    body = text if request.GET.get("plain") or not header else "\n".join(header) + "\n" + text
    response = HttpResponse(body, content_type="image/svg+xml" if name.endswith(".svg") else "text/tab-separated-values; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# ---- gene page ----

def expression_svg(g, synthetic=False, note=""):
    """Bars of mean expression (CPM) per tissue for gene row `g`, one bar per tissue in its Okabe-Ito colour, with the
    value printed (a missing value prints 'n/a'). `note` (provenance) is added to the <desc>."""
    values = [(t, g.get(f"expression_{t}")) for t in tissues()]
    top = max([v for _, v in values if v] or [1.0])
    width, left, span, step = 560, 72, 400, 26
    parts = [f'<line x1="{left}" y1="4" x2="{left}" y2="{8 + step * len(values)}" stroke="{palette.GREY[500]}"/>']
    for i, (tissue, v) in enumerate(values):
        y, w = 8 + i * step, (span * v / top if v else 0)
        label = "n/a" if v is None else f"{v:,.1f}" if v < 1000 else f"{v:,.0f}"
        parts.append(f'<text x="{left - 8}" y="{y + 13}" text-anchor="end">{escape(tissue)}</text>'
                     f'<rect x="{left}" y="{y}" width="{w:.1f}" height="18" fill="{palette.TISSUES.get(tissue, palette.GREY[500])}">'
                     f'<title>{escape(tissue)}: {label} CPM</title></rect>'
                     f'<text x="{left + w + 6:.1f}" y="{y + 13}" fill="{palette.GREY[700]}">{label}</text>')
    title = f"Expression of {g['label']} per tissue"
    desc = f"Mean counts per million (CPM) per tissue for {g['id']}. {layer('expression').get('description', '')} {note}"
    return figures.svg(width, 16 + step * len(values), title, desc, "".join(parts), synthetic)


def elements(g, window):
    """Robust ATAC peaks in the window with their state per condition (tissues, then embryo stages), the distance of
    their midpoint to the TSS (in the gene's direction), GERP overlap, Ensembl regulatory types and public variants."""
    chrom, a, b = window
    if _file("chromatin") is None:
        return [], []
    conditions = [c for c in layer("chromatin").get("columns", []) if c != "summary"]
    conditions = [c for c in conditions if c not in STAGES] + [c for c in STAGES if c in conditions]
    tss, sign = (g["start"] + 1, 1) if g["strand"] != "-" else (g["end"], -1)
    near = f"chrom = {lit(chrom)} AND \"end\" >= {int(a)} AND start < {int(b)}"
    extra = []
    for name, sql in [("gerp", "SELECT count(*) > 0 FROM x_gerp x WHERE x.start < c.\"end\" AND x.\"end\" > c.start"),
                      ("regbuild", "SELECT string_agg(DISTINCT x.type, ', ') FROM x_regbuild x WHERE x.start < c.\"end\" AND x.\"end\" > c.start"),
                      ("public_af", "SELECT count(*) FROM x_public_af x WHERE x.\"end\" > c.start AND x.\"end\" <= c.\"end\"")]:
        if _file(name):
            extra.append((name, f"x_{name} AS (SELECT * FROM read_parquet({lit(_file(name))}) WHERE {near})", f"({sql}) AS {name}"))
    ctes = ", ".join(["c AS (SELECT * FROM read_parquet(" + lit(_file("chromatin")) + f") WHERE {near})"] + [x[1] for x in extra])
    cur = jobs.connect([jobs.release()]).execute(
        f"WITH {ctes} SELECT chrom, start, \"end\", {', '.join(map(q, conditions))}{''.join(', ' + x[2] for x in extra)} "
        "FROM c ORDER BY start")
    names = [d[0] for d in cur.description]
    rows = []
    for r in cur.fetchall():
        r = dict(zip(names, r))
        mid = (r["start"] + r["end"]) / 2
        r["tss"] = "at TSS" if r["start"] < tss <= r["end"] else f"{sign * (mid - tss) / 1000:+.1f} kb"
        r["states"] = [(c, r[c], palette.state(r[c])[2]) for c in conditions]
        rows.append(r)
    return rows, [(c, "Embryo" if c in STAGES else c.split("_")[0], _short(c)) for c in conditions]


def _short(condition):
    """Column label: 'Imm F' for Brain_Immature_Female, 'Blastula' for LateBlastulation (figures.STAGE_LABELS)."""
    if condition in STAGES:
        return figures.STAGE_LABELS.get(condition, condition)
    _, maturity, sex = (condition.split("_") + ["", ""])[:3]
    return f"{maturity[:3]} {sex[:1]}"


def gene(request, gene_id):
    """/snp/gene/<id>/: names and orthologs, links, the locus view (gene +/- 20 kb), expression per tissue,
    regulatory elements and the public variants in the gene +/- ?flank (default 50 kb) tiered for ?trait, with TSV
    downloads (?download=expression.svg|expression.tsv|candidates.tsv) and 'Score these'."""
    g = gene_rows([gene_id]).get(gene_id)
    if g is None:
        raise Http404("No such gene in this release")
    presets = jobs.presets()
    trait = request.GET.get("trait", "all")
    trait = trait if trait in dict(presets) else "all"
    flank = request.GET.get("flank", "")
    flank = int(flank) if flank.isdecimal() and int(flank) in FLANKS else FLANK
    sort = request.GET.get("sort", "tier")
    info = jobs.release_info()
    synthetic = "expression" in info["synthetic"]
    window = (g["chrom"], max(1, g["start"] + 1 - flank), g["end"] + flank)
    what = request.GET.get("download")
    if what == "expression.svg" and tissues():
        note = " ".join(line[2:] for line in provenance(f"expression of {gene_id}"))
        return download(expression_svg(g, synthetic, note), f"expression_{gene_id}.svg", request, [])
    if what == "expression.tsv" and tissues():
        text = "tissue\tmean_cpm\n" + "".join(f"{t}\t{'' if g.get('expression_' + t) is None else g['expression_' + t]}\n" for t in tissues())
        return download(text, f"expression_{gene_id}.tsv", request, provenance(f"expression of {gene_id}"))
    rows, names, source = candidates([window], trait, sort)
    if what == "candidates.tsv":
        return download(_tsv([], names, rows), f"candidates_{gene_id}_{flank // 1000}kb_{trait}.tsv", request,
                        provenance(f"public variants in {gene_id} +/- {flank:,} bp ({window[0]}:{window[1]}-{window[2]})", trait))
    tiers = {}
    for r in rows:
        tiers[r.get("tier")] = tiers.get(r.get("tier"), 0) + 1
    shown = rows[:SHOW_ROWS] if request.GET.get("all") == "1" else rows[:SHOW_FIRST]
    for r in shown:
        r["url"] = search.variant_url(r["chrom"], r["pos"])
        r["gene_label"] = display_name(r.get("gene_name"), aliases().get(r.get("gene_id")), r.get("gene_ortholog_human"), r.get("gene_id"))
        r["tier_evidence"] = results.with_published(results.evidence_text(r.get("tier_evidence"), r.get("tier_terms")), r.get)
    known = {r.get("known_locus") for r in rows}  # one known locus for every row: said once, above the table
    known = known.pop() if len(known) == 1 and None not in known and "known_locus" in names else None
    plain_ids = all((r.get("id") or "").startswith(f"{r['chrom']}_{r['pos']}_") or not r.get("id") for r in rows)  # no id column
    peaks, head = elements(g, window)
    side = [(k, label) for k, label in [("gerp", "GERP"), ("regbuild", "Ensembl regulatory"), ("public_af", "Public variants")]
            if peaks and k in peaks[0]]
    query = {"trait": trait, "flank": flank, "sort": sort}
    fig = None
    if tissues():
        base = reverse("snpportal:gene", args=[gene_id])
        fig = {"name": "expression", "title": "Expression per tissue", "svg": mark_safe(expression_svg(g, synthetic)),
               "info": layer("expression").get("description", "Mean counts per million per tissue."),
               "svg_url": f"{base}?download=expression.svg", "tsv_url": f"{base}?download=expression.tsv"}
    locus = (g["chrom"], max(1, g["start"] + 1 - LOCUS_FLANK), g["end"] + LOCUS_FLANK)
    loci = [dict(r, flags=[b for b in r["badges"] if b[0] == "caveat"]) for r in catalogue() if r.get("ensembl_gene") == gene_id]
    return render(request, "snpportal/gene.html", {
        "nav": "explore", "title": g["label"], "gene": g, "synthetic": bool(info["synthetic"]),
        "meta": f"{g['id']} · chromosome {g['chrom']}:{g['start'] + 1:,}-{g['end']:,} ({g['strand']}) · {g['biotype']}",
        "loci": loci, "ss4r": ss4r([gene_id]).get(gene_id), "unnamed_tip": UNNAMED_TIP,
        "ensembl": ENSEMBL_GENE.format(gene_id), "salmobase": SALMOBASE_GENE.format(gene_id), "jbrowse": JBROWSE.format(*locus),
        "locus_url": search.locus_url(*locus),
        "locus_svg": reverse("snpportal:locus_svg") + "?" + urlencode({"r": "{}:{}-{}".format(*locus), "trait": trait}),
        "figure": fig, "peaks": peaks, "head": head, "groups": _groups(head), "side": side,
        "rows": shown, "n_rows": len(rows), "source": source, "public_source": public_source(), "known": known,
        "names": [n for n in names if not (n == "id" and plain_ids) and not (known and n == "known_locus")],
        "tiers": sorted(tiers.items(), key=lambda kv: kv[0] or 9),
        "window": window, "window_text": "{}:{:,}-{:,}".format(*window), "flank": flank, "flanks": FLANKS, "trait": trait,
        "presets": presets, "sort": sort, "query": urlencode(query),
        "sorts": [(k, label) for k, label in [("tier", "tier"), ("pos", "position"), ("maf", "minor allele frequency")]
                  if SORTS[k][0] in names], "public_af": jobs.PUBLIC_AF})


def _groups(head):
    """[(tissue or 'Embryo', number of columns)] for the element table's header."""
    groups = []
    for _, group, _ in head:
        if groups and groups[-1][0] == group:
            groups[-1] = (group, groups[-1][1] + 1)
        else:
            groups.append((group, 1))
    return groups


# ---- candidate jobs from genes or intervals ----

def targets(text, flank):
    """Windows [(chrom, start, end)] and labels from pasted gene ids, gene names (Ensembl or catalogue), positions
    (+/- flank) and intervals (as given), one per line or separated by spaces or commas. Raises jobs.InputError."""
    found, genes_wanted = [], []
    for line in re.split(r"[\n;]+", text):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [line] if search.region(line) else [t for t in re.split(r"[\s,]+", line) if t]
        for token in tokens:
            hit = search.region(token)
            if hit:
                chrom, a, b = hit
                found.append(((chrom, max(1, a - flank), b + flank), token) if a == b else ((chrom, a, b), token))
            else:
                genes_wanted.append(token)
    if len(found) + len(genes_wanted) > MAX_TARGETS:
        raise jobs.InputError(f"Paste at most {MAX_TARGETS} genes, positions or intervals at once.")
    if genes_wanted:
        path = _file("gene")
        if path is None:
            raise jobs.InputError("This release has no gene layer, so only positions and intervals can be used.")
        matches = jobs.connect([jobs.release()]).execute(f"""
            SELECT t.token, g.id, g.chrom, g.start, g."end", bool_or(lower(a.alias) = lower(t.token)) AS known
            FROM (SELECT unnest($tokens) AS token) t, read_parquet({lit(path)}) g LEFT JOIN {_aliases_sql()} ON a.gene_id = g.id
            WHERE upper(g.id) = upper(t.token) OR lower(g.name) = lower(t.token) OR lower(a.alias) = lower(t.token)
            GROUP BY t.token, g.id, g.chrom, g.start, g."end" ORDER BY try_cast(g.chrom AS INTEGER), g.start""",
            {"tokens": genes_wanted}).fetchall()
        for token in genes_wanted:
            hits = [m for m in matches if m[0] == token]
            if not hits:
                raise jobs.InputError(f"'{token[:40]}' is not a gene id, gene name, position or interval in this release.")
            known = [h for h in hits if h[5]]  # a name shared by Ss4R copies means the known-loci catalogue's gene
            if len(hits) > 1 and len(known) != 1:
                raise jobs.InputError(f"'{token[:40]}' matches {len(hits)} genes (" + ", ".join(
                    f"{h[1]} on chr{h[2]}" for h in hits[:5]) + "): paste the Ensembl id of the one you mean.")
            _, gene_id, chrom, start, end, _ = known[0] if len(hits) > 1 else hits[0]
            label = f"{token} (chr{chrom}, the known-loci gene)" if len(hits) > 1 else token
            found.append(((chrom, max(1, start + 1 - flank), end + flank), f"{label} +/- {flank // 1000} kb" if flank else label))
    if not found:
        raise jobs.InputError("Paste at least one gene id or name, position or interval, e.g. ENSSSAG00000053708 or 26:14.5-15Mb.")
    return [w for w, _ in found], [label for _, label in found]


@require_POST
@views.private  # the pasted targets may be confidential candidates: no-store, and error reports without POST values
@sensitive_post_parameters()
def candidate_job(request):
    """POST targets (genes, positions, intervals), flank and trait: the public variants there become a job (via
    jobs.create_from_rows), then its results page. Errors re-show the Score page's 'Genes or regions' tab."""
    score_page = views.score_page
    text = request.POST.get("targets", "")[:20_000]
    flank = request.POST.get("flank", "")
    flank = int(flank) if flank.isdecimal() and int(flank) <= max(FLANKS) else FLANK
    trait = request.POST.get("trait", "all")
    trait = trait if trait in dict(jobs.presets()) else "all"
    try:
        windows, labels = targets(text, flank)
        rows = public_rows(windows)
        if not rows:
            raise jobs.InputError("There are no public variants in these genes or intervals.")
        if len(rows) > MAX_CANDIDATES:
            raise jobs.InputError(f"These windows hold more than {MAX_CANDIDATES:,} public variants. Use fewer or shorter intervals.")
        label = "Public variants in " + ", ".join(labels)
        key = jobs.create_from_rows(rows, label if len(label) <= 120 else label[:117] + "...", trait)
    except jobs.InputError as e:
        return score_page(request, str(e), 400, tab="regions", targets=text)
    except jobs.QueueFull:
        response = score_page(request, "The portal is busy scoring other lists. Please try again in a minute.", 503,
                              tab="regions", targets=text)
        response["Retry-After"] = "60"
        return response
    url = reverse("snpportal:results", args=[key])
    return redirect(url if trait == "all" else f"{url}?{urlencode({'trait': trait})}")


# ---- the guided tour: an illustrated slide show ----

TOUR = [  # One slide each: a title (<= 6 words), text (<= 2 sentences, <= 40 words), the screenshot's alt text, numbered
    # callouts (label, element) and 'Try it' (label, portal path or the Score example to post; {label}: its name).
    # 'shot' is for `manage.py tour_images`: the page ({snps}, {panel}, {gwas}: the example jobs it scores), the browser
    # width, an element to click first and the crop. Elements are CSS selectors or 'text=<exact text>'; a list is their
    # union, and a leading 'row' stretches it across the crop.
    {"slug": "overview", "title": "Find SNPs with functional evidence",
     "text": "Each SNP gets a tier for the trait you pick, from 1 (strongest) to 4 (no evidence found, not evidence of no "
             "effect). Results open with the key numbers and your top SNPs.",
     "alt": "Results of the known-loci example for maturation: trait menu, key numbers, SNPs per tier and the top SNPs.",
     "callouts": [("Pick the trait", "#trait"), ("Click a number to list those SNPs", ".sp-kpis"),
                  ("Tier: 1 strongest, 4 no evidence found", "#fig-tiers"),
                  ("The evidence behind it", ["#top-h + div th:nth-child(4)", "#top-h + div tr:nth-child(4) td:nth-child(4)"])],
     "try": ("Try it: score the known loci", {"example": "known_loci"}),
     "shot": {"path": "results/{snps}/?trait=maturation", "width": 1100,
              "crop": [".nav-tabs", "#top-h + div tr:nth-child(4)"]}},
    {"slug": "score", "title": "Score your list",
     "text": "Upload a VCF, SNP table, PLINK or chip file, paste positions, name genes or regions, or upload GWAS "
             "results. Without a list, try one of the examples.",
     "alt": "The Score page: the Try it examples and the Upload SNPs, Paste positions, Genes or regions and GWAS tabs.",
     "callouts": [("No list? Try an example", ".sp-try"),
                  ("Upload, paste, genes or regions, or GWAS", "section[aria-label='Your data'] .nav-tabs"),
                  ("Drop your file, then Score", ["#pane-file .sp-drop", "#pane-file button"])],
     "try": ("Try it: open Score", "score/"),
     "shot": {"path": "score/", "width": 1000, "crop": ["#try-it", "section[aria-label='Your data']"]}},
    {"slug": "table", "title": "Filter, then open a SNP",
     "text": "Filters combine and stay in the link, so a view can be bookmarked or shared. Click any row to see that SNP's "
             "evidence beside the table.",
     "alt": "The Table tab with its filters, the top-tier SNP selected and its evidence card open on the right.",
     "callouts": [("Filter by tier, gene, position, MAF or assay", "#results .sp-filters"), ("Click a row", "tr.sp-selected"),
                  ("Its evidence; open the full card", ["#drawer-h", "#drawer .btn"])],
     "try": ("Try it: the example's table", {"example": "known_loci", "tab": "table"}),
     "shot": {"path": "results/{snps}/?trait=maturation&tab=table", "width": 1200, "click": "tr[data-card] a[hx-get]",
              "wait": "#drawer", "crop": [".nav-tabs", "tr[data-card]:nth-child(12)", "#drawer-h"]}},
    {"slug": "card", "title": "See why it got its tier",
     "text": "The evidence card adds up what earned the tier: chromatin state in 21 AQUA-FAANG conditions, the coding "
             "consequence and any published locus nearby.",
     "alt": "Evidence card of akap11 Val214Met for maturation: tier 1 for brain activity and a missense change, its "
            "published locus and the chromatin state in each condition.",
     "callouts": [("Tier, and what earned it", ["#card-body p:has(> .sp-badge)", "#card-body .sp-figure svg"]),
                  ("Published locus and effect allele", "#card-body .sp-status-ok"),
                  ("Chromatin per condition; outlined: the trait's", "#card-body .sp-card-side > .sp-figure:first-child svg")],
     "try": ("Try it: akap11 Val214Met", "variant/25-29064238-A-G/?trait=maturation"),
     "shot": {"path": "variant/25-29064238-A-G/?trait=maturation", "width": 1000,
              "crop": ["#card-body p:has(> .sp-badge)", "#card-body .sp-card-side > .sp-figure:first-child svg"]}},
    {"slug": "locus", "title": "Explore a locus",
     "text": "The locus browser lines up genes, published loci, regulatory elements, chromatin states and live RNA, ATAC "
             "and ChIP data from salmobase. Open a group for one track per condition.",
     "alt": "Locus browser at vgll3 on chromosome 25: genes and published SNPs, regulatory elements, chromatin states and "
            "the functional assays.",
     "callouts": [("Zoom and move", ".sp-bctl .btn-group:nth-of-type(1)"),
                  ("Genes, published loci and variants", "#g-genes"),
                  ("Open a group: one track per condition", "#g-hmm .sp-tog"),
                  ("RNA, ATAC and ChIP from salmobase", "#g-assays .sp-grp-h")],
     "try": ("Try it: vgll3 in the locus browser", "locus/?r=25:28983861-29008860"),
     "shot": {"path": "locus/?r=25:28983861-29008860", "width": 1280, "crop": [".sp-bctl", "#g-assays .sp-grp-h"]}},
    {"slug": "panel", "title": "Design a genotyping panel",
     "text": "The Panel tab picks the best-scoring SNPs that pass the assay checks, spread over every chromosome. Export "
             "writes the KASP, Illumina and Axiom files.",
     "alt": "The Panel tab for 50,000 public sites: designer settings, a 384-marker panel and its markers along the genome.",
     "callouts": [("How many markers, how far apart", ["#designer label:nth-child(1)", "#designer label:nth-child(2)"]),
                  ("Assay checks to pass", "#designer select[name=assay]"), ("Design panel", "#designer button"),
                  ("Export vendor files", "#panel-h + a")],
     "try": ("Try it: a panel from {label}", {"example": "public_50k", "tab": "panel"}),
     "shot": {"path": "results/{panel}/?trait=maturation&tab=panel", "width": 1100, "crop": [".nav-tabs", "#fig-panel-coverage"]}},
    {"slug": "gwas", "title": "Analyse GWAS summary statistics",
     "text": "Upload GWAS results for a Manhattan plot, the loci and fine-mapping that weights SNPs by their functional "
             "evidence (one causal variant per locus, no LD). The example is synthetic.",
     "alt": "Association page of the synthetic maturation GWAS, labelled SYNTHETIC: Manhattan plot and the loci table.",
     "callouts": [("Click a lead SNP for its regional plot", "#fig-manhattan svg a[href*='locus=1']"),
                  ("Loci, strongest first", ["#loci-h ~ * thead th:nth-child(1)", "#loci-h ~ * tbody tr:nth-child(3) td:nth-child(3)"]),
                  ("Top SNP after fine-mapping", ["text=Top SNP by PIP", "#loci-h ~ * tbody tr:nth-child(3) td:nth-child(6)"])],
     "try": ("Try it: the synthetic maturation GWAS", {"example": "gwas_maturation_SYNTHETIC"}),
     "shot": {"path": "results/{gwas}/association/?trait=maturation", "width": 1280,
              "crop": [".sp-caveat", "#loci-h ~ * tbody tr:nth-child(3)"]}},
    {"slug": "more", "title": "Search, browse and get help",
     "text": "Quick search finds one gene, SNP or region, and Known loci lists the published SNPs. For a confidential "
             "list, Help → Run locally scores it on your own computer.",
     "alt": "The front page with Quick search and the open Help menu: Guided tour, Help, Data, Methods and Run locally.",
     "callouts": [("Quick search", "form[role=search]"), ("Known loci", ".sp-nav a[href$='known-loci/']"),
                  ("Help, this tour and Run locally", ".sp-menu ul")],
     "try": ("Try it: search vgll3", "search/?q=vgll3"),
     "shot": {"path": "", "width": 1100, "click": ".sp-menu > summary", "wait": ".sp-menu[open] ul",
              "crop": [".sp-brand", ".sp-release", "form[role=search]"]}},
]


def tour(request):
    """/snp/tour/?slide=N: the guided tour, an illustrated slide show (TOUR, screenshots in static/snpportal/tour/).
    Every slide is in the page and ?slide=N picks the one shown, so Previous, Next and the dots are plain links;
    portal.js /* tour */ switches slides without reloading. 'Try it' opens the real page or posts a Score example."""
    found, home = views.examples(), reverse("snpportal:landing")
    slides = []
    for s in TOUR:
        label, target = s["try"]
        gwas = isinstance(target, dict) and target["example"].startswith("gwas_")
        if isinstance(target, str):
            try_it = {"label": label, "url": home + target}
        elif target["example"] in found:
            try_it = {"label": label.format(label=found[target["example"]]["label"]), "fields": {"trait": "maturation", **target},
                      "post": reverse("snpportal:gwas_score" if gwas else "snpportal:upload")}
        else:  # this release lacks the example
            try_it = {"label": "Try it: open Score", "url": reverse("snpportal:upload") + ("?input=gwas" if gwas else "")}
        slides.append({**s, "try_it": try_it, "image": f"snpportal/tour/{s['slug']}.webp"})
    slide = request.GET.get("slide", "")
    n = int(slide) if slide.isdecimal() and 1 <= int(slide) <= len(TOUR) else 1
    return render(request, "snpportal/tour.html", {
        "nav": "help", "title": "Guided tour", "slides": slides, "n": n, "count": len(TOUR),
        "prev": n - 1 if n > 1 else None, "next": n + 1 if n < len(TOUR) else None})
