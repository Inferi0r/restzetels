import json
import os
import re
from urllib.parse import urlparse
from typing import Any

from .config import (
    DATA_DIR,
    TARGET_YEAR_FULL,
    TARGET_YEAR_SHORT,
    BANNED_ELECTION_KEYWORDS,
    BANNED_DOC_KEYWORDS,
    BANNED_DOC_URL_ONLY,
    BANNED_NAME_RES,
)
from .config import OVERVIEW_HINT_RE
from .fetch_gemeente_urls import kiesraad_url_for
from .verified_urls import (
    get_entry as _verified_get_entry,
    latest_source_url as _verified_latest_source,
    latest_kiesraad_url as _verified_latest_kiesraad,
    record_kiesraad_url as _verified_record_kiesraad,
    add_source_url as _verified_add_source,
    needs_kiesraad_refresh as _verified_needs_refresh,
)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_names() -> list[str]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    return [it.get("name") for it in data.get("items", []) if it.get("name")]


def get_municipalities_slice(start: int, end: int) -> list[str]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    s = max(1, start) - 1
    e = max(s, end)
    return [it.get("name") for it in items[s:e] if it.get("name")]


def get_start_url(name: str) -> str | None:
    # 1) prefer previously verified sources (exact PV page) with newest date
    ent = _verified_get_entry(name)
    src = _verified_latest_source(ent)
    if src:
        # Ensure kiesraad_url is present/fresh in the store even when we return a scraped source
        try:
            if _verified_needs_refresh(ent) or not _verified_latest_kiesraad(ent):
                k = kiesraad_url_for(name)
                if k:
                    _verified_record_kiesraad(name, k)
        except Exception:
            pass
        return src
    # 2) kiesraad cached URL (no network) unless the cache is stale (>30 days)
    kr = _verified_latest_kiesraad(ent)
    if kr and not _verified_needs_refresh(ent):
        return kr
    # 3) if stale or missing, fetch fresh kiesraad URL (network) and record
    try:
        k = kiesraad_url_for(name)
        if k:
            _verified_record_kiesraad(name, k)
            return k
    except Exception:
        pass
    # 4) legacy verified format from earlier tooling
    try:
        v2 = load_json(os.path.join(DATA_DIR, "municipality_links_verified.json")).get("verified", [])
        for it in v2:
            if it.get("name") == name:
                if it.get("status") == 200:
                    return it.get("final_url") or it.get("start_url")
                if it.get("start_url"):
                    return it.get("start_url")
    except Exception:
        pass
    # 5) baseline municipalities.json
    try:
        items = load_json(os.path.join(DATA_DIR, "municipalities.json")).get("items", [])
        for it in items:
            if it.get("name") == name and it.get("url"):
                return it.get("url")
    except Exception:
        pass
    return None


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    # Allow common punctuation including ampersand for names like "B&W"
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()&]", "", name)
    return name[:150] if len(name) > 150 else name


def ensure_pdf_extension(name: str) -> str:
    try:
        if not isinstance(name, str):
            return name
        n = name.strip()
        low = n.lower()
        # Replace .htm/.html with .pdf
        if low.endswith('.htm'):
            return n[:-4] + '.pdf'
        if low.endswith('.html'):
            return n[:-5] + '.pdf'
        return n
    except Exception:
        return name


_SIZE_TOKEN_RE = re.compile(r"\b\d+[\d.,]*\s*(?:k|kb|mb|gb)\b", re.I)
_PAREN_SIZE_RE = re.compile(r"\((?:\s*pdf\s*,\s*)?\s*\d+[\d.,]*\s*(?:k|kb|mb|gb)\s*\)", re.I)


def strip_size_tokens(s: str) -> str:
    if not isinstance(s, str):
        return s
    out = _PAREN_SIZE_RE.sub("", s)
    out = _SIZE_TOKEN_RE.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = out.strip()
    return out


def clean_pdf_name_from_text(txt: str) -> str | None:
    if not isinstance(txt, str):
        return None
    t = txt.strip()
    if not t:
        return None
    t = re.sub(r"^pdf\s*bestand\s*", "", t, flags=re.I)
    m = re.search(r"([\wÀ-ÖØ-öø-ÿ _\-().]+?\.pdf)\b", t, re.I)
    if m:
        base = m.group(1)
    else:
        base = strip_size_tokens(re.sub(r"\([^)]*\)", "", t))
        if not base.lower().endswith('.pdf'):
            base = base + '.pdf'
    # Always strip size tokens even when the anchor text already contains ".pdf"
    # to avoid names like "… 2.24 MB.pdf"
    base = strip_size_tokens(base)
    return sanitize_filename(base)


def _looks_hashy_basename(base_no_ext: str) -> bool:
    try:
        b = (base_no_ext or '').strip().lower()
        if not b:
            return False
        if re.fullmatch(r"[0-9a-f]{20,}", b):
            return True
        if re.fullmatch(r"[0-9a-z]{24,}", b):
            return True
        if b.startswith('pv_'):
            if re.fullmatch(r"pv_[0-9a-f]+([._-][0-9a-f]+)+", b):
                return True
            if re.search(r"[0-9]{6,}", b):
                return True
        return False
    except Exception:
        return False


def is_current_year_pdf(label: str) -> bool:
    if not isinstance(label, str):
        return True
    s = label.lower()
    # Remove URLs for election keyword checks to avoid false hits like 'ps' in 'https'
    s_no_urls = re.sub(r"https?://\S+", " ", s)
    # election types to exclude (check without URLs to avoid false positives)
    if any(re.search(rf"\b{re.escape(k)}\b", s_no_urls) for k in BANNED_ELECTION_KEYWORDS):
        return False
    # document keywords: two categories → 'both' (name/text/URL) and 'url-only'
    urls = re.findall(r"https?://\S+", s)
    if any(k in s for k in BANNED_DOC_KEYWORDS):
        return False
    if any(any(k in u for k in BANNED_DOC_URL_ONLY) for u in urls):
        return False
    for rx in BANNED_NAME_RES:
        if rx.search(s):
            return False
    # tk2025/tk25 accept; tk2023/tk23 reject
    m = re.search(r"tk\s*[-_]?\s*20(\d{2})", s)
    if m:
        return (2000 + int(m.group(1))) == TARGET_YEAR_FULL
    m = re.search(r"tk\s*[-_]?\s*(\d{2})(?!\d)", s)
    if m:
        return int(m.group(1)) == TARGET_YEAR_SHORT
    m = re.search(r"tweede\s+kamer\s+20(\d{2})", s)
    if m:
        return (2000 + int(m.group(1))) == TARGET_YEAR_FULL
    # dates dd-mm-yyyy etc.
    for dm in re.finditer(r"(?<!\d)(\d{1,2})[-_/](\d{1,2})[-_/](\d{2,4})(?!\d)", s):
        y = dm.group(3)
        try:
            yi = int(y)
            if len(y) == 4 and yi != TARGET_YEAR_FULL:
                return False
            if len(y) == 2 and yi != TARGET_YEAR_SHORT:
                return False
        except Exception:
            pass
    # dates yyyymmdd
    m = re.search(r"(?<!\d)(20\d{2})\d{2}\d{2}(?!\d)", s)
    if m and int(m.group(1)) != TARGET_YEAR_FULL:
        return False
    # any other year token
    for ym in re.finditer(r"\b(20\d{2})\b", s):
        if int(ym.group(1)) != TARGET_YEAR_FULL:
            return False
    return True


def root_domain(u: str) -> str:
    try:
        host = urlparse(u).netloc.split(":")[0].lower()
        parts = host.split('.')
        if len(parts) >= 2:
            return '.'.join(parts[-2:])
        return host
    except Exception:
        return ''


def same_registrable_domain(a: str, b: str) -> bool:
    return bool(root_domain(a) and root_domain(a) == root_domain(b))


def registrable_origin(url: str) -> str | None:
    try:
        u = urlparse(url)
        rd = root_domain(url)
        if not (u.scheme and rd):
            return None
        return f"{u.scheme}://{rd}"
    except Exception:
        return None


def is_electionish(url_or_text: str) -> bool:
    try:
        s = (url_or_text or '').lower()
        if OVERVIEW_HINT_RE.search(s):
            return True
        # quick path checks
        if any(k in s for k in ('/verkiez', 'tweede-kamer', 'uitslag', 'proces', 'verbaal', 'stembureau', 'n10', 'na31')):
            return True
    except Exception:
        pass
    return False


def normalize_source_url(url: str) -> str:
    try:
        u = urlparse(url)
        host = (u.netloc or '').lower()
        path = (u.path or '')
        # MediaFiler: collapse /start/<collection>/<id> to /start/<collection>/
        if 'mediafiler' in host and '/start/' in path:
            parts = path.strip('/').split('/')
            try:
                i = parts.index('start')
            except ValueError:
                i = -1
            if i >= 0 and len(parts) >= i + 3:
                collapsed = '/' + '/'.join(parts[:i+2]) + '/'
                return f"{u.scheme}://{u.netloc}{collapsed}"
        return url.split('#', 1)[0]
    except Exception:
        return url
