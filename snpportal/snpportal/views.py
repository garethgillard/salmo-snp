"""Upload a SNP list, annotate it with snpscore, show it as a sortable paged table, download it as TSV."""
import json
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlencode

import duckdb
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

import snpscore

SUFFIXES = (".vcf", ".vcf.gz", ".tsv", ".csv", ".txt")
SHOWN = ["id", "chrom", "pos", "ref", "alt", "chromatin_summary", "gene_name", "gene_id", "gene_distance", "blacklist", "lore"]
PAGE_SIZE = 50


def results_dir():
    d = Path(getattr(settings, "SNPPORTAL_RESULTS_DIR", Path(tempfile.gettempdir()) / "snpportal"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def result_file(key):
    path = results_dir() / f"{key}.parquet"
    if not path.exists():
        raise Http404("Result not found or expired")
    return path


def release_version():
    return json.loads((Path(settings.SNPSCORE_RELEASE) / "manifest.json").read_text())["version"]


def upload(request):
    error = None
    f = request.FILES.get("snps")
    if request.method == "POST" and f:
        suffix = next((s for s in SUFFIXES if f.name.lower().endswith(s)), None)
        if suffix is None:
            error = "Upload a .vcf, .vcf.gz, .tsv, .csv or .txt file."
        else:
            key = uuid.uuid4()
            src = results_dir() / f"{key}{suffix}"
            with open(src, "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
            try:
                snpscore.annotate(src, settings.SNPSCORE_RELEASE, results_dir() / f"{key}.parquet")
                return redirect("snpportal:results", key=key)
            except (ValueError, duckdb.Error) as e:
                error = str(e)
            finally:
                src.unlink()
    return render(request, "snpportal/upload.html", {"error": error, "release": release_version()})


def results(request, key):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{result_file(key)}')")
    types = dict((r[0], r[1]) for r in con.execute("DESCRIBE r").fetchall())
    shown = [c for c in SHOWN if c in types]
    flags = [c for c, t in types.items() if t == "BOOLEAN"]
    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    counts = con.execute("SELECT " + ", ".join(f'count_if("{c}")' for c in flags) + " FROM r").fetchone() if flags else ()

    sort = request.GET.get("sort", "")
    sort = sort if sort in types else ""
    desc = request.GET.get("desc") == "1"
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(int(request.GET["page"]) if request.GET.get("page", "").isdigit() else 1, pages) or 1

    order = f'ORDER BY "{sort}" {"DESC" if desc else "ASC"} NULLS LAST' if sort else ""
    columns = ", ".join(f'"{c}"' for c in shown)
    rows = con.execute(f"SELECT {columns} FROM r {order} LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}").fetchall()

    def link(**changes):
        params = {"sort": sort, "desc": "1" if desc else "", "page": page, **changes}
        return "?" + urlencode({k: v for k, v in params.items() if v})

    return render(request, "snpportal/results.html", {
        "key": key,
        "release": release_version(),
        "total": total,
        "flags": list(zip(flags, counts)),
        "headers": [(c, link(sort=c, desc="1" if c == sort and not desc else "", page=1),
                     ("▼" if desc else "▲") if c == sort else "") for c in shown],
        "rows": rows,
        "page": page,
        "pages": pages,
        "prev": link(page=page - 1) if page > 1 else None,
        "next": link(page=page + 1) if page < pages else None,
    })


def download(request, key):
    path = result_file(key)
    tsv = path.with_suffix(".tsv")
    if not tsv.exists():
        duckdb.connect().execute(f"COPY (SELECT * FROM read_parquet('{path}')) TO '{tsv}' (HEADER, DELIMITER '\t')")
    return FileResponse(open(tsv, "rb"), as_attachment=True, filename=f"snps_annotated_{release_version()}.tsv")
