"""Your own tier rules (G, 2026-11-26): a weights.yaml of your own, uploaded, or set in the Tier rules mixer (a
fader and a number box per evidence term, the tier cut-offs, the chromatin states), kept in this browser (localStorage,
portal.js) and sent with each new list, or applied to finished results, which are tiered again from the evidence they
hold (jobs.retier). Only the scoring blocks (SCORING) are a user's: the others (presets, assay, design, finemap,
priors) stay the portal's. Checked as the portal's own rules are (health.rules), within bounds for a public server."""
from __future__ import annotations

import json
import re
from datetime import datetime

import snpscore
import yaml
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import jobs
from .lib import export as snp_export

SCORING = ("weights", "tiers", "active_states", "weak_states", "summit", "variant_scores")  # the blocks that are yours
MAX_WEIGHT, MAX_CUTOFF, MAX_BYTES = 100, 1000, 100_000  # PROVISIONAL bounds: a weight, a tier cut-off, a rules file
FADERS = {"weight": 10, "cutoff": 20}  # the faders' top (PROVISIONAL); the number boxes go up to the bounds
TERMS = [  # (term, label, what counts, the release layer it needs): the mixer's channels, in its order. Not here:
    # active_elsewhere, which never counts in the portal (its tiers count all conditions), and the score layers (below)
    ("active", "Active state", "An active chromatin state in at least one AQUA-FAANG condition", "chromatin"),
    ("weak", "Weak state", "A weak chromatin state, and no active one, in at least one condition", "chromatin"),
    ("coding", "Coding", "A change to the protein (missense, stop gained or lost, start lost) or of unknown effect", "region"),
    ("synonymous", "Synonymous", "A synonymous change in coding sequence (or stop retained)", "region"),
    ("splice", "Splice region", "In a splice region", "region"),
    ("utr", "UTR", "In a 5' or 3' UTR", "region"),
    ("constrained", "Constrained", "In a GERP constrained element (Ensembl's 65 fish)", "gerp"),
    ("pike", "Pike conserved", "Sequence that aligns to northern pike", "pike"),
    ("motif", "TF motif", "In a robust ATAC peak, one allele matches a JASPAR motif and the other doesn't", "motif"),
    ("summit", "ATAC summit", "Near a strong ATAC summit (the summit rule of the rules file)", "summit"),
    ("regbuild", "Ensembl regulatory", "An Ensembl regulatory feature where AQUA-FAANG has no peak", "regbuild"),
    ("molqtl", "molQTL lead", "A caQTL or eQTL lead SNP of the 12 AQUA-FAANG fish (nf-RASQUAL)", "molqtl"),
]
LABELS = {t: label for t, label, _, _ in TERMS} | {"active_elsewhere": "Active elsewhere"}


def standard():
    """The rules in use (the shipped weights.yaml, or the install's own copy), as their file says them."""
    return yaml.safe_load(snpscore.score.rules_file().read_text())


def parse(text):
    """A rules file's text as a dict. RulesError for a file that is too big, has YAML anchors (which can blow up), or
    can't be read: each says where."""
    if len(text.encode()) > MAX_BYTES:
        raise snpscore.RulesError(f"A rules file has at most {MAX_BYTES // 1000} KB; this one is larger")
    if re.search(r"(^|[\s\[{,:-])[&*][^\s,\]}]", re.sub(r"#.*", "", text), re.M):
        raise snpscore.RulesError("YAML anchors and aliases (& and *) can't be used in a rules file")
    try:
        given = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise snpscore.RulesError(f"The file can't be read{f' at line {mark.line + 1}' if mark else ''}: "
                                  f"{getattr(e, 'problem', None) or 'not YAML'}") from None
    if not isinstance(given, dict):
        raise snpscore.RulesError("The file holds no rules: it should be named blocks, as the standard weights.yaml")
    return given


def compose(given):
    """(rules, problems, unused): the rules in use with the scoring blocks of `given` (a dict) in their place; the
    mistakes that make them unusable, each named by its key; and the blocks of `given` left to the portal."""
    unused = [k for k in given if k in snpscore.score.BLOCKS and k not in SCORING]
    problems = [f"unknown block '{k}' (mistyped? the blocks your rules can set are {', '.join(SCORING)})"
                for k in given if k not in snpscore.score.BLOCKS]
    rules = {**standard(), **{k: given[k] for k in SCORING if k in given}}
    problems += snpscore.check_weights(rules) + snp_export.check_rules(rules)
    weights = rules.get("weights") if isinstance(rules.get("weights"), dict) else {}
    problems += [f"weights: '{t}' is {v}; at most {MAX_WEIGHT} here" for t, v in weights.items()
                 if isinstance(v, int) and not isinstance(v, bool) and v > MAX_WEIGHT]
    tiers = rules.get("tiers")
    if isinstance(tiers, list) and any(isinstance(t, int) and t > MAX_CUTOFF for t in tiers):
        problems.append(f"tiers: {tiers}; a cut-off is at most {MAX_CUTOFF} here")
    return rules, problems, unused


def from_json(value):
    """(rules, problems) from the scoring blocks the browser sends (JSON); (None, []) for none: the rules in use."""
    if not value:
        return None, []
    if len(value) > MAX_BYTES:
        return None, ["The tier rules sent are too large"]
    try:
        given = json.loads(value)
    except ValueError:
        return None, ["The tier rules sent can't be read"]
    if not isinstance(given, dict):
        return None, ["The tier rules sent hold no blocks"]
    rules, problems, _ = compose(given)
    return rules, problems


def scoring(rules):
    """The scoring blocks of a set of rules: what the browser keeps."""
    return {k: rules[k] for k in SCORING if k in rules}


def changes(rules, base=None):
    """How `rules` differ from the rules in use (or `base`), in words: ['Active state 3 → 5', 'tier cut-offs 5/3/1 →
    6/3/1', 'chromatin states'], [] when they are the same."""
    base = base or standard()
    bw, rw = base.get("weights") or {}, rules.get("weights") or {}
    out = [f"{LABELS.get(t, t.replace('_', ' '))} {bw.get(t, 0)} → {rw.get(t, 0)}" for t in dict.fromkeys([*bw, *rw])
           if bw.get(t, 0) != rw.get(t, 0)]
    if base.get("tiers") != rules.get("tiers"):
        out.append("tier cut-offs " + "/".join(map(str, base.get("tiers") or [])) + " → " + "/".join(map(str, rules.get("tiers") or [])))
    if any(sorted(base.get(k) or []) != sorted(rules.get(k) or []) for k in ("active_states", "weak_states")):
        out.append("chromatin states")
    if base.get("summit") != rules.get("summit"):
        out.append("summit rule")
    if (base.get("variant_scores") or {}) != (rules.get("variant_scores") or {}):
        out.append("score percentiles")
    return out


def text(rules):
    """A full weights.yaml for `rules`: the file of the rules in use, its comments kept, each value that differs
    written in its place, and a first line naming the changes; the file itself when nothing differs (so the job's
    rules hash as the rules in use do, and the public pool fits)."""
    base_text = snpscore.score.rules_file().read_text()
    base = yaml.safe_load(base_text)
    said = changes(rules, base)
    if not said:
        return base_text
    lines, out, i = base_text.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"([A-Za-z_]+):", lines[i])
        if not m or m.group(1) not in SCORING or rules.get(m.group(1)) == base.get(m.group(1)):
            out.append(lines[i])
            i += 1
            continue
        key, j = m.group(1), i + 1
        while j < len(lines) and lines[j][:1] in (" ", "\t") and lines[j].strip():  # the block's own lines
            j += 1
        block = lines[i:j]
        if key == "weights" and isinstance(rules.get(key), dict):  # each changed number in place, its comment kept
            new, seen = rules[key], set()
            for n, line in enumerate(block):
                w = re.match(r"(\s+)([A-Za-z_]+):(\s*)(-?\d+)(.*)$", line)
                if w and w.group(2) in new:
                    seen.add(w.group(2))
                    block[n] = f"{w.group(1)}{w.group(2)}:{w.group(3)}{new[w.group(2)]}{w.group(5)}"
            block += [f"  {t}: {v}" for t, v in new.items() if t not in seen]
        else:
            block = yaml.safe_dump({key: rules[key]}, default_flow_style=None, sort_keys=False, width=110).rstrip().splitlines()
        out += block
        i = j
    out += [line for k in SCORING if k in rules and k not in base
            for line in yaml.safe_dump({k: rules[k]}, default_flow_style=None, sort_keys=False).rstrip().splitlines()]
    head = (f"# Your own tier rules, set in the salmobase functional SNP portal on {datetime.now():%Y-%m-%d %H:%M}: "
            f"{'; '.join(said)}. The comments are the standard file's.")
    made = head + "\n" + "\n".join(out) + "\n"
    if yaml.safe_load(made) != rules:  # a weight the file had and the rules dropped, say: a plain file says them exactly
        made = head + "\n" + yaml.safe_dump(rules, default_flow_style=None, sort_keys=False, width=110)
    return made


def for_job(request):
    """The weights.yaml text of the browser's own rules sent with a new list (rules=), or None for the rules in use.
    InputError when they can't be used, naming each mistake."""
    rules, problems = from_json(request.POST.get("rules"))
    if problems:
        raise jobs.InputError("Your tier rules can't be used: " + "; ".join(problems))
    return text(rules) if rules is not None and changes(rules) else None


def mixer(d=None, key=None):
    """The Tier rules mixer's context (_mixer.html): its channels, from the terms whose layers this release has and
    its score layers; the chromatin states; the standard rules, and the rules of the job `d` (else the page starts
    from this browser's own, or the standard)."""
    release = d or jobs.release()
    names = {x.get("name") for x in jobs.manifest(release).get("layers", [])}
    current = yaml.safe_load(jobs.rules_file(d).read_text()) if d and jobs.rules_file(d).exists() else None
    base = standard()
    return {"terms": [(t, label, why) for t, label, why, layer in TERMS if layer in names],
            "scores": [(n, label) for n, label in jobs.score_layers(d)],
            "states": jobs.release_states(release) or list(snpscore.score.STATES),
            "standard": scoring(base), "current": scoring(current) if current else None, "key": key,
            "faders": FADERS, "max_weight": MAX_WEIGHT, "max_cutoff": MAX_CUTOFF}


def summary(d, job):
    """'' for results tiered with the rules in use when they were made, else 'your own tier rules (Active state 3 → 5,
    ...)', for the results page's header."""
    if not job.get("custom_rules") or not (d / "weights.yaml").exists():
        return ""
    said = changes(yaml.safe_load((d / "weights.yaml").read_text()))
    return "your own tier rules" + (f" ({'; '.join(said[:4])}{'; ...' if len(said) > 4 else ''})" if said else "")


# ---- views ----

def standard_file(request):
    """GET: the rules in use as a file (weights.yaml, with its comments), to edit and upload as your own."""
    response = HttpResponse(snpscore.score.rules_file().read_bytes(), content_type="application/x-yaml; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="weights.yaml"'
    return response


@require_POST
def check(request):
    """POST a rules file's text (text=) or the mixer's values (rules=, JSON): {ok, problems, unused, rules (their
    scoring blocks), changes}, for the mixer to show and keep."""
    try:
        given = parse(request.POST["text"]) if request.POST.get("text") else json.loads(request.POST.get("rules") or "{}")
        if not isinstance(given, dict):
            raise snpscore.RulesError("The tier rules sent hold no blocks")
    except (snpscore.RulesError, ValueError) as e:
        return JsonResponse({"ok": False, "problems": [str(e) if isinstance(e, snpscore.RulesError) else "The tier rules sent can't be read"]})
    rules, problems, unused = compose(given)
    return JsonResponse({"ok": not problems, "problems": problems, "unused": unused, "rules": scoring(rules),
                         "changes": [] if problems else changes(rules)})


@require_POST
def download(request):
    """POST the mixer's values (rules=, JSON): them as a full weights.yaml, for snpscore --weights or a later upload."""
    rules, problems = from_json(request.POST.get("rules"))
    if problems:
        return HttpResponseBadRequest("These tier rules can't be used: " + "; ".join(problems), content_type="text/plain")
    response = HttpResponse(text(rules or standard()), content_type="application/x-yaml; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="weights_own.yaml"'
    return response


def _job(key):
    from .views import finished
    finished(key)  # 404 unless done
    return jobs.folder(key)


@require_POST
def preview(request, key):
    """POST the mixer's values (rules=, JSON): {ok, now: {tier: SNPs}, new: {tier: SNPs}, moved: SNPs that change
    tier}, for the mixer to show while its faders move. Reads only the job's result: nothing is written."""
    d = _job(key)
    rules, problems = from_json(request.POST.get("rules"))
    if problems:
        return JsonResponse({"ok": False, "problems": problems})
    con = jobs.connect([d])
    try:
        con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{d / 'result.parquet'}', file_row_number=true)")
        columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
        path, suffix = jobs.trait_tiers(d, jobs.weights(d), "all")
        new = f"SELECT file_row_number, tier FROM ({jobs.scored_sql('r', rules or standard(), columns, 'all', d)})"
        if path:
            rows = con.execute(f"""SELECT n.tier, t.{jobs.ident('tier__' + suffix)}, count(*) FROM ({new}) n
                                   JOIN read_parquet('{path}') t USING (file_row_number) GROUP BY ALL""").fetchall()
        else:
            rows = [(t, None, k) for t, k in con.execute(f"SELECT tier, count(*) FROM ({new}) GROUP BY 1").fetchall()]
    finally:
        con.close()
    count = lambda i: {str(t): sum(r[2] for r in rows if r[i] == t) for t in (1, 2, 3, 4)}  # noqa: E731
    return JsonResponse({"ok": True, "new": count(0), "now": count(1) if path else None,
                         "moved": sum(r[2] for r in rows if path and r[0] != r[1])})


@require_POST
def apply(request, key):
    """POST the mixer's values (rules=, JSON; none: the rules in use): tier these results again with them, in the job
    queue; back to the results, which show the progress and then the new tiers."""
    _job(key)
    rules, problems = from_json(request.POST.get("rules"))
    if problems:
        return HttpResponseBadRequest("These tier rules can't be used: " + "; ".join(problems), content_type="text/plain")
    try:
        jobs.retier(key, text(rules or standard()))
    except jobs.QueueFull:
        return HttpResponse("The portal is busy scoring other lists. Please try again in a minute.", status=503,
                            content_type="text/plain")
    tab = request.POST.get("tab") if request.POST.get("tab") in ("overview", "table", "export") else "overview"
    return redirect(f"{reverse('snpportal:results', args=[key])}?tab={tab}")
