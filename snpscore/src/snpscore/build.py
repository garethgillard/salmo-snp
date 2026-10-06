"""Build a release: read every layer in layers.yaml, standardise it, write Parquet files + manifest.json."""
from __future__ import annotations

import datetime
import hashlib
import json
import urllib.request
from pathlib import Path

import duckdb
import yaml

# Each reader returns SQL selecting chrom, start, end (BED coordinates) plus the layer's value columns.


def read_bed(path, layer):
    cols = ["chrom", "start", "end"] + layer.get("columns", [])
    extra = "".join(f', "{c}"' for c in cols[3:])
    return f"""SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end"{extra}
               FROM read_csv('{path}', header=false, names={cols}, all_varchar=true, delim='\t')"""


def read_tsv(path, layer):
    # Header must include chrom, start, end (BED coordinates); `columns` picks what else to keep.
    extra = "".join(f', "{c}"' for c in layer.get("columns", []))
    return f"""SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end"{extra}
               FROM read_csv('{path}', header=true, all_varchar=true, delim='\t')"""


def read_aquafaang_peaks(path, layer):
    # Column 4 lists "Condition:State" for each condition where the peak is called.
    # Pivot to one column per condition holding its state (NULL = no peak in that condition).
    return f"""SELECT * FROM (
        PIVOT (
            SELECT chrom, start, "end", summary, split_part(cs, ':', 1) AS condition, split_part(cs, ':', 2) AS state
            FROM (SELECT chrom, start::BIGINT AS start, "end"::BIGINT AS "end", summary,
                         unnest(string_split(states, ',')) AS cs
                  FROM read_csv('{path}', header=false, all_varchar=true, delim='\t',
                                names=['chrom', 'start', 'end', 'states', 'score', 'strand', 'summary']))
        ) ON condition USING first(state) GROUP BY chrom, start, "end", summary)"""


def read_gff3_genes(path, layer):
    names = ["chrom", "source", "type", "start", "end", "score", "strand", "phase", "attributes"]
    return f"""SELECT chrom, start::BIGINT - 1 AS start, "end"::BIGINT AS "end",
                      regexp_extract(attributes, 'gene_id=([^;]+)', 1) AS id,
                      nullif(regexp_extract(attributes, 'Name=([^;]+)', 1), '') AS name,
                      regexp_extract(attributes, 'biotype=([^;]+)', 1) AS biotype,
                      strand
               FROM read_csv('{path}', header=false, names={names}, all_varchar=true, delim='\t', comment='#')
               WHERE type IN ('gene', 'ncRNA_gene', 'pseudogene')"""


READERS = {"bed": read_bed, "tsv": read_tsv, "aquafaang_peaks": read_aquafaang_peaks, "gff3_genes": read_gff3_genes}


def fetch(layers_yaml, data_dir):
    """Download every layer `url` that isn't in data_dir yet."""
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    for layer in yaml.safe_load(Path(layers_yaml).read_text())["layers"]:
        target = data / layer["file"]
        if layer.get("url") and not target.exists():
            print(f"downloading {layer['name']} -> {target}")
            urllib.request.urlretrieve(layer["url"], target)


def build(layers_yaml, data_dir, out_dir):
    cfg = yaml.safe_load(Path(layers_yaml).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    manifest = {
        "version": out.name,
        "assembly": cfg["assembly"],
        "chromosomes": cfg["chromosomes"],
        "created": datetime.date.today().isoformat(),
        "layers": [],
    }
    for layer in cfg["layers"]:
        src = Path(data_dir) / layer["file"]
        con.execute(f"CREATE OR REPLACE TABLE layer AS {READERS[layer['format']](src, layer)}")
        if layer["type"] == "interval":
            check_no_overlap(con, layer["name"])
        con.execute(f"COPY (SELECT * FROM layer ORDER BY chrom, start) TO '{out / layer['name']}.parquet' (FORMAT parquet)")
        columns = [r[0] for r in con.execute("DESCRIBE layer").fetchall()][3:]
        manifest["layers"].append({
            **{k: v for k, v in layer.items() if k not in ("file", "columns")},
            "source_file": layer["file"],
            "md5": hashlib.md5(src.read_bytes()).hexdigest(),
            "rows": con.execute("SELECT count(*) FROM layer").fetchone()[0],
            "columns": columns,
        })
        print(f"{layer['name']}: {manifest['layers'][-1]['rows']} rows")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out


def check_no_overlap(con, name):
    n = con.execute("""
        SELECT count(*) FROM (
            SELECT start, max("end") OVER (PARTITION BY chrom ORDER BY start
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
            FROM layer) WHERE start < prev_end""").fetchone()[0]
    if n:
        raise ValueError(f"layer '{name}' has {n} overlapping intervals; merge them before building")
