"""The portal's colours, defined once. HTML gets them as CSS custom properties and classes (css());
SVG figures embed the literal hex values from these dicts, so downloaded SVG/PNG files keep their colours.
Every pairing used for text passes WCAG AA (4.5:1); tests check it with contrast()."""
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from functools import lru_cache

ACCENT = "#0072BC"  # salmobase blue
GREY = {50: "#F8F9FA", 100: "#F1F3F5", 200: "#E3E6EA", 300: "#CED4DA", 500: "#6C757D", 700: "#495057", 900: "#212529"}
WHITE, BLACK = "#FFFFFF", "#000000"

# Tier -> (fill, text). Sequential blues, the number is always printed. Tier 2 is darker than the roadmap's #3182BD,
# which gives white text only 4.1:1.
TIERS = {1: ("#08519C", WHITE), 2: ("#2171B5", WHITE), 3: ("#C6DBEF", BLACK), 4: ("#F0F0F0", BLACK)}

# ChromHMM state -> (colour, abbreviation shown in every cell and legend). Two palettes (G to choose, PROVISIONAL): the
# portal's own, and AQUA-FAANG's itemRgb colours (chromatin-state-annotations/annotation_reports/state_annotations.tsv,
# docs/RESEARCH.md section 6). settings.SNPPORTAL_STATE_PALETTE sets the server's (apps.py calls use_states()); a viewer's
# cookie (the locus browser's 'Chromatin colours' links, about.state_palette) picks one per request (choose()). STATES is the
# active one.
ABBR = {"Active_TSS": "TSS", "Flanking_upstream": "Fl", "Flanking_downstream": "Fl", "Active_enhancer": "Enh",
        "Primed_enhancer": "Pri", "Poised_enhancer_1": "Poi", "Poised_enhancer_2": "Poi", "Accessible_chromatin": "Acc",
        "Bivalent": "Biv", "Repressed_polycomb": "Pc", "ZNF_genes_and_repeats": "ZNF", "Quiescent": "Q", "Unknown_1": "?"}
STATE_PALETTES = {
    "portal": {"Active_TSS": "#B2182B", "Flanking_upstream": "#F4A582", "Flanking_downstream": "#F4A582",
               "Active_enhancer": "#E66101", "Primed_enhancer": "#FEE08B", "Poised_enhancer_1": "#92C5DE",
               "Poised_enhancer_2": "#92C5DE", "Accessible_chromatin": "#2166AC", "Bivalent": "#762A83",
               "Repressed_polycomb": "#878787", "ZNF_genes_and_repeats": "#BABABA", "Quiescent": "#F0F0F0", "Unknown_1": "#DDDDDD"},
    "aquafaang": {"Active_TSS": "#BF2026", "Flanking_upstream": "#E81E25", "Flanking_downstream": "#E81E25",
                  "Active_enhancer": "#F99B1F", "Primed_enhancer": "#FFD078", "Poised_enhancer_1": "#F9E700",
                  "Poised_enhancer_2": "#F9F291", "Accessible_chromatin": "#7CD3F6", "Bivalent": "#9C247F",
                  "Repressed_polycomb": "#006367", "ZNF_genes_and_repeats": "#50BE96", "Quiescent": "#FFFFFF", "Unknown_1": "#C0C0C0"},
}
STATE_PALETTE_NAMES = {"portal": "portal palette", "aquafaang": "AQUA-FAANG itemRgb"}
COOKIE = "snpportal_palette"  # a viewer's choice of state palette
_server = ["portal"]
_viewer = ContextVar("snpportal_state_palette", default=None)  # set per request from the cookie (middleware below)


class _States(Mapping):
    """{state: (colour, abbreviation)} in the active palette: the viewer's choice, else the server's."""

    def __getitem__(self, name):
        return STATE_PALETTES[states_name()][name], ABBR[name]

    def __iter__(self):
        return iter(ABBR)

    def __len__(self):
        return len(ABBR)


STATES = _States()


def use_states(name):
    """Set the server's state palette ('portal' or 'aquafaang'; unknown names give the portal's). Returns its name."""
    _server[0] = name if name in STATE_PALETTES else "portal"
    return _server[0]


def choose(name):
    """This request's state palette (the viewer's cookie); None or an unknown name: the server's."""
    _viewer.set(name if name in STATE_PALETTES else None)


def states_name():
    return _viewer.get() or _server[0]


def middleware(get_response):
    """settings.MIDDLEWARE 'snpportal.palette.middleware': each request's state palette from the viewer's cookie (the
    locus browser's 'Chromatin colours' links). A middleware rather than the request_started signal, which Django 5
    sends in another context under ASGI, so the choice never reached the view."""
    def with_palette(request):
        choose(request.COOKIES.get(COOKIE))
        return get_response(request)
    return with_palette


def edge(fill):
    """A grey outline for fills that would vanish on white (AQUA-FAANG's Quiescent is #FFFFFF), else None."""
    return GREY[500] if contrast(fill, WHITE) < 1.15 else None


NO_PEAK = (WHITE, "#CCCCCC")  # fill, border
BLACKLISTED = ("#FFFFFF", "#878787", "BL")  # fill, hatch colour, label

# Tissues (Okabe-Ito, colour-blind safe); for lines, swatches and dots, not for text backgrounds.
TISSUES = {"Brain": "#0072B2", "Gill": "#56B4E9", "Gonad": "#CC79A7", "Liver": "#D55E00", "Muscle": "#009E73",
           "Embryo": "#E69F00", "HeadKidney": "#7B3294", "DistalIntestine": "#8C6D31"}  # the last two: RNA-seq only
# Genic region (results.REGION_LABELS) -> fill: sequential oranges from the protein outwards, apart from the tier blues
REGIONS = {"coding": "#A63603", "UTR": "#E6550D", "exon": "#FD8D3C", "intron": "#FDAE6B", "intergenic": "#FEE6CE",
           "other": GREY[300]}
CENTRE = "#FF1744"  # the locus browser's centre position on its ruler: a fluorescent red that no track uses

SNP_SETS = {  # public SNP datasets in the locus browser: the 504-fish panel keeps the old lane's grey; the others are
    # ColorBrewer Dark2 hues that no tissue uses
    "public_af": "#495057", "aquafaang12": "#7570B3", "synchrosmolt_af": "#A6761D", "axiom": "#E7298A"}
BASES = {"A": "#1A9850", "C": "#2166AC", "G": "#E69500", "T": "#D73027"}  # sequence logos: the usual base colours
MOTIF = "#66A61E"  # ColorBrewer Dark2 green: a TF motif change (score block, locus browser row); no term or tissue uses it
REGBUILD = "#56B4E9"  # Okabe-Ito sky blue: 'Ensembl regulatory' in the 'why this tier' bar (apart from the blues under CVD)

# Status -> (text, background, border). Always shown with an icon and text, never colour alone.
STATUS = {
    "ok": ("#1B5E20", "#EAF5EA", "#2E7D32"),
    "warn": ("#7A4A00", "#FFF4E0", "#B26B00"),
    "fail": ("#B2182B", "#FDECEE", "#B2182B"),
    "not_checked": ("#495057", "#F1F3F5", "#ADB5BD"),
}
PROVISIONAL = ("#212529", WHITE)  # outlined dark: text/border, fill
SYNTHETIC = ("#6A3D9A", "#7B4FAB", WHITE)  # stripe 1, stripe 2, text


def _luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two #RRGGBB colours (1 to 21)."""
    hi, lo = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def text_on(fill):
    """Black or white, whichever reads better on `fill`."""
    return BLACK if contrast(fill, BLACK) >= contrast(fill, WHITE) else WHITE


def state(name):
    """(fill, text colour, abbreviation) for a ChromHMM state; None or '' = no peak."""
    if not name:
        return NO_PEAK[0], BLACK, ""
    fill, abbr = STATES.get(name, (GREY[300], "?"))
    return fill, text_on(fill), abbr


def css():
    """CSS custom properties and the classes the templates use (.sp-tier-N, .st-<state> in the active state palette,
    .stp-<palette>-<state> for comparing the palettes, .sp-tissue-<tissue>)."""
    return _css(states_name())


@lru_cache(maxsize=4)
def _css(active):
    props = {"accent": ACCENT, "accent-text": text_on(ACCENT), "white": WHITE, "black": BLACK,
             "focus": "#FFBF47", "no-peak-border": NO_PEAK[1], "link": "#005A96",
             "prov": PROVISIONAL[0], "syn-1": SYNTHETIC[0], "syn-2": SYNTHETIC[1], "syn-text": SYNTHETIC[2]}
    props.update({f"grey-{k}": v for k, v in GREY.items()})
    for status, (text, bg, border) in STATUS.items():
        props.update({f"{status}-text": text, f"{status}-bg": bg, f"{status}-border": border})
    rules = []
    for tier, (fill, text) in TIERS.items():
        props[f"tier-{tier}"] = fill
        rules.append(f".sp-tier-{tier}{{background:var(--sp-tier-{tier});color:{text}}}")
    for name in STATES:
        fill, text, _ = state(name)
        rules.append(f".st-{name}{{background:{fill};color:{text}}}")
    for scheme, colours in STATE_PALETTES.items():
        rules += [f".stp-{scheme}-{name}{{background:{fill};color:{text_on(fill)}}}" for name, fill in colours.items()]
    for tissue, colour in TISSUES.items():
        rules.append(f".sp-tissue-{tissue}{{color:{colour}}}")
    for name, colour in SNP_SETS.items():
        rules.append(f".sp-set-{name}{{background:{colour}}}")
    root = ":root{" + ";".join(f"--sp-{k}:{v}" for k, v in props.items()) + "}"
    return "\n".join([root] + rules)
