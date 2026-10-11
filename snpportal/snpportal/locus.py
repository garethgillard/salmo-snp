"""The locus figure (single SVG), evidence card and variant page (P4.4a); the locus browser page is browser.py.

- /snp/locus/svg/?r=25:28980000-29010000[&trait=][&assay=ATAC|H3K27ac|H3K4me3][&hmm=1][&scale=track][&key=<job>[&row=]]
  is the locus figure as one SVG file (the browser's download); htmx swaps of #locus-view (HX-Target) get the browser
  page's fragment instead.
- Signal and ChromHMM come from tracks.yaml through snpscore.locus on a fixed public tile grid, cached in the Django
  cache 'snpportal_tiles' (if configured) or a LocMemCache of 5,000 entries. Views opened from a job (key=) only read
  that cache: their tiles would record, for days, where the job's SNPs are.
- The evidence card is addressed by job and row, so its URLs carry no coordinates; its locus view (the robust ATAC
  peaks around the SNP) is drawn inline.
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
from django.shortcuts import redirect, render
from django.template import engines
from django.urls import reverse
from django.utils.safestring import mark_safe

import snpscore
from snpscore import locus as sl
from snpscore import panel as snp_panel
from snpscore import tracks as st
from snpscore.formats import lit
from snpscore.score import NOT_CONDITIONS, preset_conditions

from . import explore, figures, jobs, locus_svg, palette, results, search
from .views import finished, private

DEFAULT_WIDTH = 20_000  # a single position (a card's SNP) opens this wide: the card's mini browser (+- MINI_FLANK), larger
DEFAULT_REGION = "25:28985000-29010000"  # the locus browser opens here (vgll3) when no region is given
FULL = {"published", "molqtl", "regbuild", "gerp", "variants", "signal", "snps"}  # the locus browser's optional lanes
REGION_LANES = {"published", "gerp"}  # the regional association plot (its association lane is drawn on top)
MINI_FLANK = 10_000  # the card's mini locus browser: the SNP +- this
COMPACT_WIDTH = 640  # the landing figure: about the width it is shown at (no shrunk text)
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
    s = {"trait": "all", "assay": g.get("assay") if g.get("assay") in ASSAYS else "ATAC",  # tiers: always all 21 conditions
         "hmm": g.get("hmm") == "1", "scale": "track" if g.get("scale") == "track" else "shared", "key": None, "row": None,
         "chrom": None, "error": None, "too_wide": False, "compact": g.get("compact") == "1",
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
        out.append({"row": row, "pos": pos, "id": sid, "tier": tier, "tier_score": score,
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
    """(svg, notes, synthetic) for the view s. `show`: the optional lanes (FULL or REGION_LANES); outside
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
                  "note": "" if picked else f"No {s['assay']} tracks for these conditions"}
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


@private
def locus_svg_view(request):
    """htmx swaps of #locus-view get that fragment; anything else the standalone SVG (?download=1 as an attachment)."""
    s = view_state(request)
    if request.headers.get("HX-Target") == "locus-view":
        from . import browser  # browser imports this module
        return render(request, "snpportal/locus.html", browser.context(request, s, fragment()))
    if not s["chrom"] or s["too_wide"]:
        message = s["error"] or ("Zoom in: the window is wider than 2 Mb" if s["too_wide"] else "Choose a region, e.g. 25:28,980,000-29,010,000")
        return HttpResponse(figures.placeholder(900, 120, "Locus browser", message), content_type="image/svg+xml")
    svg = draw(request, s, download=bool(request.GET.get("download")), show=FULL)[0]
    response = HttpResponse(svg, content_type="image/svg+xml")
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="locus_{s["chrom"]}_{s["start"] + 1}_{s["end"]}.svg"'
    return response


# ---- evidence card and variant page ----

TIPS = {"LORe region": "region where the duplicated chromosomes still pair; probes may cross-hybridise",
        "A/T or C/G SNP": "strand-ambiguous; needs care on arrays"}


def evidence(snp, weights, trait, synthetic=False, snps=()):
    """The evidence card for one annotated row (a dict of its columns), each part only when its columns exist: the key
    facts and the caveats; the score breakdown; the functional evidence at the locus (a mini locus browser with the
    job's `snps` in its window and the SNP's peak per condition, or one line when no condition has a peak; Ensembl
    regulatory, molQTL); as a marker (assay, flank, duplicates); context (known association; expression, the user's own
    columns and details closed). Shared by the job card and the variant page."""
    chrom, pos = snp.get("chrom"), snp.get("pos")
    ref, alt = snp.get("ref"), snp.get("alt")
    spec = f"{chrom}-{pos}" + (f"-{ref}-{alt}" if ref and alt else "")
    ev = {"trait": trait, "title": snp.get("id") or f"{chrom}:{pos:,}", "position": f"{chrom}:{pos}",
          "alleles": f"{ref}>{alt}" if ref and alt else "", "spec": spec, "synthetic": synthetic, "tier": snp.get("tier"),
          "score": snp.get("tier_score"), "samples": results.SAMPLES}
    ev["terms"] = results.tier_parts(snp.get) or None  # 'Missense p.Thr46Met (...)', 3; the blocks' hover text
    states = {c[len("chromatin_"):]: snp[c] for c in snp if c.startswith("chromatin_") and c not in NOT_CONDITIONS}
    data = None  # the mini browser's lanes, when there is a chromatin layer
    chosen = set()  # tiers count all 21 conditions: none stands out in the tiles or the counts
    if weights and "tier_terms" in snp:
        ev["blocks"] = mark_safe(locus_svg.score_blocks(score_parts(snp, states, chosen, weights), weights["tiers"], snp.get("tier_score") or 0,
                                                        synthetic))
    if states:
        tiles = locus_svg.chromatin_grid(states, chosen, bool(snp.get("blacklist")), synthetic, legend=False) if any(states.values()) else None
        if not tiles:
            ev["no_peak"] = (results.NO_PEAK if len(states) == 21 else
                             f"No AQUA-FAANG peak in the {len(states)} conditions sampled. No immune tissue, gill or skin.")
        data = lanes(chrom, *mini_window(pos))
        ev["mini"] = mark_safe(locus_svg.mini_browser(data, pos, snps, lambda gid: reverse("snpportal:gene", args=[gid]), synthetic,
                                                      tiles=tiles))
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
        cfg = (weights or {}).get("assay") or {}
        reasons = [r for r in (snp.get("assay_reasons") or "").split("; ") if r]
        icon, cls = results.ASSAY.get(snp["assay_status"], ("?", "not_checked"))
        gc, (lo, hi) = snp.get("assay_gc"), cfg.get("gc", [0.3, 0.7])
        variants = {v["pos"]: v for v in (data or {}).get("variants", [])}
        ev["assay"] = {"status": snp["assay_status"].replace("_", " "), "icon": icon, "cls": cls, "all": "; ".join(map(results.reason_text, reasons)),
                       "reasons": "; ".join(results.reason_text(r) for r in reasons if not r.startswith(ELSEWHERE)),  # not shown elsewhere
                       "flank": snp.get("assay_flank"), "flank_parts": flank_parts(snp.get("assay_flank"), pos, variants, cfg.get("max_homopolymer", 6)),
                       "gc": None if gc is None else (f"GC {gc:.0%}", "" if lo <= gc <= hi else "warn",
                                                     f"GC share of the flanks; {lo:.0%}–{hi:.0%} passes (provisional)")}
    min_maf = float(snp_panel.settings(weights)["min_maf"])
    if snp.get("public_af"):
        maf = snp.get("public_af_maf")
        ev["maf"] = {"value": _fmt(maf), "fish": snp.get("public_af_ns") or 504, "low": maf is not None and maf < min_maf,
                     "min": f"{min_maf:g}", "tip": explore.layer("public_af").get("population") or ""}
    elif "public_af" in snp:  # 'other': the panel has a different variant at this position (no MAF for these alleles)
        ev["maf"] = {"value": None, "other": snp.get("public_af_alleles") == "other"}
    ev["duplicates"] = duplicates(snp)
    ev["marker"] = marker_chips(snp, ev)
    ev["function"] = function(snp)
    ev["facts"] = facts(snp, ev, states, chosen, set((weights or {}).get("active_states", [])))
    ev["caveats"] = caveats(snp, ev)
    ev["details"] = details(snp)
    ev["yours"] = [(c[3:], v) for c, v in snp.items() if c.startswith("in_")]  # the user's own columns, original names
    a, b = max(1, pos - 100), pos + 100
    ev["links"] = [("Ensembl", ENSEMBL.format(chrom=chrom, start=a, end=b)),
                   ("salmobase JBrowse", JBROWSE.format(chrom=chrom, start=max(1, pos - 1000), end=pos + 1000))]
    ev["permalink"] = reverse("snpportal:variant", args=[spec])
    return ev


SCORE_LABELS = {"active_elsewhere": "active elsewhere", "synonymous": "synonymous", "splice": "splice region",
                "constrained": "conserved"}
CHROMATIN_TERMS = ("active", "active_elsewhere", "weak")  # their blocks say what the chromatin chip would


def score_parts(snp, states=None, chosen=(), weights=None):
    """The evidence terms that count, largest first, for the score blocks: [(label, weight, colour, full text)] with
    labels as short as the key facts' chips: 'active in 5/21' (of the chosen conditions), 'weak in 3/21', 'missense',
    'conserved', '5′ UTR', 'Ensembl enhancer'; the full text (conditions, protein change) on hover. A chromatin block
    has the colour of its strongest state there, as in the tiles."""
    g, fired, states = snp.get, snp.get("tier_terms") or [], states or {}
    raw = [x for x in (g("tier_evidence") or "").split("; ") if x]
    raw = raw if len(raw) == len(fired) else [""] * len(fired)
    among = [c for c in states if c in chosen] or list(states)
    out = []
    for (t, r), (text, w) in zip([(t, r) for t, r in zip(fired, raw) if t["weight"]], results.tier_parts(g)):
        k = t["term"]
        n = sum(states[c] in (weights or {}).get(f"{k}_states", ()) for c in among)
        label = (f"{k} in {n}/{len(among)}" if k in ("active", "weak") and among else
                 results.CONSEQUENCES.get(g("coding_consequence") or "") or "CDS" if k == "coding" else
                 results.CLASS_LABELS.get(g("region_class")) or "UTR" if k == "utr" else
                 f"Ensembl {(g('regbuild_type') or '').replace('_', ' ')}".strip() if k == "regbuild" else SCORE_LABELS.get(k, k))
        kind = (weights or {}).get(f"{'active' if k == 'active_elsewhere' else k}_states", ())
        where = [c for c in states if c not in among] if k == "active_elsewhere" else among
        found = [states[c] for c in where if states[c] in kind] if k in CHROMATIN_TERMS else []
        state = locus_svg.strongest(found) if found else None  # its strongest state, coloured as in the tiles
        tip = (f"{k.replace('_', ' ')}" + (f" ({state.replace('_', ' ')})" if state else "") + f": {conditions_text(r.partition(': ')[2])}"
               if k in CHROMATIN_TERMS and r else text)
        colour = palette.state(state)[0] if state else locus_svg._colour(locus_svg.TERMS.get(k, (palette.GREY[500], k))[0])
        out.append((label, t["weight"], colour, f"{tip} +{w}"))
    return sorted(out, key=lambda p: -p[1])


def conditions_text(items):
    """'Brain, Liver, embryo (2 stages)' from tier_evidence's tissue and stage list 'Brain,Liver,LateBlastulation,…'."""
    names = [x for x in items.split(",") if x]
    stages = [x for x in names if x in results.STAGES]
    embryo = (["embryo (all stages)" if len(stages) == len(results.STAGES) else f"embryo ({len(stages)} stage{'s' * (len(stages) > 1)})"]
              if stages else [])
    return ", ".join([x for x in names if x not in results.STAGES] + embryo)


FACT_ORDER = ("gene", "region", "gwas", "chromatin", "known", "molqtl")


def chip(text, cls="", tip="", key="", url=None):
    """One key fact: (text, class ok/warn/fail/muted or '', tooltip, group (FACT_ORDER), link or None)."""
    return text, cls, tip, key, url


def ordered(chips):
    """The key facts by group: the SNP (gene, region), then its evidence (GWAS, chromatin, known locus, molQTL).
    How it would work as a marker sits in the As a marker header (marker_chips)."""
    return sorted(chips, key=lambda c: FACT_ORDER.index(c[3]) if c[3] in FACT_ORDER else len(FACT_ORDER))


def facts(snp, ev, states, chosen, active_states):
    """The card's key facts, one chip each (chip()): the gene (the drawer's heading has it), the region where no score
    block says it (its distance outside the gene), chromatin where it didn't score, known locus and molQTL. Job
    cards add a GWAS job's p, beta and PIP (job_card)."""
    out, g = [], snp.get
    fired = {t["term"] for t in g("tier_terms") or [] if t["weight"]}  # what the score blocks already say
    gene = ev.get("gene")
    if gene:
        out.append(chip(gene["label"], "", gene.get("where", ""), "gene"))
    if "region_class" in snp and not fired & {"coding", "synonymous", "splice", "utr"}:
        out.append(chip(results.region_text(g) + (f" · {locus_svg.fmt_bp(g('gene_distance'))} away" if g("gene_distance") else ""), "",
                        results.coding_tip(g) or (gene or {}).get("where", ""), "region"))
    if states and not fired & set(CHROMATIN_TERMS):
        peak = [c for c, s in states.items() if s]
        active = [c for c in peak if states[c] in active_states]
        n = len(states)
        mine = f"; in the chosen conditions: a peak in {len(chosen & set(peak))} of {len(chosen)}, active in {len(chosen & set(active))}" \
            if chosen and len(chosen) < n else ""
        tip = f"A robust ATAC peak in {len(peak)} of {n} conditions, active (Active TSS or enhancer) in {len(active)}{mine}"
        out.append(chip(f"active in {len(active)}/{n}" if active else f"peak in {len(peak)}/{n}, not active" if peak
                        else "no ATAC peak", "" if peak else "muted", tip, "chromatin"))
    if ev.get("known"):
        k = ev["known"]
        out.append(chip("★ published SNP" if not g("known_locus_dist") else f"★ {k['where'].replace(' away', '')} from {k['id']}", "",
                        f"Known locus {k['id']}" + (f" ({k['trait']})" if k["trait"] else ""), "known"))
    if g("molqtl"):
        out.append(chip("molQTL lead", "", f"{(g('molqtl_tissues') or '').replace(',', ', ')}: display only, not counted in tiers", "molqtl"))
    return ordered(out)


def marker_chips(snp, ev):
    """The As a marker header's chips, seen when it is folded: [(text, class, tooltip)]: the assay check, MAF ('low'
    below the panel designer's minimum), LORe and A/T or C/G."""
    out = []
    if ev.get("assay"):
        a = ev["assay"]
        out.append((f"{a['icon']} assay {a['status']}", a["cls"], "Assay design check of the probe flanks" + (f": {a['all']}" if a["all"] else "")))
    m = ev.get("maf")
    if m and m["value"] is not None:
        out.append((f"MAF {m['value']}" + (" · low" if m["low"] else ""), "warn" if m["low"] else "plain",
                    results.MAF_TIP + (f"; below the panel designer's minimum ({m['min']}, provisional)" if m["low"] else "")))
    elif m:
        out.append(("no public MAF", "not_checked", "Not a site of the 504-fish public panel" if not m.get("other") else
                    "The 504-fish public panel has a different variant at this position"))
    if snp.get("lore"):
        out.append(("LORe", "warn", TIPS["LORe region"]))
    if snp.get("strand_ambiguous"):
        out.append(("A/T or C/G", "warn", TIPS["A/T or C/G SNP"]))
    return out


def gwas_chips(line):
    """A GWAS job's chips from association.snp_line: p, beta (se) and, inside a locus, its PIPs linked to the locus."""
    if not line:
        return []
    out = [chip(f"p {line['p']}", "", "GWAS p value", "gwas")]
    if line.get("beta") is not None:
        out.append(chip(f"β {line['beta']:.3f}" + (f" ({line['se']:.3f})" if line.get("se") is not None else ""), "",
                        "GWAS effect of the alt allele (standard error)", "gwas"))
    if line.get("locus") and line.get("pip_u") is not None:
        out.append(chip(f"PIP {line['pip_u']:.2f} → {line['pip_f']:.2f}", "",
                        f"Locus {line['locus']}: posterior inclusion probability, uniform → functional prior; {line['cs']}; "
                        "one causal variant per locus, no LD", "gwas", line.get("region")))
    elif line.get("locus"):
        out.append(chip(f"locus {line['locus']}", "", "The GWAS locus window this SNP falls in", "gwas", line.get("region")))
    return out


def caveats(snp, ev):
    """What to keep in mind about this SNP's evidence, said once at the top of the card."""
    out = []
    if snp.get("blacklist"):
        out.append("Blacklisted region: no peak here means can’t tell, not inactive.")
    if (ev.get("known") or {}).get("caveat"):
        out.append(f"Known locus {ev['known']['id']}: {ev['known']['caveat'].rstrip('.')}.")
    source = snp.get("position_source")
    if source:
        out.append("Position from its rs ID (EVA release 9), not from your list." if source == "rsid" else
                   f"Position moved from ICSASG_v2 ({source.split(' ', 1)[-1]}) by its rs ID (EVA release 9).")
    if snp.get("ref_check") == "mismatch":
        out.append(f"Your ref allele does not match the Ssal_v3.1 genome (it has {snp.get('genome_base') or '?'}): "
                   "check the assembly and strand.")
    elif snp.get("ref_check") == "strand_flip":
        out.append("Your alleles match the Ssal_v3.1 genome on the other strand.")
    return out


def duplicates(snp):
    """One line on copies of this region elsewhere in the genome (salmon's whole-genome duplication, Ss4R), where probes
    may also bind: {lore (its chromosome pair or ''), gene (the Ss4R copy of its gene), chrom, kind, tip, url (that
    copy in the locus browser)}; None without either."""
    gene = snp.get("ss4r_ohnolog")
    if not snp.get("lore") and not gene:
        return None
    copy = explore.gene_rows([gene]).get(gene) if gene else None
    tips = {"LORe": "LORe: a recent split, so the copies are more similar", "AORe": "AORe: split before the salmonid species"}
    return {"lore": (snp.get("lore_label") or "region") if snp.get("lore") else None, "gene": gene,
            "chrom": snp.get("ss4r_ohnolog_chrom"), "kind": snp.get("ss4r_class"), "tip": tips.get(snp.get("ss4r_class"), ""),
            "url": search.locus_url(copy["chrom"], max(1, copy["start"] + 1 - 5000), copy["end"] + 5000) if copy else None}


def function(snp):
    """[(label, value)] of the functional layers neither the tier line nor the mini browser shows: the Ensembl regulatory
    build."""
    out = []
    if snp.get("regbuild"):
        out.append(("Ensembl regulatory", " ".join(str(x) for x in ((snp.get("regbuild_type") or "").replace("_", " "), snp.get("regbuild_id")) if x)
                    + (f", promoter of {snp['regbuild_gene_id']}" if snp.get("regbuild_gene_id") else "")))
    return out


IUPAC = {"R": "A/G", "Y": "C/T", "S": "C/G", "W": "A/T", "K": "G/T", "M": "A/C", "B": "C/G/T", "D": "A/G/T", "H": "A/C/T",
         "V": "A/C/G"}
ELSEWHERE = ("GC", "homopolymer", "flank variants", "LORe", "A/T", "blacklisted")  # assay reasons the card shows elsewhere


def flank_parts(flank, pos=None, variants=None, max_run=6):
    """The probe flanks as [(text, kind, tooltip)]: kind 'snp' for the [ref/alt]; 'var' for a public variant in a flank
    (an IUPAC code: its offset from the SNP, alleles and MAF on hover; variants: {pos: lanes() variant}); 'run' for a
    single-base run longer than max_run; 'n' for unknown bases; '' for the rest."""
    if not flank or "[" not in flank:
        return []
    left, rest = flank.split("[", 1)
    allele, right = rest.split("]", 1)
    variants, out = variants or {}, []
    runs = re.compile("|".join(f"{b}{{{max_run + 1},}}" for b in "ACGTacgt"))

    def side(seq, offset):  # offset(i): bp from the SNP of the base at index i
        for m in re.finditer(r"[ACGTacgt]+|[Nn]+|.", seq):
            text = m.group(0)
            if text[0] in "Nn":
                out.append((text, "n", "unknown bases"))
            elif text[0] in "ACGTacgt":
                last = 0
                for r in runs.finditer(text):
                    if r.start() > last:
                        out.append((text[last:r.start()], "", ""))
                    out.append((r.group(0), "run", f"{len(r.group(0))} × {r.group(0)[0].upper()}: longer than {max_run}"))
                    last = r.end()
                if last < len(text):
                    out.append((text[last:], "", ""))
            else:
                d = offset(m.start())
                v = variants.get(pos + d) if pos else None
                out.append((text, "var", f"Public variant {'+' if d > 0 else '−'}{abs(d)} bp: {IUPAC.get(text.upper(), text)}"
                            + (f", MAF {_fmt(v.get('maf'))}" if v and v.get("maf") is not None else "")))

    side(left, lambda i: i - len(left))
    out.append((f"[{allele}]", "snp", "the SNP"))
    side(right, lambda i: i + 1)
    return out


def mini_window(pos):
    """The card's mini locus browser window, BED coordinates: the SNP +- MINI_FLANK."""
    return max(0, pos - 1 - MINI_FLANK), pos + MINI_FLANK


def details(snp):
    """[(label, value)] for the card's closed Details: the transcript, the public site, genetic map, flank variants
    and the reference base."""
    out = []
    if snp.get("coding_consequence"):
        out.append(("Transcript", ", ".join(x for x in (snp.get("coding_transcript"),  # the consequence is in the tier line
                                                         snp.get("coding_codons") and f"codons {snp['coding_codons']}") if x)))
    if "public_af" in snp:
        out.append(("Public variant (504-fish panel)", public_af_text(snp) if snp.get("public_af") else
                    "a different variant at this position" if snp.get("public_af_alleles") == "other" else "not a site of the 504-fish panel"))
        if snp.get("public_af_aquafaang12_af") is not None:
            out.append(("AQUA-FAANG 12 fish", f"alt AF {_fmt(snp['public_af_aquafaang12_af'])}, imputation DR2 "
                        f"{_fmt(snp.get('public_af_aquafaang12_dr2'))}"))
    if "cm" in snp:
        out.append(("Genetic map (Brekke 2023)", f"{_fmt(snp.get('cm_female'))} cM female, {_fmt(snp.get('cm_male'))} cM male"
                    if snp.get("cm") else "outside the map's first and last marker on this chromosome"))
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
            "description": re.sub(r"\s*\[Source:[^\]]*\]", "", snp.get("gene_description") or ""), "human": snp.get("gene_ortholog_human"),
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


def card_context(request, ev, locus_url):
    return {"nav": "score", "title": ev["title"], "ev": ev, "hx": bool(request.headers.get("HX-Request")), "locus_url": locus_url}


def job_card(request, key, row, job):
    """Card context for one SNP of a job, for the request's trait (the Table's drawer shows it); a GWAS job's card adds
    the SNP's p, beta and fine-mapping (association.snp_line), and every card whether this browser's Design panel
    holds the SNP. None when the row doesn't exist."""
    from . import association, panel
    con, types, where, chosen = results.open_result(request, key)
    hit = con.execute(results.CARD_SQL, [row]).fetchone()
    if hit is None:
        return None
    d = jobs.folder(key)
    synthetic = bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    snp = dict(zip(types, hit))
    gwas_query = association.query_of(request)  # a GWAS job's fine-mapping settings
    start, end = mini_window(snp["pos"])
    snps = user_snps(request, {"key": str(key), "chrom": snp["chrom"], "start": start, "end": end, "trait": chosen["trait"], "gwas": gwas_query})
    near = f"chrom = {lit(snp['chrom'])} AND pos > {start} AND pos <= {end}"
    selected = {i for i, in con.execute(f"SELECT file_row_number FROM v {where} {'AND' if where else 'WHERE'} {near}").fetchall()}
    for p in snps:
        p["out"] = p["row"] not in selected  # filtered out or taken out (−): hollow in the mini browser
    ev = evidence(snp, jobs.weights(d), chosen["trait"], synthetic, snps)
    ev["facts"] = ordered(ev["facts"] + gwas_chips(association.snp_line(request, key, row, job)))
    ctx = card_context(request, ev, f"{reverse('snpportal:locus')}?{urlencode({'key': key, 'row': row, **gwas_query})}")
    ctx.update(job=job, synthetic=synthetic, panel=panel.holds(request, snp))
    return ctx


@private
def card(request, key, row):
    """A job's SNP: its card is the Table's evidence drawer (?snp=), where this link leads; an htmx request gets the
    card itself."""
    job = finished(key)
    if not request.headers.get("HX-Request"):
        params = {k: v for k, v in request.GET.items() if k not in ("tab", "snp")}
        return redirect(f"{reverse('snpportal:results', args=[key])}?{urlencode({'tab': 'table', **params, 'snp': row})}")
    ctx = job_card(request, key, row, job)
    if ctx is None:
        raise Http404("No such SNP")
    return render(request, "snpportal/card.html", ctx)


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
    trait = "all"  # tiers always count all 21 conditions
    try:
        snp = sl.annotate_position(jobs.release(), chrom, pos, ref, alt, trait, work_dir=jobs.results_dir())
    except snpscore.InputError as e:
        raise Http404(str(e)) from None
    snp["id"] = snp.get("id") or next((r["id"] for r in sl.catalog(jobs.release()) if r.get("chrom") == chrom and r.get("pos") == str(pos)), None)
    info = jobs.release_info()
    ev = evidence(snp, jobs.weights(), trait, bool(info.get("synthetic")))
    ctx = card_context(request, ev, f"{reverse('snpportal:locus')}?{urlencode({'r': region_text(chrom, max(0, pos - 1 - 10_000), pos + 10_000)})}")
    ctx.update(nav="explore", title=ev["title"], synthetic=ev["synthetic"], crumbs=[("Locus browser", reverse("snpportal:locus")), ("Variant", None)])
    return render(request, "snpportal/card.html" if ctx["hx"] else "snpportal/variant.html", ctx)
