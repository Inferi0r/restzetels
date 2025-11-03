#!/usr/bin/env python3
"""
Compact scraper om snel PDF's (processen-verbaal/uitslagen) per gemeente te vinden
en te downloaden.

Input: data/*.json
Output: pdfs/<GemeenteNaam>/*.pdf

Benodigd:
- data/municipalities.json (met items[] {name,url})
- data/municipality_links_verified.json (met verified[] {name,final_url/start_url,status})
- optioneel data/extra_seeds.json (per gemeente extra startpagina's)
"""
import os
import re
import sys
import json
from urllib.parse import urljoin, urlparse
import argparse
import zipfile
import tempfile

import requests
from bs4 import BeautifulSoup
try:
    from playwright.sync_api import sync_playwright  # required
    PLAYWRIGHT_AVAILABLE = True
except Exception as e:
    raise RuntimeError(
        "Playwright is required. Install it with:\n"
        "  pip install playwright && python -m playwright install chromium"
    ) from e


DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
if not os.path.isdir(DATA_DIR):
    # Fallback to legacy layout at repo root
    alt = os.path.join(os.getcwd(), "data")
    if os.path.isdir(alt):
        DATA_DIR = alt
OUT_BASE = os.path.join(os.getcwd(), "pdfs")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_extra_seeds(path: str = os.path.join(DATA_DIR, "extra_seeds.json")) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def http_get(url: str, timeout: float = 20.0, headers: dict | None = None) -> requests.Response:
    default_headers = {
        "User-Agent": "restzetels-cleaned/0.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    r = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


PDF_HINT_PATTERNS = [
    r"proces[-\s]?verbaal",
    r"processen[-\s]?verbaal",
    r"stembureau",
    r"model\s*N\s*10",
    r"model\s*Na\s*31",
    r"n10\b",
    r"na\s*31|na31",
    r"verkiezing",
    r"verkiezingen",
    r"uitslag",
]
PDF_HINT_RE = re.compile("|".join(PDF_HINT_PATTERNS), re.IGNORECASE)


# Only keep PDFs for the current election year (2025)
TARGET_YEAR_FULL = 2025
TARGET_YEAR_SHORT = 25

def _is_current_year_pdf(label: str) -> bool:
    if not isinstance(label, str):
        return True
    s = label.lower()
    # TKyy code
    m = re.search(r"\btk\s*([0-9]{2})\b", s, re.I)
    if m:
        yy = int(m.group(1))
        return yy == TARGET_YEAR_SHORT
    # Date-like patterns: DD[-_/]MM[-_/](YYYY|YY)
    for dm in re.finditer(r"\b(\d{1,2})[-_/](\d{1,2})[-_/](\d{2,4})\b", s):
        year = dm.group(3)
        try:
            y = int(year)
            if len(year) == 4:
                return y == TARGET_YEAR_FULL
            else:
                return y == TARGET_YEAR_SHORT
        except Exception:
            continue
    # If no explicit year found, keep
    return True


def extract_pdf_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: list[dict] = []
    maybes: list[tuple[str, str]] = []  # (url, text)
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        p = urlparse(full).path.lower()
        classes = " ".join(a.get("class", []))
        text_raw = a.get_text(" ", strip=True)
        text = (text_raw or "").lower()
        is_pdf_like = (
            (".pdf" in p)
            or ("type=pdf" in full.lower())
            or ("type-document-pdf" in classes)
            or (text.endswith("pdf"))
        )
        if is_pdf_like:
            # score and pdf_name similar to main scraper
            score = 1
            if PDF_HINT_RE.search(text_raw or "") or PDF_HINT_RE.search(full):
                score += 3
            try:
                orig_name = os.path.basename(urlparse(full).path)
            except Exception:
                orig_name = ""
            if (not orig_name or orig_name.lower() in {"dsresource", "download", "document", "file"}):
                if text_raw:
                    t = text_raw.strip()
                    if t.lower().endswith('.pdf'):
                        orig_name = t
                    elif any(k in t.lower() for k in ("stembureau", "n10", "na ")):
                        orig_name = f"{t}.pdf"
            if not _is_current_year_pdf(orig_name or text_raw or full):
                continue
            found.append({
                "remote_url": full,
                "local_url": None,
                "text": text_raw,
                "pdf_name": orig_name or os.path.basename(urlparse(full).path) or "document.pdf",
                "score": score,
                "from": base_url,
            })
        else:
            # Probe common CMS endpoints even if anchor text doesn't say PDF
            if any(k in full.lower() for k in ("dsresource", "download", "document", "/file/", "/fileadmin/", "/wp-content/")) or any(k in text for k in ("pdf", "proces", "stembureau", "uitslag")):
                maybes.append((full, text_raw or ""))

    # Light probe: check headers for suspected endpoints
    def probe_is_pdf(u: str) -> bool:
        try:
            r = requests.get(u, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=10, stream=True)
            ct = r.headers.get("Content-Type", "").lower()
            r.close()
            return "application/pdf" in ct
        except Exception:
            return False

    for u, txt in maybes[:12]:  # cap probes
        if probe_is_pdf(u):
            score = 1
            if PDF_HINT_RE.search(txt or "") or PDF_HINT_RE.search(u):
                score += 3
            try:
                orig_name = os.path.basename(urlparse(u).path)
            except Exception:
                orig_name = ""
            if not _is_current_year_pdf(orig_name or txt or u):
                continue
            found.append({
                "remote_url": u,
                "local_url": None,
                "text": txt,
                "pdf_name": orig_name or os.path.basename(urlparse(u).path) or "document.pdf",
                "score": score,
                "from": base_url,
            })

    # dedup by remote URL while preserving order
    seen = set(); out = []
    for p in found:
        u = p.get("remote_url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(p)
    return out


# -------- MediaFiler (generic) support --------

def find_mediafiler_albums_from_html(html: str, base_url: str) -> list[str]:
    """Return MediaFiler album links discovered in the page HTML.
    Generic pattern: domain contains 'mediafiler.net' and path '/start/'.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    albums: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        u = urlparse(full)
        if "mediafiler.net" in u.netloc and "/start/" in u.path:
            # Heuristic filter: relevant album pages often mention verkiez/proces/uitslag in link text
            txt = (a.get_text(" ", strip=True) or "").lower()
            if any(k in txt for k in ("proces", "uitslag", "verkiez")) or True:
                albums.append(full)
    # Dedup preserve order
    out = []
    seen = set()
    for u in albums:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def parse_mediafiler_album_for_items(album_url: str) -> list[dict]:
    """Parse a MediaFiler album page and extract fuid + filename items using HTML/JS patterns.
    Returns list of dicts: {fuid, filename, album_url}
    """
    try:
        r = http_get(album_url)
    except Exception:
        return []
    html = r.text
    items: list[dict] = []
    # Matches: downloadTab('3682', "0200_PV_...pdf") and single-quoted filenames
    for m in re.finditer(r"downloadTab\('(\d+)'\s*,\s*&quot;([^&]+?)&quot;\)", html):
        fn = m.group(2)
        # ensure .pdf suffix if missing (some items have bare stems)
        if not fn.lower().endswith('.pdf'):
            fn = fn + '.pdf'
        items.append({"fuid": m.group(1), "filename": fn, "album_url": r.url})
    for m in re.finditer(r"downloadTab\('(\d+)'\s*,\s*'([^']+?)'\)", html):
        fn = m.group(2)
        if not fn.lower().endswith('.pdf'):
            fn = fn + '.pdf'
        items.append({"fuid": m.group(1), "filename": fn, "album_url": r.url})
    # Dedup by fuid
    seen = set(); out = []
    for it in items:
        f = it.get("fuid")
        if f in seen:
            continue
        seen.add(f)
        out.append(it)
    return out


def download_mediafiler_album(muni: str, album_url: str, items_seed: list[dict]) -> int:
    """Download all PDFs from a MediaFiler album by invoking the site's downloadTab JS.
    Paginates via the 'Volgende' link (id=#anavnext) where available.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print(f"[mediafiler] Playwright not available; skip album {album_url}")
        return 0
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    # Do not pre-mark seed items as processed; we still need to download them.
    processed: set[str] = set()
    saved = 0
    rx1 = re.compile(r"downloadTab\('(\d+)'\s*,\s*&quot;([^&]+?\.pdf)&quot;\)")
    rx2 = re.compile(r"downloadTab\('(\d+)'\s*,\s*'([^']+?\.pdf)'\)")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(album_url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1200)
        while True:
            html = page.content()
            new_items: list[tuple[str, str]] = []
            for m in rx1.finditer(html):
                f, fn = m.group(1), m.group(2)
                if f not in processed:
                    new_items.append((f, fn))
            for m in rx2.finditer(html):
                f, fn = m.group(1), m.group(2)
                if f not in processed:
                    new_items.append((f, fn))
            for fuid, fname in new_items:
                try:
                    with page.expect_download(timeout=45000) as dl_info:
                        page.evaluate("(args) => downloadTab(args[0], args[1])", [fuid, fname])
                    dl = dl_info.value
                    final_name = dl.suggested_filename or fname
                    final_path = os.path.join(out_dir, sanitize_filename(final_name))
                    base, ext = os.path.splitext(final_path)
                    i = 1; use = final_path
                    while os.path.exists(use):
                        use = f"{base}_{i}{ext}"; i += 1
                    dl.save_as(use)
                    saved += 1
                    processed.add(fuid)
                    print(f"[mediafiler] Saved: {use}")
                except Exception as e:
                    print(f"[mediafiler] Download failed fuid={fuid}: {e}")
            # Paginate
            try:
                next_btn = page.locator('#anavnext')
                if next_btn.count() == 0:
                    break
                cls = next_btn.get_attribute('class') or ''
                # if present try click
                next_btn.click(timeout=5000)
                page.wait_for_timeout(800)
            except Exception:
                break
        context.close(); browser.close()
    return saved

def collect_mediafiler_album_items(album_url: str) -> list[dict]:
    """Use Playwright to paginate an album and collect all (fuid, filename) pairs without downloading.
    Returns list of dicts: {fuid, filename, album_url}
    """
    if not PLAYWRIGHT_AVAILABLE:
        return []
    items: list[dict] = []
    rx1 = re.compile(r"downloadTab\('(\d+)'\s*,\s*&quot;([^&]+?\.pdf)&quot;\)")
    rx2 = re.compile(r"downloadTab\('(\d+)'\s*,\s*'([^']+?\.pdf)'\)")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(album_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(1200)
            processed = set()
            while True:
                html = page.content()
                for m in rx1.finditer(html):
                    f, fn = m.group(1), m.group(2)
                    if f not in processed:
                        items.append({"fuid": f, "filename": fn, "album_url": page.url}); processed.add(f)
                for m in rx2.finditer(html):
                    f, fn = m.group(1), m.group(2)
                    if f not in processed:
                        items.append({"fuid": f, "filename": fn, "album_url": page.url}); processed.add(f)
                try:
                    next_btn = page.locator('#anavnext')
                    if next_btn.count() == 0:
                        break
                    next_btn.click(timeout=5000)
                    page.wait_for_timeout(800)
                except Exception:
                    break
            context.close(); browser.close()
    except Exception:
        return items
    return items

def collect_mediafiler_albums(name: str, extra: dict) -> list[str]:
    """Discover MediaFiler album links for a municipality by scanning start/seeds and discovered pages."""
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
    albums: list[str] = []
    discover_pages_scored: list[tuple[str,int]] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|n10|na\s*31|na31|mediafiler", re.I)
    for s in seeds[:5]:
        try:
            html, base = fetch_html(s, allow_render=False)
            if not html:
                continue
            albums += find_mediafiler_albums_from_html(html, base)
            soup = BeautifulSoup(html, 'html.parser')
            pu = urlparse(base)
            base0 = f"{pu.scheme}://{pu.netloc}"
            for a in soup.select('a[href]'):
                href = a.get('href'); full = urljoin(base0, href or '')
                if not full or urlparse(full).netloc != pu.netloc:
                    continue
                if KEY_RE.search(full) or KEY_RE.search(a.get_text(' ', strip=True) or ''):
                    discover_pages_scored.append((full, 1))
        except Exception:
            pass
    # traverse a bit deeper
    seenp = set(); dedup = []
    for u,_ in discover_pages_scored:
        if u in seenp: continue
        seenp.add(u); dedup.append(u)
    for p in dedup[:15]:
        try:
            html2, base2 = fetch_html(p, allow_render=False)
            if not html2:
                continue
            albums += find_mediafiler_albums_from_html(html2, base2)
        except Exception:
            pass
    # dedup albums
    out=[]; seen=set()
    for u in albums:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out


# -------- Stackstorage (generic) support --------

def find_stackstorage_shares_from_html(html: str, base_url: str) -> list[str]:
    """Return Stackstorage share links discovered in the page HTML.
    Pattern: domain contains 'stackstorage.com' and path starts with '/s/'.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    shares: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        u = urlparse(full)
        if "stackstorage.com" in u.netloc and "/s/" in u.path:
            shares.append(full.split("?", 1)[0])
    # Dedup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in shares:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def download_stackstorage_share(muni: str, share_url: str) -> list[dict]:
    """Download PDFs from a Stackstorage share.
    Strategy: try 'Download all' (zip), else click per-file download anchors.
    Returns list of index items with local_url and pdf_name.
    """
    items: list[dict] = []
    if not PLAYWRIGHT_AVAILABLE:
        print(f"[stackstorage] Playwright not available; skip share {share_url}")
        return items
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)

    def save_download(dl) -> list[str]:
        tmpfd, tmppath = tempfile.mkstemp()
        os.close(tmpfd)
        dl.save_as(tmppath)
        saved_paths: list[str] = []
        # If it's a zip, extract PDFs
        try:
            with zipfile.ZipFile(tmppath) as z:
                for name in z.namelist():
                    if not name.lower().endswith('.pdf'):
                        continue
                    base = os.path.basename(name)
                    dest = os.path.join(out_dir, base)
                    base0, ext = os.path.splitext(dest)
                    i = 1; use = dest
                    while os.path.exists(use):
                        use = f"{base0}_{i}{ext}"; i += 1
                    with z.open(name) as src, open(use, 'wb') as f:
                        f.write(src.read())
                    saved_paths.append(use)
        except zipfile.BadZipFile:
            # Direct file (likely a single PDF)
            suggested = dl.suggested_filename or 'download.pdf'
            base = os.path.join(out_dir, suggested)
            base0, ext = os.path.splitext(base)
            if not ext.lower() == '.pdf':
                base = base0 + '.pdf'
            use = base; i = 1
            while os.path.exists(use):
                use = f"{base0}_{i}{ext or '.pdf'}"; i += 1
            os.replace(tmppath, use)
            saved_paths.append(use)
        finally:
            try:
                if os.path.exists(tmppath):
                    os.remove(tmppath)
            except Exception:
                pass
        return saved_paths

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(share_url, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=60000)
        except Exception:
            pass
        # Try 'Download all'
        try:
            dl_links = page.locator('a:has-text("Download all")')
            if dl_links.count() > 0:
                with page.expect_download(timeout=60000) as dl_ctx:
                    dl_links.first.click()
                dl = dl_ctx.value
                for path in save_download(dl):
                    fname = os.path.basename(path)
                    if not _is_current_year_pdf(fname):
                        continue
                    items.append({
                        "remote_url": share_url,
                        "local_url": "file://" + os.path.abspath(path),
                        "pdf_name": fname,
                        "text": fname,
                        "from": share_url,
                        "score": 0,
                    })
        except Exception as e:
            print(f"[stackstorage] Download-all failed for {share_url}: {e}")
        # Fallback: per-file download anchors
        anchors = page.locator('a[download], a[data-action="download"], a:has-text("Download")')
        n = anchors.count()
        for i in range(n):
            try:
                with page.expect_download(timeout=45000) as dl_ctx:
                    anchors.nth(i).click()
                dl = dl_ctx.value
                for path in save_download(dl):
                    fname = os.path.basename(path)
                    if not _is_current_year_pdf(fname):
                        continue
                    items.append({
                        "remote_url": share_url,
                        "local_url": "file://" + os.path.abspath(path),
                        "pdf_name": fname,
                        "text": fname,
                        "from": share_url,
                        "score": 0,
                    })
            except Exception:
                pass
        context.close(); browser.close()
    if items:
        print(f"[stackstorage] {muni}: downloaded {len(items)} items from {share_url}")
    return items


def collect_stackstorage_shares(name: str, extra: dict) -> list[str]:
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
    shares: list[str] = []
    discover_pages: list[str] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|stackstorage", re.I)
    for s in seeds[:5]:
        try:
            html, base = fetch_html(s, allow_render=False)
            if not html:
                continue
            shares += find_stackstorage_shares_from_html(html, base)
            soup = BeautifulSoup(html, 'html.parser')
            pu = urlparse(base)
            base0 = f"{pu.scheme}://{pu.netloc}"
            for a in soup.select('a[href]'):
                href = a.get('href'); full = urljoin(base0, href or '')
                if not full or urlparse(full).netloc != pu.netloc:
                    continue
                if KEY_RE.search(full) or KEY_RE.search(a.get_text(' ', strip=True) or ''):
                    discover_pages.append(full)
        except Exception:
            pass
    # Traverse a bit deeper
    seenp = set(); dedup = []
    for u in discover_pages:
        if u in seenp: continue
        seenp.add(u); dedup.append(u)
    for p in dedup[:15]:
        try:
            html2, base2 = fetch_html(p, allow_render=False)
            if not html2:
                continue
            shares += find_stackstorage_shares_from_html(html2, base2)
        except Exception:
            pass
    # Dedup shares
    out: list[str] = []
    seen: set[str] = set()
    for u in shares:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out


def quick_site_search(start_url: str) -> list[str]:
    """Probeer 1-2 eenvoudige zoek-url varianten om extra pagina's te vinden.
    Retourneert een lijst pagina-URLs (geen PDFs) om daarna PDF-links uit te halen.
    """
    pu = urlparse(start_url)
    base = f"{pu.scheme}://{pu.netloc}"
    # Uitgebreide termen zodat o.a. 'voorlopige-verkiezingsuitslag' gevonden wordt
    terms = [
        "documenten verkiezing", "verkiezingsuitslag", "verkiezingen uitslag", "verkiez", "uitslag",
        "proces-verbaal", "processen-verbaal", "stembureau", "voorlopige", "N10-2", "Na 31-2", "bijlage 2"
    ]
    paths = ["zoeken", "search", "site/zoeken"]
    candidates = []
    for t in terms:
        for p in paths:
            candidates.append(f"{base}/{p}?q={requests.utils.quote(t)}")
    found_pages: list[str] = []
    for u in candidates:
        try:
            r = http_get(u, timeout=8)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href]"):
                href = a.get("href"); full = urljoin(r.url, href)
                # pak alleen interne contentpagina's, geen assets
                if urlparse(full).netloc == pu.netloc and full.startswith(base):
                    low = full.lower() + " " + (a.get_text(" ", strip=True) or "").lower()
                    if any(k in low for k in ("verkiez", "uitslag", "proces", "stembur", "n10", "na 31", "bijlage", "voorlopige")):
                        found_pages.append(full)
        except Exception:
            pass
    # dedup en cap
    out = []
    seen = set()
    for u in found_pages:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:8]


def discover_via_sitemap(start_url: str, max_pages: int = 30) -> list[str]:
    pu = urlparse(start_url)
    base = f"{pu.scheme}://{pu.netloc}"
    robots = f"{base}/robots.txt"
    sitemap_urls: list[str] = []
    try:
        r = http_get(robots, timeout=6)
        for line in r.text.splitlines():
            if line.lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc:
                    sitemap_urls.append(loc)
    except Exception:
        pass
    if not sitemap_urls:
        sitemap_urls = [f"{base}/sitemap.xml"]

    found_pages: list[str] = []
    KEY_RE = re.compile(r"verkiez|uitslag|tweede.*kamer|stembur|proces|result", re.I)

    def parse_sm(url: str, depth: int = 0):
        nonlocal found_pages
        if depth > 2 or len(found_pages) >= max_pages:
            return
        try:
            rr = http_get(url, timeout=8)
        except Exception:
            return
        # Try XML parser; fallback to html if unavailable
        try:
            soup = BeautifulSoup(rr.text, "xml")
        except Exception:
            soup = BeautifulSoup(rr.text, "html.parser")
        # nested indexes
        for loc in soup.select("sitemap > loc"):
            u = loc.get_text(strip=True)
            if u:
                parse_sm(u, depth + 1)
                if len(found_pages) >= max_pages:
                    return
        # urls
        for loc in soup.select("url > loc"):
            u = loc.get_text(strip=True)
            if not u:
                continue
            if urlparse(u).netloc != pu.netloc:
                continue
            if KEY_RE.search(u):
                found_pages.append(u)
            if len(found_pages) >= max_pages:
                return

    for sm in sitemap_urls[:3]:
        parse_sm(sm, 0)
        if len(found_pages) >= max_pages:
            break
    # dedup and cap
    out = []
    seen = set()
    for u in found_pages:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:max_pages]


def download_pdf(url: str, out_dir: str) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    try:
        r = requests.get(url, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=45)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").lower()
        if "application/pdf" not in ct and not urlparse(url).path.lower().endswith(".pdf"):
            return None
        # try filename from Content-Disposition
        cd = r.headers.get("Content-Disposition", "")
        fname = None
        if cd:
            m = re.search(r"filename\*=(?:UTF-8''|)[^;]*?([^;]+)", cd, re.I)
            if m:
                from urllib.parse import unquote
                try:
                    fname = unquote(m.group(1).strip().strip('"'))
                except Exception:
                    fname = m.group(1).strip().strip('"')
            else:
                m2 = re.search(r"filename=([^;]+)", cd, re.I)
                if m2:
                    fname = m2.group(1).strip().strip('"')
        if not fname:
            fname = os.path.basename(urlparse(url).path) or "document.pdf"
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        path = os.path.join(out_dir, sanitize_filename(fname))
        base, ext = os.path.splitext(path)
        i = 1; use = path
        while os.path.exists(use):
            use = f"{base}_{i}{ext}"; i += 1
        with open(use, "wb") as f:
            f.write(r.content)
        return use
    except Exception:
        return None


def get_first_n_names(n: int = 5) -> list[str]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    return [it.get("name") for it in items[:n] if it.get("name")]


def get_municipalities_slice(start: int, end: int) -> list[str]:
    """1-based inclusive slice of municipalities by order in municipalities.json."""
    if start < 1:
        start = 1
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    # convert to 0-based slice
    s = start - 1
    e = max(s, end)  # inclusive end in user input
    selected = items[s:e]
    return [it.get("name") for it in selected if it.get("name")]


def get_all_names() -> list[str]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    return [it.get("name") for it in items if it.get("name")]


def get_verified_url(name: str) -> str | None:
    data = load_json(os.path.join(DATA_DIR, "municipality_links_verified.json"))
    for v in data.get("verified", []):
        if v.get("name") == name and v.get("status") == 200:
            return v.get("final_url") or v.get("start_url")
    return None


def get_start_url(name: str) -> str | None:
    """Return best start URL: verified final if 200, else start_url from verified, else from municipalities.json."""
    # try verified (prefer 200)
    v = None
    try:
        data = load_json(os.path.join(DATA_DIR, "municipality_links_verified.json"))
        for it in data.get("verified", []):
            if it.get("name") == name:
                v = it; break
    except Exception:
        v = None
    if v:
        if v.get("status") == 200:
            return v.get("final_url") or v.get("start_url")
        if v.get("start_url"):
            return v.get("start_url")
    # fallback to municipalities.json
    try:
        data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
        for it in data.get("items", []):
            if it.get("name") == name and it.get("url"):
                return it.get("url")
    except Exception:
        pass
    return None


def render_page_content(url: str, timeout_ms: int = 30000) -> tuple[str, str]:
    """Render a page with Playwright to capture client-side content. Returns (html, final_url)."""
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not available")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # allow dynamic content to settle
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        html = page.content()
        final_url = page.url
        context.close(); browser.close()
        return html, final_url


def is_blocked_html(text: str) -> bool:
    if not text:
        return True
    t = text.lower()
    return ("er is iets mis gegaan" in t and "gemeente amsterdam" in t) or ("403" in t and "amsterdam" in t)


def fetch_html(url: str, allow_render: bool = False) -> tuple[str, str] | tuple[None, None]:
    """Try static GET; if blocked and allow_render, try Playwright."""
    try:
        r = http_get(url)
        if r.status_code == 200 and not is_blocked_html(r.text):
            return r.text, r.url
    except Exception:
        pass
    if allow_render and PLAYWRIGHT_AVAILABLE:
        try:
            html, final = render_page_content(url)
            return html, final
        except Exception:
            return None, None
    return None, None


def collect_pdfs_for_municipality(name: str, extra: dict, force_render: bool = False) -> list[dict]:
    urls: list[dict] = []
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        # geef verified start prioriteit
        seeds.insert(0, start)
    # fetch seeds and extract pdfs + discover a small set of relevant internal pages
    discover_pages_scored: list[tuple[str,int]] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|n10|na\s*31|na31|model", re.I)
    for s in seeds[:5]:  # cap seeds processed
        try:
            allow_render = ("amsterdam.nl" in s) or force_render
            html, base = fetch_html(s, allow_render=allow_render)
            if not html:
                continue
            urls += extract_pdf_links(html, base)
            # collect relevant internal pages for 1-hop expansion
            soup = BeautifulSoup(html, "html.parser")
            pu = urlparse(base)
            base = f"{pu.scheme}://{pu.netloc}"
            for a in soup.select("a[href]"):
                href = a.get("href"); full = urljoin(base, href or "")
                if not full or ".pdf" in urlparse(full).path.lower():
                    continue
                if urlparse(full).netloc != pu.netloc or not full.startswith(base):
                    continue
                if KEY_RE.search(full) or KEY_RE.search(a.get_text(" ", strip=True) or ""):
                    score = 0
                    low = (full + " " + (a.get_text(" ", strip=True) or "")).lower()
                    if "voorlopige" in low:
                        score += 6
                    if "documenten" in low or "document" in low:
                        score += 5
                    if "uitslag" in low:
                        score += 4
                    if "verkiez" in low:
                        score += 2
                    discover_pages_scored.append((full, score))
        except Exception:
            pass
    # process discovered pages by priority
    dedup = []
    seenp = set()
    for u, sc in sorted(discover_pages_scored, key=lambda x: x[1], reverse=True):
        if u in seenp:
            continue
        seenp.add(u)
        dedup.append(u)
    for p in dedup[:20]:
        try:
            allow_render = ("amsterdam.nl" in p) or force_render
            html2, base2 = fetch_html(p, allow_render=allow_render)
            if not html2:
                continue
            urls += extract_pdf_links(html2, base2)
        except Exception:
            pass
    # quick site search as a fallback if still nothing
    if not urls and start:
        for p in quick_site_search(start):
            try:
                allow_render = ("amsterdam.nl" in p) or force_render
                html3, base3 = fetch_html(p, allow_render=allow_render)
                if not html3:
                    continue
                urls += extract_pdf_links(html3, base3)
            except Exception:
                pass
    # sitemap discovery as ultimate fallback
    if not urls and start:
        for p in discover_via_sitemap(start):
            try:
                r4 = http_get(p, timeout=12)
                urls += extract_pdf_links(r4.text, r4.url)
            except Exception:
                pass
    # dedup by remote URL if present
    seen = set(); out = []
    for entry in urls:
        u = entry.get("remote_url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(entry)
    return out


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compacte PDF-scraper voor gemeenten")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen)")
    ap.add_argument("--slice", type=str, default=None, help="1-based inclusieve slice, bijv. 1-10 of 6-10")
    ap.add_argument("--first", type=int, default=None, help="Pak de eerste N gemeenten (fallback als --slice ontbreekt)")
    ap.add_argument("--merge-from-disk", action="store_true", help="Vul index aan door lokale PDF-bestanden te scannen (geen downloads)")
    ap.add_argument("--complete-remote", action="store_true", help="Probeer ontbrekende remote_url voor bestaande items aan te vullen (geen downloads)")
    args = ap.parse_args(argv)

    # Bepaal doellijst (initieel; kan nog aangepast worden als --complete-remote zonder selectie is opgegeven)
    if args.only:
        all_names = set(get_all_names())
        names = [n for n in args.only if n in all_names]
    elif args.slice:
        try:
            a, b = args.slice.split("-", 1)
            start = int(a.strip()); end = int(b.strip())
            names = get_municipalities_slice(start, end)
        except Exception:
            print("[cleaned] Ongeldige --slice, val terug op eerste 5")
            names = get_first_n_names(5)
    elif args.first:
        names = get_first_n_names(args.first)
    else:
        names = get_first_n_names(5)
    extra = load_extra_seeds()

    # Skip municipalities that require an API key or block scraping
    # Amsterdam processes-verbaal are exposed behind an API that requires an API key:
    # https://api.data.amsterdam.nl/v1/verkiezingen/processenverbaal
    skip_map = {"Amsterdam": "https://api.data.amsterdam.nl/v1/verkiezingen/processenverbaal"}
    for s in list(names):
        if s in skip_map:
            print(f"[cleaned] Skip {s}: API key required for processen-verbaal API ({skip_map[s]})")
            names.remove(s)

    print(f"[cleaned] Target: {', '.join(names)}")
    total_saved = 0
    # Load existing index to merge instead of overwrite
    idx_path = os.path.join(DATA_DIR, "municipality_pdfs_index.json")
    existing_results: list[dict] = []
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                existing_results = data.get("results", []) or []
            elif isinstance(data, list):
                existing_results = data
    except FileNotFoundError:
        existing_results = []
    except Exception:
        existing_results = []
    existing_map: dict[str, dict] = {e.get("name"): e for e in existing_results if e.get("name")}

    # Als --complete-remote is opgegeven zonder expliciete selectie, richt op gemeenten met missende remote_url
    if args.complete_remote and not (args.only or args.slice or args.first):
        miss = []
        for n,e in existing_map.items():
            if any((not (p.get('remote_url'))) for p in (e.get('pdfs') or [])):
                miss.append(n)
        if miss:
            names = miss
            print(f"[cleaned] Auto-selected for complete-remote: {len(names)} gemeenten met missende remote_url")

    index_results: list[dict] = []

    def _normalize(p: dict) -> dict:
        # Accept legacy entries with single 'url' and new entries with 'remote_url'/'local_url'
        legacy_url = p.get("url")
        remote_url = p.get("remote_url")
        local_url = p.get("local_url")
        if not remote_url and legacy_url and isinstance(legacy_url, str) and legacy_url.lower().startswith(("http://", "https://")):
            remote_url = legacy_url
        if not local_url and legacy_url and isinstance(legacy_url, str) and legacy_url.lower().startswith("file://"):
            local_url = legacy_url
        # Derive pdf name from whichever URL is present
        base_for_name = remote_url or local_url or ""
        try:
            base_name = os.path.basename(urlparse(base_for_name).path)
        except Exception:
            base_name = ""
        pdf_name = p.get("pdf_name") or base_name or "unknown.pdf"
        text = p.get("text") or pdf_name
        score = p.get("score") if isinstance(p.get("score"), (int, float)) else 0
        from_page = p.get("from") or ((remote_url or "").split('#',1)[0] if (remote_url and "mediafiler.net" in remote_url) else (remote_url or "unknown"))
        q = dict(p)
        # Clear legacy url field to avoid confusion
        q.pop("url", None)
        q.update({
            "remote_url": remote_url,
            "local_url": local_url,
            "pdf_name": pdf_name,
            "text": text,
            "score": score,
            "from": from_page,
        })
        return q

    def merge_entry(name: str, new_pdfs: list[dict]):
        start_url = get_start_url(name)
        norm_new = [_normalize(p) for p in (new_pdfs or [])]
        new_entry = {"name": name, "start_url": start_url, "pdfs": norm_new}
        old = existing_map.get(name)
        if old and isinstance(old.get("pdfs"), list):
            # Advanced merge: unify entries by multiple keys (pdf_name, URL basename, remote/local URLs)
            def keys_for(q: dict) -> list[str]:
                ks: list[str] = []
                nm = q.get("pdf_name")
                if nm:
                    ks.append("N:" + nm.lower())
                ru = q.get("remote_url")
                if ru:
                    ks.append("R:" + ru)
                    try:
                        b = os.path.basename(urlparse(ru).path).lower()
                        if b:
                            ks.append("B:" + b)
                    except Exception:
                        pass
                lu = q.get("local_url")
                if lu:
                    ks.append("L:" + lu)
                    try:
                        b2 = os.path.basename(urlparse(lu).path).lower()
                        if b2:
                            ks.append("B:" + b2)
                    except Exception:
                        pass
                return ks

            out_list: list[dict] = []
            key_to_idx: dict[str, int] = {}

            def add_or_merge(item: dict):
                ks = keys_for(item)
                # find any existing index sharing a key
                idx = None
                for k in ks:
                    if k in key_to_idx:
                        idx = key_to_idx[k]
                        break
                if idx is None:
                    out_list.append(dict(item))
                    idx = len(out_list) - 1
                else:
                    merged = dict(out_list[idx])
                    merged.update({k: v for k, v in item.items() if v is not None})
                    out_list[idx] = merged
                # record all keys for this (updated) item
                for k in ks:
                    key_to_idx[k] = idx

            # Seed with old then merge new (so new info augments old)
            for p in old.get("pdfs", []):
                add_or_merge(_normalize(p))
            for p in norm_new:
                add_or_merge(p)
            new_entry["pdfs"] = out_list
        existing_map[name] = new_entry
        index_results.append(new_entry)
        return new_entry

    def local_pdfs_for(name: str) -> list[dict]:
        res: list[dict] = []
        dirs = [
            os.path.join(os.getcwd(), sanitize_filename(name)),
            os.path.join(os.path.dirname(__file__), sanitize_filename(name)),  # scraper/<name>
            os.path.join(OUT_BASE, sanitize_filename(name)),
        ]
        seen_paths = set()
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for fn in files:
                    if not fn.lower().endswith('.pdf'):
                        continue
                    pth = os.path.join(root, fn)
                    if pth in seen_paths:
                        continue
                    seen_paths.add(pth)
                    # Skip non-current year locals
                    if not _is_current_year_pdf(fn):
                        continue
                    res.append({
                        "remote_url": None,
                        "local_url": "file://" + os.path.abspath(pth),
                        "text": os.path.splitext(fn)[0],
                        "pdf_name": fn,
                        "score": 1,
                        "from": "local",
                    })
        return res

    def complete_local_urls_for_entry(entry: dict):
        """Fill missing local_url values by scanning the municipality's local pdf directory and matching by pdf_name or URL basename."""
        name = entry.get("name") or ""
        if not name:
            return
        out_dir = os.path.join(OUT_BASE, sanitize_filename(name))
        if not os.path.isdir(out_dir):
            return
        files = {}
        for root, _, fs in os.walk(out_dir):
            for fn in fs:
                if not fn.lower().endswith('.pdf'):
                    continue
                files[fn] = "file://" + os.path.abspath(os.path.join(root, fn))
        for p in entry.get("pdfs", []):
            if p.get("local_url"):
                continue
            # Try direct match on pdf_name
            nm = p.get("pdf_name")
            if nm and nm in files:
                p["local_url"] = files[nm]
                continue
            # Try URL basename
            ru = p.get("remote_url")
            if ru:
                try:
                    base = os.path.basename(urlparse(ru).path)
                except Exception:
                    base = None
                if base and base in files:
                    p["local_url"] = files[base]
                    continue

    def complete_remote_urls_best_effort(entry: dict):
        """Best-effort: fill missing remote_url using known 'from' page, legacy 'url',
        other remote URLs in the same municipality (to infer a base), or the municipality start_url.
        This does not guarantee a direct PDF link; it may point to the page or album containing it.
        """
        name = entry.get("name") or ""
        start = entry.get("start_url") or get_start_url(name) or ""
        # Collect a base from other remote URLs
        remote_samples = []
        for q in entry.get("pdfs", []) or []:
            ru = q.get("remote_url") or (q.get("url") if isinstance(q.get("url"), str) and q.get("url").startswith("http") else None)
            if ru:
                remote_samples.append(ru)
        base_origin = None
        if remote_samples:
            try:
                # Choose the most common origin
                from collections import Counter
                origins = [f"{urlparse(u).scheme}://{urlparse(u).netloc}" for u in remote_samples]
                base_origin = Counter(origins).most_common(1)[0][0]
            except Exception:
                base_origin = None
        if not base_origin and start:
            try:
                u = urlparse(start)
                base_origin = f"{u.scheme}://{u.netloc}"
            except Exception:
                base_origin = None
        for p in entry.get("pdfs", []) or []:
            if p.get("remote_url"):
                continue
            # Legacy url
            leg = p.get("url")
            if isinstance(leg, str) and leg.lower().startswith(("http://", "https://")):
                p["remote_url"] = leg
                p.pop("url", None)
                continue
            frm = p.get("from") or ""
            if isinstance(frm, str) and frm.lower().startswith(("http://", "https://")):
                # Use source page as approximate location (e.g., album or content page)
                p["remote_url"] = frm
                continue
            # Fall back to inferred base + filename
            nm = p.get("pdf_name")
            if base_origin and nm:
                try:
                    # Do not assume path; put at root as best-effort
                    from urllib.parse import quote
                    approx = base_origin.rstrip('/') + '/' + quote(nm)
                    p["remote_url"] = approx
                    continue
                except Exception:
                    pass
            # Last resort: use start_url itself
            if start:
                p["remote_url"] = start

    if args.merge_from_disk:
        # If --only not provided, consider all municipalities
        if not names:
            names = get_all_names()
        for n in names:
            e = merge_entry(n, local_pdfs_for(n))
            complete_local_urls_for_entry(e)
            complete_remote_urls_best_effort(e)
    elif args.complete_remote:
        # Alleen remote links ontdekken en mergen, zonder downloads
        if not names:
            names = list(existing_map.keys()) or get_all_names()
        for n in names:
            pdfs = collect_pdfs_for_municipality(n, extra, force_render=True)
            # MediaFiler albums ook meenemen, maar niet downloaden
            albums = collect_mediafiler_albums(n, extra)
            mediafiler_items: list[dict] = []
            for alb in albums:
                items = collect_mediafiler_album_items(alb) or parse_mediafiler_album_for_items(alb)
                for it in (items or []):
                    mediafiler_items.append({
                        "remote_url": f"{it.get('album_url')}#fuid={it.get('fuid')}",
                        "local_url": None,
                        "pdf_name": it.get('filename'),
                        "text": "MediaFiler",
                        "preview_text": it.get('filename'),
                        "from": it.get('album_url') or "unknown",
                        "score": 0,
                    })
            if mediafiler_items:
                pdfs = pdfs + mediafiler_items
            e = merge_entry(n, pdfs)
            complete_local_urls_for_entry(e)
            complete_remote_urls_best_effort(e)
    else:
        for n in names:
            out_dir = os.path.join(OUT_BASE, sanitize_filename(n))
            pdfs = collect_pdfs_for_municipality(n, extra)
            # MediaFiler albums discovery + downloads
            albums = collect_mediafiler_albums(n, extra)
            mediafiler_items: list[dict] = []
            for alb in albums:
                items = parse_mediafiler_album_for_items(alb)
                if items:
                    # Add items to index with album reference; download via Playwright
                    for it in items:
                        if not _is_current_year_pdf(it.get('filename') or ''):
                            continue
                        mediafiler_items.append({
                            "remote_url": f"{it.get('album_url')}#fuid={it.get('fuid')}",
                            "local_url": None,
                            "pdf_name": it.get('filename'),
                            "text": it.get('filename'),
                            "from": it.get('album_url') or "unknown",
                            "score": 0,
                        })
                    downloaded = download_mediafiler_album(n, alb, items)
                    total_saved += downloaded
            if mediafiler_items:
                pdfs = pdfs + mediafiler_items
            # Stackstorage shares discovery + downloads
            shares = collect_stackstorage_shares(n, extra)
            stack_items: list[dict] = []
            for sh in shares:
                try:
                    itms = download_stackstorage_share(n, sh)
                    if itms:
                        stack_items.extend(itms)
                except Exception as e:
                    print(f"[stackstorage] {n}: error downloading share {sh}: {e}")
            if stack_items:
                pdfs = pdfs + stack_items
            print(f"[cleaned] {n}: {len(pdfs)} pdf links (+{len(mediafiler_items)} mediafiler)")
            saved = 0
            for p in pdfs:
                u = p.get("remote_url")
                if not u:
                    continue
                if "mediafiler.net" in u and "#fuid=" in u:
                    continue
                if "stackstorage.com" in u:
                    # handled via Playwright already
                    continue
                dest = download_pdf(u, out_dir)
                if dest:
                    p["local_url"] = "file://" + os.path.abspath(dest)
                    saved += 1
            total_saved += saved
            print(f"[cleaned] {n}: saved {saved} PDFs (HTTP) -> {out_dir}")
            e = merge_entry(n, pdfs)
            complete_local_urls_for_entry(e)
            complete_remote_urls_best_effort(e)
    # Merge unprocessed municipalities back in
    for n, e in list(existing_map.items()):
        if not any(r.get("name") == n for r in index_results):
            # Normalize legacy entries and try to fill local URLs from disk
            try:
                pdfs_norm = [_normalize(p) for p in e.get("pdfs", [])]
            except Exception:
                pdfs_norm = []
            new_e = {"name": e.get("name"), "start_url": get_start_url(n), "pdfs": pdfs_norm}
            complete_local_urls_for_entry(new_e)
            complete_remote_urls_best_effort(new_e)
            index_results.append(new_e)
    # Write merged index file
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump({"results": index_results, "count": len(index_results)}, f, ensure_ascii=False, indent=2)
        print(f"[cleaned] PDF index merged -> {idx_path}")
    except Exception as e:
        print(f"[cleaned] Warning: could not save pdf index: {e}")
    print(f"[cleaned] Done. Total saved: {total_saved}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
