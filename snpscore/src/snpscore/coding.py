"""Coding consequence (VEP-lite, ROADMAP P4.5) of the SNPs in a CDS or at a splice site, from the Ensembl 116 transcript
models (the release's transcripts.parquet) and the genome. annotate runs consequences() in its sequence step, on the
SNPs whose region_class is CDS or splice_region (all SNPs when the release has no region layer), and joins COLUMNS.

- One transcript per SNP: of the transcripts whose CDS holds it, the gene's canonical one (Ensembl_canonical tag), else
  the one with the longest CDS (then the lower transcript id). The CDS parts are joined in transcript order, so codons
  can span exons and minus-strand genes are read on the minus strand. A CDS whose first part has GFF3 phase p > 0 (an
  incomplete 5' end) starts with (3 - p) % 3 N bases, as Ensembl pads it, so residues keep Ensembl's numbering.
- Alleles: the SNP's ref/alt, turned to the genome's forward strand where ref_check says swapped or strand_flip; the
  first alt of several; no alt: the 504-fish panel's alt where the panel has a site with the SNP's ref there. Unknown
  alleles, indels and a ref matching neither the genome nor its complement give coding_sequence_variant.
- SNPs in no CDS: splice_donor_variant / splice_acceptor_variant for the 2 intronic bases at an internal exon end
  (strand-aware), with the same choice of transcript among those with an exon there.
Standard genetic code; selenocysteine and other recoded codons are not handled. stop_lost is written p.Ter357ArgextTer?
(VEP reads the 3' UTR for the new stop: extTer14). Not yet compared with Ensembl VEP genome-wide (spot checks:
tests/test_coding.py)."""
from __future__ import annotations

from .fasta import Fasta
from .formats import lit

BIN = 4096  # CDS parts and SNPs meet in fixed bins, so it is an equality join
COLUMNS = ["coding_consequence", "coding_hgvsp", "coding_aa_pos", "coding_codons", "coding_transcript", "coding_note"]
SYNONYMOUS = ("synonymous_variant", "stop_retained_variant")  # no amino-acid change: the weights.yaml 'synonymous' term
AA = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu", "G": "Gly", "H": "His",
      "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp",
      "Y": "Tyr", "V": "Val", "*": "Ter"}
CODE = {a + b + c: AA[aa] for (a, b, c), aa in zip(  # the standard code, codons in TCAG order
    [(a, b, c) for a in "TCAG" for b in "TCAG" for c in "TCAG"],
    "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG")}


def _columns(con, table):
    return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]


def codon_bases(fasta, chrom, positions):
    """Forward-strand genome bases (upper case) at 1-based positions; '.' for None (outside the CDS), N off the genome."""
    known = [p for p in positions if p]
    if chrom not in fasta.index or not known:
        return "".join("N" if p else "." for p in positions)
    lo, hi = min(known), max(known)
    seq = fasta.fetch(chrom, lo - 1, hi) if hi - lo < 64 else None  # one read when the codon is in one exon
    out = []
    for p in positions:
        base = "." if not p else seq[p - lo:p - lo + 1] if seq is not None else fasta.fetch(chrom, p - 1, p)
        out.append(base or "N")
    return "".join(out).upper()


def consequences(con, location, transcripts, public_af=None, table="snps", pos="pos"):
    """Temp table `coding`: idx and COLUMNS for the SNPs of `table` (idx, and region_class when the release has it)
    in a CDS or at a splice site; the caller joins it. `pos` is annotate's narrow table (idx, chrom, pos, ref, alt;
    alleles upper case). Python reads only the 3 codon bases of each CDS SNP."""
    cols = _columns(con, table)
    where = f"WHERE idx IN (SELECT idx FROM {table} WHERE region_class IN ('CDS', 'splice_region'))" if "region_class" in cols else ""
    con.execute(f"CREATE OR REPLACE TEMP TABLE _cs AS SELECT idx, chrom, pos, ref, alt FROM {pos} {where}")
    tx = f"read_parquet({lit(transcripts)})"
    # Two scans of the transcript models. 1: the CDS parts holding a SNP and the exon ends within 2 bp of one (parts
    # meet SNPs in fixed bins by start; the few parts longer than a bin are all in bin -1). 2: every CDS and exon part
    # of those transcripts, so that a codon can be followed across exons.
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _near AS
        WITH s AS (SELECT idx, chrom, pos, unnest(list_append(range(greatest(0, (pos - 3) // {BIN} - 1),
                                                                   (pos + 1) // {BIN} + 1), -1)) AS bin FROM _cs),
        t AS (SELECT chrom, start, "end", transcript_id, part,
                     CASE WHEN "end" - start <= {BIN} THEN start // {BIN} ELSE -1 END AS bin
              FROM {tx} WHERE part IN ('CDS', 'exon'))
        SELECT s.idx, s.pos, t.transcript_id, t.part, t.start, t."end" FROM s JOIN t USING (chrom, bin)
        WHERE (t.part = 'CDS' AND s.pos > t.start AND s.pos <= t."end")
           OR (t.part = 'exon' AND s.pos IN (t.start - 1, t.start, t."end" + 1, t."end" + 2))""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _tx AS
        SELECT chrom, start, "end", transcript_id, part, strand, phase, coalesce(canonical, false) AS canonical
        FROM {tx} WHERE part IN ('CDS', 'exon') AND transcript_id IN (SELECT DISTINCT transcript_id FROM _near)""")
    con.execute("CREATE OR REPLACE TEMP TABLE _hit AS SELECT idx, transcript_id FROM _near WHERE part = 'CDS'")
    # Every CDS part of the hit transcripts in transcript order, with the CDS bases before it, the CDS length and the
    # 5' padding
    con.execute("""CREATE OR REPLACE TEMP TABLE _seg AS
        SELECT transcript_id, chrom, start, "end", strand, canonical,
               coalesce(sum("end" - start) OVER (PARTITION BY transcript_id ORDER BY o
                                                 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)::BIGINT AS before,
               (sum("end" - start) OVER (PARTITION BY transcript_id))::BIGINT AS cds_len,
               ((3 - coalesce(first_value(phase) OVER (PARTITION BY transcript_id ORDER BY o), 0)) % 3)::BIGINT AS pad
        FROM (SELECT *, CASE WHEN strand = '-' THEN -start ELSE start END AS o FROM _tx
              WHERE part = 'CDS' AND transcript_id IN (SELECT transcript_id FROM _hit))""")
    # The chosen transcript per SNP, the SNP's offset o in the padded CDS, and the genome positions of its codon
    con.execute("""CREATE OR REPLACE TEMP TABLE _codon AS
        WITH p AS (SELECT c.idx, c.chrom, c.pos, g.transcript_id, g.strand, g.pad + g.cds_len AS len,
                          g.pad + g.before + CASE WHEN g.strand = '-' THEN g."end" - c.pos ELSE c.pos - 1 - g.start END AS o
                   FROM _cs c JOIN _hit h USING (idx)
                   JOIN _seg g ON g.transcript_id = h.transcript_id AND c.pos > g.start AND c.pos <= g."end"
                   QUALIFY row_number() OVER (PARTITION BY c.idx ORDER BY g.canonical DESC, g.cds_len DESC, g.transcript_id) = 1),
        j AS (SELECT p.*, unnest([0, 1, 2]) AS j FROM p),
        m AS (SELECT j.idx, j.j, CASE WHEN g.strand = '-' THEN g."end" - (j.o - j.o % 3 + j.j - g.pad - g.before)
                                      ELSE g.start + 1 + (j.o - j.o % 3 + j.j - g.pad - g.before) END AS gpos
              FROM j LEFT JOIN _seg g ON g.transcript_id = j.transcript_id AND j.o - j.o % 3 + j.j >= g.pad + g.before
                                     AND j.o - j.o % 3 + j.j < g.pad + g.before + g."end" - g.start)
        SELECT p.*, max(gpos) FILTER (WHERE m.j = 0) AS p1, max(gpos) FILTER (WHERE m.j = 1) AS p2,
               max(gpos) FILTER (WHERE m.j = 2) AS p3
        FROM p JOIN m USING (idx) GROUP BY ALL""")
    rows = con.execute("SELECT idx, chrom, p1, p2, p3 FROM _codon ORDER BY chrom, pos").fetchall()
    fasta = Fasta(location) if rows else None
    # a few % of the SNPs, 3 bases each; passed as one string (a list parameter converts slowly)
    text = "\n".join(f"{idx}\t{codon_bases(fasta, chrom, ps)}" for idx, chrom, *ps in rows)
    con.execute("""CREATE OR REPLACE TEMP TABLE _bases AS SELECT split_part(x, '\t', 1)::BIGINT AS idx,
                   split_part(x, '\t', 2) AS bases FROM (SELECT unnest(string_split(?, '\n')) AS x) WHERE x <> ''""", [text])
    code = ", ".join(f"({lit(k)}, {lit(v)})" for k, v in CODE.items())
    public = public_af and con.execute("SELECT count(*) FROM _cs WHERE ref IS NOT NULL AND coalesce(alt, '.') = '.'").fetchone()[0]
    panel = (f"""LEFT JOIN (SELECT chrom, "end" AS pos, ref, min(alt) AS public_alt FROM read_parquet({lit(public_af)})
                            WHERE "end" IN (SELECT pos FROM _cs) GROUP BY ALL) l USING (chrom, pos, ref)"""
             if public else "")
    comp = "translate({}, 'ACGT', 'TGCA')"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _coding AS
        WITH a AS (SELECT c.*, b.bases, o % 3 AS k, o // 3 + 1 AS aa_pos, o - o % 3 + 3 > len AS incomplete,
                          s.ref, nullif(s.alt, '.') AS alt0, coalesce(split_part(nullif(s.alt, '.'), ',', 1),
                          {'l.public_alt' if public else 'NULL'}) AS alt1, substr(b.bases, o % 3 + 1, 1) AS gb
                   FROM _codon c JOIN _bases b USING (idx) JOIN _cs s USING (idx, chrom, pos) {panel}),
        f AS (SELECT *, CASE WHEN length(ref) <> 1 OR length(alt1) <> 1 OR alt1 NOT IN ('A', 'C', 'G', 'T') THEN NULL
                             WHEN ref = gb THEN alt1 WHEN alt1 = gb THEN ref
                             WHEN {comp.format('ref')} = gb THEN {comp.format('alt1')}
                             WHEN {comp.format('alt1')} = gb THEN {comp.format('ref')} END AS alt_fwd,
                        CASE WHEN strand = '-' THEN {comp.format('bases')} ELSE bases END AS rc FROM a),
        x AS (SELECT *, substr(rc, 1, k) || CASE WHEN strand = '-' THEN {comp.format('alt_fwd')} ELSE alt_fwd END
                        || substr(rc, k + 2) AS ac FROM f),
        t AS (SELECT x.*, r.aa AS ref_aa, v.aa AS alt_aa FROM x
              LEFT JOIN (VALUES {code}) r(codon, aa) ON r.codon = x.rc LEFT JOIN (VALUES {code}) v(codon, aa) ON v.codon = x.ac),
        e AS (SELECT *, CASE WHEN incomplete THEN 'incomplete_terminal_codon_variant'
                             WHEN alt_fwd IS NULL OR ref_aa IS NULL OR alt_aa IS NULL THEN 'coding_sequence_variant'
                             WHEN aa_pos = 1 AND ref_aa = 'Met' AND alt_aa <> 'Met' THEN 'start_lost'
                             WHEN ref_aa = 'Ter' AND alt_aa = 'Ter' THEN 'stop_retained_variant'
                             WHEN ref_aa = 'Ter' THEN 'stop_lost' WHEN alt_aa = 'Ter' THEN 'stop_gained'
                             WHEN ref_aa = alt_aa THEN 'synonymous_variant' ELSE 'missense_variant' END AS consequence
              FROM t)
        SELECT idx, consequence AS coding_consequence,
               CASE consequence WHEN 'missense_variant' THEN 'p.' || ref_aa || aa_pos || alt_aa
                                WHEN 'stop_gained' THEN 'p.' || ref_aa || aa_pos || 'Ter'
                                WHEN 'synonymous_variant' THEN 'p.' || ref_aa || aa_pos || '='
                                WHEN 'stop_retained_variant' THEN 'p.Ter' || aa_pos || '='
                                WHEN 'stop_lost' THEN 'p.Ter' || aa_pos || alt_aa || 'extTer?'
                                WHEN 'start_lost' THEN 'p.Met1?' END AS coding_hgvsp,
               aa_pos AS coding_aa_pos,
               CASE WHEN alt_fwd IS NOT NULL THEN replace(lower(substr(rc, 1, k)) || substr(rc, k + 1, 1) || lower(substr(rc, k + 2))
                    || '/' || lower(substr(ac, 1, k)) || substr(ac, k + 1, 1) || lower(substr(ac, k + 2)), '.', '') END AS coding_codons,
               transcript_id AS coding_transcript,
               CASE WHEN gb NOT IN ('A', 'C', 'G', 'T') THEN 'genome base unknown'
                    WHEN ref IS NULL OR alt1 IS NULL THEN 'alleles unknown'
                    WHEN length(ref) <> 1 OR length(alt1) <> 1 THEN 'not a SNP'
                    WHEN alt_fwd IS NULL THEN 'alleles do not match the genome'
                    WHEN contains(alt0, ',') THEN 'first of several alt alleles'
                    WHEN alt0 IS NULL THEN 'alt allele from the public panel' END AS coding_note
        FROM e""")
    add_splice(con)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE coding AS
        SELECT idx, {', '.join(COLUMNS)} FROM (SELECT * FROM _coding UNION ALL BY NAME SELECT * FROM _splice)""")
    for t in ("_cs", "_near", "_tx", "_hit", "_seg", "_codon", "_bases", "_coding", "_splice"):
        con.execute(f"DROP TABLE {t}")


def add_splice(con):
    """Temp table _splice (idx, coding_consequence, coding_transcript) for the _cs SNPs in no CDS that are one of the 2
    intronic bases next to an internal exon end: splice donor at the intron's 5' end, acceptor at its 3' end."""
    con.execute("""CREATE OR REPLACE TEMP TABLE _splice AS
        WITH h AS (SELECT idx, pos, transcript_id, start, CASE WHEN pos > "end" THEN 'after' ELSE 'before' END AS side
                   FROM _near WHERE part = 'exon' AND idx NOT IN (SELECT idx FROM _hit)),
        x AS (SELECT transcript_id, start, strand, canonical, lag("end") OVER w AS prev_end, lead(start) OVER w AS next_start
              FROM _tx WHERE part = 'exon' WINDOW w AS (PARTITION BY transcript_id ORDER BY start)),
        n AS (SELECT transcript_id, sum("end" - start) AS cds_len FROM _tx WHERE part = 'CDS' GROUP BY 1)
        SELECT h.idx, CASE WHEN (h.side = 'after') = (x.strand = '+') THEN 'splice_donor_variant'
                           ELSE 'splice_acceptor_variant' END AS coding_consequence, h.transcript_id AS coding_transcript
        FROM h JOIN x USING (transcript_id, start) LEFT JOIN n USING (transcript_id)
        WHERE (h.side = 'before' AND h.pos > x.prev_end) OR (h.side = 'after' AND h.pos <= x.next_start)
        QUALIFY row_number() OVER (PARTITION BY h.idx ORDER BY x.canonical DESC, n.cds_len DESC NULLS LAST,
                                   h.transcript_id, h.side) = 1""")
