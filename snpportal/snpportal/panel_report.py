"""A printable design report per panel (ROADMAP I12): the working Design panel (/snp/panel/report/) or a saved project
version (/snp/projects/<name>/<n>/report/, local installs). One page per panel, like the results report: what it is
for (sources, note, the designer's settings), markers per chromosome with their spacing in bp and cM, MAF (public and
the user's population), the assay check, functional content, the chip it is compared with or upgrades, what changed
since the previous version, and provenance. portal.css /* report */ lays it out for A4; every number comes from the
panel's own files (panel._open)."""
from __future__ import annotations

import statistics

import snpscore
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import jobs, panel, tools
from .lib import export as snp_export
from .lib import panel as snp_panel
from .views import private

MAF_BINS = ((0, 0.01, "< 0.01"), (0.01, 0.05, "0.01–0.05"), (0.05, 0.1, "0.05–0.1"), (0.1, 0.3, "0.1–0.3"), (0.3, 0.51, "0.3–0.5"))


def _maf_bins(con, column):
    rows = con.execute(f"SELECT {jobs.ident(column)} FROM p").fetchall()
    values = [r[0] for r in rows]
    known = [x for x in values if x is not None]
    return {"bins": [(label, sum(lo <= x < hi for x in known)) for lo, hi, label in MAF_BINS],
            "unknown": len(values) - len(known), "median": round(statistics.median(known), 3) if known else None}


def _chromosomes(con, types):
    """[{chrom, markers, median, largest (spacing as text), median_cm, span_cm}] in genome order: cM spacing on the sex-averaged map when the panel
    has annotate's cm columns."""
    cm = snp_panel.CM_MAPS["mean"] if {"cm_male", "cm_female"} <= set(types) else "NULL::DOUBLE"
    rows = con.execute(f"""SELECT chrom, count(*), median(d), max(d), median(dcm), max(c) - min(c) FROM (
                               SELECT chrom, pos - lag(pos) OVER w AS d, {cm} AS c, c - lag(c) OVER w AS dcm FROM p
                               WINDOW w AS (PARTITION BY chrom ORDER BY pos)) GROUP BY chrom
                           ORDER BY TRY_CAST(chrom AS INTEGER), chrom""").fetchall()
    return [{"chrom": c, "markers": n, "median": None if md is None else tools._bp(md), "largest": None if mx is None else tools._bp(mx),
             "median_cm": None if mc is None else round(mc, 2), "span_cm": None if span is None or n < 2 else round(span, 1)}
            for c, n, md, mx, mc, span in rows]


def build(d, title, note=None, previous=None, synthetic=False):
    """The report's numbers for the panel in folder d (a working panel or a version folder)."""
    con, rel = panel._open(d)
    if rel is None:
        con.close()
        raise Http404("The panel is empty")
    types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE p)").fetchall())
    n = con.execute("SELECT count(*) FROM p").fetchone()[0]
    out = {"title": title, "note": note, "n": n, "chroms": _chromosomes(con, types), "has_cm": {"cm_male", "cm_female"} <= set(types),
           "settings": snp_panel.settings(jobs.weights())}
    out["tiers"] = sorted(con.execute("SELECT tier, count(*) FROM p WHERE tier IS NOT NULL GROUP BY 1").fetchall()) if "tier" in types else []
    if "region_class" in types:
        out["regions"] = con.execute("SELECT coalesce(region_class, 'intergenic'), count(*) FROM p GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()
    out["known"] = con.execute("SELECT count(*) FROM p WHERE known_locus IS NOT NULL").fetchone()[0] if "known_locus" in types else None
    out["mafs"] = [("Public panel", _maf_bins(con, "public_af_maf"))] if "public_af_maf" in types else []
    pops = panel.populations(d)
    for x in pops:
        column = f"pop_{x['slug']}_maf"
        if column in types:
            b = _maf_bins(con, column)
            c = f"pop_{x['slug']}_"
            call_rate, hwe_low = con.execute(f'SELECT avg("{c}call_rate"), count(*) FILTER (WHERE "{c}hwe_p" < ?) FROM p',
                                             [out["settings"]["upgrade_min_hwe_p"]]).fetchall()[0]
            b.update(call_rate=None if call_rate is None else round(call_rate, 3), hwe_low=hwe_low)
            out["mafs"].append((x["label"], b))
    out["uniqueness"] = panel.uniqueness_summary(con, d, types)
    readiness = tools.assay_readiness(con, types, synthetic, lambda **_: None)
    out["readiness"] = {"svg": mark_safe(readiness["svg"]), "line": readiness["line"]} if readiness else None
    chip = jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}
    res = None
    if chip:
        pool = jobs.release() / "pool" / "pool.parquet"
        res = snp_panel.compare(con, d / "chip.parquet", "all", weights=jobs.weights(), table="p0", pool=pool if pool.exists() else None,
                                chrom_sizes=jobs.manifest().get("chrom_sizes"))
        on = con.execute("SELECT count(*) FILTER (WHERE on_chip), count(*) FILTER (WHERE NOT on_chip) FROM p").fetchone()
        out["chip"] = {"label": chip.get("label") or "your chip", "markers": res["summary"]["chip_snps"], "on": on[0], "new": on[1],
                       "novel": res["summary"]["novel_functional"], "window": tools._bp(res["summary"]["window_bp"]),
                       "gaps": res["summary"]["gaps"], "gap": tools._bp(res["summary"]["gap_bp"]),
                       "others": [c["label"] for c in panel.chips(d)]}
    out["fig"] = mark_safe(panel._figure(con, d, chip, res, synthetic))
    con.close()
    out["previous"] = previous
    m = jobs.manifest()
    out["provenance"] = [f"Release {m.get('version')} ({m.get('assembly', 'Ssal_v3.1')}); weights "
                         f"{(jobs._file('sha256', snpscore.score.WEIGHTS) or 'none')[:12]} (provisional rules)",
                         ", ".join(f"{k} {v}" for k, v in snp_export.installed().items()) + f"; printed {jobs.utc()}"]
    out["synthetic"] = synthetic
    return out


def _render(request, ctx, back):
    return render(request, "snpportal/panel_report.html", {"nav": "panel", "title": f"Design report · {ctx['title']}", "r": ctx,
                                                            "actions": [{"label": "Back", "url": back}],
                                                            "meta": f"{ctx['n']:,} SNPs · printed {jobs.utc()}"})


@private
def report(request):
    """/snp/panel/report/: the working Design panel's report."""
    d = panel._folder(request)
    if d is None:
        raise Http404("No panel")
    s = jobs.read_json(d / "panel.json")
    chip = jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}
    synthetic = any(x.get("synthetic") for x in s["sources"]) or bool(chip.get("synthetic"))
    ctx = build(d, "Design panel", note="Sources: " + "; ".join(x["label"] for x in s["sources"]), synthetic=synthetic)
    return _render(request, ctx, reverse("snpportal:design_panel"))


@private
def project_report(request, name, n):
    """/snp/projects/<name>/<n>/report/: a saved version's report, with what changed since the version before it."""
    from . import projects
    d = projects.project(name)
    v = d / f"v{n}"
    if not (v / "meta.json").exists():
        raise Http404("No such version")
    meta, title = jobs.read_json(v / "meta.json"), jobs.read_json(d / "project.json").get("name", d.name)
    earlier = [x["version"] for x in projects.versions(d) if x["version"] < n]
    previous = None
    if earlier:
        added, removed = projects.diff(d, max(earlier), n)
        previous = {"version": max(earlier), "added": len(added), "removed": len(removed)}
    chip = jobs.read_json(v / "chip.json") if (v / "chip.json").exists() else {}
    note = " · ".join(x for x in [meta.get("note"), "Sources: " + "; ".join(meta.get("sources") or []) if meta.get("sources") else None,
                                  f"saved {meta.get('created_utc')}"] if x)
    ctx = build(v, f"{title}, version {n}", note=note, previous=previous, synthetic=bool(chip.get("synthetic")))
    if meta.get("release") and meta["release"] != jobs.manifest().get("version"):
        ctx["provenance"].insert(0, f"Saved with release {meta['release']}: the chip comparison uses the release in use now")
    return _render(request, ctx, f"{reverse('snpportal:projects')}?project={d.name}")
