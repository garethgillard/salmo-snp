"""Design panel (/snp/panel/): a curated SNP panel built from Table selections of any results ('Add to panel' on the
Table copies its whole selection: the cart), compared with an existing chip (the usual case: SNPs to add to it),
checked and exported as vendor files.

It belongs to one browser: its folder (results/panel-<uuid>) is named by an HttpOnly cookie, never by a URL, and
jobs.cleanup removes it 24 hours after it was started (its 'created' marker). To keep it longer, download its TSV
and score that list again later. Its SNPs carry their tiers for all 21 conditions, so SNPs from lists scored for
other conditions compare."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import snpscore
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from .lib import export as snp_export
from .lib import panel as snp_panel
from snpscore.formats import lit

from . import figures, jobs, results, tools
from .views import UploadToResults, accepted_suffix, finished, private

COOKIE = "snpportal_panel"
BIN = 250_000  # the figure's marks: one per 250 kb, coloured by the best tier in it
SHOWN, LISTED = 50, 2000  # SNPs listed, then with 'Show all'
SCOPES = {"all": "all panel SNPs", "new": "SNPs not on the chip"}


# ---- the panel folder: this browser's only ----

def _age(d):
    return time.time() - (d / "created").stat().st_mtime


def _folder(request):
    """This browser's panel folder, or None (no cookie, or a panel that is gone or expired)."""
    try:
        d = jobs.results_dir() / f"panel-{uuid.UUID(request.COOKIES.get(COOKIE, ''))}"
    except ValueError:
        return None
    try:
        fresh = jobs.keep_seconds() is None or _age(d) < jobs.keep_seconds()
    except FileNotFoundError:
        return None
    return d if fresh and (d / "panel.json").exists() else None


def _new():
    d = jobs.results_dir() / f"panel-{uuid.uuid4()}"
    d.mkdir(mode=0o700)
    (d / "created").touch(mode=0o600)  # never changes: cleanup counts the 24 hours from it
    jobs._write_json(d / "panel.json", {"sources": [], "next": 1, "created_utc": jobs.utc(),
                                        "release": jobs.manifest().get("version")})  # its sources' release (I17)
    return d


def _cookie(response, d):
    keep = jobs.keep_seconds()
    left = jobs.FOREVER if keep is None else max(0, int(keep - _age(d)))
    response.set_cookie(COOKIE, d.name[len("panel-"):], max_age=left, httponly=True, samesite="Lax")
    return response


def count(request):
    """The nav's 'Design panel' badge: the panel's SNP count (empty without a panel)."""
    d = _folder(request)
    s = jobs.read_json(d / "panel.json") if d else {}
    n = sum(x["n"] for x in s.get("sources", [])) - len(s.get("dropped", []))  # sources overlap: an upper bound
    return HttpResponse(f" ({n:,})" if n else "", content_type="text/plain")


def holds(request, snp):
    """For a SNP's card: None without a panel, else {sources: ['S1', ...] that hold it (same chrom, pos and alleles),
    chip: where the panel's chip has its nearest marker, in words (None without a chip)}."""
    d = _folder(request)
    if d is None:
        return None
    s, files = jobs.read_json(d / "panel.json"), sorted(d.glob("source_*.parquet"))
    con = jobs.connect([d])
    found = []
    if files:
        src = f"read_parquet([{', '.join(lit(f) for f in files)}], union_by_name=true)"
        alleles = [c for c in ("ref", "alt") if c in snp and c in {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}]
        same = " AND ".join(["chrom = ?", "pos = ?"] + [f"coalesce({c}, '') = ?" for c in alleles])
        found = [x for x, in con.execute(f"SELECT DISTINCT panel_source FROM {src} WHERE {same}",
                                         [snp["chrom"], snp["pos"]] + [snp.get(c) or "" for c in alleles]).fetchall()]
    names = {x["id"]: f"S{i + 1}" for i, x in enumerate(s.get("sources", []))}
    out = {"sources": [names.get(x, "?") for x in sorted(found)], "chip": None}
    if (d / "chip.parquet").exists():
        label = (jobs.read_json(d / "chip.json").get("label") or "your chip").lower()
        dist = con.execute(f"SELECT min(abs(pos - ?)) FROM read_parquet({lit(d / 'chip.parquet')}) WHERE chrom = ?",
                           [snp["pos"], snp["chrom"]]).fetchone()[0]
        out["chip"] = (f"On {label}." if dist == 0 else f"The nearest marker of {label} is {tools._bp(dist)} away." if dist is not None
                       else f"No marker of {label} on this chromosome.")
    con.close()
    return out


# ---- adding a Table selection ----

@private
def add(request, key):
    """POST from the Table: copy the whole selection of results `key` (its rows, with their tiers for all
    conditions) into this browser's panel, starting one if needed, and go back to the Table."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    job = finished(key)
    jd = jobs.folder(key)
    query = results.selection(jd)
    req = results.selection_request(query)
    back = f"{reverse('snpportal:results', args=[key])}?{query + '&' if query else ''}tab=table"
    con, types, where, _ = results.open_result(req, key, write=True)
    n = con.execute(f"SELECT count(*) FROM v {where}").fetchone()[0]
    cap = int(jobs.setting("SNPPORTAL_MAX_PANEL_SNPS", 50_000))
    if not n or n > cap:
        return redirect(f"{back}&panel_error={'empty' if not n else 'many'}")
    rows = jd / f".panel-rows-{uuid.uuid4().hex}.parquet"
    con.execute(f"COPY (SELECT file_row_number FROM v {where}) TO '{rows}' (FORMAT parquet)")
    con.close()
    d = _folder(request)
    if d is not None and jobs.read_json(d / "panel.json").get("release") not in (None, job.get("release")):
        return redirect(f"{back}&panel_error=release")  # I17: a panel holds SNPs of one release
    d = d or _new()
    s = jobs.read_json(d / "panel.json")
    i = s["next"]
    try:
        _copy(jd, rows, d / f"source_{i}.parquet", i)
    finally:
        rows.unlink(missing_ok=True)
    s["sources"].append({"id": i, "job": str(key), "label": job.get("label") or "Results", "n": n, "selection": query,
                         "filters": [label for _, label, _ in results.filters(req, types, jobs.weights(jd))],
                         "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")), "added_utc": jobs.utc()})
    s["next"] = i + 1
    jobs._write_json(d / "panel.json", s)
    return _cookie(redirect(f"{back}&added={n}"), d)


def _copy(jd, rows, out, source):
    """source_<n>.parquet: the selected result rows with their tiers for all conditions (tier__all), the source id and
    the row in its results."""
    con = jobs.connect([jd, out.parent], out.parent)
    result, tiers = jd / "result.parquet", jd / "tiers.parquet"
    columns = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{result}'))").fetchall()]
    stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{tiers}'))").fetchall()] \
        if tiers.exists() else []
    picked = [c for c in jobs.TIER_COLUMNS if f"{c}__all" in stored]
    drop = ["file_row_number"] + [c for c in jobs.TIER_COLUMNS if c in columns and c in picked]
    tier_sql = "".join(f", t.{jobs.ident(c + '__all')} AS {c}" for c in picked)
    join = f"JOIN read_parquet('{tiers}') t USING (file_row_number)" if picked else ""
    tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}")
    con.execute(f"COPY (SELECT r.* EXCLUDE ({', '.join(drop)}){tier_sql}, {int(source)} AS panel_source, "
                f"r.file_row_number AS source_row FROM read_parquet('{result}', file_row_number=true) r "
                f"JOIN read_parquet('{rows}') s USING (file_row_number) {join}) TO '{tmp}' (FORMAT parquet)")
    con.close()
    tmp.chmod(0o600)
    os.replace(tmp, out)


# ---- the panel's SNPs ----

def _open(d):
    """(connection reading the panel folder and the release, writing only the folder; view p, or None when empty):
    p has one row per SNP kept in the panel (the first source's), `sources` (the source ids that hold it), snp_key
    (chrom:pos:ref:alt) and file_row_number in genome order; with a chip, also on_chip, dist_to_chip, near_chip and
    novel_functional (snp_panel.compare_sql). View pa also holds the SNPs dropped by hand (dropped: true), for the
    list to show them; downloads, the chip comparison and every count read p."""
    con = jobs.connect([d, jobs.release()], d)
    files = sorted(d.glob("source_*.parquet")) or [f for f in [d / "panel.parquet"] if f.exists()]  # or a saved version (I7)
    if not files:
        return con, None
    con.execute("CREATE VIEW u AS SELECT * FROM read_parquet([" + ", ".join(f"'{f}'" for f in files) + "], union_by_name=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE u)").fetchall()]
    same = ", ".join(["chrom", "pos"] + [f"coalesce({c}, '')" for c in ("ref", "alt") if c in columns])
    key = "concat_ws(':', " + ", ".join(["chrom", "pos"] + [f"coalesce({c}, '')" for c in ("ref", "alt") if c in columns]) + ")"
    dropped = [lit(k) for k in (jobs.read_json(d / "panel.json").get("dropped", []) if (d / "panel.json").exists() else [])]
    con.execute(f"""CREATE VIEW pa0 AS SELECT * EXCLUDE (_n), row_number() OVER (ORDER BY TRY_CAST(chrom AS INTEGER), chrom, pos) - 1
                    AS file_row_number, {key} AS snp_key, list_contains({'[' + ', '.join(dropped) + ']' if dropped else '[]::VARCHAR[]'}, {key})
                    AS dropped FROM (SELECT *, row_number() OVER (PARTITION BY {same} ORDER BY panel_source, source_row) AS _n,
                    list(DISTINCT panel_source) OVER (PARTITION BY {same}) AS sources FROM u) WHERE _n = 1""")
    pops = [(p["slug"], d / "populations" / f"{p['slug']}.parquet") for p in populations(d)
            if (d / "populations" / f"{p['slug']}.parquet").exists()]
    if pops and "ref" in columns and "alt" in columns:  # I9: the user's populations' frequencies, call rate and HWE p
        from .lib import population
        con.execute(f"CREATE VIEW pa1p AS {population.join_sql('pa0', pops)}")
    else:
        con.execute("CREATE VIEW pa1p AS SELECT * FROM pa0")
    if (d / "uniqueness.parquet").exists() and "paralog_identity" not in columns:  # I10: the probe uniqueness check
        con.execute(f"CREATE VIEW pa1 AS SELECT x.*, q.* EXCLUDE (snp_key) FROM pa1p x "
                    f"LEFT JOIN read_parquet({lit(d / 'uniqueness.parquet')}) q USING (snp_key)")
    else:
        con.execute("CREATE VIEW pa1 AS SELECT * FROM pa1p")
    con.execute("CREATE VIEW p0 AS SELECT * FROM pa1 WHERE NOT dropped")
    chip = d / "chip.parquet"
    if chip.exists():
        window = snp_panel.settings(jobs.weights())["chip_window"]
        con.execute(f"CREATE VIEW pa AS {snp_panel.compare_sql('pa1', f'read_parquet({chr(39)}{chip}{chr(39)})', window)}")
    else:
        con.execute("CREATE VIEW pa AS SELECT * FROM pa1")
    con.execute("CREATE VIEW p AS SELECT * FROM pa WHERE NOT dropped")
    con.execute("CREATE VIEW v AS SELECT * FROM p")  # tools.assay_readiness reads v
    return con, "p"


def _figure(con, d, chip, res, synthetic):
    """The panel along the genome (a mark per 250 kb, coloured by the best tier), with the chip's markers per Mb
    above it and its gaps highlighted when there is a chip."""
    rows = con.execute(f"SELECT chrom, pos // {BIN} * {BIN}, min(tier), count(*) FROM p GROUP BY ALL ORDER BY ALL").fetchall()
    marks = [(c, b, b + BIN, tools._tier_fill(t), f"{c}:{b / 1e6:.2f}–{(b + BIN) / 1e6:.2f} Mb: {n:,} SNPs (best tier {t})")
             for c, b, t, n in rows]
    counts = dict(con.execute("SELECT chrom, count(*) FROM p GROUP BY 1").fetchall())
    density, gaps = None, []
    legend = [(tools._tier_fill(t), figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)]
    if chip:
        top = max([n for _, _, n in chip["density"]] + [1])
        density = [(c, mb * 1_000_000, (mb + 1) * 1_000_000, n / top, f"{c}:{mb}–{mb + 1} Mb: {n:,} chip markers")
                   for c, mb, n in chip["density"]]
        gaps = [(g["chrom"], g["start"], g["end"], f"Chip gap {g['chrom']}:{g['start']:,}–{g['end']:,} ({tools._bp(g['size'])})")
                for g in res["gaps"]]
        legend += [(figures.mix(figures.palette.GREY[200], figures.palette.GREY[700], 0.6), "chip markers per Mb"),
                   tools._gap_legend(f"chip gap > {res['summary']['gap_bp'] / 1e6:g} Mb")]
    ends = con.execute("SELECT chrom, max(pos) FROM p GROUP BY 1").fetchall()
    return tools.coverage(tools._chroms(d, ends) if (d / "manifest.json").exists() else _chroms(ends), marks,
                          "Panel SNPs along the genome", "Panel SNPs per 250 kb, coloured by tier (all conditions)"
                          + ("; the chip's markers per Mb above, chip gaps highlighted" if chip else ""),
                          synthetic, gaps, density, counts, legend)


def _chroms(ends):
    """[(chrom, length)] from the release's chromosome sizes, with the panel's chromosomes in any case."""
    sizes = {k: int(v) for k, v in (jobs.manifest().get("chrom_sizes") or {}).items()}
    for c, end in ends:
        sizes[c] = max(sizes.get(c, 0), int(end))
    return [(c, sizes[c]) for c in sorted(sizes, key=results._chrom_key)]


# ---- the page ----

@private
def page(request):
    """/snp/panel/: the sources, the panel at a glance, the chip comparison, the assay check, the SNP list and the
    downloads; an empty panel says how to fill it."""
    d = _folder(request)
    ctx = {"nav": "panel", "title": "Design panel", "error": request.GET.get("error"), "local": jobs.local()}
    if jobs.local():  # saved projects (I7): the save form offers their names
        from . import projects
        ctx["projects"] = projects.everything()
    if d is None:
        return render(request, "snpportal/panel.html", ctx)
    s = jobs.read_json(d / "panel.json")
    con, rel = _open(d)
    ctx["populations"] = populations(d)
    ctx["genome"] = genome() is not None
    ctx["positions"] = jobs.position_choices()  # I18, I19: chips on another assembly
    chip = jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}
    synthetic = any(x.get("synthetic") for x in s["sources"]) or bool(chip.get("synthetic"))
    ctx.update(sources=[{**x, "url": f"{reverse('snpportal:projects')}#{x['project']}" if x.get("project") else
                         f"{reverse('snpportal:results', args=[x['job']])}?{x['selection'] + '&' if x['selection'] else ''}tab=table"}
                        for x in s["sources"]],
               meta=("Kept until you clear it" if jobs.keep_seconds() is None
                     else f"Deleted after {jobs.utc((d / 'created').stat().st_mtime + jobs.keep_seconds())}") + " · only this browser can open it",
               chip=chip, chip_demo=(jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv").is_file(),
               chip_error=tools.CHIP_ERRORS.get(request.GET.get("chip_error"), "").format(cap=f"{tools.chip_cap():,}") or None)
    if rel is None:
        return render(request, "snpportal/panel.html", ctx)
    types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE p)").fetchall())
    n = con.execute("SELECT count(*) FROM p").fetchone()[0]
    several = con.execute("SELECT count(*) FROM p WHERE len(sources) > 1").fetchone()[0]
    tiers = dict(con.execute("SELECT tier, count(*) FROM p GROUP BY 1").fetchall()) if "tier" in types else {}
    res = None
    if chip:
        pool = jobs.release() / "pool" / "pool.parquet"
        res = snp_panel.compare(con, d / "chip.parquet", "all", weights=jobs.weights(), table="p0", pool=pool if pool.exists() else None,
                                chrom_sizes=jobs.manifest().get("chrom_sizes"))
        cs = res["summary"]
        on = con.execute("SELECT count(*) FILTER (WHERE on_chip), count(*) FILTER (WHERE NOT on_chip) FROM p").fetchone()
        ctx["compare"] = [(f"{cs['chip_snps']:,}", "chip markers"), (f"{on[0]:,}", "already on the chip"),
                          (f"{on[1]:,}", "not on the chip"), (f"{cs['novel_functional']:,}", f"tier 1–2 with no chip marker within {tools._bp(cs['window_bp'])}"),
                          (f"{cs['gaps']:,}", f"chip gaps over {tools._bp(cs['gap_bp'])}")]
        ctx["chips"] = chips(d)
        if ctx["chips"]:
            ctx["matrix"] = _matrix(con, d, chip)
        params = _upgrade_params(request.GET, chip)
        ctx["upgrade_form"] = params
        if request.GET.get("upgrade"):
            rows, pop = _upgrade(con, d, params)
            ctx["upgrade"] = _upgrade_summary(rows, params, pop)
    every = request.GET.get("show") == "all"
    order = "genome" if request.GET.get("order") == "genome" else "problems"
    new_only = bool(chip) and request.GET.get("chip") == "new"
    dropped = con.execute("SELECT count(*) FROM pa WHERE dropped").fetchone()[0]
    ctx.update(n=n, several=several, tiers=sorted((t, k) for t, k in tiers.items() if t is not None),
               fig=mark_safe(_figure(con, d, chip, res, synthetic)),
               readiness=tools.assay_readiness(con, types, synthetic, lambda **_: None),
               rows=_rows(con, dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE pa)").fetchall()), s["sources"],
                          LISTED if every else SHOWN, order, new_only),
               more=None if every or n + dropped <= SHOWN else "?" + urlencode({k: v for k, v in (("show", "all"), ("order", order),
                                                                                         ("chip", "new" if new_only else "")) if v and v != "problems"}),
               order=order, new_only=new_only, dropped=dropped, uniqueness=uniqueness_summary(con, d, types),
               uniqueness_max=UNIQUENESS_MAX, ss4r="ss4r_ohnolog" in types,
               downloads=_downloads(con, chip, n))
    return render(request, "snpportal/panel.html", ctx)


def _rows(con, types, sources, limit, order="problems", new_only=False):
    """The panel's SNPs as display values, the dropped ones dimmed in their place (to put back): problems first by default
    (assay fail, warn, low MAF, LORe, another panel SNP closer than the panel designer's minimum spacing), else genome
    order; new_only: not on the chip. Each says how close the nearest other kept SNP is when it is that close."""
    names = {x["id"]: f"S{i + 1}" for i, x in enumerate(sources)}
    cfg = snp_panel.settings(jobs.weights())
    spacing, low = int(cfg["min_spacing"]), float(cfg["min_maf"])
    own = next((c for c in types if c.startswith("pop_") and c.endswith("_maf")), None)  # I9: the first own population
    extra = (own, own[:-3] + "call_rate", own[:-3] + "hwe_p", own[:-3] + "n") if own else ()
    cols = [c for c in ("chrom", "pos", "id", "ref", "alt", "gene_name", "gene_id", "gene_ortholog_human", "region_class", "coding_consequence",
                        "coding_hgvsp", "tier", "assay_status", "public_af_maf", "lore", "on_chip", "near_chip", "dist_to_chip", "sources",
                        "snp_key", "dropped", "paralog_identity", "paralog_left", "paralog_right", "paralog_at", "paralog_gene") + extra
            if c in types]
    limit_id = ((jobs.weights() or {}).get("assay") or {}).get("max_paralog_identity")  # I10: G's threshold, if set
    maf = own or ("public_af_maf" if "public_af_maf" in types else "NULL")
    lore = "coalesce(lore, false)" if "lore" in types else "false"
    sql = f"""WITH k AS (SELECT snp_key, chrom, pos, coalesce(nullif(id, '.'), chrom || ':' || pos) AS name FROM p),
              n AS (SELECT snp_key, pos - lag(pos) OVER w AS dp, lag(name) OVER w AS np, lead(pos) OVER w - pos AS dn,
                           lead(name) OVER w AS nn FROM k WINDOW w AS (PARTITION BY chrom ORDER BY pos)),
              c AS (SELECT snp_key, CASE WHEN dn IS NULL OR dp <= dn THEN dp ELSE dn END AS close_bp,
                           CASE WHEN dn IS NULL OR dp <= dn THEN np ELSE nn END AS close_to FROM n)
              SELECT {', '.join('a.' + x for x in cols)}, c.close_bp, c.close_to,
                     (a.assay_status = 'fail')::INT * 4 + (a.assay_status = 'warn')::INT * 2 + coalesce({maf} < {low}, false)::INT
                     + {lore}::INT + coalesce(c.close_bp <= {spacing}, false)::INT AS problems
              FROM pa a LEFT JOIN c USING (snp_key)
              {'WHERE NOT coalesce(a.on_chip, false)' if new_only and 'on_chip' in types else ''}
              ORDER BY {'problems DESC, ' if order == 'problems' else ''}a.file_row_number LIMIT {int(limit)}"""
    cur = con.execute(sql)
    names_ = [x[0] for x in cur.description]
    out = []
    for r in (dict(zip(names_, x)) for x in cur.fetchall()):
        g = r.get
        status = g("assay_status") or "not_checked"
        near = g("close_bp") is not None and g("close_bp") <= spacing and not g("dropped")
        chip = None if "on_chip" not in r else "on the chip" if g("on_chip") else (
            f"near · {tools._bp(g('dist_to_chip'))}" if g("near_chip") else "new")
        out.append({"key": g("snp_key"), "dropped": g("dropped"), "snp": g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos'):,}",
                    "position": f"{g('chrom')}:{g('pos'):,}", "alleles": results._alleles(g),
                    "gene": results.gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "region": results.region_text(g),
                    "tier": g("tier"), "assay": (results.ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "),)),
                    "maf": _maf_cell(g, own, low),
                    "lore": bool(g("lore")), "close": f"{tools._bp(g('close_bp'))} from {g('close_to')}" if near else "",
                    "chip": chip, "sources": " ".join(names.get(x, "?") for x in g("sources") or []),
                    "paralog": _paralog_cell(g, limit_id) if "paralog_gene" in r else None})
    return out


def _paralog_cell(g, limit):
    """(text, over G's threshold, tooltip) of the probe uniqueness check (I10), or None when the SNP was not checked or
    has no Ss4R duplicate gene."""
    if g("paralog_gene") is None and g("paralog_left") is None and g("paralog_right") is None:
        return ("no duplicate", False, "No Ss4R duplicate gene, or no close copy found in it") if g("snp_key") else None
    pct = lambda x: "< 89%" if x is None else f"{x:.0%}"  # noqa: E731
    ident = g("paralog_identity")
    tip = f"Best match in the Ss4R duplicate: left flank {pct(g('paralog_left'))}, right flank {pct(g('paralog_right'))}" \
        + (f", at {g('paralog_at')} ({g('paralog_gene')})" if g("paralog_at") else "")
    return (pct(ident), limit is not None and ident is not None and ident > float(limit), tip)


def _maf_cell(g, own, low):
    """(MAF text, below the designer's minimum, tooltip) from the user's population when there is one, else the public
    panel's; None when unknown."""
    if own:
        m = g(own)
        if m is None:
            return ("–", False, "Not in your population's file")
        base = own[:-3]
        tip = f"Your population: {g(base + 'n') or 0} fish" + (f", call rate {g(base + 'call_rate'):.2f}" if g(base + "call_rate") is not None else "") \
            + (f", HWE p {g(base + 'hwe_p'):.2g}" if g(base + "hwe_p") is not None else "") \
            + (f"; public panel {g('public_af_maf'):.2f}" if g("public_af_maf") is not None else "")
        return (f"{m:.2f}", m < low, tip)
    m = g("public_af_maf")
    return None if m is None else (f"{m:.2f}", m < low, "504 public fish, pooled")


def _downloads(con, chip, n):
    url = reverse("snpportal:panel_download")
    new = con.execute("SELECT count(*) FILTER (WHERE NOT on_chip) FROM p").fetchone()[0] if chip else None
    scopes = [("all", f"All panel SNPs ({n:,})")] + ([("new", f"Not on the chip ({new:,})")] if chip else [])
    return {"scopes": scopes, "formats": [("kasp", "KASP"), ("illumina", "Illumina"), ("axiom", "Axiom"), ("agena", "Agena"),
                                          ("primer3", "Primer3")],
            "tsv": f"{url}?format=tsv", "url": url}


# ---- changes: remove a source, the chip, clear ----

@csrf_exempt  # so the upload handler can be set before the body is read; _change checks the CSRF token
@private
def change(request):
    """POST: remove=<source id>, a chip (upload, demo=1, chip_remove=1), or clear=1 (the whole panel). A chip streams
    into the results dir like a SNP list (views.UploadToResults)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    handler = UploadToResults(request)
    request.upload_handlers = [handler]
    try:
        return _change(request)
    except Exception:
        request._files = MultiValueDict()  # keep uploaded file names out of error reports
        raise
    finally:
        handler.discard()


@csrf_protect
@sensitive_post_parameters()
def _change(request):
    d = _folder(request)
    back = redirect(reverse("snpportal:design_panel"))
    if d is None:
        return back
    if request.POST.get("clear"):
        shutil.rmtree(d, ignore_errors=True)
        back.delete_cookie(COOKIE)
        return back
    if request.POST.get("remove"):
        s = jobs.read_json(d / "panel.json")
        i = int(request.POST["remove"]) if request.POST["remove"].isdecimal() else -1
        s["sources"] = [x for x in s["sources"] if x["id"] != i]
        (d / f"source_{i}.parquet").unlink(missing_ok=True)
        jobs._write_json(d / "panel.json", s)
        return back
    if request.POST.get("drop") or request.POST.get("keep"):  # one SNP out of the panel, or back in
        s = jobs.read_json(d / "panel.json")
        out = set(s.get("dropped", []))
        out = out | {request.POST["drop"][:200]} if request.POST.get("drop") else out - {request.POST["keep"]}
        s["dropped"] = sorted(out)
        jobs._write_json(d / "panel.json", s)
        return redirect(reverse("snpportal:design_panel") + "?" + urlencode({k: v for k, v in request.POST.items() if k in ("order", "chip")})
                        + "#list-h")
    if request.POST.get("chip_remove"):
        for path in (d / "chip.parquet", d / "chip.json"):
            path.unlink(missing_ok=True)
        return back
    if request.POST.get("chip_extra_remove"):
        gone = request.POST["chip_extra_remove"]
        (d / "chips" / f"{gone}.parquet").unlink(missing_ok=True)
        jobs._write_json(d / "chips.json", {"chips": [c for c in chips(d) if c["slug"] != gone]})
        return redirect(reverse("snpportal:design_panel") + "#chip-h")
    if request.FILES.get("population") or request.POST.get("population_remove"):
        return _population(request, d)
    if request.POST.get("uniqueness"):
        return _uniqueness(d)
    return _chip(request, d)


UNIQUENESS_MAX = 5000  # SNPs checked at most (about 0.02 s each, from a local genome)


def genome():
    """The release's genome as a local file (the probe uniqueness check reads ~100 kb around every ohnolog), or None."""
    from snpscore.annotate import genome_location
    where = genome_location(jobs.manifest())
    return where if where and not str(where).startswith(("http://", "https://")) and Path(where).exists() else None


def _uniqueness(d):
    """POST uniqueness=1: lib.uniqueness.scan of the panel's SNPs (up to UNIQUENESS_MAX) against their Ss4R duplicate,
    written to uniqueness.parquet (snp_key and the paralog_* columns) and uniqueness.json."""
    from snpscore.fasta import Fasta
    from .lib import uniqueness
    back = reverse("snpportal:design_panel")
    where = genome()
    if where is None:
        return redirect(f"{back}?{urlencode({'error': 'The probe uniqueness check needs the genome on this computer (salmo-snp download).'})}")
    con, rel = _open(d)
    if rel is None:
        return redirect(back)
    types = {c for c, in con.execute("SELECT column_name FROM (DESCRIBE p)").fetchall()}
    if "ss4r_ohnolog" not in types:
        con.close()
        return redirect(f"{back}?{urlencode({'error': 'These results have no Ss4R duplicate genes (the ss4r layer).'})}")
    flank = "assay_flank" if "assay_flank" in types else "NULL"
    dist = "gene_distance" if "gene_distance" in types else "0"
    rows = con.execute(f"SELECT snp_key, chrom, pos, {dist}, ss4r_ohnolog, {flank} FROM p ORDER BY file_row_number "
                       f"LIMIT {UNIQUENESS_MAX}").fetchall()
    wanted = sorted({g for r in rows if r[4] for g in r[4].split(",")})
    genes = {}
    if wanted:
        genes = {g: (c, a, b) for g, c, a, b in con.execute(
            f"SELECT id, chrom, start, \"end\" FROM read_parquet({lit(jobs.release() / 'gene.parquet')}) WHERE list_contains(?, id)",
            [wanted]).fetchall()}
    snps = [{"key": k, "chrom": c, "pos": pos, "gene_distance": gd, "ohnologs": (o or "").split(",") if o else [], "assay_flank": f}
            for k, c, pos, gd, o, f in rows]
    found = uniqueness.scan(snps, genes, Fasta(where), flank=int(snp_assay_flank()))
    tmp = d / f".uniqueness-{uuid.uuid4().hex}.tsv"
    cols = ("paralog_identity", "paralog_left", "paralog_right", "paralog_at", "paralog_gene")
    with open(tmp, "w") as f:
        f.write("\t".join(("snp_key",) + cols) + "\n")
        for k, v in found.items():
            f.write("\t".join([k] + ["" if v[c] is None else str(v[c]) for c in cols]) + "\n")
    types = "{'snp_key': 'VARCHAR', 'paralog_identity': 'DOUBLE', 'paralog_left': 'DOUBLE', 'paralog_right': 'DOUBLE', " \
            "'paralog_at': 'VARCHAR', 'paralog_gene': 'VARCHAR'}"
    out = d / "uniqueness.parquet"
    try:
        con.execute(f"COPY (SELECT * FROM read_csv({lit(tmp)}, delim='\t', header=true, columns={types}, nullstr='')) "
                    f"TO {lit(d / '.uniqueness.parquet')} (FORMAT parquet)")
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    os.chmod(d / ".uniqueness.parquet", 0o600)
    os.replace(d / ".uniqueness.parquet", out)
    jobs._write_json(d / "uniqueness.json", {"checked": len(rows), "with_ohnolog": len(found), "capped": len(rows) == UNIQUENESS_MAX,
                                             "checked_utc": jobs.utc()})
    return redirect(f"{back}#uniq-h")


def snp_assay_flank():
    """The assay check's flank length (weights.yaml assay.flank: Axiom's 35 nt)."""
    return ((jobs.weights() or {}).get("assay") or {}).get("flank", 35)


def uniqueness_summary(con, d, types):
    """The probe uniqueness check's counts for the page and the report (None before it ran)."""
    if not (d / "uniqueness.json").exists() or "paralog_identity" not in types:
        return None
    info = jobs.read_json(d / "uniqueness.json")
    limit = ((jobs.weights() or {}).get("assay") or {}).get("max_paralog_identity")
    close, high, over = con.execute("SELECT count(paralog_identity), count(*) FILTER (WHERE paralog_identity >= 0.97), "
                                    "count(*) FILTER (WHERE paralog_identity > ?) FROM p", [2.0 if limit is None else float(limit)]).fetchall()[0]
    return {**info, "close": close, "high": high, "limit": limit, "over": over if limit is not None else None}


def populations(d):
    """[{slug, label, format, sites, fish, added_utc}] of the panel folder's own populations (I9; local installs)."""
    return jobs.read_json(d / "populations.json").get("populations", []) if (d / "populations.json").exists() else []


def _population(request, d):
    """POST population=<file> (VCF genotypes or a frequency table) with population_name, or population_remove=<slug>:
    per-SNP counts only (lib.population) in populations/<slug>.parquet; the upload is deleted once counted."""
    back = reverse("snpportal:design_panel")
    pops = populations(d)
    if request.POST.get("population_remove"):
        gone = request.POST["population_remove"]
        (d / "populations" / f"{gone}.parquet").unlink(missing_ok=True)
        jobs._write_json(d / "populations.json", {"populations": [p for p in pops if p["slug"] != gone]})
        return redirect(back)
    if not jobs.local():  # a server never takes genotypes, even as counts
        return redirect(f"{back}?error=Your own population is only for a copy of the portal on your computer.")
    from .lib import population
    upload = request.FILES["population"]
    label = (request.POST.get("population_name") or "My population").strip()[:40]
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:24] or "pop"
    (d / "populations").mkdir(mode=0o700, exist_ok=True)
    try:
        info = population.count(Path(upload.path), jobs.release(), d / "populations" / f"{slug}.parquet")
    except snpscore.InputError as e:
        return redirect(f"{back}?{urlencode({'error': str(e)})}")
    finally:
        Path(upload.path).unlink(missing_ok=True)
    pops = [p for p in pops if p["slug"] != slug] + [{"slug": slug, "label": label, **info, "added_utc": jobs.utc()}]
    jobs._write_json(d / "populations.json", {"populations": pops})
    return redirect(f"{back}#list-h")


def _chip(request, d):
    """The baseline chip: an uploaded SNP list (manifest, PLINK, VCF, table) or the release's demo chip. With
    extra=1, another chip to compare with it (I11: chips/<slug>.parquet, listed in chips.json)."""
    extra = bool(request.POST.get("extra"))
    demo, upload = jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv", request.FILES.get("chip")
    back = reverse("snpportal:design_panel") + ("#chip-h" if extra else "")
    if request.POST.get("demo") and demo.is_file():
        src, label, synthetic = demo, "Demo chip", True
    elif upload and upload.size:
        suffix = accepted_suffix(upload.name)
        if suffix is None:
            return redirect(f"{reverse('snpportal:design_panel')}?chip_error=type")
        src, label, synthetic = d / f".chip-input{suffix}", "Your chip", "SYNTHETIC" in upload.name
        os.replace(upload.path, src)
    else:
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error=missing")
    if extra:
        label = (request.POST.get("chip_name") or "").strip()[:40] or f"Chip {len(chips(d)) + 2}"
    new = d / ".chip-new.parquet"
    try:
        positions = request.POST.get("positions") or ("flank" if request.POST.get("by_flank") else None)  # I18, I19
        positions = positions if positions in jobs.POSITIONS and src != demo else None
        report = snp_panel.read_chip(src, jobs.release(), new, max_snps=tools.chip_cap(), place_by_flank=positions == "flank",
                                     lift_from="icsasg_v2" if positions == "icsasg_v2" else None)
    except (snpscore.InputError, duckdb.Error):
        new.unlink(missing_ok=True)
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error={positions or 'format'}")
    finally:
        if src != demo:
            src.unlink(missing_ok=True)
    if not report.get("snps_kept"):
        new.unlink(missing_ok=True)
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error=empty")
    os.chmod(new, 0o600)
    if extra:
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:24] or "chip"
        (d / "chips").mkdir(mode=0o700, exist_ok=True)
        os.replace(new, d / "chips" / f"{slug}.parquet")
        jobs._write_json(d / "chips.json", {"chips": [c for c in chips(d) if c["slug"] != slug] + [
            {"slug": slug, "label": label, "synthetic": synthetic, "kept": report["snps_kept"], "created_utc": jobs.utc(),
             **({"flank": report["flank"]} if report.get("flank") else {})}]})
        return redirect(back)
    con = jobs.connect([d], d)
    density = [list(x) for x in con.execute(f"SELECT chrom, (pos - 1) // 1000000, count(*) FROM read_parquet('{new}') "
                                            "GROUP BY ALL ORDER BY ALL").fetchall()]
    con.close()
    os.replace(new, d / "chip.parquet")
    jobs._write_json(d / "chip.json", {"label": label, "synthetic": synthetic, "kept": report["snps_kept"],
                                       "rejected": {k: v for k, v in (report.get("rejected") or {}).items() if v},
                                       "density": density, "created_utc": jobs.utc(),
                                       **({"flank": report["flank"]} if report.get("flank") else {}),
                                       **({"liftover": report["liftover"]} if report.get("liftover") else {})})
    return redirect(back)


def chips(d):
    """[{slug, label, synthetic, kept, created_utc}] of the other chips compared with the panel's chip (I11)."""
    return jobs.read_json(d / "chips.json").get("chips", []) if (d / "chips.json").exists() else []


def _matrix(con, d, chip):
    """The chips side by side (snp_panel.chip_matrix): the panel's chip, the other chips and the panel itself."""
    tmp = d / f".matrix-{uuid.uuid4().hex}.parquet"
    con.execute(f"COPY (SELECT chrom, pos, NULL::VARCHAR AS id FROM p) TO {lit(tmp)} (FORMAT parquet)")
    pool = jobs.release() / "pool" / "pool.parquet"
    others = [(c["label"], d / "chips" / f"{c['slug']}.parquet") for c in chips(d)]
    try:
        m = snp_panel.chip_matrix([(chip.get("label") or "Your chip", d / "chip.parquet")]
                                  + [x for x in others if x[1].exists()] + [("This panel", tmp)],
                                  pool=pool if pool.exists() else None, chrom_sizes=jobs.manifest().get("chrom_sizes"),
                                  window_bp=snp_panel.settings(jobs.weights())["chip_window"],
                                  gap_bp=snp_panel.settings(jobs.weights())["chip_gap"])
    finally:
        tmp.unlink(missing_ok=True)
    return {"rows": [{**r, "near": near} for r, (_, near) in zip(m["rows"], m["overlap"])], "labels": [x for x, _ in m["overlap"]],
            "pool": pool.exists(), "window": tools._bp(snp_panel.settings(jobs.weights())["chip_window"])}


def _upgrade_params(get, chip):
    """The Upgrade form's values (GET n, call_rate, hwe), each checked, with the panel designer's defaults."""
    p = snp_panel.settings(jobs.weights())

    def num(key, default, cast, lo, hi):
        try:
            v = cast(get.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(max(v, lo), hi)
    return {"n": num("n", chip.get("kept") or 0, int, 1, tools.chip_cap()),
            "call_rate": num("call_rate", p["upgrade_min_call_rate"], float, 0.0, 1.0),
            "hwe": num("hwe", p["upgrade_min_hwe_p"], float, 0.0, 1.0)}


def _upgrade(con, d, params):
    """snp_panel.upgrade of the panel's chip: its markers QC'd in your first population (when there is one; else all
    kept), the panel's SNPs not on the chip as candidates. Returns (rows, the population's label or None)."""
    pops = [x for x in populations(d) if (d / "populations" / f"{x['slug']}.parquet").exists()]
    columns = {c for c, in con.execute("SELECT column_name FROM (DESCRIBE p)").fetchall()}
    ident = "coalesce(id::VARCHAR, snp_key)" if "id" in columns else "snp_key"
    tmp = d / f".candidates-{uuid.uuid4().hex}.parquet"
    con.execute(f"""COPY (SELECT chrom, pos, {ident} AS id, {'tier' if 'tier' in columns else 'NULL::INTEGER'} AS tier,
                    {'tier_score' if 'tier_score' in columns else 'NULL::INTEGER'} AS tier_score FROM p
                    {'WHERE NOT on_chip' if 'on_chip' in columns else ''}) TO {lit(tmp)} (FORMAT parquet)""")
    p = snp_panel.settings(jobs.weights())
    try:
        rows = snp_panel.upgrade(d / "chip.parquet", tmp, qc=d / "populations" / f"{pops[0]['slug']}.parquet" if pops else None,
                                 n_target=params["n"], min_call_rate=params["call_rate"], min_hwe_p=params["hwe"],
                                 min_spacing_bp=p["min_spacing"], gap_bp=p["chip_gap"], chrom_sizes=jobs.manifest().get("chrom_sizes"))
    finally:
        tmp.unlink(missing_ok=True)
    return rows, pops[0]["label"] if pops else None


def _upgrade_summary(rows, params, pop):
    actions = {a: sum(r["action"] == a for r in rows) for a in ("keep", "drop", "add")}
    return {**actions, "n": actions["keep"] + actions["add"], "params": params, "pop": pop, "full": actions["keep"] >= params["n"],
            "gap": sum(r["action"] == "add" and r["reason"] == "fills a chip gap" for r in rows),
            "dropped": [r for r in rows if r["action"] == "drop"][:10], "added": [r for r in rows if r["action"] == "add"][:10],
            "url": f"{reverse('snpportal:panel_upgrade')}?{urlencode({k: v for k, v in params.items()})}"}


@private
def upgrade(request):
    """GET ?n=&call_rate=&hwe=: the upgraded chip as a TSV (chrom, pos, id, action, reason, tier), every marker kept or
    dropped and every SNP added, with the settings in '#' lines."""
    d = _folder(request)
    if d is None or not (d / "chip.parquet").exists():
        raise Http404("No panel chip to upgrade")
    con, rel = _open(d)
    if rel is None:
        raise Http404("The panel is empty")
    chip = jobs.read_json(d / "chip.json")
    params = _upgrade_params(request.GET, chip)
    rows, pop = _upgrade(con, d, params)
    con.close()
    s = _upgrade_summary(rows, params, pop)
    head = [f"# salmobase functional SNP portal: Design panel, upgrade of {chip.get('label') or 'your chip'}",
            f"# {', '.join(f'{k} {v}' for k, v in snp_export.installed().items())}; release {jobs.manifest().get('version', '?')}",
            f"# {s['keep']:,} markers kept, {s['drop']:,} dropped, {s['add']:,} added ({s['gap']:,} in chip gaps): {s['n']:,} in all",
            f"# QC in {pop}: call rate >= {params['call_rate']:g}, HWE p >= {params['hwe']:g}" if pop
            else "# no population of yours: every marker kept (add one on the Design panel to check call rate and HWE)",
            "# candidates: the panel's SNPs not on the chip, chip gaps first, then by tier and tier score, "
            f"{snp_panel.settings(jobs.weights())['min_spacing']:,} bp apart at least",
            "# PROVISIONAL thresholds (weights.yaml design): to confirm"]
    if any(x.get("synthetic") for x in jobs.read_json(d / "panel.json")["sources"]) or chip.get("synthetic"):
        head.append("# SYNTHETIC: made from a synthetic list or chip")
    body = ["\t".join(("chrom", "pos", "id", "action", "reason", "tier"))] + [
        "\t".join("" if r[k] is None else str(r[k]) for k in ("chrom", "pos", "id", "action", "reason", "tier")) for r in rows]
    response = HttpResponse("\n".join(head + body) + "\n", content_type="text/tab-separated-values")
    response["Content-Disposition"] = 'attachment; filename="chip_upgrade.tsv"'
    return response


# ---- downloads ----

@private
def download(request):
    """?format=tsv (the panel's SNPs with their annotations: score that file again to keep the panel beyond 24
    hours) or kasp, illumina, axiom; ?scope=new: only the SNPs not on the chip."""
    d = _folder(request)
    fmt = request.GET.get("format", "tsv")
    if d is None or fmt not in ("tsv", *tools.VENDORS):
        raise Http404("No panel, or no such format")
    con, rel = _open(d)
    if rel is None:
        raise Http404("The panel is empty")
    scope = request.GET.get("scope") if request.GET.get("scope") in SCOPES and (d / "chip.parquet").exists() else "all"
    con.execute("CREATE VIEW out AS SELECT * EXCLUDE (panel_source, source_row, sources) FROM p"  # the panel's own columns stay out
                + (" WHERE NOT on_chip" if scope == "new" else ""))
    table = "out"
    s = jobs.read_json(d / "panel.json")
    meta = {"tool": "salmobase functional SNP portal: Design panel", "preset": "all", "panel": f"{len(s['sources'])} sources",
            "filters": {"scope": SCOPES[scope]}, "synthetic": any(x.get("synthetic") for x in s["sources"]), "created_utc": s.get("created_utc")}
    name = f"panel_{scope}_{fmt}.{'tsv' if fmt == 'tsv' else snp_export.filename(fmt, 'release', 'all', None).rsplit('.', 1)[1]}"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".export-", suffix="." + name.rsplit(".", 1)[1])
    os.close(fd)
    try:
        snp_export.export(con, fmt, tmp, jobs.release(), "all", meta, request.GET.get("include_failed") == "1",
                          request.GET.get("plain") == "1", table=table, sidecars=False)
        f = open(tmp, "rb")
    except snpscore.InputError as e:
        return render(request, "snpportal/stub.html", {"nav": "panel", "title": "Export not possible", "message": str(e)}, status=400)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return FileResponse(f, as_attachment=True, filename=name, content_type=tools.MIME.get(fmt, "text/plain"))
