"""Locus browser (P4.3a/b), evidence card and variant page (P4.4a).

- /snp/locus/?r=25:28980000-29010000[&trait=][&assay=ATAC|H3K27ac|H3K4me3][&hmm=1][&scale=track][&key=<job>[&row=]]
  draws the release's lanes, the job's SNPs (tier lollipops, only with key=) and live salmobase signal rows; without a
  region it opens at vgll3. &slim=1 draws the card's mini view (genes and the trait's chromatin rows).
  htmx swaps #locus-view from /snp/locus/svg/ (same parameters); without htmx that URL is the SVG file.
- Signal and ChromHMM come from tracks.yaml through snpscore.locus on a fixed public tile grid, cached in the Django
  cache 'snpportal_tiles' (if configured) or a LocMemCache of 5,000 entries. Views opened from a job (key=) only read
  that cache: their tiles would record, for days, where the job's SNPs are.
- The evidence card is addressed by job and row, so its URLs (and the mini locus') carry no coordinates.
- /snp/variant/<chrom>-<pos>[-ref-alt]/ annotates one position against the release on the fly, without a job."""
from __future__ import annotations

import re
import time
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template import engines
from django.urls import reverse
from django.utils.safestring import mark_safe

import snpscore
from snpscore import locus as sl
from snpscore import tracks as st
from snpscore.formats import lit
from snpscore.score import NOT_CONDITIONS, preset_conditions

from . import explore, figures, jobs, locus_svg, results
from .views import finished, private

DEFAULT_WIDTH = 10_000  # a single position opens this wide
DEFAULT_REGION = "25:28985000-29010000"  # the locus browser opens here (vgll3) when no region is given
FULL = {"published", "molqtl", "regbuild", "gerp", "variants", "signal", "snps"}  # the locus browser's optional lanes
REGION_LANES = {"published", "gerp"}  # the regional association plot (its association lane is drawn on top)
CARD_LANES = set()  # the card's mini view: genes and the trait's chromatin rows (and a GWAS job's association lane)
CARD_FLANK = 5_000  # mini locus: the SNP +- this
COMPACT_WIDTH = 640  # the card's mini locus and the landing figure: about the width they are shown at (no shrunk text)
ASSAYS = ("ATAC", "H3K27ac", "H3K4me3")
MAX_SNPS = 5_000  # user SNPs drawn per view
VARIANT = re.compile(r"^(\w{1,40})-(\d{1,10})(?:-([ACGTNacgtn]{1,50})-([ACGTNacgtn]{1,50}))?$")
JBROWSE = ("https://salmobase.org/jbrowse/?assembly=Ssal_v3.1&loc={chrom}:{start}..{end}"
           "&tracks=Ssal_v3.1-Ensembl-FeatureTrack,Ssal_v3.1-NCBI-FeatureTrack")
ENSEMBL = "https://www.ensembl.org/Salmo_salar/Location/View?r={chrom}:{start}-{end}"
MOLQTL_KINDS = {"e": "eQTL (gene expression)", "ca": "caQTL (chromatin accessibility)"}
MOLQTL = re.compile(r"^(\w+) (ca|e) (\S+) \(BF ([^,]+), pi ([^)]+)\)$")  # one feature of molqtl_features
_TILES = LocMemCache("snpportal-tiles", {"TIMEOUT": 7 * 86400, "OPTIONS": {"MAX_ENTRIES": 5000}})
_fragment = []


def tile_cache(read_only=False):
    """The Django cache 'snpportal_tiles' when settings.CACHES has it, else a process-local LocMemCache (5,000 tiles);
    read_only: a view of it that never stores a tile."""
    cache = caches["snpportal_tiles"] if "snpportal_tiles" in getattr(settings, "CACHES", {}) else _TILES
    return ReadOnly(cache) if read_only else cache


class ReadOnly:
    """A tile cache that reads tiles others stored and stores none."""

    def __init__(self, cache):
        self.cache = cache

    def get_many(self, keys):
        return self.cache.get_many(keys)

    def set_many(self, values):
        pass


def fragment():
    """A layout with only the 'main' block, so locus.html renders the part that htmx swaps."""
    if not _fragment:
        _fragment.append(engines["django"].from_string("{% block main %}{% endblock main %}").template)
    return _fragment[0]


def registry():
    """tracks.yaml of the release, or SNPPORTAL_TRACKS (a file) when set; None when there is none."""
    try:
        return st.load_tracks(jobs.setting("SNPPORTAL_TRACKS", None) or jobs.release())
    except (OSError, ValueError):
        return None


def synthetic_track(t):
    return "SYNTHETIC" in (t.get("url", "") + t.get("source", "") + t.get("id", ""))


def pick_tracks(cfg, trait, assay):
    """At most defaults.max_rows (8) tracks of one assay (replicate R1) for the preset's conditions: tracks.yaml
    defaults.presets[trait] if listed, else the preset's weights.yaml condition prefixes (PROVISIONAL)."""
    d = cfg.get("defaults", {})
    conditions = d.get("presets", {}).get(trait)
    if conditions is None:
        conditions = ((jobs.weights() or {}).get("presets") or {}).get(trait)
    return st.select(cfg, assay, conditions or None, d.get("replicate", "R1"), d.get("max_rows", 8))


def region_text(chrom, start, end, commas=False):
    """'25:28980000-29010000' (1-based, for URLs) from BED coordinates; with commas for people."""
    return f"{chrom}:{start + 1:,}-{end:,}" if commas else f"{chrom}:{start + 1}-{end}"


# ---- view state from whitelisted URL parameters ----

def view_state(request):
    """{chrom, start, end (BED), trait, assay, hmm, scale, key, row, error, too_wide, mark, compact} from ?r= (also
    ?region= or ?chrom=&start=&end=, 1-based), or the SNP in ?key=&row=."""
    g = request.GET
    presets = dict(jobs.presets())
    s = {"trait": g.get("trait") if g.get("trait") in presets else "all", "assay": g.get("assay") if g.get("assay") in ASSAYS else "ATAC",
         "hmm": g.get("hmm") == "1", "scale": "track" if g.get("scale") == "track" else "shared", "key": None, "row": None,
         "chrom": None, "error": None, "too_wide": False, "compact": g.get("compact") == "1", "slim": g.get("slim") == "1",
         "mark": int(g["mark"]) if g.get("mark", "").isdecimal() else None, "gwas": {}}
    if g.get("key"):
        try:
            finished(g["key"])
        except (ValueError, Http404):
            raise Http404("Result not found or expired") from None
        s["key"] = str(uuid.UUID(g["key"]))  # canonical, as URLs spell it
        s["row"] = int(g["row"]) if g.get("row", "").isdecimal() else None
        s["gwas"] = results.gwas_settings(request)  # a GWAS job's fine-mapping settings, kept by every link
    text = g.get("r") or g.get("region") or (f"{g['chrom']}:{g.get('start', '')}-{g.get('end', '')}" if g.get("chrom") else "")
    try:
        if text:
            chrom, start, end = sl.parse_region(text[:200], jobs.release())
        elif s["key"] and s["row"] is not None:
            con = results.open_result(request, s["key"])[0]
            hit = con.execute("SELECT chrom, pos FROM v WHERE file_row_number = ?", [s["row"]]).fetchone()
            if hit is None:
                raise Http404("No such SNP")
            chrom, start, end = hit[0], hit[1] - 1, hit[1]
            s["mark"] = hit[1]
        else:
            chrom, start, end = sl.parse_region(DEFAULT_REGION, jobs.release())
    except ValueError as e:
        s["error"] = str(e)
        return s
    size = (jobs.manifest().get("chrom_sizes") or {}).get(chrom)
    if end - start == 1:
        start, end = sl.clamp(start, end, size, DEFAULT_WIDTH)
    start, end = sl.clamp(start, end, size)
    s.update(chrom=chrom, start=start, end=end, size=size, too_wide=end - start > sl.MAX_WINDOW)
    return s


def query(s, **changes):
    """URL parameters of the view s, with changes (start/end in BED coordinates)."""
    start, end = changes.pop("start", s["start"]), changes.pop("end", s["end"])
    params = {"r": region_text(s["chrom"], start, end), "trait": s["trait"], "assay": s["assay"],
              "hmm": "1" if s["hmm"] else "", "scale": "track" if s["scale"] == "track" else "", "key": s["key"] or "",
              **s.get("gwas", {})}
    params.update(changes)
    return urlencode({k: v for k, v in params.items() if v not in ("", None, "all", "ATAC")})


def moves(s):
    """Toolbar: (label, query, title) for zoom in x3, out x3 and x10, and pan by half a window."""
    w, mid = s["end"] - s["start"], (s["start"] + s["end"]) // 2
    span = lambda width, centre=mid: sl.clamp(centre - width // 2, centre + width - width // 2, s.get("size"), sl.MIN_WINDOW, sl.MAX_WINDOW)
    out = []
    for label, (a, b), title in [("Zoom in", span(w // 3), "zoom in 3x"), ("Out ×3", span(w * 3), "zoom out 3x"),
                                 ("Out ×10", span(w * 10), "zoom out 10x"), ("◀ Left", span(w, mid - w // 2), "move left half a window"),
                                 ("Right ▶", span(w, mid + w // 2), "move right half a window")]:
        if (a, b) != (s["start"], s["end"]):
            out.append((label, query(s, start=a, end=b), title))
    return out


# ---- the figure ----

def user_snps(request, s, link=True):
    """The job's SNPs in the window, with tiers for the preset; drawn at render time, never cached."""
    if not s["key"]:
        return []
    con, types = results.open_result(request, s["key"])[:2]
    optional = ", ".join(c if c in types else f"NULL AS {c}" for c in ("id", "ref", "alt"))  # lists may lack them
    terms = "tier_terms" if "tier_terms" in types else "NULL"
    rows = con.execute(f"""SELECT file_row_number, {optional}, pos, tier, tier_score, tier_evidence, {terms} FROM v
                           WHERE chrom = ? AND pos > ? AND pos <= ? ORDER BY tier NULLS LAST, pos LIMIT {MAX_SNPS}""",
                       [s["chrom"], s["start"], s["end"]]).fetchall()
    out = []
    for row, sid, ref, alt, pos, tier, score, evidence, fired in rows:
        evidence = results.evidence_text(evidence, fired)
        alleles = f" {ref}>{alt}" if ref else ""
        out.append({"pos": pos, "id": sid, "tier": tier, "tier_score": score,
                    "title": f"{sid or '(no id)'} · {s['chrom']}:{pos:,}{alleles} · tier {tier} (score {score}): {evidence or 'no evidence'}",
                    "url": f"{reverse('snpportal:card', args=[s['key'], row])}?{urlencode({'trait': s['trait'], **s.get('gwas', {})})}" if link else None})
    return out


def molqtl_rows(chrom, start, end):
    """molQTL leads (molqtl.parquet) in a window, BED coordinates: [{pos, tissues, kinds, best_bf, title}]."""
    path = jobs.release() / "molqtl.parquet"
    if not path.exists():
        return []
    rows = jobs.connect([jobs.release()]).execute(
        f"SELECT \"end\", ref, alt, tissues, kinds, best_bf, features FROM read_parquet({lit(path)}) "
        "WHERE chrom = ? AND \"end\" > ? AND \"end\" <= ? ORDER BY \"end\"", [chrom, start, end]).fetchall()
    return [{"pos": pos, "tissues": tissues, "kinds": kinds, "best_bf": bf,
             "title": f"{chrom}:{pos:,} {ref}>{alt} · molQTL lead (nf-RASQUAL, 12 fish): {features}"}
            for pos, ref, alt, tissues, kinds, bf, features in rows]


def lanes(chrom, start, end):
    """snpscore.locus lanes plus the evidence kind of each published association and the molQTL leads."""
    data = sl.locus(jobs.release(), chrom, start, end)
    names = explore.aliases()
    for g in data.get("genes", []):  # one label per gene everywhere: the catalogue's name for genes Ensembl leaves unnamed
        if not g.get("name") and g.get("id") in names:
            g["label"] = names[g["id"]]
    for k in data.get("known", []):
        k["kind"] = explore.evidence_kind(k)
    data["molqtl"] = molqtl_rows(chrom, start, end)
    return data


def draw(request, s, download=False, show=FULL):
    """(svg, notes, synthetic) for the view s. `show`: the optional lanes (FULL, REGION_LANES or CARD_LANES); outside
    the locus browser only the trait's chromatin rows are drawn (all 21 for 'all'). On screen the figure carries no
    title or provenance lines (the page has them; a download keeps them)."""
    info = jobs.release_info()
    data = lanes(s["chrom"], s["start"], s["end"])
    weights = jobs.weights()
    chosen = set(preset_conditions(weights, [f"chromatin_{c}" for c in data["conditions"]], s["trait"])[0]) if weights else set()
    if show is not FULL and chosen:
        data["conditions"] = [c for c in data["conditions"] if c in chosen]
    notes, synthetic = [], bool(info.get("synthetic"))
    cfg, width = registry(), s["end"] - s["start"]
    signal = hmm = None
    deadline = float(jobs.setting("SNPPORTAL_SIGNAL_DEADLINE", 4.0))
    prefix = f"snpportal:{(info.get('sha256') or 'release')[:12]}"
    tiles = tile_cache(read_only=bool(s["key"]))  # a view opened from a job may centre on one of its SNPs
    live = "signal" in show  # live salmobase rows: the locus browser only
    if live and cfg is None:
        notes.append("This release lists no signal tracks, so no signal rows are shown.")
    elif live and width > sl.MAX_SIGNAL:
        signal = {"title": f"{s['assay']} signal", "rows": [], "note": f"Zoom in to {sl.MAX_SIGNAL // 1000} kb or less to see signal"}
    elif live:
        picked, t0 = pick_tracks(cfg, s["trait"], s["assay"]), time.monotonic()
        read = sl.signal(picked, s["chrom"], s["start"], s["end"], tiles, prefix, deadline)
        rows = [{"track": t, "values": v, "label": " ".join(locus_svg.condition_label(t["condition"])) + f" {t.get('replicate') or ''}"
                 + (" SYNTHETIC" if synthetic_track(t) else "")} for t, v in zip(picked, read["values"])]
        signal = {"title": f"{s['assay']} signal", "subtitle": "salmobase, live", "rows": rows, "start": read["start"],
                  "rung": read["rung"], "scale": s["scale"],
                  "note": "" if picked else f"No {s['assay']} tracks for this trait"}
        synthetic = synthetic or any(synthetic_track(t) for t in picked)
        failed = sum(r["values"] is None for r in rows)
        if failed:
            notes.append(f"{failed} of {len(rows)} signal rows are unavailable: salmobase did not answer within {deadline:g} s. "
                         "Reload to try again; signal is never filled in.")
        if s["hmm"]:
            by_condition = {t["condition"]: t for t in cfg.get("chromhmm", [])}
            have = [by_condition[c] for c in data["conditions"] if c in by_condition]
            left = max(1.0, deadline - (time.monotonic() - t0))  # signal and segments share the deadline
            found = dict(zip([t["condition"] for t in have], sl.segments(have, s["chrom"], s["start"], s["end"], tiles, prefix, left)))
            hmm = [{"condition": c, "segments": found.get(c)} for c in data["conditions"]]
            synthetic = synthetic or any(synthetic_track(t) for t in have)
            if any(r["segments"] is None for r in hmm):
                notes.append("ChromHMM segmentation is unavailable for some conditions (hatched rows).")
    if live and s["hmm"] and width > sl.MAX_SIGNAL:
        notes.append(f"ChromHMM segmentation is read in windows up to {sl.MAX_SIGNAL // 1000} kb; showing states in peaks.")
    gwas = None
    if s["key"]:
        from . import association  # a GWAS job draws its association lane instead of the tier lollipops (P7.3)
        job = jobs.read(s["key"])
        synthetic = synthetic or bool(job.get("synthetic_input") or job.get("synthetic_layers"))
        gwas = association.browser_lane(request, s["key"], s["chrom"], s["start"], s["end"], link=not download)
    snps = [] if gwas or "snps" not in show else user_snps(request, s, link=not download)
    caption = provenance(info, cfg)
    title = f"Chromosome {s['chrom']}: {s['start'] + 1:,}-{s['end']:,} ({locus_svg.fmt_bp(width)})"
    svg = locus_svg.locus(
        data, title=title, caption=caption if download else "", desc=f"{title}. {caption}", snps=snps,
        snp_note=f"tiers: {s['trait'].replace('_', ' ')}" if snps else "", signal=signal, hmm=hmm, chosen=chosen, mark=s["mark"],
        gene_url=None if download else (lambda gid: reverse("snpportal:gene", args=[gid])), compact=s["compact"],
        width=COMPACT_WIDTH if s["compact"] else locus_svg.WIDTH, gutter=118 if s["compact"] else locus_svg.GUTTER, synthetic=synthetic,
        gwas=gwas, lanes=None if show is FULL else show, heading=download)
    return svg, notes, synthetic


def provenance(info, cfg):
    when = (cfg or {}).get("generated")
    return (f"salmobase functional SNP portal · release {info['version']} ({info['assembly']}) · manifest sha256 "
            f"{(info.get('sha256') or '')[:12]} · Ensembl 116, AQUA-FAANG, Ensembl Compara GERP, 504-fish panel variants, "
            "nf-RASQUAL molQTL, published associations (catalog/known_loci.tsv)\n"
            f"Signal read live from salmobase.org bigWigs listed in tracks.yaml{f' ({when})' if when else ''}; default "
            "track sets and tier rules are PROVISIONAL.")


def page(request, s, layout="snpportal/base_portal.html"):
    """Context for locus.html. `changed` counts the display options away from their defaults (they open by themselves)."""
    ctx = {"nav": "explore", "title": "Locus browser", "layout": layout, "s": s, "presets": jobs.presets(), "assays": ASSAYS,
           "changed": (s["assay"] != "ATAC") + s["hmm"] + (s["scale"] == "track")}
    if s["chrom"]:
        ctx["region_text"] = region_text(s["chrom"], s["start"], s["end"], commas=True)
        if s["too_wide"]:
            mid = (s["start"] + s["end"]) // 2
            ctx["centre"] = query(s, start=mid - sl.MAX_WINDOW // 2, end=mid + sl.MAX_WINDOW // 2)
        else:
            svg, notes, synthetic = draw(request, s)
            a, b = s["start"] + 1, s["end"]
            ctx.update(svg=mark_safe(svg), notes=notes, synthetic=synthetic, moves=moves(s), query=query(s),
                       jbrowse=JBROWSE.format(chrom=s["chrom"], start=a, end=b), ensembl=ENSEMBL.format(chrom=s["chrom"], start=a, end=b),
                       file_name=f"locus_{s['chrom']}_{a}_{b}")
    else:
        ctx["region_text"] = request.GET.get("r") or request.GET.get("region") or ""
    return ctx


@private
def locus(request):
    """The locus browser page."""
    return render(request, "snpportal/locus.html", page(request, view_state(request)))


@private
def locus_svg_view(request):
    """htmx swaps of #locus-view get that fragment; anything else the standalone SVG (?download=1 as an attachment)."""
    s = view_state(request)
    if request.headers.get("HX-Target") == "locus-view":
        return render(request, "snpportal/locus.html", page(request, s, fragment()))
    if not s["chrom"] or s["too_wide"]:
        message = s["error"] or ("Zoom in: the window is wider than 2 Mb" if s["too_wide"] else "Choose a region, e.g. 25:28,980,000-29,010,000")
        return HttpResponse(figures.placeholder(900, 120, "Locus browser", message), content_type="image/svg+xml")
    svg = draw(request, s, download=bool(request.GET.get("download")), show=CARD_LANES if s["slim"] else FULL)[0]
    response = HttpResponse(svg, content_type="image/svg+xml")
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="locus_{s["chrom"]}_{s["start"] + 1}_{s["end"]}.svg"'
    return response


# ---- evidence card and variant page ----

TIPS = {"LORe region": "region where the duplicated chromosomes still pair; probes may cross-hybridise",
        "A/T or C/G SNP": "strand-ambiguous; needs care on arrays"}


def evidence(snp, weights, trait, synthetic=False):
    """The evidence card for one annotated row (a dict of its columns), each part only when its columns exist: the tier
    line, the known association, chromatin (grid, or one line when no condition has a peak), the assay and population
    lines, then the closed parts (expression, the user's own columns, details). Shared by the job card and the variant
    page."""
    chrom, pos = snp.get("chrom"), snp.get("pos")
    ref, alt = snp.get("ref"), snp.get("alt")
    spec = f"{chrom}-{pos}" + (f"-{ref}-{alt}" if ref and alt else "")
    ev = {"trait": trait, "title": snp.get("id") or f"{chrom}:{pos:,}", "position": f"{chrom}:{pos}",
          "alleles": f"{ref}>{alt}" if ref and alt else "", "spec": spec, "synthetic": synthetic, "tier": snp.get("tier"),
          "samples": results.SAMPLES}
    ev["terms"] = results.tier_parts(snp.get) or None  # 'Missense p.Thr46Met (...)', 3; the same as the table's drawer
    if weights and len([t for t in snp.get("tier_terms") or [] if t["weight"]]) > 1:
        named = {t: results.region_text(snp.get) for t in results.CODING_TERMS} if snp.get("coding_consequence") else {}
        ev["why"] = mark_safe(locus_svg.tier_contribution(snp["tier_terms"], snp.get("tier_score") or 0, snp.get("tier") or 4,
                                                          weights["tiers"], synthetic, labels=named))
    states = {c[len("chromatin_"):]: snp[c] for c in snp if c.startswith("chromatin_") and c not in NOT_CONDITIONS}
    if states:
        chosen = set(preset_conditions(weights, list(snp), trait)[0]) if weights else set()
        if any(states.values()):
            ev["grid"] = mark_safe(locus_svg.chromatin_grid(states, chosen, bool(snp.get("blacklist")), synthetic))
        else:
            ev["no_peak"] = (results.NO_PEAK if len(states) == 21 else
                             f"No AQUA-FAANG peak in the {len(states)} conditions sampled. No immune tissue, gill or skin.")
        ev["blacklisted"] = bool(snp.get("blacklist"))
    if snp.get("gene_id"):
        ev["gene"] = gene_context(snp)
    expression = {c[len("expression_"):]: snp[c] for c in snp if c.startswith("expression_")}
    if any(v is not None for v in expression.values()):
        ev["expression"] = mark_safe(locus_svg.expression_bars(expression, synthetic))
    if snp.get("known_locus"):
        ev["known"] = known(snp)
    if snp.get("molqtl"):
        ev["molqtl"] = molqtl(snp)
    if snp.get("assay_status"):
        reasons = [r for r in (snp.get("assay_reasons") or "").split("; ") if r]
        reasons += [label for flag, label in (("lore", "LORe region"), ("strand_ambiguous", "A/T or C/G SNP"))
                    if snp.get(flag) and not any(r.startswith(label[:5]) for r in reasons)]
        ev["assay"] = {"status": snp["assay_status"].replace("_", " "), "reasons": "; ".join(map(results.reason_text, reasons)), "flank": snp.get("assay_flank"),
                       "tip": "; ".join(f"{k}: {v}" for k, v in TIPS.items() if any(r.startswith(k[:5]) for r in reasons))}
    if snp.get("public_af"):
        ev["maf"] = {"value": _fmt(snp.get("public_af_maf")), "fish": snp.get("public_af_ns") or 504,
                     "tip": explore.layer("public_af").get("population") or ""}
    elif "public_af" in snp:  # 'other': the panel has a different variant at this position (no MAF for these alleles)
        ev["maf"] = {"value": None, "other": snp.get("public_af_alleles") == "other"}
    ev["details"] = details(snp)
    ev["yours"] = [(c[3:], v) for c, v in snp.items() if c.startswith("in_")]  # the user's own columns, original names
    a, b = max(1, pos - 100), pos + 100
    ev["links"] = [("Ensembl", ENSEMBL.format(chrom=chrom, start=a, end=b)),
                   ("salmobase JBrowse", JBROWSE.format(chrom=chrom, start=max(1, pos - 1000), end=pos + 1000))]
    ev["permalink"] = reverse("snpportal:variant", args=[spec])
    return ev


def details(snp):
    """[(label, value)] for the card's closed Details: the genic region, Ensembl regulatory build, GERP, the public
    site, genetic map, where the position came from, flank variants and the reference base."""
    out = []
    if "region_class" in snp:
        out.append(("Genic region", snp["region_class"] or "intergenic"))
    if snp.get("coding_consequence"):
        out.append(("Transcript", ", ".join(x for x in (snp.get("coding_transcript"),  # the consequence is in the tier line
                                                         snp.get("coding_codons") and f"codons {snp['coding_codons']}") if x)))
    if "regbuild" in snp:
        out.append(("Ensembl regulatory", " ".join(str(x) for x in (snp.get("regbuild_type"), snp.get("regbuild_id")) if x)
                    + (f" (promoter of {snp['regbuild_gene_id']})" if snp.get("regbuild_gene_id") else "") or "none"))
    if "gerp" in snp:
        out.append(("GERP constrained element", f"score {snp['gerp_score']}" if snp.get("gerp") else "none"))
    if "public_af" in snp:
        out.append(("Public variant (504-fish panel)", public_af_text(snp) if snp.get("public_af") else
                    "a different variant at this position" if snp.get("public_af_alleles") == "other" else "not a site of the 504-fish panel"))
        if snp.get("public_af_aquafaang12_af") is not None:
            out.append(("AQUA-FAANG 12 fish", f"alt AF {_fmt(snp['public_af_aquafaang12_af'])}, imputation DR2 "
                        f"{_fmt(snp.get('public_af_aquafaang12_dr2'))}"))
    if "cm" in snp:
        out.append(("Genetic map (Brekke 2023)", f"{_fmt(snp.get('cm_female'))} cM female, {_fmt(snp.get('cm_male'))} cM male"
                    if snp.get("cm") else "outside the map's first and last marker on this chromosome"))
    if snp.get("position_source"):
        out.append(("Position from", "its rs ID (EVA release 9)" if snp["position_source"] == "rsid"
                    else f"its ICSASG_v2 position {snp['position_source'].split(' ', 1)[-1]}, moved to Ssal_v3.1 by its rs ID (EVA release 9)"))
    if "flank_variants" in snp:
        out.append(("Variants within 35 bp", snp["flank_variants"]))
    if "ref_check" in snp:
        out.append(("Reference base", f"{snp.get('genome_base') or '?'} ({snp['ref_check']})"))
    return out


def gene_context(snp):
    """Nearest gene: label (ortholog fallback), ids, where the SNP is relative to it, orthologs and description."""
    where = "inside the gene" + (f", {snp['region_class'].replace('_', ' ')}" if snp.get("region_class") else "")
    path = jobs.release() / "gene.parquet"
    if snp.get("gene_distance") and path.exists():
        hit = jobs.connect([jobs.release()]).execute(f"SELECT start, \"end\", strand FROM read_parquet('{path}') WHERE id = ?",
                                                     [snp["gene_id"]]).fetchone()
        if hit:
            start, end, strand = hit
            upstream = snp["pos"] <= start if strand == "+" else snp["pos"] > end
            where = f"{locus_svg.fmt_bp(snp['gene_distance'])} {'upstream of the TSS' if upstream else 'downstream of the gene end'}"
    name = snp.get("gene_name") or explore.aliases().get(snp["gene_id"])  # the catalogue's name when Ensembl has none
    return {"id": snp["gene_id"], "label": sl.gene_label(name, snp.get("gene_ortholog_human"), snp.get("gene_ortholog_zebrafish"),
                                                         snp["gene_id"]),
            "named": bool(name), "tip": "" if name else explore.UNNAMED_TIP,
            "biotype": snp.get("gene_biotype"), "strand": snp.get("gene_strand"),
            "description": snp.get("gene_description"), "human": snp.get("gene_ortholog_human"),
            "zebrafish": snp.get("gene_ortholog_zebrafish"), "where": where, "url": reverse("snpportal:gene", args=[snp["gene_id"]]),
            "salmobase": explore.SALMOBASE_GENE.format(snp["gene_id"])}


def known(snp):
    """The known association, said once: the nearest catalogue SNP (annotate's known_locus; at its position the effect
    allele is matched to the SNP's alleles), its evidence kind, effect, caveat, rs ID and DOIs, and every other
    catalogue row within the catalogue window."""
    rows = explore.nearby(snp["chrom"], snp["pos"])
    row = next((r for r in rows if r.get("id") == snp["known_locus"]), {})
    kind = (row.get("badges") or [("", "", "")])[0]
    effect, allele, note = (row.get("effect") or "").rstrip("."), snp.get("known_effect_allele"), snp.get("known_effect_note")
    if allele and note:  # 'T (Met54) = early maturation (1SW)' -> 'effect allele T (alt) = early maturation (1SW)'
        effect = (f"effect allele {allele} ({note}) = {effect.split(' = ', 1)[1]}" if effect.startswith(allele + " ") and " = " in effect
                  else f"effect allele {allele} ({note})" + (f"; {effect}" if effect else ""))
    dist = snp.get("known_locus_dist")
    return {"id": snp["known_locus"], "trait": (row.get("trait") or "").replace("_", " "),
            "where": f"{locus_svg.fmt_bp(dist)} away" if dist else "at this position", "kind": kind[1][:1].upper() + kind[1][1:],
            "kind_tip": kind[2], "effect": effect, "rsid": row.get("rsid"), "dois": row.get("dois", []),
            "flags": [b for b in row.get("badges", []) if b[0] == "caveat"], "caveat": row.get("caveat"),
            "others": [{"id": r["id"], "url": reverse("snpportal:variant", args=[f"{r['chrom']}-{r['pos']}"]),
                        "dist": locus_svg.fmt_bp(r["dist"])} for r in rows if r.get("id") != snp["known_locus"]]}


def molqtl(snp):
    """molQTL section of the card (lead SNPs only): {features: [{tissue, kind, feature, url, bf, pi}], citation, licence}."""
    features = []
    for part in (snp.get("molqtl_features") or "").split("; "):
        m = MOLQTL.match(part.strip())
        if not m:
            continue
        tissue, kind, feature, bf, pi = m.groups()
        url = reverse("snpportal:gene", args=[feature]) if feature.startswith("ENSSSAG") else None
        if re.fullmatch(r"\w+:\d+-\d+", feature):  # a peak in BED coordinates: show it 1-based, link it +- 2 kb
            chrom, span = feature.split(":", 1)
            a, b = span.split("-")
            feature = f"{chrom}:{int(a) + 1:,}-{int(b):,}"
            url = reverse("snpportal:locus") + "?" + urlencode({"r": f"{chrom}:{max(1, int(a) + 1 - 2000)}-{int(b) + 2000}"})
        features.append({"tissue": tissue, "kind": MOLQTL_KINDS.get(kind, kind), "feature": feature, "url": url, "bf": bf, "pi": pi})
    layer = explore.layer("molqtl")
    return {"features": features, "alleles": snp.get("molqtl_alleles"), "citation": layer.get("citation"),
            "licence": layer.get("licence"), "max_bf": layer.get("max_bf")}


def public_af_text(snp):
    """'MAF 0.48, alt AF 0.48 (484 of 1,008 alleles, 504 fish)' from the public_af columns."""
    ac, an, ns = snp.get("public_af_ac"), snp.get("public_af_an"), snp.get("public_af_ns")
    counts = f" ({ac:,} of {an:,} alleles, {ns:,} fish)" if isinstance(ac, int) and isinstance(an, int) and isinstance(ns, int) else ""
    return (f"MAF {_fmt(snp.get('public_af_maf'))}, alt AF {_fmt(snp.get('public_af_af'))}{counts}"
            + (f", alleles {snp['public_af_alleles'].replace('_', ' ')}" if snp.get("public_af_alleles") else ""))


def _fmt(v):
    return "n/a" if v is None else f"{v:.3g}" if isinstance(v, float) else str(v)


def card_context(request, ev, presets, switch_url, mini_url, locus_url, keep=None):
    hx = bool(request.headers.get("HX-Request"))
    return {"nav": "score", "title": ev["title"], "ev": ev, "presets": presets, "switch_url": switch_url, "hx": hx,
            "mini_url": mini_url, "locus_url": locus_url, "trait": ev["trait"], "keep": sorted((keep or {}).items())}


@private
def card(request, key, row):
    """Evidence card for one SNP of a job, a page of its own (htmx swaps only the card when the trait changes). A GWAS
    job's card adds the SNP's p, beta and fine-mapping (association.snp_line)."""
    from . import association
    job = finished(key)
    con, types, _, chosen = results.open_result(request, key)
    hit = con.execute(results.CARD_SQL, [row]).fetchone()
    if hit is None:
        raise Http404("No such SNP")
    d = jobs.folder(key)
    synthetic = bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    ev = evidence(dict(zip(types, hit)), jobs.weights(d), chosen["trait"], synthetic)
    ev["gwas"] = association.snp_line(request, key, row, job)
    gwas_query = association.query_of(request)  # a GWAS job's fine-mapping settings
    q = urlencode({"trait": chosen["trait"], **gwas_query})
    ctx = card_context(request, ev, jobs.presets(d), reverse("snpportal:card", args=[key, row]),
                       f"{reverse('snpportal:card_locus', args=[key, row])}?{q}",
                       f"{reverse('snpportal:locus')}?{urlencode({'key': key, 'row': row, 'trait': chosen['trait'], **gwas_query})}",
                       gwas_query)
    ctx.update(job=job, synthetic=synthetic, crumbs=[("Results", f"{reverse('snpportal:results', args=[key])}?{q}"), ("SNP", None)])
    return render(request, "snpportal/card.html" if ctx["hx"] else "snpportal/card_page.html", ctx)


@private
def card_locus(request, key, row):
    """Mini locus (SNP +- 5 kb) for the card, addressed by row: genes and the trait's chromatin rows, plus the
    association lane of a GWAS job."""
    finished(key)
    con = results.open_result(request, key)[0]
    hit = con.execute("SELECT chrom, pos FROM v WHERE file_row_number = ?", [row]).fetchone()
    if hit is None:
        raise Http404("No such SNP")
    s = mini_state(request, hit[0], hit[1])
    s["key"] = str(key)
    return HttpResponse(draw(request, s, show=CARD_LANES)[0], content_type="image/svg+xml")


def mini_state(request, chrom, pos):
    trait = request.GET.get("trait") if request.GET.get("trait") in dict(jobs.presets()) else "all"
    size = (jobs.manifest().get("chrom_sizes") or {}).get(chrom)
    start, end = sl.clamp(pos - 1 - CARD_FLANK, pos + CARD_FLANK, size)
    return {"chrom": chrom, "start": start, "end": end, "size": size, "trait": trait, "assay": "ATAC", "hmm": False,
            "scale": "shared", "key": None, "row": None, "mark": pos, "compact": True, "too_wide": False, "error": None}


@private
def variant(request, spec):
    """/snp/variant/<chrom>-<pos>[-<ref>-<alt>]/: the evidence for one position, annotated on the fly (no job)."""
    m = VARIANT.match(spec)
    if not m:
        raise Http404("Write the variant as chrom-pos or chrom-pos-ref-alt, e.g. 25-28996360-C-T")
    try:
        chrom = sl.resolve_chrom(jobs.release(), m.group(1))
    except ValueError as e:
        raise Http404(str(e)) from None
    pos, ref, alt = int(m.group(2)), (m.group(3) or "").upper() or None, (m.group(4) or "").upper() or None
    presets = jobs.presets()
    trait = request.GET.get("trait") if request.GET.get("trait") in dict(presets) else "all"
    try:
        snp = sl.annotate_position(jobs.release(), chrom, pos, ref, alt, trait, work_dir=jobs.results_dir())
    except snpscore.InputError as e:
        raise Http404(str(e)) from None
    snp["id"] = snp.get("id") or next((r["id"] for r in sl.catalog(jobs.release()) if r.get("chrom") == chrom and r.get("pos") == str(pos)), None)
    info = jobs.release_info()
    ev = evidence(snp, jobs.weights(), trait, bool(info.get("synthetic")))
    mini = {"r": region_text(chrom, max(0, pos - 1 - CARD_FLANK), pos + CARD_FLANK), "trait": trait, "mark": pos, "compact": 1, "slim": 1}
    ctx = card_context(request, ev, presets, reverse("snpportal:variant", args=[spec]), f"{reverse('snpportal:locus_svg')}?{urlencode(mini)}",
                       f"{reverse('snpportal:locus')}?{urlencode({'r': region_text(chrom, max(0, pos - 1 - 10_000), pos + 10_000), 'trait': trait})}")
    ctx.update(nav="explore", title=ev["title"], synthetic=ev["synthetic"], crumbs=[("Locus browser", reverse("snpportal:locus")), ("Variant", None)])
    return render(request, "snpportal/card.html" if ctx["hx"] else "snpportal/variant.html", ctx)
