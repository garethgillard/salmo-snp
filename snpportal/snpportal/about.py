"""Data, Methods, Help and 'Run it locally' pages, generated from the current release (P5.4). Data: one table of
layers (what, source, version) with the technical details (rows, files, sha256, tracks, samples, citations) closed.
Methods: the tier rules from weights.yaml (evidence weights, tiers, chromatin states with their colours, presets), a
glossary (anchors #term-<term>, #tiers, #state-<name>, #g-<word>), fine-mapping, all other settings closed, and the
methods text for a paper. Help: quick start, questions, input formats, search syntax, exports and privacy, mostly as
closed items. Run it locally: the commands to score a confidential list on your own computer."""
from __future__ import annotations

import csv
import re
from collections import Counter

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from snpscore import formats

from . import explore, jobs, palette, search

# One-line definitions; the states are AQUA-FAANG's ChromHMM labels.
STATE_TEXT = {
    "Active_TSS": "Active promoter: the start of an expressed gene (H3K4me3 with H3K27ac).",
    "Flanking_upstream": "Next to an active promoter, upstream of it.",
    "Flanking_downstream": "Next to an active promoter, downstream of it.",
    "Active_enhancer": "Active enhancer: distal element with H3K27ac and H3K4me1.",
    "Primed_enhancer": "Primed enhancer: H3K4me1 without H3K27ac.",
    "Poised_enhancer_1": "Poised enhancer: H3K4me1 with the repressive H3K27me3.",
    "Poised_enhancer_2": "Poised enhancer, second state of the model.",
    "Accessible_chromatin": "Open chromatin (ATAC) without active histone marks.",
    "Bivalent": "Both active H3K4me3 and repressive H3K27me3.",
    "Repressed_polycomb": "Repressed by Polycomb (H3K27me3).",
    "ZNF_genes_and_repeats": "Zinc-finger gene clusters and repeats.",
    "Quiescent": "No marks: inactive or unmarked.",
    "Unknown_1": "A state the model did not label.",
}
TERM_TEXT = {  # weights.yaml evidence terms -> what fires them (see snpscore.scored)
    "active": "An active state in at least one condition of the trait.",
    "active_elsewhere": "An active state only in conditions outside the trait.",
    "weak": "A weak state in a condition of the trait, and no active state there.",
    "coding": "Inside a coding sequence (CDS); amino-acid effect not computed.",
    "splice": "In a splice region.",
    "utr": "In a 5' or 3' UTR.",
    "constrained": "Inside a GERP constrained element (65 fish).",
    "regbuild": "Inside an Ensembl regulatory feature with no AQUA-FAANG peak.",
    "molqtl": "A molQTL lead SNP: shown, not scored.",
}
GLOSSARY = [  # (anchor, term, definition)
    ("peak", "Robust ATAC peak", "An AQUA-FAANG open-chromatin peak reproduced across samples. States are only known inside these peaks."),
    ("blacklist", "Blacklisted", "A region where peaks can't be called: no peak there means 'can't tell', not 'inactive'."),
    ("lore", "LORe", "Region where the duplicated chromosomes still pair; genotyping probes may cross-hybridise."),
    ("strand_ambiguous", "A/T or C/G SNP", "Reads the same on both strands; needs care on arrays."),
    ("flank_variants", "Flank variants", "Other public variants within 35 bp: they can disturb a genotyping probe."),
    ("public_af", "MAF", "Minor allele frequency in 504 public fish, wild and farmed, pooled; your strain can differ."),
    ("molqtl", "molQTL lead SNP", "The SNP most associated with a gene's expression (eQTL) or a peak's accessibility (caQTL) "
     "in 12 AQUA-FAANG fish. Lead SNPs only, not fine-mapped; display only."),
    ("cm", "cM", "Position on the Brekke et al. 2023 linkage map (AquaGen), interpolated between markers."),
    ("known_locus", "Known locus", "A published SNP from the catalogue within {window:,} bp of yours."),
    ("ohnolog", "Ss4R ohnolog", "The second copy of a gene from the salmonid genome duplication."),
    ("coordinates", "Coordinates", "Ssal_v3.1, chromosomes 1–29. Layers use BED intervals; a SNP at 1-based pos is inside "
     "one when start < pos ≤ end."),
    ("synthetic", "Synthetic", "Built from synthetic test data: not real results, never counted in tiers."),
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
    ("rsid", "rs IDs only (.txt, .tsv)", "One rs ID per line, optionally under an id header (or a table whose id column holds rs IDs "
     "and that has no chromosome and position columns). Each is placed at its Ssal_v3.1 position from EVA release 9 (the "
     "results' position_source column says rsid). rs IDs that are not in the release's table, or sit on several Ssal_v3.1 "
     "positions, are rejected as unknown_rsid and listed in the upload QC.", "id\nrs863754587\nrs863785818"),
    ("gwas", "GWAS summary statistics", "GCTA-fastGWA, PLINK2 .glm, regenie, BOLT-LMM or GEMMA output, or a table with chrom, "
     "pos and p (optionally alleles, beta, se, af and n). Alleles are turned to the Ssal_v3.1 reference (alt = effect allele) "
     "using the genome, else the 504-fish panel sites; p values are read as text, so p = 1e-400 stays 400 on the -log10 scale.",
     "CHR\tPOS\tA1\tA2\tBETA\tSE\tP\n25\t28996360\tT\tC\t0.44\t0.039\t2.6e-30"),
]
STANDARD = ("provisional", "active_states", "weak_states", "weights", "tiers", "presets")  # weights.yaml blocks shown as tables
LAYERS = {  # layer -> (what it is, source) for the Data page; other layers fall back to their manifest description
    "chromatin": ("Chromatin state in 21 tissues and stages, inside robust ATAC peaks", "AQUA-FAANG"),
    "region": ("Genic region: CDS, splice region, UTR, exon or intron", "Ensembl"),
    "regbuild": ("Regulatory build: promoters, enhancers, open chromatin", "Ensembl"),
    "gerp": ("Constrained elements in a 65-fish alignment (GERP)", "Ensembl Compara"),
    "blacklist": ("Regions where ATAC peaks can't be called", "AQUA-FAANG"),
    "lore": ("Late-rediploidized (LORe) regions", "AQUA-FAANG"),
    "gene": ("Nearest gene", "Ensembl"),
    "transcripts": ("Transcript models, for drawing genes", "Ensembl"),
    "gene_ortholog": ("Human and zebrafish orthologs", "Ensembl Compara"),
    "flank_variants": ("Public variants within 35 bp (probe flanks)", "504-fish panel"),
    "public_af": ("Allele frequencies in 504 public fish, pooled", "504-fish panel"),
    "molqtl": ("molQTL lead SNPs in 12 fish (display only)", "nf-RASQUAL"),
    "cm": ("Genetic map position (cM)", "Brekke et al."),
    "expression": ("Expression of the nearest gene per tissue", "nf-RASQUAL RNA-seq"),
}
ENA = "https://www.ebi.ac.uk/ena/browser/view/{}"
AQUAFAANG_PROJECTS = [  # (atlas, assay, ENA project); RESEARCH.md section 6
    ("BodyMap", "RNA-seq", "PRJEB47409"), ("BodyMap", "ATAC-seq", "PRJEB47408"), ("BodyMap", "ChIP-seq", "PRJEB55063"),
    ("DevMap", "RNA-seq", "PRJEB51855"), ("DevMap", "ATAC-seq", "PRJEB51854"), ("DevMap", "ChIP-seq", "PRJEB53399")]
BODYMAP_FISH = [("Immature female", "J8, J9, J10"), ("Immature male", "J15, J16, J18"), ("Mature female", "A14, A15, A24"),
                ("Mature male", "A19, A20, A22")]
CITATIONS = [  # (what, reference, DOI or URL): wording provisional (author lists to confirm)
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


def _version(layer):
    """'Ensembl 116' for Ensembl layers, else the year of its citation, else ''."""
    text = f"{layer.get('citation', '')} {layer.get('url', '')}"
    release = re.search(r"release[- ](\d+)", text)
    if release and "nsembl" in text:
        return f"Ensembl {release.group(1)}"
    year = re.search(r"\b(?:19|20)\d\d\b", layer.get("citation", ""))
    return year.group(0) if year else ""


def release_facts(m):
    """One line of release statistics from the manifest."""
    layers = {x["name"]: x for x in m.get("layers", [])}
    conditions = [c for c in layers.get("chromatin", {}).get("columns", []) if c != "summary"]
    facts = [f"{len(layers)} layers"] + ([f"{len(conditions)} chromatin conditions"] if conditions else [])
    for name, label in [("chromatin", "ATAC peaks"), ("gene", "genes"), ("public_af", "public variants")]:
        if layers.get(name, {}).get("rows"):
            facts.append(f"{layers[name]['rows']:,} {label}")
    if (m.get("catalog") or {}).get("rows"):
        facts.append(f"{m['catalog']['rows']} known loci")
    return ", ".join(facts + [f"{len(jobs.presets())} trait presets"])


def data(request):
    """/snp/about/data/: what each layer is, its source and version; rows, files, checksums, signal tracks, samples
    and citations under closed details."""
    info, m = jobs.release_info(), jobs.manifest()
    layers = []
    for x in m.get("layers", []):
        what, source = LAYERS.get(x["name"], (x.get("description", "").split(";")[0].split(" (")[0], (x.get("citation") or "").split(",")[0]))
        layers.append(dict(x, what=what, source=source, version=_version(x), link=x.get("url") or (x.get("urls") or [None])[0]))
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
        "nav": "about", "title": "Data", "release": info, "layers": layers, "files": files, "facts": release_facts(m),
        "built": f"Release {info['version']} ({info['assembly']})" + (f", built {info['created']}" if info.get("created") else ""),
        "genome": m.get("genome", {}).get("url"), "chromosomes": len(m.get("chrom_sizes") or {}),
        "tracks": track_summary(), "citations": CITATIONS,
        "projects": [(atlas, assay, acc, ENA.format(acc)) for atlas, assay, acc in AQUAFAANG_PROJECTS], "fish": BODYMAP_FISH,
        "population": next((x.get("population") for x in m.get("layers", []) if x["name"] == "public_af"), None)})


def track_summary():
    """Track registry counts {tissues, rows: [(assay, [n per tissue], total)], n, assays, chromhmm, replicates, defaults},
    or None."""
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
            "n": len(rows), "kinds": sorted({"ChIP" if a not in ("ATAC", "RNA") else a for a in assays}, key=("ATAC", "RNA", "ChIP").index),
            "chromhmm": len(cfg.get("chromhmm", [])), "replicates": sorted(Counter(t.get("replicate") for t in rows if t.get("replicate")).items()),
            "defaults": cfg.get("defaults") or {}, "generated": cfg.get("generated"), "hosts": cfg.get("hosts") or []}


def benchmark_rows():
    path = jobs.release() / "benchmark.tsv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))
    return [r for r in rows if r.get("share_pos") not in (None, "") and r.get("positives")]


def methods(request):
    """/snp/about/methods/: the tier rules from weights.yaml (weights, tiers, chromatin states with their colours,
    presets with their conditions), a glossary, fine-mapping, the other settings (closed), the benchmark as one line
    (?download=benchmark.tsv) and the methods text for a paper."""
    w, m = jobs.weights() or {}, jobs.manifest()
    rows = benchmark_rows()
    if request.GET.get("download") == "benchmark.tsv" and rows:
        header = explore.provenance("benchmark of the known loci (n = %s, smoke test only)" % rows[0]["positives"])
        return explore.download((jobs.release() / "benchmark.tsv").read_text(), "benchmark.tsv", request, header)
    conditions = [c for c in explore.layer("chromatin").get("columns", []) if c != "summary"]
    presets = [(name, ", ".join(prefixes or []), len([c for c in conditions if not prefixes or c.startswith(tuple(prefixes))]))
               for name, prefixes in (w.get("presets") or {}).items()]
    cuts = list(w.get("tiers") or [])
    tiers = [(i + 1, f"tier_score {c} or more" if i == 0 else f"tier_score {c} to {cuts[i - 1] - 1}") for i, c in enumerate(cuts)]
    if cuts:
        tiers.append((len(cuts) + 1, f"tier_score below {cuts[-1]}: no evidence found (not evidence of no effect)"))
    active, weak = w.get("active_states") or [], w.get("weak_states") or []
    states = [(name, palette.state(name)[2], STATE_TEXT.get(name, ""), "active" if name in active else "weak" if name in weak else "")
              for name in palette.STATES]
    blocks = [(name, [(k, _flat(v)) for k, v in (value.items() if isinstance(value, dict) else [("value", value)])])
              for name, value in w.items() if name not in STANDARD]
    return render(request, "snpportal/methods.html", {
        "nav": "about", "title": "Methods", "states": states, "presets": presets, "tiers": tiers, "blocks": blocks,
        "weights": [(name, value, TERM_TEXT.get(name, "")) for name, value in sorted((w.get("weights") or {}).items(), key=lambda kv: -kv[1])],
        "finemap": w.get("finemap") or {},
        "glossary": [(a, t, text.format(window=(m.get("catalog") or {}).get("window") or 50_000)) for a, t, text in GLOSSARY],
        "benchmark": rows[0]["positives"] if rows else None, "text": methods_text(m, w), "citations": citations(m)})


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
    """/snp/help/: quick start, questions, input formats with examples, search syntax, exports and vendor files, and
    privacy; the details are closed items that a link to their #id opens."""
    from snpscore import export, panel
    try:
        from snpscore.annotate import ASSEMBLY_WARNING
    except ImportError:
        ASSEMBLY_WARNING = 0.10
    return render(request, "snpportal/help.html", {
        "nav": "help", "title": "Help", "formats": FORMATS,
        "aliases": [(name, ", ".join(names)) for name, names in formats.ALIASES.items()],
        "chrom_aliases": chrom_aliases("25"), "assembly_share": f"{ASSEMBLY_WARNING:.0%}",
        "keep_hours": f"{float(jobs.setting('SNPPORTAL_KEEP_HOURS', 24)):g}", "searches": search.EXAMPLES,
        "max_mb": f"{float(jobs.setting('SNPPORTAL_MAX_UPLOAD_MB', 300)):g}", "max_snps": int(jobs.setting("SNPPORTAL_MAX_SNPS", 3_000_000)),
        "vendor_cap": int(jobs.setting("SNPPORTAL_MAX_VENDOR_SNPS", 50_000)), "locus_name": export.locus_name("25", 28996360, {"25"}),
        "bins": (panel.INFINIUM_I_MIN, panel.INFINIUM_I_POLYPLOID, panel.INFINIUM_II_MIN), "close_bp": panel.CLOSE_BP})


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


def state_palette(request):
    """/snp/colours/?name=portal|aquafaang: remember the viewer's chromatin-state palette in a cookie (palette.COOKIE) and
    go back to the page the link was on (its same-site Referer, so no URL travels in the query), else the landing page."""
    back = request.META.get("HTTP_REFERER", "")
    if not url_has_allowed_host_and_scheme(back, {request.get_host()}, request.is_secure()):
        back = reverse("snpportal:landing")
    response = redirect(back)
    name = request.GET.get("name")
    if name in palette.STATE_PALETTES:
        response.set_cookie(palette.COOKIE, name, max_age=365 * 86400, samesite="Lax", httponly=True, secure=request.is_secure())
    return response
