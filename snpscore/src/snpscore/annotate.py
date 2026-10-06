"""Annotate a SNP list against a release and write one row per input SNP, in input order."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb


def read_snps(con, path):
    """VCF (.vcf / .vcf.gz) or a TSV/CSV whose header has at least `chrom` and `pos`. Other columns are kept."""
    path = str(path)
    if path.endswith((".vcf", ".vcf.gz")):
        src = f"""SELECT chrom, pos, id, ref, alt FROM read_csv('{path}', header=false, all_varchar=true, delim='\t',
                                                         comment='#', names=['chrom', 'pos', 'id', 'ref', 'alt'])"""
    else:
        src = f"SELECT * FROM read_csv('{path}', header=true, all_varchar=true)"
    con.execute(f"""CREATE OR REPLACE TABLE snps AS
                    SELECT row_number() OVER () AS idx, chrom, pos::BIGINT AS pos, * EXCLUDE (chrom, pos)
                    FROM ({src})""")


def annotate(snps_path, release_dir, out_path):
    """Write the annotated SNPs to out_path: Parquet if it ends in .parquet, CSV if .csv, otherwise TSV."""
    con = duckdb.connect()
    release = Path(release_dir)
    manifest = json.loads((release / "manifest.json").read_text())
    read_snps(con, snps_path)
    known = f"SELECT DISTINCT chrom FROM read_parquet('{release}/*.parquet', union_by_name=true)"
    if con.execute(f"SELECT count(*) FROM snps WHERE chrom IN ({known})").fetchone()[0] == 0:
        raise ValueError("No SNP chromosomes match the release. Expected Ssal_v3.1 names 1-29.")

    for layer in manifest["layers"]:
        name, cols, parquet = layer["name"], layer["columns"], release / f"{layer['name']}.parquet"
        if layer["type"] == "interval":
            # ASOF picks the last interval starting before pos; it's a hit if it also ends at or after pos.
            values = "".join(f', CASE WHEN l."end" >= s.pos THEN l."{c}" END AS "{name}_{c}"' for c in cols)
            con.execute(f"""CREATE OR REPLACE TABLE snps AS
                SELECT s.*, coalesce(l."end" >= s.pos, false) AS "{name}"{values}
                FROM snps s ASOF LEFT JOIN read_parquet('{parquet}') l ON s.chrom = l.chrom AND s.pos > l.start""")
        elif layer["type"] == "nearest":
            w = layer["max_distance"]
            values = "".join(f', n."{c}" AS "{name}_{c}"' for c in cols)
            con.execute(f"""CREATE OR REPLACE TABLE snps AS
                SELECT s.*{values}, n.distance AS "{name}_distance"
                FROM snps s LEFT JOIN (
                    SELECT s.idx, l.*, greatest(l.start + 1 - s.pos, s.pos - l."end", 0) AS distance
                    FROM snps s JOIN read_parquet('{parquet}') l
                      ON s.chrom = l.chrom AND l.start < s.pos + {w} AND l."end" > s.pos - {w}
                    QUALIFY row_number() OVER (PARTITION BY s.idx ORDER BY distance, l.start) = 1
                ) n USING (idx)""")

    out = str(out_path)
    fmt = "FORMAT parquet" if out.endswith(".parquet") else "HEADER, DELIMITER ','" if out.endswith(".csv") else "HEADER, DELIMITER '\t'"
    con.execute(f"COPY (SELECT * EXCLUDE (idx) FROM snps ORDER BY idx) TO '{out}' ({fmt})")
    return Path(out_path)
