"""Data, methods, help and 'Run it locally' pages, generated from the current release (P5.4): every manifest layer
with its source, checksum, synthetic flag and citation; the track registry; weights.yaml as tables with PROVISIONAL
badges; the methods text and a benchmark plot; a glossary of ChromHMM states and tier terms (anchors #state-<name>,
#term-<term>, #tiers, #g-<word>); input formats; and the commands to score a confidential list locally."""
from __future__ import annotations

import csv
import math
from collections import Counter
from html import escape

from django.shortcuts import render
from django.utils.safestring import mark_safe

from snpscore import formats

from . import explore, figures, jobs, palette

# One-line definitions. PROVISIONAL wording (G to confirm); the states are AQUA-FAANG's ChromHMM labels.
STATE_TEXT = {
    "Active_TSS": "Active promoter: the transcription start site of an expressed gene (H3K4me3 with H3K27ac).",
    "Flanking_upstream": "Next to an active promoter, upstream of it.",
    "Flanking_downstream": "Next to an active promoter, downstream of it.",
    "Active_enhancer": "Active enhancer: distal element with H3K27ac and H3K4me1.",
    "Primed_enhancer": "Primed enhancer: H3K4me1 without H3K27ac, ready but not active in this condition.",
    "Poised_enhancer_1": "Poised enhancer: H3K4me1 with the repressive mark H3K27me3.",
    "Poised_enhancer_2": "Poised enhancer, second state of the model.",
    "Accessible_chromatin": "Open chromatin (ATAC) without the active histone marks.",
    "Bivalent": "Both the active H3K4me3 and the repressive H3K27me3 mark.",
    "Repressed_polycomb": "Repressed by Polycomb (H3K27me3).",
    "ZNF_genes_and_repeats": "The state found at zinc-finger gene clusters and repeats.",
    "Quiescent": "No marks: inactive or unmarked.",
    "Unknown_1": "A state the model did not label.",
}
TERM_TEXT = {  # weights.yaml evidence terms -> what fires them (see snpscore.scored)
    "active": "An active state (the active_states below) in at least one condition of the preset.",
    "active_elsewhere": "An active state only in conditions outside the preset.",
    "weak": "A weak state (weak_states below) in a preset condition, and no active state there.",
    "coding": "Inside a coding sequence (CDS); the amino-acid effect is not computed yet.",
    "splice": "In a splice region.",
    "utr": "In a 5' or 3' UTR.",
    "constrained": "Inside a GERP constrained element of the Ensembl 65-fish alignment.",
    "regbuild": "Inside an Ensembl regulatory feature that has no AQUA-FAANG peak.",
}
GLOSSARY = [  # (anchor, term, definition)
    ("preset", "Trait preset", "The conditions (tissues and stages) that count as relevant for a trait; tiers are computed per preset."),
    ("peak", "Robust ATAC peak", "An AQUA-FAANG open-chromatin peak reproduced across samples; its ChromHMM state is given per condition. States are only shown inside these peaks."),
    ("blacklist", "Blacklisted", "A region where peaks can't be called reliably: no peak there means 'can't tell', not 'inactive'."),
    ("lore", "LORe", "Late-rediploidized region: the two Ss4R copies are near-identical, so genotyping probes may cross-hybridise."),
    ("strand_ambiguous", "A/T or C/G SNP", "Reads the same on both strands, which some genotyping assays can't tell apart."),
    ("flank_variants", "Flank variants", "Other public variants within 35 bp either side: they can disturb a genotyping probe."),
    ("public_af", "Public AF and MAF", "Alternative and minor allele frequency in the 504-fish reference panel of nf-RASQUAL "
     "(Beagle-phased; mostly the wild and farmed fish of Bertolotti et al. 2020, of European and North American descent, plus "
     "the 12 AQUA-FAANG fish and 13 others). Pooled over populations, so it hides population structure."),
    ("aquafaang12", "AQUA-FAANG 12 fish AF, DR2", "Alternative allele frequency in the 12 AQUA-FAANG BodyMap fish (whose "
     "chromatin and molQTL data the portal shows) and its imputation quality DR2 (0 to 1). Shown apart from the 504-fish AF."),
    ("molqtl", "molQTL lead SNP", "The SNP with the strongest association to a gene's expression (eQTL) or a peak's "
     "accessibility (caQTL) in the nf-RASQUAL analysis of the 12 AQUA-FAANG fish, when its eigenMT-adjusted p is below 0.1 "
     "(PROVISIONAL). Only lead SNPs are published, so it is not fine-mapping; display only, weight 0."),
    ("cm", "cM (genetic map)", "Position on the Brekke et al. 2023 linkage map (AquaGen breeding population), female and "
     "male, interpolated between markers; empty beyond a chromosome's first and last marker."),
    ("rsid", "rs ID", "A dbSNP/EVA reference SNP id. The portal knows EVA release 9's rs IDs on Ssal_v3.1 and their ICSASG_v2 "
     "positions, so rs IDs can be searched and uploaded."),
    ("known_locus", "Known locus", "A published SNP from the catalogue within the catalogue window; the effect allele is matched to your ref and alt."),
    ("ohnolog", "Ss4R ohnolog", "The second copy of a gene from the salmonid genome duplication; it often has the same name or human ortholog."),
    ("provisional", "PROVISIONAL", "A rule or threshold chosen so the prototype works, pending a decision by G."),
    ("synthetic", "SYNTHETIC", "Built from synthetic test data: not real results, and never counted in tiers."),
]
FORMATS = [  # (anchor, format, what is read, example built from the published vgll3 SNP)
    ("vcf", "VCF (.vcf, .vcf.gz)", "CHROM, POS, ID, REF and ALT only: genotype columns are never read or stored.",
     "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n25\t28996360\tvgll3_Met54Thr\tC\tT\t.\t.\t."),
    ("table", "SNP table (.tsv, .csv, .txt, optionally gzipped)", "A header naming the chromosome and position columns "
     "(header aliases below). Other columns are kept with the results as in_<name>.",
     "CHR,BP,SNP,A2,A1\n25,28996360,vgll3_Met54Thr,C,T"),
    ("plain", "Positions without a header (also the paste box)", "chrom pos, or chrom pos ref alt, separated by spaces, tabs or commas.",
     "25 28996360 C T\n25 28998410"),
    ("plink", "PLINK .bim and .map", ".bim: chromosome, id, cM, position, A1 (read as alt), A2 (read as ref). .map: the first four.",
     "25\tvgll3_Met54Thr\t0\t28996360\tT\tC"),
    ("illumina", "Illumina manifest (.csv)", "The [Assay] section: Chr and MapInfo, Name as id, the alleles from the SNP column.",
     "[Assay]\nName,Chr,MapInfo,SNP\nvgll3_Met54Thr,25,28996360,[C/T]"),
    ("axiom", "Axiom annotation (.csv)", "'#%' header lines, then Probe Set ID, Chromosome, Physical Position and Allele A/B.",
     '#%chip_type=example\n"Probe Set ID","Chromosome","Physical Position","Allele A","Allele B"\n"vgll3_Met54Thr","25","28996360","C","T"'),
]
STANDARD = ("provisional", "active_states", "weak_states", "weights", "tiers", "presets")  # weights.yaml blocks shown as tables
ENA = "https://www.ebi.ac.uk/ena/browser/view/{}"
AQUAFAANG_PROJECTS = [  # (atlas, assay, ENA project); RESEARCH.md section 6
    ("BodyMap", "RNA-seq", "PRJEB47409"), ("BodyMap", "ATAC-seq", "PRJEB47408"), ("BodyMap", "ChIP-seq", "PRJEB55063"),
    ("DevMap", "RNA-seq", "PRJEB51855"), ("DevMap", "ATAC-seq", "PRJEB51854"), ("DevMap", "ChIP-seq", "PRJEB53399")]
BODYMAP_FISH = [("Immature female", "J8, J9, J10"), ("Immature male", "J15, J16, J18"), ("Mature female", "A14, A15, A24"),
                ("Mature male", "A19, A20, A22")]
CITATIONS = [  # (what, reference, DOI or URL): wording PROVISIONAL (G to confirm the author lists)
    ("AQUA-FAANG chromatin states, ATAC peaks and signal", "Baudement M-O, Perojil Morata D, Gillard GB, ..., Kent MP, Lien S, "
     "Macqueen DJ. Salmonids reveal principles of regulatory evolution following autotetraploidization. bioRxiv 2025 (v2, "
     "2025-12-23; not yet peer reviewed).", "https://doi.org/10.64898/2025.12.18.695160"),
    ("504-fish panel allele frequencies, molQTL and expression", "Nguyen DT, Sandve SR, Lien S, Grønvold L. BMC Genomics "
     "2025;26:1070.", "https://doi.org/10.1186/s12864-025-12302-5"),
    ("Samples of most of the 504-fish panel", "Bertolotti et al. 2020 (ENA PRJEB38061).", ENA.format("PRJEB38061")),
    ("Genetic map (cM)", "Brekke et al. 2023, Scientific Reports (map file: bioRxiv 2023.06.07.543993 v2).",
     "https://doi.org/10.1038/s41598-023-47208-3"),
    ("rs IDs and ICSASG_v2 positions", "European Variation Archive, release 9 (Salmo salar).", "https://www.ebi.ac.uk/eva/"),
    ("FAANG data portal", "Harrison PW et al. 2021, Frontiers in Genetics 12:639238.", "https://doi.org/10.3389/fgene.2021.639238"),
    ("SalmoBase", "Samy et al. 2017, BMC Genomics 18.", "https://salmobase.org/"),
    ("Genes, regulatory build, GERP", "Ensembl release 116 (Salmo salar, Ssal_v3.1).", "https://www.ensembl.org/Salmo_salar/"),
]


def data(request):
    """/snp/about/data/: the release's layers and other files from manifest.json, and the track registry."""
    info, m = jobs.release_info(), jobs.manifest()
    files = []
    if m.get("alias"):
        a = m["alias"]
        files.append(("alias.parquet", "Chromosome names accepted in uploads and search (25, chr25, ssa25, NC_059466.1, ...)",
                      a.get("rows"), a.get("sha256"), a.get("url"), a.get("source_file")))
    if m.get("rsid"):
        r = m["rsid"]
        files.append((r.get("file", "rsid.parquet"), f"rs IDs of EVA release 9 on Ssal_v3.1 and ICSASG_v2, for search and rs-ID uploads "
                      f"({r.get('left_out', 0):,} rs IDs on several Ssal_v3.1 positions left out)", r.get("rows"), r.get("sha256"),
                      (r.get("urls") or [None])[0], r.get("source_file")))
    if m.get("catalog"):
        c = m["catalog"]
        files.append((c.get("file", "catalog/known_loci.tsv"), f"Known-loci catalogue; uploads within {c.get('window', 0):,} bp get a badge",
                      c.get("rows"), c.get("sha256"), None, None))
    for name, sha in (m.get("files") or {}).items():
        files.append((name, {"weights.yaml": "Tier rules and trait presets", "tracks.yaml": "Signal track registry"}.get(name, ""),
                      None, sha, None, None))
    if (jobs.release() / "pool" / "pool.parquet").exists():
        files.append(("pool/pool.parquet", "Public variants annotated with this release (gene pages, candidate lists)", None, None, None, None))
    return render(request, "snpportal/about_data.html", {
        "nav": "about", "title": "Data", "release": info, "layers": m.get("layers", []), "files": files,
        "genome": m.get("genome", {}).get("url"), "chromosomes": len(m.get("chrom_sizes") or {}),
        "tracks": track_summary(), "provisional": m.get("provisional") or [], "citations": CITATIONS,
        "projects": [(atlas, assay, acc, ENA.format(acc)) for atlas, assay, acc in AQUAFAANG_PROJECTS], "fish": BODYMAP_FISH,
        "population": next((x.get("population") for x in m.get("layers", []) if x["name"] == "public_af"), None),
        "meta": f"Release {info['version']} ({info['assembly']})" + (f", built {info['created']}" if info.get("created") else "")})


def track_summary():
    """Track registry counts {tissues, rows: [(assay, [n per tissue], total)], n, chromhmm, replicates, defaults}, or None."""
    try:
        from snpscore import tracks
        cfg = tracks.load_tracks(jobs.release())
    except (ImportError, OSError, ValueError):
        return None
    rows = cfg.get("tracks", [])
    counts = Counter((t["assay"], t["tissue"]) for t in rows)
    order = list(palette.TISSUES) + ["Sperm", "HeadKidney", "DistalIntestine"]
    tissues = sorted({t["tissue"] for t in rows}, key=lambda t: (order.index(t) if t in order else len(order), t))
    assays = sorted({t["assay"] for t in rows}, key=lambda a: (a not in ("ATAC", "RNA"), a == "Input", a))
    return {"tissues": tissues, "rows": [(a, [counts.get((a, t), 0) for t in tissues], sum(counts[(a, t)] for t in tissues)) for a in assays],
            "n": len(rows), "chromhmm": len(cfg.get("chromhmm", [])), "replicates": sorted(Counter(t.get("replicate") for t in rows if t.get("replicate")).items()),
            "defaults": cfg.get("defaults") or {}, "generated": cfg.get("generated"), "hosts": cfg.get("hosts") or []}


def wilson(share, n, z=1.96):
    """95% Wilson interval of a proportion."""
    if not n:
        return 0.0, 1.0
    d = 1 + z * z / n
    centre, half = (share + z * z / (2 * n)) / d, z * math.sqrt(share * (1 - share) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def benchmark_rows():
    path = jobs.release() / "benchmark.tsv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))
    return [r for r in rows if r.get("share_pos") not in (None, "") and r.get("positives")]


def benchmark_svg(rows, note=""):
    """Dot plot: share of positives (known loci, filled) and of matched controls (open) per feature, with 95% Wilson
    intervals."""
    left, span, step, top = 230, 380, 22, 34
    x = lambda v: left + span * v
    parts = [f'<circle cx="{left}" cy="10" r="5" fill="{palette.ACCENT}"/><text x="{left + 10}" y="14">known loci</text>'
             f'<circle cx="{left + 110}" cy="10" r="5" fill="{palette.WHITE}" stroke="{palette.GREY[700]}" stroke-width="1.5"/>'
             f'<text x="{left + 120}" y="14">matched controls</text>']
    height = top + step * len(rows) + 24
    for v in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<line x1="{x(v):.1f}" y1="{top - 6}" x2="{x(v):.1f}" y2="{height - 22}" stroke="{palette.GREY[200]}"/>'
                     f'<text x="{x(v):.1f}" y="{height - 8}" text-anchor="middle" fill="{palette.GREY[700]}">{v:g}</text>')
    for i, r in enumerate(rows):
        y = top + i * step + 6
        parts.append(f'<text x="{left - 10}" y="{y + 4}" text-anchor="end">{escape(r["feature"])}</text>')
        for share, n, dy, fill in [(r["share_pos"], r["positives"], -4, palette.ACCENT), (r["share_ctrl"], r["controls"], 4, palette.WHITE)]:
            share, n = float(share or 0), int(n or 0)
            lo, hi = wilson(share, n)
            label = f"{r['feature']}: {share:.2f} of {n} ({lo:.2f} to {hi:.2f})"
            parts.append(f'<line x1="{x(lo):.1f}" y1="{y + dy}" x2="{x(hi):.1f}" y2="{y + dy}" stroke="{palette.GREY[500]}"/>'
                         f'<circle cx="{x(share):.1f}" cy="{y + dy}" r="4" fill="{fill}" stroke="{palette.GREY[700] if fill == palette.WHITE else fill}" '
                         f'stroke-width="1.5"><title>{escape(label)}</title></circle>')
    n = rows[0]["positives"] if rows else 0
    desc = f"Share of the {n} known loci and of matched public controls with each feature, with 95% Wilson intervals. {note}"
    return figures.svg(left + span + 30, height, "Benchmark: known loci vs matched controls", desc, "".join(parts))


def methods(request):
    """/snp/about/methods/: weights.yaml as tables (PROVISIONAL blocks badged), coordinates, the methods text with
    citations, and the benchmark plot (?download=benchmark.svg|benchmark.tsv)."""
    w, m = jobs.weights() or {}, jobs.manifest()
    rows = benchmark_rows()
    what = request.GET.get("download")
    if what in ("benchmark.svg", "benchmark.tsv") and rows:
        header = explore.provenance("benchmark of the known loci (n = %s, smoke test only)" % rows[0]["positives"])
        if what == "benchmark.svg":
            return explore.download(benchmark_svg(rows, " ".join(line[2:] for line in header)), "benchmark.svg", request, [])
        return explore.download((jobs.release() / "benchmark.tsv").read_text(), "benchmark.tsv", request, header)
    provisional = set(w.get("provisional") or []) | set(m.get("provisional") or [])
    conditions = [c for c in explore.layer("chromatin").get("columns", []) if c != "summary"]
    presets = [(name, prefixes or [], [c for c in conditions if not prefixes or c.startswith(tuple(prefixes))])
               for name, prefixes in (w.get("presets") or {}).items()]
    cuts = list(w.get("tiers") or [])
    tiers = [(i + 1, f"{c} or more" if i == 0 else f"{c} to {cuts[i - 1] - 1}") for i, c in enumerate(cuts)]
    if cuts:
        tiers.append((len(cuts) + 1, f"below {cuts[-1]}"))
    blocks = [(name, [(k, _flat(v)) for k, v in (value.items() if isinstance(value, dict) else [("value", value)])])
              for name, value in w.items() if name not in STANDARD]
    fig = None
    if rows:
        fig = {"name": "benchmark", "title": "Benchmark: known loci vs matched controls", "svg": mark_safe(benchmark_svg(rows)),
               "info": "Share of the published known loci (filled) and of public sites matched to them (open) that have each "
                       "feature, with 95% Wilson intervals. With so few loci this only checks that the layers work.",
               "svg_url": "?download=benchmark.svg", "tsv_url": "?download=benchmark.tsv",
               "caption": f"n = {rows[0]['positives']}, smoke test only. snpscore benchmark on release {m.get('version')}."}
    return render(request, "snpportal/methods.html", {
        "nav": "about", "title": "Methods", "provisional": provisional,
        "weights": [(name, value, TERM_TEXT.get(name, "")) for name, value in sorted((w.get("weights") or {}).items(), key=lambda kv: -kv[1])],
        "tiers": tiers, "presets": presets, "active": w.get("active_states") or [], "weak": w.get("weak_states") or [],
        "blocks": blocks, "text": methods_text(m, w), "citations": citations(m), "figure": fig,
        "window": (m.get("catalog") or {}).get("window")})


def _flat(value):
    """A weights.yaml value as text: lists joined with commas, mappings as 'key = value; ...'."""
    if isinstance(value, dict):
        return "; ".join(f"{k} = {_flat(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_flat(v) for v in value)
    return str(value)


def methods_text(m, w):
    """(paragraphs, references) for a paper's methods: snpscore.export.methods_text when this snpscore has it, else a
    short paragraph from the manifest."""
    try:
        from snpscore import export
        body, _, tail = export.methods_text(m, w, release_dir=jobs.release()).partition("\n\nReferences\n")
        cited = [x["citation"] for x in m.get("layers", []) if x.get("citation")]  # listed with their layers below
        refs = [r[2:] for r in tail.splitlines() if r.startswith("- ") and not any(r[2:].startswith(c) for c in cited)]
        return [p.strip() for p in body.split("\n\n") if p.strip()], refs
    except (ImportError, AttributeError, TypeError, KeyError, ValueError):
        pass
    layers = {x["name"] for x in m.get("layers", [])}
    n = len([c for c in explore.layer("chromatin").get("columns", []) if c != "summary"])
    text = (f"SNPs were annotated with snpscore {m.get('snpscore_version') or ''} against release {m.get('version')} on "
            f"{m.get('assembly', 'Ssal_v3.1')}: AQUA-FAANG robust ATAC peaks with their ChromHMM state in {n} conditions"
            + (", Ensembl 116 genic region classes and the nearest gene" if "region" in layers else "")
            + (", the Ensembl regulatory build" if "regbuild" in layers else "")
            + (", GERP constrained elements from the Ensembl Compara 65-fish alignment" if "gerp" in layers else "")
            + (" and allele frequencies of the 504-fish reference panel" if "public_af" in layers else "")
            + ". Each SNP's tier_score is the sum of the weights of its evidence for the chosen trait preset, and tiers "
              "are cut-offs on that score (rules in weights.yaml, sha256 given in each download; PROVISIONAL).")
    return [text], []


def citations(m):
    """Distinct layer citations, in manifest order, with the layers that use each."""
    seen = {}
    for layer in m.get("layers", []):
        if layer.get("citation"):
            seen.setdefault(layer["citation"], []).append(layer["name"])
    return list(seen.items())


def help_page(request):
    """/snp/help/: quick start, input formats with examples, chromosome aliases, assembly check, privacy, glossary,
    colour key and how to cite."""
    w = jobs.weights() or {}
    cuts = list(w.get("tiers") or [])
    tiers = [(t, f"tier_score {cuts[t - 1]} or more" if t <= len(cuts) else "none of the above") for t in palette.TIERS]
    try:
        from snpscore.annotate import ASSEMBLY_WARNING
    except ImportError:
        ASSEMBLY_WARNING = 0.10
    return render(request, "snpportal/help.html", {
        "nav": "help", "title": "Help", "tiers": tiers, "tissues": list(palette.TISSUES),
        "states": [(name, palette.state(name)[2], STATE_TEXT.get(name, "")) for name in palette.STATES],
        "palettes": [(key, label, key == palette.states_name()) for key, label in palette.STATE_PALETTE_NAMES.items()],
        "terms": [(name, value, TERM_TEXT.get(name, "")) for name, value in (w.get("weights") or {}).items()],
        "active": w.get("active_states") or [], "weak": w.get("weak_states") or [], "glossary": GLOSSARY,
        "formats": FORMATS, "aliases": [(name, ", ".join(names)) for name, names in formats.ALIASES.items()],
        "chrom_aliases": chrom_aliases("25"), "assembly_share": f"{ASSEMBLY_WARNING:.0%}",
        "keep_hours": f"{float(jobs.setting('SNPPORTAL_KEEP_HOURS', 24)):g}"})


def chrom_aliases(chrom):
    """The names alias.parquet accepts for one chromosome (lower case, as stored), e.g. chr25, ssa25, nc_059466.1."""
    path = jobs.release() / "alias.parquet"
    if not path.exists():
        return []
    return [a for a, in jobs.connect([jobs.release()]).execute(
        f"SELECT alias FROM read_parquet({formats.lit(path)}) WHERE chrom = ? AND alias <> chrom ORDER BY alias", [chrom]).fetchall()]


def run_locally(request):
    """/snp/run-locally/: how to score a confidential list on your own computer with the same release and settings."""
    info, presets = jobs.release_info(), jobs.presets()
    trait = request.GET.get("trait", "all")
    trait = trait if trait in dict(presets) else "all"
    release = jobs.release()
    checksum = None
    if (release / "release.zip.sha256").exists():
        checksum = ((release / "release.zip.sha256").read_text().split() or [None])[0]
    folder = f"release/{info['version']}"
    return render(request, "snpportal/run_locally.html", {
        "nav": "about", "title": "Run it locally", "release": info, "presets": presets, "trait": trait, "folder": folder,
        "zip": (release / "release.zip").exists(), "zip_sha256": checksum,
        "command": f"snpscore annotate my_snps.vcf.gz --release {folder} --trait {trait} -o my_snps_{trait}.tsv",
        "keep_hours": f"{float(jobs.setting('SNPPORTAL_KEEP_HOURS', 24)):g}"})
