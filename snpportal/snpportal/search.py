"""Search resolver for the one search box: positions and regions (chromosome aliases, kb/Mb units), rs IDs (EVA release
9 through snpscore.rsid, which also knows ICSASG_v2 positions), genes by Ensembl id, name, catalogue name, NCBI LOC symbol
(where Ensembl's description cites the NCBI gene), human or zebrafish ortholog symbol or description, and known-loci
SNP names. One hit redirects; several show a list; suggest/ gives the top 10 for htmx autocomplete."""
from __future__ import annotations

import re
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.urls import reverse

import snpscore
from snpscore.formats import lit

from . import explore, jobs

POSITION = re.compile(r"^(?:chromosome\s*)?([A-Za-z0-9_.]+?)\s*[:\s]\s*([\d.,]+)\s*(bp|kb|mb)?"
                      r"(?:\s*[-–]\s*([\d.,]+)\s*(bp|kb|mb)?)?$", re.I)
RSID = re.compile(r"^rs(\d{1,12})$", re.I)
LOC = re.compile(r"^LOC(\d{3,12})$", re.I)  # NCBI gene symbol of an unnamed gene: LOC + NCBI gene id
UNITS = {None: 1, "bp": 1, "kb": 1_000, "mb": 1_000_000}
EXAMPLES = ["vgll3", "six6", "bco1l", "rs863754587", "LOC106600468", "25:28,990,000-29,000,000", "25:28.99-29.0Mb", "25:28996360"]
MATCHED = ["Ensembl id", "name", "ortholog", "name starts with", "id starts with", "ortholog starts with", "description", "NCBI gene id"]


def _number(text, unit):
    return int(round(float(text.replace(",", "")) * UNITS[unit.lower() if unit else None]))


@lru_cache(maxsize=4)
def _aliases(path, mtime):
    con = jobs.connect([Path(path).parent])
    return dict(con.execute(f"SELECT alias, chrom FROM read_parquet({lit(path)})").fetchall())


def chromosome(name):
    """Release chromosome for a name or alias (25, chr25, ssa25, NC_059466.1, ...), or None."""
    path = jobs.release() / "alias.parquet"
    if path.exists():
        return _aliases(str(path), path.stat().st_mtime).get(name.lower())
    bare = re.sub(r"^(chr|ssa)", "", name.lower())  # releases from before alias.parquet
    return bare if bare in (jobs.manifest().get("chrom_sizes") or [str(i) for i in range(1, 30)]) else None


def locus_url(chrom, start, end):
    """Locus browser URL for 1-based start..end. Carries both ?r= (ROADMAP P4.3a) and ?chrom=&start=&end= (stage 1)."""
    return reverse("snpportal:locus") + "?" + urlencode({"chrom": chrom, "start": start, "end": end, "r": f"{chrom}:{start}-{end}"})


def variant_url(chrom, pos):
    return reverse("snpportal:variant", args=[f"{chrom}-{pos}"])


def region(query):
    """(chrom, start, end) for '25:28,990,000-29,000,000', 'ssa25:28.99-29.0Mb' or a position (start == end); None if the
    query isn't one, or its chromosome is unknown."""
    m = POSITION.match(" ".join(query.split()))
    if not m:
        return None
    name, start, unit1, end, unit2 = m.groups()
    chrom = chromosome(name)
    if chrom is None:
        return None
    try:
        a = _number(start, unit1 or (unit2 if end else None))
        b = _number(end, unit2 or unit1) if end else a
    except ValueError:
        return None
    a, b = min(a, b), max(a, b)  # '25:29,000,000-28,990,000' means the same region
    return (chrom, a, b) if a >= 1 else None


def genes(query, limit=10):
    """Genes matching a query, best first, from one DuckDB query: [{id, name, label, chrom, start, end, strand, biotype,
    human, zebrafish, alias, matched}]. Ranks: exact id, exact name (Ensembl or catalogue), exact ortholog symbol, name
    or id prefix, ortholog prefix, then words in the description (4+ characters)."""
    release = jobs.release()
    if not query or not (release / "gene.parquet").exists():
        return []
    ortho = release / "gene_ortholog.parquet"
    join = (f"LEFT JOIN read_parquet({lit(ortho)}) o ON o.gene_id = g.id" if ortho.exists()
            else "LEFT JOIN (SELECT NULL::VARCHAR AS gene_id, NULL::VARCHAR AS human, NULL::VARCHAR AS zebrafish) o ON false")
    pairs = sorted({(r["ensembl_gene"], r["locus"]) for r in explore.catalogue() if r.get("ensembl_gene") and r.get("locus")})
    aliases = ("(VALUES " + ", ".join(f"({lit(g)}, {lit(a)})" for g, a in pairs) + ") a(gene_id, alias)" if pairs
               else "(SELECT NULL::VARCHAR AS gene_id, NULL::VARCHAR AS alias) a")
    symbols = "list_concat(string_split(lower(coalesce(o.human, '')), ','), string_split(lower(coalesce(o.zebrafish, '')), ','))"
    ncbi = LOC.match(query)
    rows = jobs.connect([release]).execute(f"""
        SELECT * FROM (
            SELECT g.id, g.name, g.chrom, g.start, g."end", g.strand, g.biotype, o.human, o.zebrafish, a.alias,
                   CASE WHEN $ncbi <> '' AND contains(g.description, 'NCBI gene') AND g.description LIKE '%Acc:' || $ncbi || ']%' THEN 7
                        WHEN upper(g.id) = upper($q) THEN 0
                        WHEN lower(g.name) = $lq OR lower(a.alias) = $lq THEN 1
                        WHEN list_contains({symbols}, $lq) THEN 2
                        WHEN starts_with(lower(g.name), $lq) OR starts_with(lower(a.alias), $lq) THEN 3
                        WHEN length($q) >= 9 AND starts_with(upper(g.id), upper($q)) THEN 4
                        WHEN len(list_filter({symbols}, s -> s <> '' AND starts_with(s, $lq))) > 0 THEN 5
                        WHEN length($q) >= 4 AND contains(lower(g.description), $lq) THEN 6 END AS rank
            FROM read_parquet({lit(release / 'gene.parquet')}) g {join}
            LEFT JOIN (SELECT gene_id, string_agg(alias, ', ') AS alias FROM {aliases} GROUP BY 1) a ON a.gene_id = g.id)
        WHERE rank IS NOT NULL
        ORDER BY rank = 7 DESC, rank, alias IS NULL, name IS NULL, try_cast(chrom AS INTEGER), chrom, start LIMIT {int(limit)}""",
                                                {"q": query, "lq": query.lower(), "ncbi": ncbi.group(1) if ncbi else ""}).fetchall()
    keys = ["id", "name", "chrom", "start", "end", "strand", "biotype", "human", "zebrafish", "alias", "rank"]
    found = [dict(zip(keys, row)) for row in rows]
    for g in found:
        g["label"] = explore.display_name(g["name"], g["alias"], g["human"], g["id"])
        g["matched"] = MATCHED[g.pop("rank")]
    return found


def resolve(query, limit=10):
    """[{kind, label, detail, url}] for a search query, best first."""
    query = " ".join(query.split())[:200]
    if not query:
        return []
    found = region(query)
    if found:
        chrom, a, b = found
        if a == b:
            return [{"kind": "variant", "label": f"{chrom}:{a:,}", "detail": "position", "url": variant_url(chrom, a)}]
        return [{"kind": "locus", "label": f"{chrom}:{a:,}-{b:,}", "detail": f"region of {b - a + 1:,} bp",
                 "url": locus_url(chrom, a, b)}]
    hits = rs_hits(query) if RSID.match(query) else []
    for g in genes(query, limit):
        extra = [f"human {g['human']}" if g["human"] else None, f"known locus {g['alias']}" if g["alias"] else None,
                 f"Ensembl name {g['name']}" if g["name"] and g["name"] != g["label"] else None]
        hits.append({"kind": "gene", "label": g["label"], "url": reverse("snpportal:gene", args=[g["id"]]),
                     "detail": " · ".join(x for x in [g["id"], f"{g['chrom']}:{g['start'] + 1:,}-{g['end']:,} ({g['strand']})",
                                                       g["biotype"], *extra, f"matched {g['matched']}"] if x)})
    q = query.lower()
    for r in explore.catalogue():
        names = [(r.get("locus") or "").lower(), (r.get("locus") or "").lower().split(" (")[0]]
        if r.get("chrom") and r.get("pos") and not RSID.match(query) and (q in names or (r.get("id") or "").lower().startswith(q)):
            hits.append({"kind": "known locus SNP", "label": r.get("id") or f"{r['chrom']}:{r['pos']}",
                         "detail": f"{r.get('locus', '')} · {r.get('trait', '').replace('_', ' ')} · {r['chrom']}:{int(r['pos']):,}",
                         "url": variant_url(r["chrom"], r["pos"])})
    return hits[:limit]


def rs_hits(query):
    """The variant page of an rs ID: from the known-loci catalogue (rs IDs newer than EVA release 9), else snpscore.rsid
    (EVA release 9, Ssal_v3.1 position and alleles, with the ICSASG_v2 position when EVA has one). [] when unknown."""
    rs = "rs" + RSID.match(query).group(1).lstrip("0")
    known = next((r for r in explore.catalogue() if (r.get("rsid") or "").lower() == rs and (r.get("pos") or "").isdecimal()), None)
    if known:
        spec = f"{known['chrom']}-{known['pos']}" + (f"-{known['ref']}-{known['alt']}" if known.get("ref") and known.get("alt") else "")
        return [{"kind": "rs ID (known locus)", "label": rs, "url": reverse("snpportal:variant", args=[spec]),
                 "detail": f"{known['chrom']}:{int(known['pos']):,} · {known.get('id')} · {known.get('trait_text')}"}]
    hit = snpscore.rsid(jobs.release(), rs) if hasattr(snpscore, "rsid") else None
    if not hit:
        return []
    spec = f"{hit['chrom']}-{hit['pos']}" + (f"-{hit['ref']}-{hit['alt']}" if hit.get("ref") and hit.get("alt") else "")
    v2 = f" · ICSASG_v2 {hit['v2_chrom']}:{hit['v2_pos']:,} {hit['v2_ref']}>{hit['v2_alt']}" if hit.get("v2_pos") else ""
    return [{"kind": "rs ID", "label": hit["rs"], "url": reverse("snpportal:variant", args=[spec]),
             "detail": f"{hit['chrom']}:{hit['pos']:,} {hit.get('ref') or ''}>{hit.get('alt') or ''} (Ssal_v3.1, EVA release 9){v2}"}]


def search(request):
    query = request.GET.get("q", "")[:200]
    hits = resolve(query) if query.strip() else []
    if len(hits) == 1:
        return redirect(hits[0]["url"])
    return render(request, "snpportal/search.html", {"nav": "explore", "title": "Search", "query": query, "hits": hits,
                                                     "examples": EXAMPLES, "rsid": bool(RSID.match(query.strip())),
                                                     "loc": bool(LOC.match(query.strip()))})


def suggest(request):
    """Autocomplete fragment for hx-get: the top 10 hits. The Server-Timing header reports the resolver's time."""
    query = request.GET.get("q", "")[:200]
    t0 = time.perf_counter()
    hits = resolve(query) if len(query.strip()) >= 2 else []
    response = render(request, "snpportal/_suggest.html", {"hits": hits, "query": query})
    response["Server-Timing"] = f"resolve;dur={1000 * (time.perf_counter() - t0):.1f}"
    return response
