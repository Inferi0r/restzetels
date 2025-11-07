import os
import re
from dataclasses import dataclass
from typing import Final


REPO_ROOT: Final[str] = os.path.dirname(os.path.dirname(__file__))
DATA_DIR: Final[str] = os.path.join(REPO_ROOT, "pdf_scraper_input")
OUT_BASE: Final[str] = os.path.join(REPO_ROOT, "pdfs")
# Keep traces under the package folder as requested
TRACES_DIR: Final[str] = os.path.join(REPO_ROOT, "pdf_scraper", "traces")
INDEX_PATH: Final[str] = os.path.join(DATA_DIR, "municipality_pdfs_index.json")
# Manual overview URL seeds are stored alongside the package for easier editing
MANUAL_SEEDS_PATH: Final[str] = os.path.join(REPO_ROOT, "pdf_scraper", "gemeente_manual_urls.json")

# Election/year config (grouped for easy future changes)
TARGET_YEAR_FULL: Final[int] = 2025
TARGET_YEAR_SHORT: Final[int] = 25
ELECTION_SLUG: Final[str] = "tk"  # used in a few endpoints/searches

# Filter keywords for other elections and generic non-PV docs
# Split election bans into two categories:
# - BANNED_ELECTION_SUBSTR: long tokens banned on substring match
# - BANNED_ELECTION_TOKENS: short abbreviations banned only when token-like
BANNED_ELECTION_SUBSTR = {
    # Other elections (exclude)
    "waterschap", "provinciale", "europees",
    # Explicit municipal election terms (not generic site sections like 'gemeenteraad-en-college')
    "gemeenteraadsverkiez", "gemeenteraadsverkiezing", "gemeenteraadsverkiezingen",
}
BANNED_ELECTION_TOKENS = {
    # Abbreviations: PS/EP/GR/WS — ban only when token-like (non-alnum boundaries)
    "ps", "ep", "gr", "ws",
}

BANNED_DOC_KEYWORDS = {
    # common non-PV document keywords
    "volmacht", "kiezerspas", "kennisgeving", "kandidaat", "kandidaten",
    "aanwijzing", "krant", "flyer", "afval", "aansluit", "woo", "wob", "bekendmaking", 
    "bezwaar", "registratie", "inspectie", "publicatie", "begroting", "stukken", "beleid", "nota",
    "rapport", "handreiking", "handleiding", "verklaring", "wet", "route",
    "onderzoek", "machtig", "stempas", "privacy", "toegankelijk", "posters",
    "rapport", "voorschrift",
}

# URL-only banned document keywords: only trigger when present inside a URL
BANNED_DOC_URL_ONLY = {
    "zorg",
}

# Regex patterns compiled once
BANNED_NAME_RES = [
    # Block explicit EP year patterns like "ep24", "ep 2024", etc.
    re.compile(r"\bep\s*[-_ ]?\s*(?:20)?\d{2}\b", re.I),
]

# PDF page/link hints
PDF_PAGE_HINT_RE = re.compile(
    # Simplified: rely on generic tokens; remove redundant combos
    r"verkiez|uitslag|uitkomst|proces|verbaal|process[-\s]?verbal|"
    r"stembureau|tweede\s*-?\s*kamer|document|download|\bpv\b|"
    r"n10|na\s*31|election|second\s*chamber|polling|evenementenhal|telling",
    re.I,
)

OVERVIEW_HINT_RE = re.compile(
    (
        r"overzicht|proces[-\s]?verbaal|processen[-\s]?verbaal|proces[-\s]?verbal(?:en)?|"
        r"kies\s+stembureau|stembureau[s]?|stadsdeel|verkiez|uitslag|uitkomst|"
        r"na\s*31|tweede\s*-?\s*kamer|process[-\s]?verbal|second\s*chamber|evenementenhal|telling|"
        r"zo[\s_-]*is[\s_-]*er[\s_-]*gestemd|\bgestemd\b"
    ),
    re.I,
)

def _load_manual_seeds(path: str = MANUAL_SEEDS_PATH) -> dict:
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Accept either of these shapes:
        # 1) {"Gemeente": ["url1", "url2", ...], ...}
        # 2) {"Gemeente": "url", ...}  (single URL per line, compact format)
        if isinstance(data, dict):
            out: dict[str, list[str]] = {}
            for k, v in data.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, str) and v.strip():
                    out[k] = [v.strip()]
                elif isinstance(v, list):
                    out[k] = [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
            return out
    except Exception:
        pass
    return {}

# Extra seeds per municipality for known overview pages (loaded from JSON if present)
EXTRA_SEEDS = _load_manual_seeds()

# Minimal site-search queries (tuned to be small set to limit requests)
SITE_SEARCH_QUERIES = [
    "proces verbaal",
    "proces-verbaal",
    "pv stembureau",
    "N10",
    "Na31",
]


@dataclass(frozen=True)
class HeuristicLimits:
    # caps to minimize crawling
    max_candidate_overview_pages: int = 12
    max_site_search_tries: int = 12
    max_playwright_clicks: int = 200
    # early stop guards
    max_total_pdfs: int = 450
    pivot_pdf_threshold: int = 6  # treat a page as pivot when >= this many PDFs found
    max_platform_hubs: int = 3
    max_ranked_overview_pages: int = 12


LIMITS = HeuristicLimits()
