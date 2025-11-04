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
from urllib.parse import parse_qs, unquote
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

    # Explicitly skip non-TK election types regardless of year
    if "waterschap" in s:
        return False
    if "gemeenteraad" in s or "gemeenteraads" in s:
        return False
    if "provinciale" in s:
        return False
    if "europees" in s or "europees parlement" in s:
        return False

    # Explicit bans by compact election codes regardless of year, e.g. ep24, ep2024, ps23, ws25, gr22
    if re.search(r"(?<![A-Za-z])ep\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![A-Za-z])ps\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![A-Za-z])ws\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![A-Za-z])gr\s*[-_]?\s*(?:20)?\d{2}", s):
        return False

    # Reject other elections by explicit codes/words + year (including glued forms without separators)
    # EP (Europees Parlement)
    if re.search(r"(ep|europees|europees\s+parlement)\s*[-_]?\s*20(\d{2})", s):
        y = int(re.search(r"(ep|europees|europees\s+parlement)\s*[-_]?\s*20(\d{2})", s).group(2))
        return (2000 + y) == TARGET_YEAR_FULL
    # PS (Provinciale Staten)
    if re.search(r"ps\s*[-_]?\s*20(\d{2})", s):
        return False
    # WS (Waterschapsverkiezingen) — always banned
    if re.search(r"ws\s*[-_]?\s*20(\d{2})", s):
        return False
    # GR (Gemeenteraad) — banned regardless of year
    if re.search(r"gr\s*[-_]?\s*20(\d{2})(?!\d)", s):
        return False

    # TKYYYY code (e.g., tk2025)
    m = re.search(r"tk\s*[-_]?\s*20(\d{2})", s, re.I)
    if m:
        yy = int(m.group(1))
        return (2000 + yy) == TARGET_YEAR_FULL
    # TKyy code (e.g., tk25)
    m = re.search(r"tk\s*[-_]?\s*([0-9]{2})", s, re.I)
    if m:
        yy = int(m.group(1))
        return yy == TARGET_YEAR_SHORT

    # "tweede kamer YYYY" — accept only 2025
    m = re.search(r"\btweede\s+kamer\s+20(\d{2})\b", s)
    if m:
        y = int(m.group(1))
        return (2000 + y) == TARGET_YEAR_FULL

    # Date-like patterns: DD[-_/]MM[-_/](YYYY|YY)
    for dm in re.finditer(r"(?<!\d)(\d{1,2})[-_/](\d{1,2})[-_/](\d{2,4})(?!\d)", s):
        year = dm.group(3)
        try:
            y = int(year)
            if len(year) == 4:
                if y != TARGET_YEAR_FULL:
                    return False
            else:
                if y != TARGET_YEAR_SHORT:
                    return False
        except Exception:
            continue

    # Date-like patterns: YYYY[-_/]MM[-_/]DD or YY[-_/]MM[-_/]DD
    for dm in re.finditer(r"(?<!\d)(\d{2,4})[-_/](\d{1,2})[-_/](\d{1,2})(?!\d)", s):
        year = dm.group(1)
        try:
            y = int(year)
            if len(year) == 4:
                if y != TARGET_YEAR_FULL:
                    return False
            else:
                if y != TARGET_YEAR_SHORT:
                    return False
        except Exception:
            continue

    # Date-like patterns without separators: YYYYMMDD
    for dm in re.finditer(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", s):
        year = dm.group(1)
        try:
            y = int(year)
            if y != TARGET_YEAR_FULL:
                return False
        except Exception:
            continue

    # General year tokens: any 4-digit year in 2000..2099 not equal to 2025 implies reject
    for ym in re.finditer(r"\b(20\d{2})\b", s):
        y = int(ym.group(1))
        if y != TARGET_YEAR_FULL:
            return False

    # If no explicit contrary year found, keep
    return True


def _is_relevant_nav_target(label: str) -> bool:
    """Return True if a navigation link (URL/text) is relevant for TK25 before visiting it.
    - Skip Gemeenteraad/Europees/Provinciale/Waterschap pages
    - Skip pages that explicitly mention a non-2025 year
    - Allow general pages that do not conflict, prefer those mentioning TK/stembureau/uitslag/proces/verbaal
    """
    if not isinstance(label, str) or not label:
        return True
    s = label.lower()
    # Hard bans by other election types
    if any(k in s for k in ("gemeenteraad", "gemeenteraads", "europees parlement", "europees", "provinciale", "waterschap", "waterschappen")):
        # Allow back in only if explicitly mentions Tweede Kamer and not an explicit non-2025 year
        if ("tweede" in s and "kamer" in s) and not re.search(r"\b20(?!25)\d{2}\b", s):
            pass
        else:
            return False
    # Skip if explicit TK year not 2025
    m = re.search(r"\btweede\s+kamer\s+20(\d{2})\b", s)
    if m and (2000 + int(m.group(1))) != TARGET_YEAR_FULL:
        return False
    # Skip if any 2000..2099 year not equal to 2025
    for ym in re.finditer(r"\b(20\d{2})\b", s):
        if int(ym.group(1)) != TARGET_YEAR_FULL:
            return False
    # Also skip contiguous YYYYMMDD with year != 2025
    m2 = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", s)
    if m2 and int(m2.group(1)) != TARGET_YEAR_FULL:
        return False
    # Skip EP/PS/WS short codes (e.g., ep24, ps23, ws25)
    if re.search(r"(?<![A-Za-z])(ep|ps|ws|gr)\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    # Skip EP/PS/WS/GR with 4-digit years (redundant due to previous, kept for clarity)
    if re.search(r"(?<![A-Za-z])(ep|ps|ws|gr)\s*[-_]?\s*20\d{2}", s):
        return False
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
        # Detect docReader wrappers that point to an underlying PDF via ?url=
        is_docreader = ("docreader.readspeaker.com" in full.lower()) and ("url=" in full.lower())
        target_pdf_url = None
        if is_docreader:
            try:
                q = parse_qs(urlparse(full).query)
                url_param = q.get("url") or q.get("doc")
                if url_param and url_param[0]:
                    target_pdf_url = unquote(url_param[0])
            except Exception:
                target_pdf_url = None
        is_pdf_like = (
            (".pdf" in p)
            or ("type=pdf" in full.lower())
            or ("type-document-pdf" in classes)
            or (text.endswith("pdf"))
            or (is_docreader and target_pdf_url and target_pdf_url.lower().endswith('.pdf'))
        )
        is_zip_like = (".zip" in p) and any(k in (text + " " + full).lower() for k in (
            "n10", "na 31", "proces", "verbaal", "verkiez", "verslag", "stembureau"))
        if is_pdf_like:
            # score and pdf_name similar to main scraper
            score = 1
            if PDF_HINT_RE.search(text_raw or "") or PDF_HINT_RE.search(full):
                score += 3
            try:
                use_url = target_pdf_url or full
                orig_name = os.path.basename(urlparse(use_url).path)
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
                "remote_url": target_pdf_url or full,
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
            # Also record relevant ZIP archives that likely contain PV PDFs
            if is_zip_like and _is_current_year_pdf(text_raw or full):
                found.append({
                    "remote_url": full,
                    "local_url": None,
                    "text": text_raw,
                    "pdf_name": os.path.basename(urlparse(full).path) or "archive.zip",
                    "score": 2,
                    "from": base_url,
                })

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


# -------- Generic "file hub" discovery + download (external portals) --------

GENERIC_FILEHUB_KEY_RE = re.compile(
    r"verkiez|uitslag|proces|stembur|tweede.*kamer|pv\b|gsb\b|document|documenten|files|bestand|bestanden|download",
    re.I,
)


def find_generic_filehub_links_from_html(html: str, base_url: str, allow_external: bool) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    hubs: list[str] = []
    try:
        pu = urlparse(base_url)
        base_origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        pu = None
        base_origin = None
    for a in soup.select("a[href]"):
        href = a.get("href"); full = urljoin(base_url, href or "")
        if not full:
            continue
        # Limit scope unless external crawling allowed
        if not allow_external and pu and urlparse(full).netloc != pu.netloc:
            continue
        low = (full + " " + (a.get_text(" ", strip=True) or "")).lower()
        # Heuristics: likely 'file hubs' or folders
        if any(k in low for k in ("/files/", "/file/", "/document", "/documenten", "documenten", "bestanden", "download")):
            if GENERIC_FILEHUB_KEY_RE.search(low):
                hubs.append(full)
                continue
        # Generic 'Documenten' sections
        if ("documenten" in low or "bestanden" in low) and GENERIC_FILEHUB_KEY_RE.search(low):
            hubs.append(full)
    # Dedup preserve order
    seen = set(); out = []
    for u in hubs:
        if u in seen:
            continue
        seen.add(u); out.append(u)
    return out[:10]


def download_generic_filehub(muni: str, hub_url: str, max_click_folders: int = 3, max_downloads: int = 200) -> list[dict]:
    """Generic downloader for dynamic file-list pages using Playwright.
    Navigates to hub_url, optionally clicks into a few folder-like anchors, collects file-view or direct PDF anchors,
    and triggers downloads via visible 'Download' controls.
    """
    items: list[dict] = []
    if not PLAYWRIGHT_AVAILABLE:
        return items
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)

    def save_if_new(dl) -> str | None:
        try:
            suggested = dl.suggested_filename or "download.pdf"
            if not suggested.lower().endswith(".pdf"):
                suggested += ".pdf"
            if not _is_current_year_pdf(suggested):
                return None
            dest = os.path.join(out_dir, sanitize_filename(suggested))
            if os.path.exists(dest):
                return None
            dl.save_as(dest)
            return dest
        except Exception:
            return None

    visited: set[str] = set()
    downloaded = 0
    KEY_FOLDER_RE = re.compile(r"proces|stembur|document|documenten|files|map|folder|verkiez|uitslag|pv|gsb", re.I)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(hub_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            # Click into 1-3 obvious folder-like anchors by text
            try:
                candidates = [
                    'a:has-text("proces")',
                    'a:has-text("verbaal")',
                    'a:has-text("stembur")',
                    'a:has-text("document")',
                    'a:has-text("documenten")',
                    'a:has-text("bestanden")',
                    'a:has-text("files")',
                ]
                clicked = 0
                for sel in candidates:
                    if clicked >= max_click_folders:
                        break
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        try:
                            with page.expect_navigation(timeout=15000):
                                loc.first.click()
                            try:
                                page.wait_for_load_state('networkidle', timeout=10000)
                            except Exception:
                                pass
                            page.wait_for_timeout(1500)
                            clicked += 1
                        except Exception:
                            pass
            except Exception:
                pass

            # From the current page, attempt to harvest both direct PDFs and file view pages
            def try_downloads_from_current() -> None:
                nonlocal downloaded
                if downloaded >= max_downloads:
                    return
                anchors = page.query_selector_all('a[href]')
                for el in anchors[:300]:
                    if downloaded >= max_downloads:
                        break
                    try:
                        href = el.get_attribute('href') or ''
                    except Exception:
                        continue
                    try:
                        txt = (el.inner_text() or "").strip()
                    except Exception:
                        txt = ''
                    full = urljoin(page.url, href)
                    low = (href + " " + txt).lower()
                    if not href:
                        continue
                    # Likely file view pages — try to open and click Download first
                    if '/files/view/' in href or '/document/view/' in href or ('/view/' in href and GENERIC_FILEHUB_KEY_RE.search(low)):
                        view = urljoin(page.url, href)
                        if view in visited:
                            continue
                        visited.add(view)
                        view_page = None
                        try:
                            # open in same tab; some portals auto-trigger a download on page load
                            try:
                                with page.expect_download(timeout=20000) as dlctx:
                                    page.goto(view, wait_until='domcontentloaded', timeout=20000)
                                dl = dlctx.value
                                saved = save_if_new(dl)
                                if saved:
                                    items.append({
                                        "remote_url": view,
                                        "local_url": "file://" + os.path.abspath(saved),
                                        "pdf_name": os.path.basename(saved),
                                        "text": os.path.basename(saved),
                                        "from": hub_url,
                                        "score": 2,
                                    })
                                    downloaded += 1
                                    continue
                            except Exception:
                                # Fallback: look for explicit download controls
                                page.goto(view, wait_until='domcontentloaded', timeout=20000)
                                view_page = page
                                try:
                                    view_page.wait_for_load_state('networkidle', timeout=10000)
                                except Exception:
                                    pass
                                dl_btns = view_page.locator('a[download], a:has-text("Download"), button:has-text("Download"), a[href*="/download"]')
                                if dl_btns.count() > 0:
                                    try:
                                        with view_page.expect_download(timeout=30000) as dlctx:
                                            dl_btns.first.click()
                                        dl = dlctx.value
                                        saved = save_if_new(dl)
                                        if saved:
                                            items.append({
                                                "remote_url": view,
                                                "local_url": "file://" + os.path.abspath(saved),
                                                "pdf_name": os.path.basename(saved),
                                                "text": os.path.basename(saved),
                                                "from": hub_url,
                                                "score": 2,
                                            })
                                            downloaded += 1
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        finally:
                            # navigate back to hub listing to continue
                            try:
                                page.goto(hub_url, wait_until='domcontentloaded', timeout=15000)
                            except Exception:
                                pass
                        continue
                    # Direct PDF links
                    if href.lower().endswith('.pdf') or '.pdf' in urlparse(full).path.lower():
                        # Shortcut: perform HTTP download using existing helper
                        dest = download_pdf(full, out_dir)
                        if dest:
                            items.append({
                                "remote_url": full,
                                "local_url": "file://" + os.path.abspath(dest),
                                "pdf_name": os.path.basename(dest),
                                "text": txt or os.path.basename(dest),
                                "from": page.url,
                                "score": 2,
                            })
                            downloaded += 1
                        continue

            try_downloads_from_current()
        finally:
            context.close(); browser.close()
    if items:
        print(f"[generic] {muni}: downloaded {len(items)} PDFs from hub {hub_url}")
    return items


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
            txt = (a.get_text(" ", strip=True) or "")
            if _is_relevant_nav_target((txt + " " + full).lower()):
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
                if f not in processed and _is_current_year_pdf(fn):
                    new_items.append((f, fn))
            for m in rx2.finditer(html):
                f, fn = m.group(1), m.group(2)
                if f not in processed and _is_current_year_pdf(fn):
                    new_items.append((f, fn))
            for fuid, fname in new_items:
                try:
                    # Skip if file already exists to avoid duplicates
                    expected = os.path.join(out_dir, sanitize_filename(fname))
                    if os.path.exists(expected):
                        processed.add(fuid)
                        print(f"[mediafiler] Skip exists: {expected}")
                        continue
                    with page.expect_download(timeout=45000) as dl_info:
                        page.evaluate("(args) => downloadTab(args[0], args[1])", [fuid, fname])
                    dl = dl_info.value
                    final_name = dl.suggested_filename or fname
                    final_path = os.path.join(out_dir, sanitize_filename(final_name))
                    if os.path.exists(final_path):
                        processed.add(fuid)
                        print(f"[mediafiler] Skip exists: {final_path}")
                        continue
                    dl.save_as(final_path)
                    saved += 1
                    processed.add(fuid)
                    print(f"[mediafiler] Saved: {final_path}")
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
            dyn = ("amsterdam.nl" in s) or ("gemeente.emmen.nl" in s) or ("ermelo.nl" in s)
            html, base = fetch_html(s, allow_render=dyn)
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
                txt = a.get_text(' ', strip=True) or ''
                if (KEY_RE.search(full) or KEY_RE.search(txt)) and _is_relevant_nav_target((full + ' ' + txt).lower()):
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
            dyn = ("amsterdam.nl" in p) or ("gemeente.emmen.nl" in p) or ("ermelo.nl" in p)
            html2, base2 = fetch_html(p, allow_render=dyn)
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
            txt = a.get_text(" ", strip=True) or ""
            low = (full + " " + txt).lower()
            if _is_relevant_nav_target(low):
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


# -------- MijnStembureau portals (generic) --------

def _is_mijnstembureau_link(full_url: str, text: str | None = None) -> bool:
    try:
        u = urlparse(full_url)
        if "mijnstembureau" in (u.netloc or "") and "/uitslagen/verkiezingen/tk/" in (u.path or ""):
            return True
    except Exception:
        pass
    return False


def collect_mijnstembureau_pages(name: str, extra: dict) -> list[str]:
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
    pages: list[str] = []
    for s in seeds[:5]:
        try:
            html, base = fetch_html(s, allow_render=False)
            if not html:
                continue
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.select('a[href]'):
                href = a.get('href') or ''
                full = urljoin(base, href)
                if _is_mijnstembureau_link(full, a.get_text(' ', strip=True) or ''):
                    if _is_relevant_nav_target((full + ' ' + (a.get_text(' ', strip=True) or '')).lower()):
                        pages.append(full)
        except Exception:
            pass
    # Fallback: try quick site search and sitemap if nothing found yet
    if not pages and start:
        try:
            for u in quick_site_search(start):
                if _is_mijnstembureau_link(u):
                    if _is_relevant_nav_target(u):
                        pages.append(u)
        except Exception:
            pass
        try:
            for u in discover_via_sitemap(start):
                if _is_mijnstembureau_link(u):
                    if _is_relevant_nav_target(u):
                        pages.append(u)
        except Exception:
            pass
    # Dedup preserve order
    seen = set(); out = []
    for u in pages:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def download_mijnstembureau_portal(muni: str, page_url: str, max_items: int = 200) -> list[dict]:
    """Download PVs from a mijnstembureau portal page by clicking the PV buttons and capturing the PDF response.
    Saves files using the visible button text as filename.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return []
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    items: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(page_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            # If there is an OPEN toggle for the election, try clicking it
            try:
                open_btn = page.locator('button:has-text("OPEN")')
                if open_btn.count() > 0:
                    open_btn.first.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass
            # Go to Processen Verbaal section
            try:
                pv_tab = page.locator('button:has-text("Processen verbaal")')
                if pv_tab.count() > 0:
                    pv_tab.first.click()
                    page.wait_for_timeout(700)
            except Exception:
                pass
            # Collect buttons under main that look like PV filenames (end with .pdf)
            btns = page.locator('main button')
            count = btns.count()
            processed = 0
            for i in range(count):
                if processed >= max_items:
                    break
                try:
                    label = (btns.nth(i).inner_text() or '').strip()
                except Exception:
                    continue
                if not label or not label.lower().endswith('.pdf'):
                    continue
                # Filter and duplicate check before clicking
                if not _is_current_year_pdf(label):
                    continue
                dest = os.path.join(out_dir, sanitize_filename(label))
                if os.path.exists(dest):
                    continue
                # Expect the specific PDF API response when clicking
                def is_pdf_resp(resp) -> bool:
                    try:
                        return ('/uitslagen/api/view-pv/' in resp.url) and (resp.status == 200) and ('application/pdf' in (resp.headers or {}).get('content-type', '').lower())
                    except Exception:
                        return False
                try:
                    with page.expect_response(is_pdf_resp, timeout=60000) as resp_ctx:
                        btns.nth(i).click()
                    resp = resp_ctx.value
                    data = resp.body()
                    if data:
                        with open(dest, 'wb') as f:
                            f.write(data)
                        items.append({
                            'remote_url': resp.url,
                            'local_url': 'file://' + os.path.abspath(dest),
                            'pdf_name': os.path.basename(dest),
                            'text': label,
                            'from': page_url,
                            'score': 3,
                        })
                        processed += 1
                except Exception:
                    # ignore and continue on timeouts or non-PDF responses
                    continue
        finally:
            context.close(); browser.close()
    if items:
        print(f"[mijnstembureau] {muni}: downloaded {len(items)} PVs from {page_url}")
    return items

# -------- MijnStembureau (PV portal) support --------

def find_mijnstembureau_links_from_html(html: str, base_url: str) -> list[str]:
    """Return MijnStembureau portal links discovered in the page HTML.
    We look for hosts containing 'mijnstembureau' and a path with '/uitslagen/verkiezingen'.
    If a link points to the portal root, we normalize to the 'download-opties' page.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    links: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        u = urlparse(full)
        host = (u.netloc or "").lower()
        path = (u.path or "")
        if "mijnstembureau" in host and "/uitslagen" in path:
            # prefer explicit download options subpage
            if not path.rstrip("/").endswith("download-opties"):
                full = urljoin(full.rstrip("/") + "/", "download-opties")
            links.append(full)
    # Dedup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in links:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# -------- PV Overview (dynamic selects) support --------

def find_pv_overview_links_from_html(html: str, base_url: str) -> list[str]:
    """Return links that likely point to PV overview pages, e.g., 'overzicht-proces-verbalen' pages.
    Also, when the current page text looks like an overview (mentions Kies stembureau, proces-verba(a)l, overzicht),
    include the base_url itself as a candidate.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    links: list[str] = []
    # anchor-based discovery
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        path = (urlparse(full).path or "").lower()
        txt = (a.get_text(" ", strip=True) or "").lower()
        if any(k in path for k in ("overzicht-proces", "processen-verbaal", "proces-verbalen")) or any(k in txt for k in ("proces-verbaal", "overzicht", "stembureau")):
            links.append(full)
    # page-level detection: if content itself indicates overview, include the page
    page_text = soup.get_text(" ", strip=True).lower() if soup else ""
    if any(k in page_text for k in ("kies stembureau", "kies stadsdeel", "overzicht proces", "proces-verbaal", "processen-verbaal")):
        links.insert(0, base_url)
    # Dedup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in links:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def collect_pv_overview_pages(name: str, extra: dict) -> list[str]:
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
        # also probe common paths used by municipalities
        try:
            for u in probe_well_known_pages(start)[:8]:
                if u not in seeds:
                    seeds.append(u)
        except Exception:
            pass
    portals: list[str] = []
    discover_pages: list[str] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|verbaal|stembur|tweede.*kamer|overzicht|stadsdeel|kies", re.I)
    for s in seeds[:6]:
        try:
            html, base = fetch_html(s, allow_render=("amsterdam.nl" in s))
            if not html:
                continue
            portals += find_pv_overview_links_from_html(html, base)
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
            html2, base2 = fetch_html(p, allow_render=("amsterdam.nl" in p))
            if not html2:
                continue
            portals += find_pv_overview_links_from_html(html2, base2)
        except Exception:
            pass
    # Sitemap fallback
    if start and not portals:
        try:
            for p in discover_via_sitemap(start, max_pages=50):
                try:
                    html4, base4 = fetch_html(p, allow_render=("amsterdam.nl" in p))
                    if not html4:
                        continue
                    portals += find_pv_overview_links_from_html(html4, base4)
                except Exception:
                    continue
        except Exception:
            pass
    # Dedup portals
    out=[]; seen=set()
    for u in portals:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out


def download_pv_overview_page(muni: str, portal_url: str) -> list[dict]:
    """Download PV PDFs from an overview page that renders selects and direct links.
    Uses Playwright if available. Returns list of index items.
    """
    items: list[dict] = []
    if not PLAYWRIGHT_AVAILABLE:
        return items
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    saved = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(locale='nl-NL', user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
            page = ctx.new_page()
            page.goto(portal_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            # Gather PDF URLs from options and anchors, and remember anchor labels
            pdf_urls: set[str] = set()
            labels_for_url: dict[str, str] = {}
            try:
                vals = page.eval_on_selector('body', 'b => Array.from(b.querySelectorAll("option")).map(o=>o.value)') or []
                for v in vals:
                    if isinstance(v, str) and v.lower().endswith('.pdf'):
                        # normalize to drop cache busting/query strings when we later look up labels
                        vv = v.split('?')[0]
                        pdf_urls.add(vv)
            except Exception:
                pass
            try:
                anchors = page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: e.innerText}))') or []
                for a in anchors:
                    href = a.get('href') or ''
                    txt = (a.get('text') or '').strip()
                    try:
                        u = urljoin(portal_url, href)
                    except Exception:
                        u = href
                    if not u:
                        continue
                    u_norm = u.split('?')[0]
                    txt_low = (txt or '').lower()
                    looks_pdf = u_norm.lower().endswith('.pdf') or ('pdf' in txt_low) or ('proces' in txt_low) or ('verbaal' in txt_low) or ('stembureau' in txt_low)
                    if looks_pdf:
                        pdf_urls.add(u_norm)
                        if txt:
                            # store both normalized and raw as keys to maximize match chances later
                            labels_for_url.setdefault(u_norm, txt)
                            labels_for_url.setdefault(u, txt)
            except Exception:
                pass
            # Download (filter to TK2025 before saving)
            for u in sorted(pdf_urls):
                try:
                    resp = ctx.request.get(u, timeout=60000)
                    ctype = (resp.headers.get('content-type','') or '').lower()
                    is_pdf_resp = ('application/pdf' in ctype) or u.lower().endswith('.pdf')
                    if resp.ok and is_pdf_resp:
                        fname = os.path.basename(urlparse(u).path) or "document.pdf"
                        # Skip non‑TK25 and other election types (EP/PS/WS/GR) early
                        if not _is_current_year_pdf(fname + ' ' + u + ' ' + portal_url):
                            continue
                        dest = os.path.join(out_dir, sanitize_filename(fname))
                        if os.path.exists(dest):
                            key = u.split('?')[0]
                            items.append({
                                "remote_url": u,
                                "local_url": "file://" + os.path.abspath(dest),
                                "pdf_name": os.path.basename(dest),
                                "text": labels_for_url.get(key, labels_for_url.get(u, os.path.basename(dest))),
                                "score": 4,
                                "from": portal_url,
                            })
                            continue
                        with open(dest, 'wb') as f:
                            f.write(resp.body())
                        saved += 1
                        key = u.split('?')[0]
                        items.append({
                            "remote_url": u,
                            "local_url": "file://" + os.path.abspath(dest),
                            "pdf_name": os.path.basename(dest),
                            "text": labels_for_url.get(key, labels_for_url.get(u, os.path.basename(dest))),
                            "score": 4,
                            "from": portal_url,
                        })
                except Exception:
                    continue
            ctx.close(); browser.close()
    except Exception:
        return items
    if saved:
        print(f"[pv-overview] {muni}: saved {saved} PDFs")
    return items

def collect_mijnstembureau_portals(name: str, extra: dict) -> list[str]:
    """Discover MijnStembureau portal links for a municipality by scanning start/seeds and discovered pages."""
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
    portals: list[str] = []
    discover_pages: list[str] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|mijnstembureau", re.I)
    for s in seeds[:5]:
        try:
            html, base = fetch_html(s, allow_render=False)
            if not html:
                continue
            portals += find_mijnstembureau_links_from_html(html, base)
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
        # Also accept the seed itself if it points to a mijnstembureau uitslagen portal
        try:
            from urllib.parse import urlparse, urljoin
            u = urlparse(s)
            if 'mijnstembureau' in (u.netloc or '').lower() and '/uitslagen' in (u.path or ''):
                full = s
                # normalize to download-opties if not already
                if not u.path.rstrip('/').endswith('download-opties'):
                    full = urljoin(full.rstrip('/') + '/', 'download-opties')
                portals.append(full)
        except Exception:
            pass
    # Also probe a few likely pages via quick site search
    if start:
        try:
            for p in quick_site_search(start):
                try:
                    html3, base3 = fetch_html(p, allow_render=False)
                    if not html3:
                        continue
                    portals += find_mijnstembureau_links_from_html(html3, base3)
                except Exception:
                    continue
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
            portals += find_mijnstembureau_links_from_html(html2, base2)
        except Exception:
            pass
    # Sitemap discovery as a last resort
    if start and not portals:
        try:
            for p in discover_via_sitemap(start, max_pages=40):
                try:
                    html4, base4 = fetch_html(p, allow_render=False)
                    if not html4:
                        continue
                    portals += find_mijnstembureau_links_from_html(html4, base4)
                    if portals:
                        break
                except Exception:
                    continue
        except Exception:
            pass
    # Dedup portals
    out=[]; seen=set()
    for u in portals:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out


def download_mijnstembureau_portal(muni: str, portal_url: str) -> list[dict]:
    """Open a MijnStembureau download-options page and download PV PDFs by intercepting PDF responses.
    Returns a list of index items with local_url and pdf_name (remote_url set to the PDF API endpoint).
    """
    if not PLAYWRIGHT_AVAILABLE:
        print(f"[mijnstembureau] Playwright not available; skip portal {portal_url}")
        return []
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    items: list[dict] = []
    saved = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(portal_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            try:
                page.wait_for_selector('a,button,[role=button],[role=link]', timeout=5000)
                page.wait_for_timeout(800)
            except Exception:
                pass
            # If we landed on the generic '/uitslagen' page, try to navigate to the current Tweede Kamer election
            try:
                cur_url = page.url
                if '/uitslagen' in cur_url and 'download-opties' not in cur_url:
                    # Click a tile/link that mentions 'Tweede Kamer' or 'verkiez'
                    for t in ("Tweede Kamer", "verkiez", "2025"):
                        try:
                            el = page.get_by_text(t, exact=False).first
                            if el and el.is_visible():
                                el.click(timeout=15000)
                                page.wait_for_timeout(800)
                                break
                        except Exception:
                            continue
                    # Try to click a 'Download' or 'Download opties' action if present
                    for t in ("Download", "Download opties", "download-opties"):
                        try:
                            el = page.get_by_text(t, exact=False).first
                            if el and el.is_visible():
                                el.click(timeout=15000)
                                page.wait_for_timeout(800)
                                break
                        except Exception:
                            continue
            except Exception:
                pass
            # If we started at a non-existing '/download-opties', go back to '/uitslagen/' root and proceed
            try:
                if 'download-opties' in page.url:
                    # Navigate to root '/uitslagen/' by trimming after '/uitslagen'
                    u = page.url
                    i = u.lower().find('/uitslagen')
                    if i != -1:
                        root = u[:i] + '/uitslagen/'
                        page.goto(root, wait_until='domcontentloaded', timeout=60000)
                        page.wait_for_timeout(600)
                        # Repeat election + download navigation
                        for t in ("Tweede Kamer", "verkiez", "2025"):
                            try:
                                el = page.get_by_text(t, exact=False).first
                                if el and el.is_visible():
                                    el.click(timeout=15000)
                                    page.wait_for_timeout(800)
                                    break
                            except Exception:
                                continue
                        for t in ("Download", "Download opties", "download-opties"):
                            try:
                                el = page.get_by_text(t, exact=False).first
                                if el and el.is_visible():
                                    el.click(timeout=15000)
                                    page.wait_for_timeout(800)
                                    break
                            except Exception:
                                continue
            except Exception:
                pass
            # Try a one-shot 'download all' ZIP first (minimal requests)
            try:
                from tempfile import mkstemp
                import zipfile
                import tempfile
                # Look for a visible control that indicates bulk download
                bulk_texts = [
                    "Download alle",
                    "Alles downloaden",
                    "Alle processen",
                    "Alle proces",
                    "ZIP",
                ]
                bulk_clicked = False
                for t in bulk_texts:
                    try:
                        el = page.get_by_text(t, exact=False).first
                        if el and el.is_visible():
                            with page.expect_download(timeout=45000) as dl_info:
                                el.click(timeout=15000)
                            dl = dl_info.value
                            # Save to temp and inspect type
                            fd, tmpzip = tempfile.mkstemp()
                            os.close(fd)
                            try:
                                dl.save_as(tmpzip)
                            except Exception:
                                try:
                                    os.remove(tmpzip)
                                except Exception:
                                    pass
                                tmpzip = None
                            if tmpzip and zipfile.is_zipfile(tmpzip):
                                z = zipfile.ZipFile(tmpzip)
                                for nm in z.namelist():
                                    if not nm.lower().endswith('.pdf'):
                                        continue
                                    try:
                                        data = z.read(nm)
                                        base = os.path.basename(nm) or 'document.pdf'
                                        dest = os.path.join(out_dir, sanitize_filename(base))
                                        if not os.path.exists(dest):
                                            with open(dest, 'wb') as f:
                                                f.write(data)
                                            saved += 1
                                        items.append({
                                            "remote_url": None,
                                            "local_url": "file://" + os.path.abspath(dest),
                                            "pdf_name": os.path.basename(dest),
                                            "text": os.path.basename(dest),
                                            "score": 5,
                                            "from": page.url,
                                        })
                                    except Exception:
                                        continue
                                z.close()
                                try:
                                    os.remove(tmpzip)
                                except Exception:
                                    pass
                                bulk_clicked = True
                                break
                            # Not a ZIP; clean up temp file
                            if tmpzip:
                                try:
                                    os.remove(tmpzip)
                                except Exception:
                                    pass
                    except Exception:
                        continue
                if bulk_clicked:
                    print(f"[mijnstembureau] {muni}: downloaded bulk ZIP with {saved} PDFs")
            except Exception:
                pass

            # Reveal PV list / navigate to downloads if needed
            clicked = False
            for t in ("Processen verbaal", "Proces-verbaal", "Processen-verbaal", "Procesverbaal", "Proces", "verbaal"):
                try:
                    el = page.get_by_text(t, exact=False).first
                    if el and el.is_visible():
                        el.click(timeout=15000)
                        clicked = True
                        break
                except Exception:
                    continue
            # Try to navigate to 'Tweede Kamer 2025' tile first if present
            if not clicked:
                for t in ("Tweede Kamer", "Tweede", "2025", "verkiez", "Kamer"):
                    try:
                        el = page.get_by_text(t, exact=False).first
                        if el and el.is_visible():
                            el.click(timeout=15000)
                            page.wait_for_timeout(800)
                            break
                    except Exception:
                        continue
            if not clicked:
                # Try a generic 'Download' button that opens the options
                for t in ("Download", "Download opties", "download-opties"):
                    try:
                        el = page.get_by_text(t, exact=False).first
                        if el and el.is_visible():
                            el.click(timeout=15000)
                            page.wait_for_timeout(800)
                            clicked = True
                            break
                    except Exception:
                        continue
            if not clicked:
                # Proceed anyway: some portals expose direct download buttons without an explicit section/tab
                print(f"[mijnstembureau] {muni}: proceeding without explicit downloads tab on {portal_url}")
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
            # Match both buttons and anchors likely to trigger a PDF
            buttons = page.locator(
                'button:has-text(".pdf"), a:has-text(".pdf"), '
                'button:has-text("Download"), a:has-text("Download"), '
                '[aria-label*="Download" i], [title*="Download" i]'
            )
            count = buttons.count()
            for i in range(count):
                try:
                    btn = buttons.nth(i)
                    inner = (btn.inner_text() or '').strip()
                    label = sanitize_filename(inner) or f"pv_{i+1}.pdf"
                    if not label.lower().endswith('.pdf'):
                        label += '.pdf'
                    dest = os.path.join(out_dir, label)
                    if os.path.exists(dest):
                        items.append({
                            "remote_url": None,
                            "local_url": "file://" + os.path.abspath(dest),
                            "pdf_name": label,
                            "text": label,
                            "score": 5,
                            "from": portal_url,
                        })
                        continue
                    def is_pdf(resp):
                        try:
                            ct = (resp.headers.get('content-type') or '').lower()
                            return ('application/pdf' in ct) or resp.url.lower().endswith('.pdf')
                        except Exception:
                            return False
                    with page.expect_response(is_pdf, timeout=45000) as resp_info:
                        btn.click(timeout=15000)
                    resp = resp_info.value
                    data = resp.body()
                    with open(dest, 'wb') as f:
                        f.write(data)
                    saved += 1
                    items.append({
                        "remote_url": resp.url,
                        "local_url": "file://" + os.path.abspath(dest),
                        "pdf_name": label,
                        "text": label,
                        "score": 5,
                        "from": portal_url,
                    })
                except Exception as e:
                    print(f"[mijnstembureau] {muni}: error item {i+1}: {e}")
                    continue
            # As a last resort, passively capture any PDF responses for a short window while clicking a few generic elements
            if not items:
                pdfs_captured = []
                def on_resp(resp):
                    try:
                        ct = (resp.headers.get('content-type') or '').lower()
                        if ('application/pdf' in ct) or resp.url.lower().endswith('.pdf'):
                            pdfs_captured.append(resp)
                    except Exception:
                        return
                page.on('response', on_resp)
                # Click up to 3 generic candidates
                gens = page.locator('a,button,[role=button],[role=link]')
                lim = min(3, gens.count())
                for i in range(lim):
                    try:
                        el = gens.nth(i)
                        if el.is_visible():
                            el.click(timeout=5000)
                            page.wait_for_timeout(800)
                    except Exception:
                        continue
                page.wait_for_timeout(1500)
                # Save captured PDFs
                for resp in pdfs_captured:
                    try:
                        data = resp.body()
                        from urllib.parse import urlparse
                        fname = os.path.basename(urlparse(resp.url).path) or 'document.pdf'
                        dest = os.path.join(out_dir, sanitize_filename(fname))
                        if not os.path.exists(dest):
                            with open(dest, 'wb') as f:
                                f.write(data)
                            saved += 1
                        items.append({
                            "remote_url": resp.url,
                            "local_url": "file://" + os.path.abspath(dest),
                            "pdf_name": os.path.basename(dest),
                            "text": os.path.basename(dest),
                            "score": 5,
                            "from": page.url,
                        })
                    except Exception:
                        continue
                try:
                    page.off('response', on_resp)
                except Exception:
                    pass
            ctx.close(); browser.close()
    except Exception:
        return items
    if saved:
        print(f"[mijnstembureau] {muni}: saved {saved}/{len(items)} PV PDFs")
    return items

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
                    # Skip banned PDFs before writing to disk
                    if not _is_current_year_pdf(base):
                        continue
                    dest = os.path.join(out_dir, sanitize_filename(base))
                    if os.path.exists(dest):
                        # Skip duplicates
                        continue
                    with z.open(name) as src, open(dest, 'wb') as f:
                        f.write(src.read())
                    saved_paths.append(dest)
        except zipfile.BadZipFile:
            # Direct file (likely a single PDF)
            suggested = dl.suggested_filename or 'download.pdf'
            base = os.path.join(out_dir, sanitize_filename(suggested))
            base0, ext = os.path.splitext(base)
            if not ext.lower() == '.pdf':
                base = base0 + '.pdf'
            # Skip banned PDFs before saving
            if not _is_current_year_pdf(os.path.basename(base)):
                # ensure tmp is cleaned below and do not save
                return []
            # Do not create numbered duplicates
            if os.path.exists(base):
                # Nothing to save, duplicate
                return []
            os.replace(tmppath, base)
            saved_paths.append(base)
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
        # Fallback: per-file download anchors (skip banned and duplicates before clicking/saving)
        anchors = page.locator('a[download], a[data-action="download"], a:has-text("Download")')
        n = anchors.count()
        for i in range(n):
            try:
                a = anchors.nth(i)
                cand = (a.get_attribute('download') or '').strip()
                if not cand:
                    # Fallback to link text as rough guess
                    try:
                        cand = (a.inner_text(timeout=1000) or '').strip()
                    except Exception:
                        cand = ''
                if cand and not cand.lower().endswith('.pdf'):
                    cand = cand + '.pdf'
                if cand:
                    if not _is_current_year_pdf(cand):
                        continue
                    dest_guess = os.path.join(out_dir, sanitize_filename(cand))
                    if os.path.exists(dest_guess):
                        # Already present; skip clicking to avoid duplicate download
                        continue
                with page.expect_download(timeout=45000) as dl_ctx:
                    a.click()
                dl = dl_ctx.value
                # Early check on suggested filename, skip saving if banned or duplicate
                sf = dl.suggested_filename or 'download.pdf'
                if not sf.lower().endswith('.pdf'):
                    sf = sf + '.pdf'
                if not _is_current_year_pdf(sf):
                    continue
                if os.path.exists(os.path.join(out_dir, sanitize_filename(sf))):
                    continue
                for path in save_download(dl):
                    fname = os.path.basename(path)
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
            dyn = ("amsterdam.nl" in s) or ("gemeente.emmen.nl" in s) or ("ermelo.nl" in s)
            html, base = fetch_html(s, allow_render=dyn)
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
            dyn = ("amsterdam.nl" in p) or ("gemeente.emmen.nl" in p) or ("ermelo.nl" in p)
            html2, base2 = fetch_html(p, allow_render=dyn)
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


def collect_generic_filehubs(name: str, extra: dict, allow_external: bool = False, force_render: bool = False) -> list[str]:
    """Find generic 'file hub' pages (internal or external if allowed) that likely contain documents for this municipality."""
    start = get_start_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.insert(0, start)
    hubs: list[str] = []
    # scan seeds
    for s in seeds[:5]:
        try:
            html, base = fetch_html(s, allow_render=force_render)
            if not html:
                continue
            hubs += find_generic_filehub_links_from_html(html, base, allow_external=allow_external)
        except Exception:
            pass
    # shallow expansion: follow discovered pages from seeds that look promising
    expanded: list[str] = []
    seenp: set[str] = set()
    for u in list(hubs)[:8]:
        if u in seenp:
            continue
        seenp.add(u)
        try:
            html2, base2 = fetch_html(u, allow_render=force_render)
            if not html2:
                continue
            expanded += find_generic_filehub_links_from_html(html2, base2, allow_external=allow_external)
        except Exception:
            pass
    hubs += expanded
    # Dedup
    out: list[str] = []
    seen: set[str] = set()
    for u in hubs:
        if u in seen:
            continue
        # Skip same-page fragment anchors like '#documenten-...' on the start page
        try:
            st = start or ""
            if st and '#' in u:
                from urllib.parse import urlparse
                up = urlparse(u); sp = urlparse(st)
                if up.netloc == sp.netloc and up.path == sp.path:
                    continue
        except Exception:
            pass
        seen.add(u)
        out.append(u)
    return out[:12]


def quick_site_search(start_url: str) -> list[str]:
    """Probeer 1-2 eenvoudige zoek-url varianten om extra pagina's te vinden.
    Retourneert een lijst pagina-URLs (geen PDFs) om daarna PDF-links uit te halen.
    """
    pu = urlparse(start_url)
    base = f"{pu.scheme}://{pu.netloc}"
    # Uitgebreide termen zodat o.a. 'voorlopige-verkiezingsuitslag' gevonden wordt
    terms = [
        "documenten verkiezing", "verkiezingsuitslag", "verkiezingen uitslag", "verkiez", "uitslag",
        "proces-verbaal", "processen-verbaal", "stembureau", "voorlopige", "N10-2", "Na 31-2", "bijlage 2",
        "bestanden", "documenten", "gestemd", "zo is er gestemd"
    ]
    paths = ["zoeken", "search", "site/zoeken"]
    candidates = []
    for t in terms:
        for p in paths:
            q = requests.utils.quote(t)
            # probeer zowel ?q=, ?search= als ?trefwoord=
            candidates.append(f"{base}/{p}?q={q}")
            candidates.append(f"{base}/{p}?search={q}")
            candidates.append(f"{base}/{p}?trefwoord={q}")
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
                    if any(k in low for k in ("verkiez", "uitslag", "proces", "stembur", "n10", "na 31", "bijlage", "voorlopige", "document", "bestanden")):
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


def probe_well_known_pages(start_url: str) -> list[str]:
    """Probeer een handvol vaak gebruikte paden die gemeenten gebruiken voor verkiezingspagina's.
    Bijvoorbeeld '/verkiezingen', '/bestanden', '/tweede-kamerverkiezingen', '/tk2025'.
    """
    try:
        pu = urlparse(start_url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    # Kandidaten (orde: meest algemeen eerst)
    cand = [
        "/verkiezingen",
        "/verkiezingen/verslagen-verkiezingen/",
        "/verkiezingen/overzicht-proces-verbalen/",
        "/verkiezingen/overzicht-proces-verbalen/processen-verbaal-25/",
        "/bestanden",
        "/tweede-kamerverkiezingen/",
        "/tweede-kamerverkiezingen",
        "/verkiezing",
        "/verkiezingsuitslag",
        "/voorlopige-uitslag",
        "/documenten",
        "/downloads",
        "/uitslagen",
        "/uitslagen-verkiezingen",
        "/zo-is-er-gestemd",
        "/zo-is-er-gestemd-in",
        "/tk2025",
        "/site/zoeken?search=proces-verbaal",
        "/zoeken?search=proces-verbaal",
        "/search?q=proces-verbaal",
    ]
    out: list[str] = []
    seen = set()
    for path in cand:
        u = origin.rstrip("/") + path
        if u in seen:
            continue
        seen.add(u)
        # Optimistic include; actual fetching happens later with graceful handling
        out.append(u)
    # dedup and cap
    res = []
    seen2 = set()
    for u in out:
        if u in seen2:
            continue
        seen2.add(u)
        res.append(u)
    return res[:12]


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
    KEY_RE = re.compile(r"verkiez|uitslag|tweede.*kamer|stembur|proces|result|gestemd", re.I)

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


def _pleio_direct_url(url: str) -> str:
    """If URL is a Pleio '/files/view/<guid>/*' view URL, convert it to the direct
    '/file/download/<guid>' endpoint which returns the PDF via plain HTTP.
    Otherwise return the original URL.
    """
    try:
        pu = urlparse(url)
        if pu.netloc and pu.netloc.endswith('pleio.nl') and '/files/view/' in (pu.path or ''):
            m = re.search(r"/files/view/([0-9a-f\-]+)/", pu.path, re.I)
            if m:
                guid = m.group(1)
                return f"{pu.scheme}://{pu.netloc}/file/download/{guid}"
    except Exception:
        pass
    return url


def download_pdf(url: str, out_dir: str) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    try:
        url = _pleio_direct_url(url)
        # Use streaming and a higher timeout for large municipal PDFs
        r = requests.get(url, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=(15, 180), stream=True)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()
        if ("application/pdf" not in ct and "application/octet-stream" not in ct
                and not urlparse(url).path.lower().endswith(".pdf")):
            r.close()
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
        # Skip if file already exists; do not create numbered duplicates
        if os.path.exists(path):
            return None
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                f.write(chunk)
        r.close()
        return path
    except Exception:
        return None


def download_zip_and_extract_pdfs(url: str, out_dir: str) -> list[str]:
    """Download a ZIP archive and extract contained PDFs into out_dir.
    Returns a list of saved file paths. Minimal requests: single GET then local extract.
    """
    saved: list[str] = []
    os.makedirs(out_dir, exist_ok=True)
    try:
        r = requests.get(url, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=(15, 180), stream=True)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()
        if "zip" not in ct and not urlparse(url).path.lower().endswith('.zip'):
            r.close(); return saved
        import tempfile, zipfile
        fd, tmppath = tempfile.mkstemp()
        os.close(fd)
        with open(tmppath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
        r.close()
        if not zipfile.is_zipfile(tmppath):
            try:
                os.remove(tmppath)
            except Exception:
                pass
            return saved
        z = zipfile.ZipFile(tmppath)
        for name in z.namelist():
            if not name.lower().endswith('.pdf'):
                continue
            base = os.path.basename(name) or 'document.pdf'
            if not _is_current_year_pdf(base):
                continue
            dest = os.path.join(out_dir, sanitize_filename(base))
            if os.path.exists(dest):
                continue
            try:
                with z.open(name) as src, open(dest, 'wb') as f:
                    f.write(src.read())
                saved.append(dest)
            except Exception:
                continue
        z.close()
        try:
            os.remove(tmppath)
        except Exception:
            pass
    except Exception:
        return saved
    return saved


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
    """Fetch page HTML.
    - If allow_render=True and Playwright is available, prefer a rendered page (client-side content).
    - Otherwise, try a static GET and fall back to rendered if blocked/empty.
    """
    if allow_render and PLAYWRIGHT_AVAILABLE:
        try:
            html, final = render_page_content(url)
            if html:
                return html, final
        except Exception:
            # fall through to static
            pass
    try:
        r = http_get(url)
        if r.status_code == 200 and not is_blocked_html(r.text):
            return r.text, r.url
    except Exception:
        pass
    if PLAYWRIGHT_AVAILABLE and allow_render:
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
        seeds.insert(0, start)
        # Probeer bekende paden (zoals /verkiezingen, /bestanden) ook als seed
        try:
            for u in probe_well_known_pages(start)[:6]:
                if u not in seeds:
                    seeds.append(u)
        except Exception:
            pass
    # fetch seeds and extract pdfs + discover a small set of relevant internal pages
    discover_pages_scored: list[tuple[str,int]] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|tweede-?kamerverkiez|n10|na\s*31|na31|model", re.I)
    for s in seeds[:5]:
        try:
            allow_render = ("amsterdam.nl" in s) or ("gemeente.emmen.nl" in s) or ("ermelo.nl" in s) or force_render
            html, base = fetch_html(s, allow_render=allow_render)
            if not html:
                continue
            urls += extract_pdf_links(html, base)
            # Also capture relevant ZIP archives on the page (e.g., Leiden bundles)
            try:
                soup_zip = BeautifulSoup(html or "", "html.parser")
                for a2 in soup_zip.select('a[href]'):
                    h2 = a2.get('href') or ''
                    full2 = urljoin(base, h2)
                    low2 = (full2 + ' ' + (a2.get_text(' ', strip=True) or '')).lower()
                    if full2.lower().endswith('.zip') and any(k in low2 for k in ('n10','na 31','na31','proces','verbaal','stembureau','verkiez','verslag')):
                        if _is_current_year_pdf(full2):
                            urls.append({
                                'remote_url': full2,
                                'local_url': None,
                                'text': a2.get_text(' ', strip=True) or 'ZIP',
                                'pdf_name': os.path.basename(urlparse(full2).path) or 'archive.zip',
                                'score': 2,
                                'from': base,
                            })
            except Exception:
                pass
            # Early stop if this seed already yields a strong PV set
            try:
                if _is_probably_complete(urls, name):
                    break
            except Exception:
                pass
            soup = BeautifulSoup(html, "html.parser")
            pu = urlparse(base)
            base0 = f"{pu.scheme}://{pu.netloc}"
            for a in soup.select("a[href]"):
                href = a.get("href"); full = urljoin(base0, href or "")
                if not full or ".pdf" in urlparse(full).path.lower():
                    continue
                if urlparse(full).netloc != pu.netloc or not full.startswith(base0):
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
            try:
                if _is_probably_complete(urls, name):
                    break
            except Exception:
                pass
        except Exception:
            pass
    # quick site search to discover extra pages (even if some URLs already found)
    if start:
        for p in quick_site_search(start):
            try:
                allow_render = ("amsterdam.nl" in p) or force_render
                html3, base3 = fetch_html(p, allow_render=allow_render)
                if not html3:
                    continue
                urls += extract_pdf_links(html3, base3)
                try:
                    if _is_probably_complete(urls, name):
                        break
                except Exception:
                    pass
            except Exception:
                pass
    # As a deeper fallback: shallow BFS on internal pages to catch hubs like '/bestanden'
    if len(urls) < 5:
        try:
            bfs = collect_pdfs_bfs_internal(name, max_depth=2, max_pages=60, force_render=force_render)
            if bfs:
                urls += bfs
        except Exception:
            pass
    # sitemap discovery as additional source (news pages like 'Zo is er gestemd ...')
    if start:
        for p in discover_via_sitemap(start):
            try:
                r4 = http_get(p, timeout=12)
                urls += extract_pdf_links(r4.text, r4.url)
                try:
                    if _is_probably_complete(urls, name):
                        break
                except Exception:
                    pass
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


# -------- Early-stop heuristic for sufficient PV coverage --------

PDF_STRONG_HINT_RE = re.compile(r"stembur|proces|verbaal|\bpv\b|\bn10\b|na\s*31|na31|uitkomst|verklaring", re.I)


def _is_probably_complete(pdfs: list[dict], muni: str) -> bool:
    """Return True if the current set of discovered PDFs likely covers the municipality PV set.
    Heuristics:
      - many PDFs (>= 40), or
      - strong-signal PDFs (label contains stembureau/proces/verbaal/N10/Na31/PV) >= 12, or
      - cluster by same source page or same host >= 20.
    """
    if not pdfs:
        return False
    n = len(pdfs)
    if n >= 40:
        return True
    strong = 0
    for p in pdfs:
        s = " ".join([
            str(p.get("pdf_name") or ""),
            str(p.get("text") or ""),
            str(p.get("from") or ""),
        ])
        if PDF_STRONG_HINT_RE.search(s):
            strong += 1
    if strong >= 12:
        return True
    # cluster by from-page or by host
    try:
        from collections import Counter
        from_hosts = Counter()
        from_pages = Counter()
        for p in pdfs:
            frm = p.get("from") or ""
            if frm:
                from_pages[frm] += 1
                try:
                    u = urlparse(frm)
                    from_hosts[f"{u.scheme}://{u.netloc}"] += 1
                except Exception:
                    pass
        if from_pages and max(from_pages.values()) >= 20:
            return True
        if from_hosts and max(from_hosts.values()) >= 20:
            return True
    except Exception:
        pass
    return False


# -------- BFS discovery on internal site (generic) --------

def collect_pdfs_bfs_internal(name: str, max_depth: int = 3, max_pages: int = 120, force_render: bool = False) -> list[dict]:
    """BFS over internal pages up to max_depth, selecting links by election/PV heuristics,
    extracting PDFs from each visited page. Keeps within the municipality domain.
    """
    start = get_start_url(name)
    if not start:
        return []
    try:
        pu = urlparse(start)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    KEY_RE = re.compile(r"verkiez|uitslag|voorlopige|gestemd|proces|verbaal|stembur|tweede.*kamer|pv\b|n10|na\s*31|na31|model|document|download", re.I)
    visited: set[str] = set()
    queue: list[tuple[str,int]] = [(start, 0)]
    pages: list[str] = []
    while queue and len(pages) < max_pages:
        u, d = queue.pop(0)
        if u in visited:
            continue
        visited.add(u)
        try:
            html, base = fetch_html(u, allow_render=force_render)
        except Exception:
            html, base = None, None
        if not html or not base:
            continue
        pages.append(base)
        if d >= max_depth:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        pu2 = urlparse(base)
        base0 = f"{pu2.scheme}://{pu2.netloc}"
        for a in soup.select('a[href]'):
            href = a.get('href'); full = urljoin(base0, href or '')
            if not full:
                continue
            # stay on same host
            if urlparse(full).netloc != pu.netloc:
                continue
            # do not follow direct pdfs
            if urlparse(full).path.lower().endswith('.pdf'):
                continue
            low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
            if KEY_RE.search(low):
                queue.append((full, d + 1))
    # scan collected pages for PDFs
    out: list[dict] = []
    seen: set[str] = set()
    for p in pages:
        try:
            r = http_get(p, timeout=15)
        except Exception:
            continue
        eps = extract_pdf_links(r.text, r.url)
        for e in eps:
            u = e.get('remote_url')
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(e)
    return out


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compacte PDF-scraper voor gemeenten")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen)")
    ap.add_argument("--slice", type=str, default=None, help="1-based inclusieve slice, bijv. 1-10 of 6-10")
    ap.add_argument("--first", type=int, default=None, help="Pak de eerste N gemeenten (fallback als --slice ontbreekt)")
    ap.add_argument("--starts-with", dest="starts_with", type=str, default=None,
                    help="Beperk tot gemeenten die beginnen met deze letters (bijv. 'G' of 'GHI'). Hoofd-/kleine letters genegeerd.")
    ap.add_argument("--index-path", type=str, default=None, help="Pad naar indexbestand i.p.v. standaard municipality_pdfs_index.json")
    ap.add_argument("--no-index-write", action="store_true", help="Schrijf geen index-bestand weg aan het einde")
    ap.add_argument("--merge-from-disk", action="store_true", help="Vul index aan door lokale PDF-bestanden te scannen (geen downloads)")
    ap.add_argument("--complete-remote", action="store_true", help="Probeer ontbrekende remote_url voor bestaande items aan te vullen (geen downloads)")
    ap.add_argument("--follow-external", action="store_true", help="Volg relevante externe links (beperkt, geheuristiceerd)")
    ap.add_argument("--generic-filehubs", action="store_true", help="Zoek algemene document-portalen (folders/files) en probeer downloads via Playwright")
    ap.add_argument("--render", action="store_true", help="Render pagina's via Playwright om dynamische lijsten te zien")
    ap.add_argument("--pleio-headful", action="store_true", help="Open Pleio-hubs headful voor eenmalige enumeratie (stabieler)")
    args = ap.parse_args(argv)

    # Bepaal doellijst (initieel; kan nog aangepast worden als --complete-remote zonder selectie is opgegeven)
    if args.only:
        all_names = set(get_all_names())
        names = [n for n in args.only if n in all_names]
    elif args.starts_with:
        letters = set((args.starts_with or "").upper())
        names = [n for n in get_all_names() if isinstance(n, str) and n[:1].upper() in letters]
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

    # Previously we skipped Amsterdam due to API-only PV endpoint; now we support the public PV overview page.

    print(f"[cleaned] Target: {', '.join(names)}")
    total_saved = 0
    # Load existing index to merge instead of overwrite
    # Index pad kan overschreven worden om parallelle runs te isoleren
    idx_path = args.index_path or os.path.join(DATA_DIR, "municipality_pdfs_index.json")
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
        # Clear legacy/unused fields to avoid confusion
        q.pop("url", None)
        q.pop("preview_text", None)
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
                    fn = it.get('filename') or ''
                    if not _is_current_year_pdf(fn):
                        continue
                    mediafiler_items.append({
                        "remote_url": f"{it.get('album_url')}#fuid={it.get('fuid')}",
                        "local_url": None,
                        "pdf_name": fn,
                        "text": "MediaFiler",
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
            pdfs = collect_pdfs_for_municipality(n, extra, force_render=args.render)
            # Only do BFS if we have not yet found enough direct PDF links (reduce timeouts)
            if not pdfs or len(pdfs) < 3:
                try:
                    bfs_pdfs = collect_pdfs_bfs_internal(n, max_depth=2, max_pages=60, force_render=False)
                    if bfs_pdfs:
                        pdfs = pdfs + bfs_pdfs
                except Exception:
                    pass
            # Pleio hubs: enumerate view links headless, then download via direct HTTP endpoints
            try:
                start_url = get_start_url(n)
                hubs = []
                if start_url:
                    hhtml, hbase = fetch_html(start_url, allow_render=False)
                    if hhtml:
                        hubs += find_pleio_hubs_from_html(hhtml, hbase)
                if extra.get(n):
                    for s in extra.get(n, [])[:3]:
                        try:
                            sh, sb = fetch_html(s, allow_render=False)
                            if sh:
                                hubs += find_pleio_hubs_from_html(sh, sb)
                        except Exception:
                            pass
                # Dedup hubs
                _seen_h = set(); hubs2 = []
                for u in hubs:
                    if u in _seen_h: continue
                    _seen_h.add(u); hubs2.append(u)
                pleio_items: list[dict] = []
                for hub in hubs2[:4]:
                    try:
                        views = pleio_enumerate_view_links(hub, headful=args.pleio_headful)
                        for v in views:
                            try:
                                base_name = os.path.basename(urlparse(v).path) or 'document.pdf'
                            except Exception:
                                base_name = 'document.pdf'
                            pleio_items.append({
                                'remote_url': v,
                                'local_url': None,
                                'pdf_name': base_name if base_name.lower().endswith('.pdf') else base_name + '.pdf',
                                'text': 'Pleio',
                                'from': hub,
                                'score': 3,
                            })
                    except Exception:
                        continue
                if pleio_items:
                    pdfs = pdfs + pleio_items
            except Exception:
                pass
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
            # MijnStembureau portals discovery + downloads (PV buttons -> PDF responses)
            portals = collect_mijnstembureau_pages(n, extra)
            msb_items: list[dict] = []
            for portal in portals:
                try:
                    its = download_mijnstembureau_portal(n, portal)
                    if its:
                        msb_items.extend(its)
                except Exception as e:
                    print(f"[mijnstembureau] {n}: error downloading portal {portal}: {e}")
            if msb_items:
                pdfs = pdfs + msb_items
            # PV overview dynamic pages (e.g., Amsterdam) discovery + downloads
            pv_pages = collect_pv_overview_pages(n, extra)
            pv_items: list[dict] = []
            for pg in pv_pages:
                try:
                    its = download_pv_overview_page(n, pg)
                    if its:
                        pv_items.extend(its)
                except Exception as e:
                    print(f"[pv-overview] {n}: error downloading page {pg}: {e}")
            if pv_items:
                pdfs = pdfs + pv_items
            # Generic file-hubs (external portals)
            if args.generic_filehubs:
                hubs = collect_generic_filehubs(n, extra, allow_external=args.follow_external, force_render=args.render)
                hub_items: list[dict] = []
                for hub in hubs:
                    try:
                        its = download_generic_filehub(n, hub)
                        if its:
                            hub_items.extend(its)
                    except Exception as e:
                        print(f"[generic] {n}: error downloading hub {hub}: {e}")
                if hub_items:
                    pdfs = pdfs + hub_items
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
                if "mijnstembureau" in u:
                    # handled via Playwright already
                    continue
                # Handle relevant ZIP archives (e.g., Leiden bundles)
                if u.lower().endswith('.zip'):
                    extracted = download_zip_and_extract_pdfs(u, out_dir)
                    for path in extracted:
                        pdfs.append({
                            "remote_url": u + "#" + os.path.basename(path),
                            "local_url": "file://" + os.path.abspath(path),
                            "pdf_name": os.path.basename(path),
                            "text": os.path.basename(path),
                            "score": 5,
                            "from": p.get('from') or u,
                        })
                    continue
                # Pre-skip if a file with the intended pdf_name already exists in this municipality dir
                nm = p.get("pdf_name")
                if isinstance(nm, str) and nm.strip():
                    candidate = os.path.join(out_dir, sanitize_filename(nm))
                    if os.path.exists(candidate):
                        p["local_url"] = "file://" + os.path.abspath(candidate)
                        continue
                else:
                    # fallback: use URL basename
                    try:
                        base = os.path.basename(urlparse(u).path)
                    except Exception:
                        base = None
                    if base:
                        candidate = os.path.join(out_dir, sanitize_filename(base))
                        if os.path.exists(candidate):
                            p["local_url"] = "file://" + os.path.abspath(candidate)
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
    if not args.no_index_write:
        try:
            os.makedirs(os.path.dirname(idx_path) or DATA_DIR, exist_ok=True)
            with open(idx_path, "w", encoding="utf-8") as f:
                json.dump({"results": index_results, "count": len(index_results)}, f, ensure_ascii=False, indent=2)
            print(f"[cleaned] PDF index merged -> {idx_path}")
        except Exception as e:
            print(f"[cleaned] Warning: could not save pdf index: {e}")
    else:
        print("[cleaned] Index schrijven overgeslagen (--no-index-write)")
    print(f"[cleaned] Done. Total saved: {total_saved}")
    return 0


# -------- Pleio (generic) support: enumerate view links then direct-download via HTTP --------

def find_pleio_hubs_from_html(html: str, base_url: str) -> list[str]:
    """Return Pleio hub links discovered in the page HTML.
    Heuristics: domain contains 'pleio.nl' and path contains '/groups/view/' or '/files/'.
    Prefer anchors whose text mentions 'proces' and 'verbaal'.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    hubs: list[str] = []
    prefers: list[str] = []
    for a in soup.select('a[href]'):
        href = a.get('href'); full = urljoin(base_url, href or '')
        u = urlparse(full)
        if not u.netloc or 'pleio.nl' not in u.netloc:
            continue
        if '/groups/view/' in u.path or '/files/' in u.path or '/verkiezingen' in u.path:
            txt = (a.get_text(' ', strip=True) or '').lower()
            if 'proces' in txt and 'verbaal' in txt:
                prefers.append(full)
            else:
                hubs.append(full)
    out = []
    seen = set()
    for lst in (prefers, hubs):
        for u in lst:
            if u in seen:
                continue
            seen.add(u); out.append(u)
    return out[:6]


def pleio_enumerate_view_links(hub_url: str, max_links: int = 400, headful: bool = False) -> list[str]:
    """Use Playwright headless to open a Pleio hub and enumerate '/files/view/<guid>/' links.
    Does not download; caller will convert to direct HTTP download endpoints.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return []
    links: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=(not headful))
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118 Safari/537.36', locale='nl-NL', viewport={'width': 1280, 'height': 900})
            page = context.new_page()
            page.goto(hub_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            # Try collect directly (wait and parse DOM)
            try:
                page.wait_for_selector("a[href*='/files/view/']", timeout=20000)
            except Exception:
                pass
            try:
                # Locator path
                loc = page.locator("a[href*='/files/view/']")
                cnt = loc.count()
                for i in range(min(cnt, max_links)):
                    try:
                        href = loc.nth(i).get_attribute('href') or ''
                        if '/files/view/' in href:
                            links.append(urljoin(page.url, href))
                    except Exception:
                        continue
            except Exception:
                pass
            if not links:
                try:
                    html = page.content()
                    import re as _re
                    for m in _re.finditer(r"href=\"([^\"]*/files/view/[^\"]+)\"", html):
                        links.append(urljoin(page.url, m.group(1)))
                except Exception:
                    pass
            # If none, click tiles with 'Gescande processen-verbaal' variants
            if not links:
                # Prefer obvious tile anchors by text
                folder_selectors = [
                    'a:has-text("Gescande processen-verbaal")',
                    'a:has-text("processen-verbaal")',
                    'a:has-text("proces")',
                    'a:has-text("Bestanden")',
                ]
                for sel in folder_selectors:
                    try:
                        loc = page.locator(sel)
                        if loc.count() == 0:
                            continue
                        with page.expect_navigation(timeout=20000):
                            loc.first.click()
                        try:
                            page.wait_for_load_state('networkidle', timeout=8000)
                        except Exception:
                            pass
                        # Wait for any view links to appear
                        try:
                            page.wait_for_selector('a[href*="/files/view/"]', timeout=20000)
                        except Exception:
                            pass
                        try:
                            page.wait_for_selector("a[href*='/files/view/']", timeout=20000)
                        except Exception:
                            pass
                        try:
                            loc2 = page.locator("a[href*='/files/view/']")
                            cnt2 = loc2.count()
                            for i in range(min(cnt2, max_links)):
                                try:
                                    href = loc2.nth(i).get_attribute('href') or ''
                                    if '/files/view/' in href:
                                        links.append(urljoin(page.url, href))
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        if not links:
                            try:
                                html2 = page.content()
                                import re as _re
                                for m in _re.finditer(r"href=\"([^\"]*/files/view/[^\"]+)\"", html2):
                                    links.append(urljoin(page.url, m.group(1)))
                            except Exception:
                                pass
                        if links:
                            break
                    except Exception:
                        continue
            context.close(); browser.close()
    except Exception:
        return []
    # Dedup and cap
    out = []
    seen = set()
    for u in links:
        if u in seen:
            continue
        seen.add(u); out.append(u)
        if len(out) >= max_links:
            break
    return out


if __name__ == "__main__":
    sys.exit(run())
