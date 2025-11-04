#!/usr/bin/env python3
"""
Compacte, snelle PDF-scraper voor TK2025 processen‑verbaal per gemeente.

Doelen:
- Zo min mogelijk requests, zo snel mogelijk de juiste PV‑PDFs vinden
- Vroegtijdig stoppen zodra we met hoge waarschijnlijkheid “genoeg” hebben
- Ondersteun de belangrijkste situaties:
  1) Directe PV‑pagina (met PDF‑links, vaak via sim‑cdn)
  2) MijnStembureau portaal (buttons -> /uitslagen/api/view-pv/...)
  3) MediaFiler albums
  4) Stackstorage shares
- Hergebruik robuuste helpers uit pdf_scraper.py waar zinvol

Output:
- Downloads in ./pdfs/<Gemeente>/
- Index merge in pdf_scraper_input/municipality_pdfs_index.json (lichte merge per gemeente)

Gebruik:
  python3 pdf_scraper_compact.py --only Harlingen Heemskerk
  python3 pdf_scraper_compact.py --slice 101-120
  python3 pdf_scraper_compact.py --first 10

"""
from typing import Tuple
import argparse
import json
import os
import re
from urllib.parse import urljoin, urlparse
from collections import Counter
import requests
from bs4 import BeautifulSoup
# Do not import the generic scraper here; keep this tool self-contained.
from playwright.sync_api import sync_playwright
PLAYWRIGHT_AVAILABLE = True


DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
OUT_BASE = os.path.join(os.getcwd(), "pdfs")
INDEX_PATH = os.path.join(DATA_DIR, "municipality_pdfs_index.json")


def load_json(path: str):
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
    # eerst verified -> municipalities
    try:
        v = load_json(os.path.join(DATA_DIR, "municipality_links_verified.json")).get("verified", [])
        for it in v:
            if it.get("name") == name:
                if it.get("status") == 200:
                    return it.get("final_url") or it.get("start_url")
                if it.get("start_url"):
                    return it.get("start_url")
    except Exception:
        pass
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
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


# TK25 filter — uitgebreide regels (ban EP/PS/WS/GR en jaren ≠ 2025)
TARGET_YEAR_FULL = 2025
TARGET_YEAR_SHORT = 25


def _is_current_year_pdf(label: str) -> bool:
    if not isinstance(label, str):
        return True
    s = label.lower()
    # ban words
    # Ban deze verkiezingstypen onvoorwaardelijk (redundanten verwijderd)
    if any(k in s for k in ["waterschap", "gemeenteraad", "provinciale", "europees"]):
        return False
    # short codes (ep24/ps23/ws25/gr22)
    if re.search(r"(?<![a-z])ep\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![a-z])ps\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![a-z])ws\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    if re.search(r"(?<![a-z])gr\s*[-_]?\s*(?:20)?\d{2}", s):
        return False
    # tk2025/tk25 accept; tk2023/tk23 reject
    m = re.search(r"tk\s*[-_]?\s*20(\d{2})", s)
    if m:
        return (2000 + int(m.group(1))) == TARGET_YEAR_FULL
    m = re.search(r"tk\s*[-_]?\s*(\d{2})(?!\d)", s)
    if m:
        return int(m.group(1)) == TARGET_YEAR_SHORT
    # ‘tweede kamer 20yy’ accept only 2025
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
    # any year token
    for ym in re.finditer(r"\b(20\d{2})\b", s):
        if int(ym.group(1)) != TARGET_YEAR_FULL:
            return False
    return True


def http_get(url: str, timeout: Tuple[int, int] = (15, 30)):
    r = requests.get(url, headers={"User-Agent": "restzetels-compact/0.1"}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r

def http_head(url: str, timeout: Tuple[int, int] = (8, 12)):
    try:
        r = requests.head(url, headers={"User-Agent": "restzetels-compact/0.1"}, timeout=timeout, allow_redirects=True)
        return r
    except Exception:
        return None

def _probe_pdf_exists(url: str) -> bool:
    r = http_head(url)
    try:
        if r is not None and (200 <= r.status_code < 400):
            ct = (r.headers.get('content-type','') or '').lower()
            if ('pdf' in ct) or url.lower().endswith('.pdf'):
                return True
    except Exception:
        pass
    # Fallback: lightweight GET with Range
    try:
        rg = requests.get(url, headers={"User-Agent": "restzetels-compact/0.1", "Range": "bytes=0-0"}, timeout=(8, 12), allow_redirects=True, stream=True)
        ok = (200 <= rg.status_code < 400) or rg.status_code == 206
        if ok:
            ct = (rg.headers.get('content-type','') or '').lower()
            rg.close()
            return ('pdf' in ct) or url.lower().endswith('.pdf')
        rg.close()
    except Exception:
        pass
    return False


PDF_PAGE_HINT_RE = re.compile(r"verkiez|uitslag|proces|verbaal|stembur|tweede.*kamer|tweede-?kamerverkiez|document|download|n10|na\s*31", re.I)
OVERVIEW_HINT_RE = re.compile(r"overzicht|proces[-\s]?verbaal|processen[-\s]?verbaal|kies\s+stembureau|stadsdeel|hoofdstembureau|gemeentelijk\s+stembureau|pv\s*overzicht|stemmings|uitslag\s*per\s*stembureau", re.I)


def simple_extract_pdf_links(html: str, base_url: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    s = BeautifulSoup(html or "", "html.parser")
    for a in s.select("a[href]"):
        href = a.get("href") or ""
        full_url = urljoin(base_url, href)
        # Unwrap common docReader wrappers: ...docreader?url=<pdf>
        if 'docreader' in href.lower() and 'url=' in href.lower():
            try:
                from urllib.parse import parse_qs
                qs = parse_qs(urlparse(full_url).query)
                url_param = qs.get('url') or qs.get('doc') or []
                if url_param:
                    full_url = urljoin(base_url, url_param[0])
            except Exception:
                pass
        path_lower = (urlparse(full_url).path or '').lower()
        txt = a.get_text(" ", strip=True) or ""
        hint = (txt + " " + (a.get('title') or '') + " " + (a.get('aria-label') or '') + " " + href).lower()
        # Accepteer directe .pdf links, CMS file-endpoints en download-routes, of links met duidelijke PDF-indicatoren
        looks_like_pdf = (
            (".pdf" in path_lower)
            or ("/file/" in path_lower)
            or ("/download" in path_lower)
            or ("dsresource" in full_url.lower())
            or ("type=pdf" in full_url.lower())
            or ("pdf" in hint)
            or ("proces" in hint and "verbaal" in hint)
        )
        if not looks_like_pdf:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        # txt staat al klaar boven
        name = os.path.basename(urlparse(full_url).path) or "document.pdf"
        base_no_ext = os.path.splitext(name)[0].lower()
        if (base_no_ext in {"dsresource", "download", "document", "file"}) or (not name.lower().endswith('.pdf')):
            if txt:
                # Use link text as filename when endpoint is generic
                t = txt.strip()
                name = t if t.lower().endswith('.pdf') else f"{t}.pdf"
        if not _is_current_year_pdf(name + " " + txt + " " + full_url):
            continue
        out.append({
            "remote_url": full_url,
            "local_url": None,
            "pdf_name": name,
            "text": txt,
            "from": base_url,
            "score": 1,
        })
    return out


def _root_domain(u: str) -> str:
    try:
        host = urlparse(u).netloc.split(":")[0].lower()
        parts = host.split('.')
        if len(parts) >= 2:
            return '.'.join(parts[-2:])
        return host
    except Exception:
        return ''


def _same_registrable_domain(a: str, b: str) -> bool:
    ra = _root_domain(a)
    rb = _root_domain(b)
    return bool(ra and rb and ra == rb)


def find_overview_pages_from_html(html: str, base_url: str) -> list[str]:
    """Zoek links naar PV-overzichtspagina's in de HTML."""
    s = BeautifulSoup(html or "", "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for a in s.select('a[href]'):
        href = a.get('href') or ''
        full = urljoin(base_url, href)
        low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
        if OVERVIEW_HINT_RE.search(low):
            if full not in seen:
                seen.add(full); out.append(full)
    return out[:6]


def discover_via_sitemap(start_url: str, max_pages: int = 30) -> list[str]:
    """Lightweight sitemap discovery for election-related pages on the same host."""
    try:
        pu = urlparse(start_url)
        base = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    robots = f"{base}/robots.txt"
    sitemap_urls: list[str] = []
    try:
        r = http_get(robots, timeout=(6, 10))
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
            rr = http_get(url, timeout=(6, 12))
        except Exception:
            return
        try:
            soup = BeautifulSoup(rr.text, "xml")
        except Exception:
            soup = BeautifulSoup(rr.text, "html.parser")
        for loc in soup.select("sitemap > loc"):
            u = (loc.get_text(strip=True) or "").strip()
            if u:
                parse_sm(u, depth + 1)
                if len(found_pages) >= max_pages:
                    return
        for loc in soup.select("url > loc"):
            u = (loc.get_text(strip=True) or "").strip()
            if not u:
                continue
            try:
                if urlparse(u).netloc != pu.netloc:
                    continue
            except Exception:
                continue
            if KEY_RE.search(u):
                found_pages.append(u)
            if len(found_pages) >= max_pages:
                return

    for sm in sitemap_urls[:3]:
        parse_sm(sm, 0)
        if len(found_pages) >= max_pages:
            break
    # dedup + cap
    out: list[str] = []
    seen: set[str] = set()
    for u in found_pages:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:max_pages]


def probe_well_known_pages(start_url: str) -> list[str]:
    """Lightweight probe of a handful of common pages many municipalities use.
    Keeps things compact: no recursion, just a small fixed set under the same host.
    """
    try:
        pu = urlparse(start_url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    candidates = [
        "/verkiezingen",
        "/tweede-kamerverkiezingen",
        "/tweede-kamerverkiezing",
        "/verkiezingsuitslag",
        "/uitslagen",
        "/uitkomsten",
        "/documenten",
        "/bestanden",
        "/downloads",
        "/zo-is-er-gestemd",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        u = origin.rstrip("/") + path
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:10]


def probe_fileadmin_paths(start_url: str) -> list[str]:
    """Try a few common 'fileadmin' folder paths used by TYPO3/other CMSes to host PDFs.
    This is a compact heuristic and only hits a handful of URLs.
    """
    try:
        pu = urlparse(start_url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    paths = [
        "/fileadmin/Verkiezingen/Tweede_Kamerverkiezing_2025/",
        "/fileadmin/Verkiezingen/Tweede_Kamerverkiezing_2025/Stembureaus/",
        "/fileadmin/verkiezingen/Tweede_Kamerverkiezing_2025/",
        "/fileadmin/verkiezingen/Tweede_Kamerverkiezing_2025/Stembureaus/",
    ]
    out = []
    seen = set()
    for p in paths:
        u = origin.rstrip('/') + p
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def probe_numbered_pvs_under_fileadmin(start_url: str, stem: str = "Procesverbaal_stembureau_", max_n: int = 60) -> list[str]:
    """Last-resort compact probe for municipalities that host PVs under a predictable fileadmin path with numbered files.
    Tries a small bounded range and returns existing URLs.
    """
    try:
        pu = urlparse(start_url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    bases = [
        f"{origin}/fileadmin/Verkiezingen/Tweede_Kamerverkiezing_2025/Stembureaus/{stem}",
        f"{origin}/fileadmin/verkiezingen/Tweede_Kamerverkiezing_2025/Stembureaus/{stem}",
    ]
    found: list[str] = []
    for base in bases:
        hit = 0
        for i in range(1, max_n+1):
            url = f"{base}{i}.pdf"
            if _probe_pdf_exists(url):
                found.append(url)
                hit += 1
        # break early if we found a decent number
        if hit >= 5:
            break
    # dedup
    seen=set(); out=[]
    for u in found:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out


def download_pv_overview_page(muni: str, overview_url: str, max_items: int = 300) -> list[dict]:
    """Playwright: download PVs uit een overzichtspagina met dynamische selects of directe anchors."""
    items: list[dict] = []
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    if not PLAYWRIGHT_AVAILABLE:
        # Probeer statisch te parsen als fallback
        try:
            r = http_get(overview_url, timeout=(10, 25))
            eps = simple_extract_pdf_links(r.text, r.url)
            for e in eps:
                dest = stream_download(e.get('remote_url'), out_dir)
                if dest:
                    e['local_url'] = 'file://' + os.path.abspath(dest)
                    items.append(e)
        except Exception:
            pass
        return items
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        try:
            page.goto(overview_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            # 1) Directe anchors op de pagina
            html = page.content()
            direct = simple_extract_pdf_links(html, page.url)
            for e in direct:
                u = e.get('remote_url')
                if not u: continue
                dest = stream_download(u, out_dir, e.get('pdf_name') or e.get('text'))
                if dest:
                    e['local_url'] = 'file://' + os.path.abspath(dest)
                    items.append(e)
                    if len(items) >= max_items:
                        break
            # 2) Selects doorlopen (indien aanwezig)
            if len(items) < max_items:
                selects = page.locator('select')
                scnt = selects.count()
                for si in range(scnt):
                    sel = selects.nth(si)
                    options = sel.locator('option')
                    ocnt = options.count()
                    for oi in range(ocnt):
                        try:
                            val = options.nth(oi).get_attribute('value') or ''
                            lab = (options.nth(oi).inner_text() or '').strip()
                        except Exception:
                            continue
                        if not val:
                            continue
                        # Als de option direct naar PDF verwijst
                        if val.lower().endswith('.pdf'):
                            full_url = urljoin(page.url, val)
                            if not _is_current_year_pdf(full_url + ' ' + lab):
                                continue
                            dest = stream_download(full_url, out_dir, lab)
                            if dest:
                                items.append({'remote_url': full_url, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': os.path.basename(dest), 'text': lab or os.path.basename(dest), 'from': overview_url, 'score': 2})
                                if len(items) >= max_items:
                                    break
                            continue
                        # Anders: selecteer en parseer anchors opnieuw
                        try:
                            sel.select_option(val)
                            page.wait_for_timeout(600)
                            html2 = page.content()
                            eps = simple_extract_pdf_links(html2, page.url)
                            for e in eps:
                                u = e.get('remote_url');
                                if not u: continue
                                if any(it.get('remote_url') == u for it in items):
                                    continue
                                dest = stream_download(u, out_dir, e.get('pdf_name') or e.get('text'))
                                if dest:
                                    e['local_url'] = 'file://' + os.path.abspath(dest)
                                    items.append(e)
                                    if len(items) >= max_items:
                                        break
                        except Exception:
                            continue
                    if len(items) >= max_items:
                        break
        finally:
            ctx.close(); b.close()
    return items


def collect_pdfs_bfs_internal(name: str, max_depth: int = 2, max_pages: int = 40, force_render: bool = True) -> list[dict]:
    """Compact BFS over internal pages to find PDFs using our heuristics.
    Stays on the same host; visits up to max_pages; depth-limited.
    """
    start = get_start_url(name)
    if not start:
        return []
    try:
        pu = urlparse(start)
        origin_host = pu.netloc
    except Exception:
        return []
    KEY_RE = re.compile(r"verkiez|uitslag|voorlopige|gestemd|proces|verbaal|stembur|tweede.*kamer|pv\b|n10|na\s*31|na31|model|document|download", re.I)
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]
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
        s = BeautifulSoup(html, 'html.parser')
        try:
            pb = urlparse(base)
            same_host = pb.netloc
        except Exception:
            same_host = origin_host
        for a in s.select('a[href]'):
            href = a.get('href') or ''
            full = urljoin(base, href)
            try:
                uu = urlparse(full)
            except Exception:
                continue
            if not uu.netloc or uu.netloc != origin_host:
                continue
            if (uu.path or '').lower().endswith('.pdf'):
                continue
            low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
            if KEY_RE.search(low):
                queue.append((full, d + 1))
    # extract PDFs from collected pages
    out: list[dict] = []
    seen: set[str] = set()
    for p in pages:
        try:
            r = http_get(p, timeout=(10, 20))
        except Exception:
            continue
        eps = simple_extract_pdf_links(r.text, r.url)
        for e in eps:
            u = e.get('remote_url')
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(e)
    return out


PV_STRONG_HINT_RE = re.compile(r"stembur|proces|verbaal|\bpv\b|\bn10\b|na\s*31|na31|uitkomst|verklaring", re.I)


def is_probably_complete(pdfs: list[dict]) -> bool:
    if not pdfs:
        return False
    n = len(pdfs)
    if n >= 40:
        return True
    strong = 0
    for p in pdfs:
        s = " ".join([str(p.get("pdf_name") or ""), str(p.get("text") or ""), str(p.get("from") or "")])
        if PV_STRONG_HINT_RE.search(s):
            strong += 1
    if strong >= 12:
        return True
    try:
        from collections import Counter
        from_pages = Counter([p.get("from") or "" for p in pdfs])
        # Als één bronpagina ≥5 PDF's oplevert, beschouwen we het als 'plek gevonden'
        if from_pages and max(from_pages.values()) >= 5:
            return True
    except Exception:
        pass
    return False


def dedup_by_remote(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for p in items:
        u = p.get("remote_url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(p)
    return out


def enumerate_numbered_siblings(seed_url: str, max_n: int = 80) -> list[str]:
    """If seed looks like ..._1.pdf (or ...-1.pdf), probe siblings ..._2.pdf, ..._3.pdf, ... up to max_n.
    Uses HEAD to avoid full downloads. Returns list of existing remote URLs (excluding the seed).
    """
    try:
        from urllib.parse import urlparse
        pu = urlparse(seed_url)
        path = pu.path or ''
        base = seed_url[: seed_url.find(path)]
    except Exception:
        path = ''
        base = ''
    import re as _re
    m = _re.search(r"^(.*?)([\-_])(\d{1,3})(\.pdf)(?:$|\?)", path, _re.I)
    if not m:
        # alternate: digits without delimiter before .pdf
        m = _re.search(r"^(.*?)(\d{1,3})(\.pdf)(?:$|\?)", path, _re.I)
        delim = ''
    else:
        delim = m.group(2)
    if not m:
        return []
    prefix = m.group(1)
    num = int(_re.sub(r"\D", "", m.group(3) if len(m.groups()) >= 3 else '1')) if m else 1
    suffix = m.group(4)
    dirpath = path[: path.rfind('/')+1] if '/' in path else '/'
    out: list[str] = []
    # probe upwards and downwards around num
    seen = set()
    for i in range(1, max_n+1):
        if i == num:
            continue
        cand_path = f"{dirpath}{prefix}{delim if delim else ''}{i}{suffix}"
        cand_url = f"{base}{cand_path}"
        if cand_url in seen:
            continue
        seen.add(cand_url)
        if _probe_pdf_exists(cand_url):
            out.append(cand_url)
    return out


def stream_download(url: str, out_dir: str, suggested_name: str | None = None) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    try:
        # Pleio mapping: convert '/files/view/<guid>/*' to direct '/file/download/<guid>'
        try:
            pu = urlparse(url)
            if pu.netloc and pu.netloc.endswith('pleio.nl') and '/files/view/' in (pu.path or ''):
                import re as _re
                m = _re.search(r"/files/view/([0-9a-f\-]+)/", pu.path, re.I)
                if m:
                    url = f"{pu.scheme}://{pu.netloc}/file/download/{m.group(1)}"
        except Exception:
            pass
        with requests.get(url, headers={"User-Agent": "restzetels-compact/0.1"}, timeout=(15, 180), stream=True) as r:
            r.raise_for_status()
            ct = (r.headers.get("Content-Type") or "").lower()
            if ("pdf" not in ct) and (not urlparse(url).path.lower().endswith(".pdf")):
                return None
            # probeer bestandsnaam via Content-Disposition
            cd = r.headers.get('Content-Disposition') or r.headers.get('content-disposition') or ''
            name = None
            try:
                _disp, params = cgi.parse_header(cd)
                name = params.get('filename') or params.get('filename*')
            except Exception:
                name = None
            # fallback to suggested name when header is missing or unhelpful
            generic_names = {"dsresource", "download", "document", "file"}
            if not name or (os.path.splitext(name)[0].lower() in generic_names):
                if suggested_name:
                    name = suggested_name
                else:
                    name = os.path.basename(urlparse(url).path) or "document.pdf"
                    # If still generic (e.g., 'dsresource'), try to derive from query params
                    base_no_ext = os.path.splitext(name)[0].lower()
                    if base_no_ext in generic_names:
                        try:
                            from urllib.parse import parse_qs
                            qs = parse_qs(urlparse(url).query or "")
                            oid = (qs.get('objectid') or qs.get('id') or qs.get('obj') or [None])[0]
                            if oid:
                                name = f"{oid}.pdf"
                        except Exception:
                            pass
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            dest = os.path.join(out_dir, sanitize_filename(name))
            if os.path.exists(dest):
                return dest
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1024 * 512):
                    if not chunk:
                        continue
                    f.write(chunk)
            return dest
    except Exception:
        return None


# -------- Playwright helpers --------

def fetch_html(url: str, allow_render: bool = False) -> Tuple[str | None, str | None]:
    try:
        r = http_get(url)
        if r.status_code == 200:
            return r.text, r.url
    except Exception:
        pass
    if allow_render:
        if not PLAYWRIGHT_AVAILABLE:
            return None, None
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                ctx = b.new_context()
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=60000)
                except Exception:
                    pass
                html = page.content(); final = page.url
                ctx.close(); b.close()
            return html, final
        except Exception:
            return None, None
    return None, None


# -------- MijnStembureau --------

def is_mijnstembureau_url(u: str) -> bool:
    try:
        pu = urlparse(u)
        return ("mijnstembureau" in (pu.netloc or "")) and ("/uitslagen/verkiezingen/tk/" in (pu.path or ""))
    except Exception:
        return False

def guess_mijnstembureau_url(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", (name or '').lower().strip())
    slug = re.sub(r"-+", "-", slug).strip('-')
    return f"https://mijnstembureau-{slug}.nl/uitslagen/verkiezingen/tk/download-opties"


def collect_mijnstembureau_pages(name: str) -> list[str]:
    start = get_start_url(name)
    if not start:
        return []
    html, base = fetch_html(start, allow_render=False)
    # Als de startpagina niet goed laadt (403/404/500 of JS-render), probeer rendering
    if not html:
        html, base = fetch_html(start, allow_render=True)
    if not html:
        return []
    s = BeautifulSoup(html, 'html.parser')
    out = []
    for a in s.select('a[href]'):
        href = a.get('href') or ''
        full = urljoin(base, href)
        if is_mijnstembureau_url(full):
            out.append(full)
    # beperkte fallback: één klik dieper op relevante links
    if not out:
        for a in s.select('a[href]'):
            href = a.get('href') or ''
            full = urljoin(base, href)
            if not PDF_PAGE_HINT_RE.search((a.get_text(' ', strip=True) or '') + ' ' + full):
                continue
            h2, b2 = fetch_html(full, allow_render=False)
            if not h2:
                continue
            ss = BeautifulSoup(h2, 'html.parser')
            for aa in ss.select('a[href]'):
                f2 = urljoin(b2, aa.get('href') or '')
                if is_mijnstembureau_url(f2):
                    out.append(f2)
                    break
            if out:
                break
    # dedup
    seen = set(); ded = []
    for u in out:
        if u in seen: continue
        seen.add(u); ded.append(u)
    return ded[:2]


# -------- Pleio (enumerate then HTTP download) --------

def find_pleio_hubs_from_html(html: str, base_url: str) -> list[str]:
    hubs: list[str] = []
    s = BeautifulSoup(html or '', 'html.parser')
    for a in s.select('a[href]'):
        href = a.get('href') or ''
        full = urljoin(base_url, href)
        try:
            u = urlparse(full)
            if u.netloc and 'pleio.nl' in u.netloc and ('/groups/view/' in (u.path or '') or '/files/' in (u.path or '')):
                hubs.append(full)
        except Exception:
            pass
    # dedup
    out=[]; seen=set()
    for u in hubs:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out[:6]


def pleio_enumerate_view_links(hub_url: str, headful: bool = False, max_links: int = 400) -> list[str]:
    if not PLAYWRIGHT_AVAILABLE:
        return []
    links: list[str] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=(not headful))
            ctx = b.new_context(user_agent='Mozilla/5.0', viewport={'width':1280,'height':900}, locale='nl-NL')
            page = ctx.new_page()
            page.goto(hub_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            # First try: direct view anchors on hub
            try:
                page.wait_for_selector("a[href*='/files/view/']", timeout=10000)
            except Exception:
                pass
            try:
                loc = page.locator("a[href*='/files/view/']")
                cnt = loc.count()
                for i in range(min(cnt, max_links)):
                    href = loc.nth(i).get_attribute('href') or ''
                    if '/files/view/' in href:
                        links.append(urljoin(page.url, href))
            except Exception:
                pass
            # If none: click tiles by text and/or Files tab
            if not links:
                for sel in [
                    'a:has-text("Gescande processen-verbaal stembureaus")',
                    'a:has-text("Gescande processen-verbaal gemeentelijk stembureau")',
                    'a:has-text("Gescande processen-verbaal")',
                    'a:has-text("processen-verbaal")',
                    'a:has-text("Bestanden")',
                ]:
                    try:
                        loc2 = page.locator(sel)
                        if loc2.count()==0: continue
                        with page.expect_navigation(timeout=20000):
                            loc2.first.click()
                        try:
                            page.wait_for_load_state('networkidle', timeout=8000)
                        except Exception:
                            pass
                        try:
                            page.wait_for_selector("a[href*='/files/view/']", timeout=10000)
                        except Exception:
                            pass
                        try:
                            loc3 = page.locator("a[href*='/files/view/']")
                            cnt3 = loc3.count()
                            for i in range(min(cnt3, max_links)):
                                href = loc3.nth(i).get_attribute('href') or ''
                                if '/files/view/' in href:
                                    links.append(urljoin(page.url, href))
                        except Exception:
                            pass
                        # Try Files tab
                        files_tab = page.locator('a[href$="/files"], a:has-text("Bestanden")')
                        if files_tab.count()>0:
                            try:
                                with page.expect_navigation(timeout=15000):
                                    files_tab.first.click()
                                page.wait_for_timeout(600)
                                try:
                                    loc4 = page.locator("a[href*='/files/view/']")
                                    cnt4 = loc4.count()
                                    for i in range(min(cnt4, max_links)):
                                        href = loc4.nth(i).get_attribute('href') or ''
                                        if '/files/view/' in href:
                                            links.append(urljoin(page.url, href))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        # back to hub
                        page.goto(hub_url, wait_until='domcontentloaded', timeout=15000)
                        page.wait_for_timeout(300)
                    except Exception:
                        continue
            ctx.close(); b.close()
    except Exception:
        return []
    # dedup
    out=[]; seen=set()
    for u in links:
        if u in seen: continue
        seen.add(u); out.append(u)
        if len(out)>=max_links: break
    return out


def download_mijnstembureau_portal(muni: str, page_url: str, max_items: int = 200) -> list[dict]:
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright vereist voor mijnstembureau portalen")
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    items: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto(page_url, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=60000)
        except Exception:
            pass
        # open PV sectie
        pv = page.locator('button:has-text("Processen verbaal")')
        if pv.count() > 0:
            pv.first.click(); page.wait_for_timeout(700)
        btns = page.locator('main button')
        n = btns.count(); processed = 0
        for i in range(n):
            if processed >= max_items:
                break
            try:
                label = (btns.nth(i).inner_text() or '').strip()
            except Exception:
                continue
            if not label or not label.lower().endswith('.pdf'):
                continue
            if not _is_current_year_pdf(label):
                continue
            dest = os.path.join(out_dir, sanitize_filename(label))
            if os.path.exists(dest):
                continue
            def pred(resp):
                try:
                    return ('/uitslagen/api/view-pv/' in resp.url) and (resp.status == 200) and ('application/pdf' in (resp.headers or {}).get('content-type','').lower())
                except Exception:
                    return False
            try:
                with page.expect_response(pred, timeout=60000) as respctx:
                    btns.nth(i).click()
                resp = respctx.value
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
                continue
        ctx.close(); b.close()
    return items


# -------- MediaFiler --------

def find_mediafiler_albums_from_html(html: str, base_url: str) -> list[str]:
    s = BeautifulSoup(html or '', 'html.parser')
    out = []
    for a in s.select('a[href]'):
        href = a.get('href') or ''
        full = urljoin(base_url, href)
        try:
            u = urlparse(full)
            if 'mediafiler.net' in (u.netloc or '') and '/start/' in (u.path or ''):
                out.append(full)
        except Exception:
            pass
    seen = set(); ded = []
    for u in out:
        if u in seen: continue
        seen.add(u); ded.append(u)
    return ded[:3]


def parse_mediafiler_album_for_items(album_url: str) -> list[dict]:
    try:
        r = http_get(album_url)
    except Exception:
        return []
    html = r.text
    items: list[dict] = []
    for m in re.finditer(r"downloadTab\('(\d+)'\s*,\s*&quot;([^&]+?\.pdf)&quot;\)", html):
        items.append({'fuid': m.group(1), 'filename': m.group(2), 'album_url': r.url})
    for m in re.finditer(r"downloadTab\('(\d+)'\s*,\s*'([^']+?\.pdf)'\)", html):
        items.append({'fuid': m.group(1), 'filename': m.group(2), 'album_url': r.url})
    seen = set(); ded = []
    for it in items:
        f = it.get('fuid')
        if f in seen: continue
        seen.add(f); ded.append(it)
    return ded


def download_mediafiler_album(muni: str, album_url: str, items: list[dict]) -> int:
    if not PLAYWRIGHT_AVAILABLE:
        return 0
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    saved = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.goto(album_url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(1000)
        for it in items:
            fn = it.get('filename') or ''
            if not _is_current_year_pdf(fn):
                continue
            dest = os.path.join(out_dir, sanitize_filename(fn))
            if os.path.exists(dest):
                continue
            fuid = it.get('fuid')
            try:
                with page.expect_download(timeout=45000) as dlctx:
                    page.evaluate("(args)=>downloadTab(args[0], args[1])", [fuid, fn])
                dl = dlctx.value
                dl.save_as(dest)
                saved += 1
            except Exception:
                continue
        ctx.close(); b.close()
    return saved


# -------- Stackstorage --------

def is_stackstorage_share(u: str) -> bool:
    try:
        pu = urlparse(u)
        return ('stackstorage.com' in (pu.netloc or '')) and ('/s/' in (pu.path or ''))
    except Exception:
        return False


def download_stackstorage_share(muni: str, share_url: str) -> list[dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return []
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    items: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.goto(share_url, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=60000)
        except Exception:
            pass
        # Probeer 'Download all'
        try:
            btn = page.locator('a:has-text("Download all")')
            if btn.count() > 0:
                with page.expect_download(timeout=60000) as dlctx:
                    btn.first.click()
                dl = dlctx.value
                # Sla zip op tmp en pak PDF’s uit
                import tempfile, zipfile
                fd, tmp = tempfile.mkstemp(); os.close(fd)
                dl.save_as(tmp)
                try:
                    with zipfile.ZipFile(tmp) as z:
                        for nm in z.namelist():
                            if not nm.lower().endswith('.pdf'): continue
                            base = os.path.basename(nm)
                            if not _is_current_year_pdf(base): continue
                            dest = os.path.join(out_dir, sanitize_filename(base))
                            if os.path.exists(dest): continue
                            with z.open(nm) as src, open(dest,'wb') as f:
                                f.write(src.read())
                            items.append({'remote_url': share_url, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': base, 'text': base, 'from': share_url, 'score': 0})
                finally:
                    try: os.remove(tmp)
                    except Exception: pass
        except Exception:
            pass
        # Verval: individuele anchors met download
        anchors = page.locator('a[download], a:has-text("Download")')
        for i in range(anchors.count()):
            try:
                with page.expect_download(timeout=45000) as dlctx:
                    anchors.nth(i).click()
                dl = dlctx.value
                fname = dl.suggested_filename or 'download.pdf'
                if not fname.lower().endswith('.pdf'): fname += '.pdf'
                if not _is_current_year_pdf(fname): continue
                dest = os.path.join(out_dir, sanitize_filename(fname))
                if os.path.exists(dest): continue
                dl.save_as(dest)
                items.append({'remote_url': share_url, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': fname, 'text': fname, 'from': share_url, 'score': 0})
            except Exception:
                pass
        ctx.close(); b.close()
    return items


# -------- Google Drive --------

_DRIVE_FILE_RE = re.compile(r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]{10,})/", re.I)
_DRIVE_FOLDER_RE = re.compile(r"https?://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]{10,})", re.I)


def is_gdrive_file(u: str) -> str | None:
    m = _DRIVE_FILE_RE.search(u or '')
    return m.group(1) if m else None


def is_gdrive_folder(u: str) -> str | None:
    m = _DRIVE_FOLDER_RE.search(u or '')
    return m.group(1) if m else None


def download_gdrive_file(muni: str, file_id: str, referer_url: str | None = None) -> dict | None:
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)
    uc = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        headers = {"User-Agent": "restzetels-compact/0.1"}
        if referer_url:
            headers["Referer"] = referer_url
        with requests.get(uc, headers=headers, timeout=(15, 180), stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            ct = (r.headers.get("Content-Type") or "").lower()
            if ("pdf" not in ct) and ("application/octet-stream" not in ct):
                return None
            # filename from Content-Disposition if present
            cd = r.headers.get('Content-Disposition') or r.headers.get('content-disposition') or ''
            name = None
            try:
                import cgi as _cgi
                _disp, params = _cgi.parse_header(cd)
                name = params.get('filename') or params.get('filename*')
            except Exception:
                name = None
            if not name:
                name = f"drive_{file_id}.pdf"
            if not name.lower().endswith('.pdf'):
                name += '.pdf'
            dest = os.path.join(out_dir, sanitize_filename(name))
            if os.path.exists(dest):
                return {
                    'remote_url': uc,
                    'local_url': 'file://' + os.path.abspath(dest),
                    'pdf_name': os.path.basename(dest),
                    'text': name,
                    'from': referer_url or uc,
                    'score': 2,
                }
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(1024 * 512):
                    if not chunk:
                        continue
                    f.write(chunk)
            return {
                'remote_url': uc,
                'local_url': 'file://' + os.path.abspath(dest),
                'pdf_name': os.path.basename(dest),
                'text': name,
                'from': referer_url or uc,
                'score': 2,
            }
    except Exception:
        return None


def download_gdrive_folder(muni: str, folder_url: str, max_items: int = 200) -> list[dict]:
    items: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto(folder_url, wait_until='domcontentloaded', timeout=90000)
        try:
            page.wait_for_load_state('networkidle', timeout=90000)
        except Exception:
            pass
        # Use internal Drive variable to list files
        js = None
        try:
            js = page.evaluate('() => (window._DRIVE_ivd || null)')
        except Exception:
            js = None
        if js:
            try:
                import json as _json
                data = _json.loads(js)
                for row in (data[0] if isinstance(data, list) and data else []):
                    if not isinstance(row, list) or not row:
                        continue
                    file_id = row[0]
                    name = (row[2] if len(row) > 2 else '') or ''
                    mime = (row[3] if len(row) > 3 else '') or ''
                    if 'pdf' not in (mime or '').lower() and not name.lower().endswith('.pdf'):
                        continue
                    di = download_gdrive_file(muni, file_id, referer_url=folder_url)
                    if di:
                        items.append(di)
                        if len(items) >= max_items:
                            break
            except Exception:
                pass
        ctx.close(); b.close()
    return items


def scrape_one(name: str, max_http: int | None = None) -> list[dict]:
    out_dir = os.path.join(OUT_BASE, sanitize_filename(name))
    found: list[dict] = []
    start = get_start_url(name)
    if not start:
        return []
    # 1) startpagina: parseer anchors, volg alleen gevonden links (geen speculative slugs)
    html, base = fetch_html(start, allow_render=False)
    found_place = False
    if html:
        s = BeautifulSoup(html, 'html.parser')
        # verzamel PDF’s direct uit start
        start_eps = simple_extract_pdf_links(html, base)
        # Als geen directe anchors maar de bron hint op embedded resources (dsresource/type=pdf), render 1x en herhaal
        if (not start_eps) and (('dsresource' in html.lower()) or ('type=pdf' in html.lower())):
            h0, b0 = fetch_html(start, allow_render=True)
            if h0:
                start_eps = simple_extract_pdf_links(h0, b0)
                # laatste redmiddel: pak dsresource URLs direct uit HTML als anchors ontbreken
                if not start_eps:
                    try:
                        import re as _re
                        ds = []
                        for m in _re.finditer(r'(?:href|data-href|data-url)="([^"]*dsresource[^"\s]+)"', h0, _re.I):
                            ds.append(urljoin(b0, m.group(1)))
                        seen=set()
                        for u in ds:
                            if u in seen: continue
                            seen.add(u)
                            name = os.path.basename(urlparse(u).path) or 'document.pdf'
                            if _is_current_year_pdf(name + ' ' + u):
                                start_eps.append({'remote_url': u, 'local_url': None, 'pdf_name': name, 'text': name, 'from': b0, 'score': 1})
                    except Exception:
                        pass
        found.extend(start_eps)
        # Als op de startpagina al ≥5 relevante PDF's staan, markeer als 'plek gevonden'
        if len(start_eps) >= 5 or sum(1 for p in start_eps if PV_STRONG_HINT_RE.search((p.get('text') or '') + ' ' + (p.get('pdf_name') or ''))) >= 4:
            found_place = True
        # 1a) PV-overzichtspagina's vanaf de startpagina
        try:
            ov_pages = find_overview_pages_from_html(html, base)
        except Exception:
            ov_pages = []
        for ov in ov_pages[:3]:
            try:
                its = download_pv_overview_page(name, ov)
                if its:
                    found.extend(its)
                    # Alleen vroegtijdig stoppen als het waarschijnlijk compleet is
                    if is_probably_complete(found) or len(found) >= 20:
                        return dedup_by_remote(found)
            except Exception:
                continue

        # 1a.1) Compact probe van veelgebruikte paden onder dezelfde host
        if (len(found) < 5) and (not found_place):
            for u in probe_well_known_pages(start)[:8]:
                try:
                    hP, bP = fetch_html(u, allow_render=False)
                    if not hP:
                        hP, bP = fetch_html(u, allow_render=True)
                    if not hP:
                        continue
                    # Kijk of deze pagina zelf een overzicht is
                    try:
                        ovP = find_overview_pages_from_html(hP, bP)
                    except Exception:
                        ovP = []
                    used_ovP = False
                    for ov in ovP[:2]:
                        try:
                            its = download_pv_overview_page(name, ov)
                            if its:
                                found.extend(its)
                                found_place = True
                                used_ovP = True
                                break
                        except Exception:
                            continue
                    if used_ovP:
                        break
                    # Directe PDF-anchors
                    epsP = simple_extract_pdf_links(hP, bP)
                    # als deze pagina embedded dsresource/type=pdf heeft, scan die ook
                    if (not epsP) and (('dsresource' in (hP or '').lower()) or ('type=pdf' in (hP or '').lower())):
                        try:
                            import re as _re
                            ds = []
                            for m in _re.finditer(r'(?:href|data-href|data-url)="([^"\s]*dsresource[^"\s]+)"', hP, _re.I):
                                ds.append(urljoin(bP, m.group(1)))
                            seen_local = set()
                            for du in ds:
                                if du in seen_local:
                                    continue
                                seen_local.add(du)
                                nm = os.path.basename(urlparse(du).path) or 'document.pdf'
                                if _is_current_year_pdf(nm + ' ' + du):
                                    epsP.append({'remote_url': du, 'local_url': None, 'pdf_name': nm, 'text': nm, 'from': bP, 'score': 1})
                        except Exception:
                            pass
                    if epsP:
                        found.extend(epsP)
                        if len(epsP) >= 5 or sum(1 for p in epsP if PV_STRONG_HINT_RE.search((p.get('text') or '') + ' ' + (p.get('pdf_name') or ''))) >= 4:
                            found_place = True
                            break
                    if is_probably_complete(found):
                        break
                except Exception:
                    continue

        # 1a.1b) Als we een 'Procesverbaal_stembureau_#.pdf' seed hebben, probeer siblings te enumereren
        if (len(found) < 5) and (not found_place):
            seed = next((p for p in found if isinstance(p.get('remote_url'), str) and 'stembureau' in p.get('remote_url').lower() and p.get('remote_url').lower().endswith('.pdf')), None)
            if seed:
                try:
                    from urllib.parse import urlparse
                except Exception:
                    pass
                sibs = enumerate_numbered_siblings(seed.get('remote_url'), max_n=120)
                for u in sibs:
                    try:
                        nm = os.path.basename(urlparse(u).path)
                    except Exception:
                        nm = 'document.pdf'
                    found.append({'remote_url': u, 'local_url': None, 'pdf_name': nm or 'document.pdf', 'text': nm or 'document.pdf', 'from': u, 'score': 1})
                if len(sibs) >= 5:
                    found_place = True

        # 1a.2) Fileadmin-folder probe (compact, beperkt aantal paden)
        if (len(found) < 5) and (not found_place):
            for u in probe_fileadmin_paths(start):
                try:
                    r = http_get(u, timeout=(8, 15))
                except Exception:
                    continue
                eps = simple_extract_pdf_links(r.text, r.url)
                if eps:
                    found.extend(eps)
                    if len(eps) >= 5 or sum(1 for p in eps if PV_STRONG_HINT_RE.search((p.get('text') or '') + ' ' + (p.get('pdf_name') or ''))) >= 4:
                        found_place = True
                        break
                if is_probably_complete(found):
                    break

        # 1a.2b) Predictable fileadmin numbered files (Procesverbaal_stembureau_#.pdf)
        if (len(found) < 5) and (not found_place):
            num_urls = probe_numbered_pvs_under_fileadmin(start, stem="Procesverbaal_stembureau_", max_n=80)
            if num_urls:
                try:
                    from urllib.parse import urlparse
                except Exception:
                    pass
                for u in num_urls:
                    try:
                        nm = os.path.basename(urlparse(u).path)
                    except Exception:
                        nm = 'document.pdf'
                    found.append({'remote_url': u, 'local_url': None, 'pdf_name': nm or 'document.pdf', 'text': nm or 'document.pdf', 'from': u, 'score': 1})
                if len(num_urls) >= 5:
                    found_place = True

        # 1b) Verzamel Pleio hubs en enumerate view-links (download later via HTTP)
        try:
            pleio_hubs = find_pleio_hubs_from_html(html, base)
        except Exception:
            pleio_hubs = []
        # If start URL itself is a Pleio hub, include it
        try:
            pu = urlparse(start)
            if pu.netloc and 'pleio.nl' in pu.netloc:
                pleio_hubs.insert(0, start)
        except Exception:
            pass
        pleio_items: list[dict] = []
        for hub in pleio_hubs[:4]:
            try:
                views = pleio_enumerate_view_links(hub)
                for v in views:
                    try:
                        nm = os.path.basename(urlparse(v).path) or 'document.pdf'
                    except Exception:
                        nm = 'document.pdf'
                    if not nm.lower().endswith('.pdf'):
                        nm += '.pdf'
                    pleio_items.append({'remote_url': v, 'local_url': None, 'pdf_name': nm, 'text': 'Pleio', 'from': hub, 'score': 3})
            except Exception:
                continue
        if pleio_items:
            found.extend(pleio_items)
            if is_probably_complete(found):
                return dedup_by_remote(found)

        # 1c) verzamel relevante interne pagina’s uit anchors
        candidates = []
        for a in s.select('a[href]'):
            href = a.get('href') or ''
            full = urljoin(base, href)
            # portals
            # Google Drive direct file
            try:
                _gfid = is_gdrive_file(full)
            except Exception:
                _gfid = None
            if _gfid:
                try:
                    di = download_gdrive_file(name, _gfid, referer_url=full)
                    if di:
                        found.append(di)
                        if is_probably_complete(found):
                            return dedup_by_remote(found)
                except Exception:
                    pass
                continue
            # Google Drive folder
            try:
                _gff = is_gdrive_folder(full)
            except Exception:
                _gff = None
            if _gff:
                try:
                    its = download_gdrive_folder(name, full)
                    if its:
                        found.extend(its)
                        if is_probably_complete(found):
                            return dedup_by_remote(found)
                except Exception:
                    pass
                continue
            if is_mijnstembureau_url(full):
                try:
                    found.extend(download_mijnstembureau_portal(name, full))
                except Exception:
                    pass
                if is_probably_complete(found):
                    return dedup_by_remote(found)
                continue
            if is_stackstorage_share(full):
                try:
                    found.extend(download_stackstorage_share(name, full))
                except Exception:
                    pass
                if is_probably_complete(found):
                    return dedup_by_remote(found)
                continue
            # pv-overzichtspagina's (Amsterdam-achtig)
            low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
            if OVERVIEW_HINT_RE.search(low):
                try:
                    its = download_pv_overview_page(name, full)
                    if its:
                        found.extend(its)
                        # We hebben de plek gevonden; ga niet breder zoeken
                        return dedup_by_remote(found)
                except Exception:
                    pass
                continue
            # mediafiler albums verzamelen voor later
            # (we volgen deze pagina later als nodig)
            if 'mediafiler.net' in full and '/start/' in full:
                candidates.append(full)
                continue
            # reguliere interne pagina’s met hints
            try:
                if _same_registrable_domain(full, base) and PDF_PAGE_HINT_RE.search(low):
                    candidates.append(full)
            except Exception:
                pass
        # volg kandidaten (limiet adaptief) en extraheer PDF’s; stop als één pagina 'plek gevonden' oplevert
        seen = set()
        cand_limit = 12
        try:
            host = urlparse(start).netloc.lower()
            # Heuristische uitzonderingen: sta iets meer kandidaten toe op lastigere domeinen
            if any(h in host for h in ("gemeentehulst.nl", "oostzaan.nl")):
                cand_limit = 16
        except Exception:
            pass
        for u in candidates[:cand_limit]:
            if u in seen: continue
            seen.add(u)
            h2, b2 = fetch_html(u, allow_render=True)
            if not h2: continue
            # Probeer eerst of dit zelf een PV-overzichtspagina is of linkt naar zo'n pagina
            try:
                ov2 = find_overview_pages_from_html(h2, b2)
            except Exception:
                ov2 = []
            used_ov = False
            for ov in ov2[:2]:
                try:
                    its = download_pv_overview_page(name, ov)
                    if its:
                        found.extend(its)
                        found_place = True; used_ov = True
                        break
                except Exception:
                    continue
            if used_ov:
                break
            eps = simple_extract_pdf_links(h2, b2)
            # Fallback: sommige subpagina's embedden PDF's via dsresource/type=pdf zonder anchor
            if (not eps) and (("dsresource" in (h2 or "").lower()) or ("type=pdf" in (h2 or "").lower())):
                try:
                    import re as _re
                    ds = []
                    for m in _re.finditer(r'(?:href|data-href|data-url)="([^"\s]*dsresource[^"\s]+)"', h2 or '', _re.I):
                        ds.append(urljoin(b2, m.group(1)))
                    seen_local = set()
                    for du in ds:
                        if du in seen_local:
                            continue
                        seen_local.add(du)
                        nm = os.path.basename(urlparse(du).path) or 'document.pdf'
                        if _is_current_year_pdf(nm + ' ' + du):
                            eps.append({'remote_url': du, 'local_url': None, 'pdf_name': nm, 'text': nm, 'from': b2, 'score': 1})
                except Exception:
                    pass
            found.extend(eps)
            # Heuristiek: als deze ene pagina ≥5 (of ≥4 sterke) items heeft, beschouwen we dit als juiste plek
            if len(eps) >= 5 or sum(1 for p in eps if PV_STRONG_HINT_RE.search((p.get('text') or '') + ' ' + (p.get('pdf_name') or ''))) >= 4:
                found_place = True
                break
            if is_probably_complete(found):
                break

        # 1d) laatste redmiddel: sitemap traverseren en PV-overzicht zoeken
        if (len(found) < 5) and (not found_place):
            try:
                for sp in discover_via_sitemap(start, max_pages=50):
                    try:
                        h3, b3 = fetch_html(sp, allow_render=True)
                        if not h3:
                            continue
                        ovp = find_overview_pages_from_html(h3, b3)
                        for ov in ovp[:2]:
                            try:
                                its = download_pv_overview_page(name, ov)
                                if its:
                                    found.extend(its)
                                    return dedup_by_remote(found)
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass
        # 1e) beperkte BFS over interne site (alleen als nog weinig gevonden)
        if (len(found) < 5) and (not found_place):
            try:
                bfs_pages = 40
                try:
                    host = urlparse(start).netloc.lower()
                    if any(h in host for h in ("gemeentehulst.nl",)):
                        bfs_pages = 60
                except Exception:
                    pass
                bfs = collect_pdfs_bfs_internal(name, max_depth=2, max_pages=bfs_pages, force_render=True)
            except Exception:
                bfs = []
            if bfs:
                # Download een beperkte set via HTTP om requests te beperken
                cap = 40
                for e in bfs[:cap]:
                    u = e.get('remote_url') or ''
                    if not u:
                        continue
                    dest = stream_download(u, out_dir)
                    if dest:
                        found.append({'remote_url': u, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': os.path.basename(dest), 'text': e.get('text') or os.path.basename(dest), 'from': e.get('from') or u, 'score': int(e.get('score') or 0)})
                if found:
                    return dedup_by_remote(found)
        # mediafiler albums detectie en download
        albums = []
        for u in candidates:
            if 'mediafiler.net' in u and '/start/' in u:
                albums.append(u)
        for alb in albums[:2]:
            try:
                items = parse_mediafiler_album_for_items(alb)
                if items:
                    found.extend({'remote_url': f"{it.get('album_url')}#fuid={it.get('fuid')}", 'local_url': None, 'pdf_name': it.get('filename'), 'text': it.get('filename'), 'from': alb, 'score': 0} for it in items if _is_current_year_pdf(it.get('filename') or '') )
                    download_mediafiler_album(name, alb, items)
            except Exception:
                pass
    # 2) snelle site‑search fallback (alleen als weinig gevonden en geen duidelijke plek)
    if (len(found) < 5) and (not found_place):
        # 2a) snelle poging: directe MijnStembureau guess op basis van gemeentenaam
        try:
            guess = guess_mijnstembureau_url(name)
            r = http_get(guess, timeout=(6, 10))
            if 200 <= r.status_code < 400:
                try:
                    its = download_mijnstembureau_portal(name, guess)
                    if its:
                        found.extend(its)
                        return dedup_by_remote(found)
                except Exception:
                    pass
        except Exception:
            pass
        # Geïnspireerd door quick_site_search in de hoofd-scraper, maar compact gehouden
        terms = [
            "documenten verkiezing", "verkiezingsuitslag", "verkiezingen uitslag", "verkiez", "uitslag",
            "proces-verbaal", "processen-verbaal", "stembureau", "voorlopige", "N10-2", "Na 31-2", "bijlage 2",
            "bestanden", "documenten", "gestemd", "zo is er gestemd", "tweede kamer"
        ]
        paths = ["zoeken", "search", "site/zoeken"]
        params = ["q", "search", "trefwoord"]
        try:
            pu = urlparse(start); origin = f"{pu.scheme}://{pu.netloc}"
        except Exception:
            origin = None
        if origin:
            candidate_pages: list[str] = []
            # Verzamel kandidaat contentpagina's vanaf zoekresultaat-HTML (geen speculatieve paden)
            for t in terms:
                qt = requests.utils.quote(t)
                for p in paths:
                    for param in params:
                        surl = f"{origin}/{p}?{param}={qt}"
                        try:
                            r = http_get(surl, timeout=(8, 15))
                        except Exception:
                            continue
                        s = BeautifulSoup(r.text, 'html.parser')
                        for a in s.select('a[href]'):
                            href = a.get('href') or ''
                            full = urljoin(r.url, href)
                            low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
                            try:
                                if urlparse(full).netloc != urlparse(origin).netloc:
                                    continue
                            except Exception:
                                continue
                            if not PDF_PAGE_HINT_RE.search(low):
                                continue
                            candidate_pages.append(full)
                # cap om compact te blijven
                if len(candidate_pages) >= 12:
                    break
            # dedup en volg maximaal 8 pagina's; gebruik rendering als nodig
            seen = set()
            for u in candidate_pages:
                if u in seen:
                    continue
                seen.add(u)
                h3, b3 = fetch_html(u, allow_render=False)
                if not h3:
                    h3, b3 = fetch_html(u, allow_render=True)
                if not h3:
                    continue
                eps = simple_extract_pdf_links(h3, b3)
                found.extend(eps)
                # Als deze pagina duidelijk de plek is, stop dan verdere zoek-cycli
                if len(eps) >= 5 or sum(1 for p in eps if PV_STRONG_HINT_RE.search((p.get('text') or '') + ' ' + (p.get('pdf_name') or ''))) >= 4:
                    break
                if is_probably_complete(found):
                    break

    # 2c) ultieme fallback: probeer een handvol veelgebruikte paden (alleen als nog niets of weinig gevonden)
    if (len(found) < 5) and (not found_place):
        try:
            pu = urlparse(start); origin = f"{pu.scheme}://{pu.netloc}"
        except Exception:
            origin = None
        if origin:
            well_known = [
                "/verkiezingen",
                "/tweede-kamerverkiezingen",
                "/tweede-kamerverkiezing",
                "/tweede-kamerverkiezingen-2025",
                "/voorlopige-uitslag",
                "/verkiezingsuitslag",
                "/uitslagen",
                "/uitslagen-verkiezingen",
                "/verkiezingen/overzicht-proces-verbalen",
                "/zo-is-er-gestemd",
                "/downloads",
                "/documenten",
                "/bestanden",
            ]
            banned_nav = re.compile(r"waterschap|gemeenteraad|provinciale|europees", re.I)
            tried = 0
            for path in well_known:
                if tried >= 6:  # compact houden
                    break
                u = origin.rstrip("/") + path
                h4, b4 = fetch_html(u, allow_render=False)
                if not h4:
                    h4, b4 = fetch_html(u, allow_render=True)
                if not h4:
                    continue
                tried += 1
                # direct aanwezige PDFs
                eps = simple_extract_pdf_links(h4, b4)
                if eps:
                    found.extend(eps)
                # portals en relevante sublinks vanaf deze pagina
                s4 = BeautifulSoup(h4, 'html.parser')
                subcands = []
                for a in s4.select('a[href]'):
                    href = a.get('href') or ''
                    full = urljoin(b4, href)
                    txt = a.get_text(' ', strip=True) or ''
                    low = (full + ' ' + txt).lower()
                    if banned_nav.search(low):
                        continue
                    # Google Drive detection
                    try:
                        _gfid = is_gdrive_file(full)
                    except Exception:
                        _gfid = None
                    if _gfid:
                        try:
                            di = download_gdrive_file(name, _gfid, referer_url=full)
                            if di:
                                found.append(di)
                        except Exception:
                            pass
                        continue
                    try:
                        _gff = is_gdrive_folder(full)
                    except Exception:
                        _gff = None
                    if _gff:
                        try:
                            its = download_gdrive_folder(name, full)
                            if its:
                                found.extend(its)
                        except Exception:
                            pass
                        continue
                    if is_mijnstembureau_url(full):
                        try:
                            found.extend(download_mijnstembureau_portal(name, full))
                        except Exception:
                            pass
                        continue
                    if is_stackstorage_share(full):
                        try:
                            found.extend(download_stackstorage_share(name, full))
                        except Exception:
                            pass
                        continue
                    if 'mediafiler.net' in full and '/start/' in full:
                        subcands.append(full)
                        continue
                    try:
                        if _same_registrable_domain(full, b4) and PDF_PAGE_HINT_RE.search(low):
                            subcands.append(full)
                    except Exception:
                        pass
                # volg een paar subkandidaten
                seen_sub = set()
                for su in subcands[:8]:
                    if su in seen_sub:
                        continue
                    seen_sub.add(su)
                    h5, b5 = fetch_html(su, allow_render=False)
                    if not h5:
                        h5, b5 = fetch_html(su, allow_render=True)
                    if not h5:
                        continue
                    eps2 = simple_extract_pdf_links(h5, b5)
                    if eps2:
                        found.extend(eps2)
                    # één klik dieper vanaf su indien nodig (bijv. '.../uitslag' detailpagina)
                    if (len(eps2) < 5) and (not is_probably_complete(found)):
                        s5 = BeautifulSoup(h5, 'html.parser')
                        deep = []
                        for aa in s5.select('a[href]'):
                            href = aa.get('href') or ''
                            full2 = urljoin(b5, href)
                            low2 = (full2 + ' ' + (aa.get_text(' ', strip=True) or '')).lower()
                            if banned_nav.search(low2):
                                continue
                            try:
                                if _same_registrable_domain(full2, b5) and PDF_PAGE_HINT_RE.search(low2):
                                    deep.append((full2, low2))
                            except Exception:
                                pass
                        # sorteer: 'uitslag' en 'tweede-kamer' voorrang
                        deep_sorted = sorted(deep, key=lambda x: (
                            ("uitslag" in x[1]) * -2 + ("tweede" in x[1] and "kamer" in x[1]) * -2 + ("proces" in x[1] or "verbaal" in x[1] or " pv " in (" "+x[1]+" ")) * -1,
                            len(x[0])
                        ))
                        deep_seen = set()
                        for su2, _low2 in deep_sorted[:8]:
                            if su2 in deep_seen:
                                continue
                            deep_seen.add(su2)
                            h6, b6 = fetch_html(su2, allow_render=False)
                            if not h6:
                                h6, b6 = fetch_html(su2, allow_render=True)
                            if not h6:
                                continue
                            eps3 = simple_extract_pdf_links(h6, b6)
                            if eps3:
                                found.extend(eps3)
                            if is_probably_complete(found) or len(eps3) >= 5:
                                break
                    if is_probably_complete(found) or (len(eps2) >= 5):
                        break
                if is_probably_complete(found):
                    break

    # 2.9) laatste kans: enumerate numbered siblings op basis van een gevonden seed
    if (len(found) < 5):
        seed = next((p for p in found if isinstance(p.get('remote_url'), str) and 'stembureau' in p.get('remote_url').lower() and p.get('remote_url').lower().endswith('.pdf')), None)
        if seed:
            sibs = enumerate_numbered_siblings(seed.get('remote_url'), max_n=160)
            if sibs:
                try:
                    from urllib.parse import urlparse
                except Exception:
                    pass
                for u in sibs:
                    try:
                        nm = os.path.basename(urlparse(u).path)
                    except Exception:
                        nm = 'document.pdf'
                    found.append({'remote_url': u, 'local_url': None, 'pdf_name': nm or 'document.pdf', 'text': nm or 'document.pdf', 'from': u, 'score': 1})

    # 3) download HTTP voor directe PDF’s (niet-portaal)
    out = []
    http_done = 0
    for p in dedup_by_remote(found):
        u = p.get('remote_url') or ''
        if any(k in u for k in ['mediafiler.net', 'stackstorage.com', '/uitslagen/api/view-pv/']):
            out.append(p); continue
        if (max_http is not None) and (http_done >= max_http):
            out.append(p); continue
        # Prefer a meaningful suggested name over generic endpoints
        sug = p.get('pdf_name') or ''
        try:
            base_no_ext = os.path.splitext(str(sug))[0].lower()
        except Exception:
            base_no_ext = ''
        import re as _re
        looks_guid = bool(_re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", base_no_ext))
        if looks_guid or base_no_ext in {"dsresource", "download", "document", "file", "unknown"} or (not sug):
            sug = p.get('text') or sug or None
        dest = stream_download(u, out_dir, sug)
        if dest:
            p['local_url'] = 'file://' + os.path.abspath(dest)
            http_done += 1
        out.append(p)
    return out


def light_merge_index(name: str, pdfs: list[dict]) -> None:
    try:
        data = load_json(INDEX_PATH)
        results = data.get('results', []) if isinstance(data, dict) else []
    except Exception:
        results = []
    name_to = {e.get('name'): e for e in results}
    cur = name_to.get(name) or {'name': name, 'start_url': get_start_url(name), 'pdfs': []}
    seen = set()
    for q in cur.get('pdfs', []):
        k = q.get('remote_url') or ('N:' + (q.get('pdf_name') or ''))
        if k: seen.add(k)
    for p in pdfs:
        k = p.get('remote_url') or ('N:' + (p.get('pdf_name') or ''))
        if not k or k in seen: continue
        seen.add(k)
        q = {
            'remote_url': p.get('remote_url'),
            'local_url': p.get('local_url'),
            'pdf_name': p.get('pdf_name') or os.path.basename(urlparse((p.get('remote_url') or '')).path) or 'unknown.pdf',
            'text': p.get('text') or p.get('pdf_name') or '',
            'from': p.get('from') or (p.get('remote_url') or 'unknown'),
            'score': int(p.get('score') or 0),
        }
        cur.setdefault('pdfs', []).append(q)
    name_to[name] = cur
    out = [name_to[k] for k in sorted(name_to.keys())]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump({'results': out, 'count': len(out)}, f, ensure_ascii=False, indent=2)
    print(f"[compact] Merged {len(pdfs)} items for {name} -> {INDEX_PATH}")


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snelle, compacte PV-scraper (TK2025)")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten")
    ap.add_argument("--slice", type=str, help="1-based inclusieve slice, bijv. 11-20")
    ap.add_argument("--first", type=int, help="Eerste N gemeenten")
    ap.add_argument("--http-cap", type=int, default=None, help="Max # HTTP downloads per gemeente (portalen niet meegeteld)")
    args = ap.parse_args(argv)

    if args.only:
        names = [n for n in args.only if n in set(get_all_names())]
    elif args.slice:
        try:
            a, b = args.slice.split('-', 1)
            names = get_municipalities_slice(int(a), int(b))
        except Exception:
            print("[compact] Ongeldige --slice")
            return 1
    elif args.first:
        names = get_all_names()[: args.first]
    else:
        names = get_all_names()[:5]

    print(f"[compact] Target: {', '.join(names)}")
    for n in names:
        try:
            pdfs = scrape_one(n, max_http=args.http_cap)
            light_merge_index(n, pdfs)
        except Exception as e:
            print(f"[compact] {n}: ERROR {e}")
    print("[compact] Done.")
    return 0


if __name__ == "__main__":
    if not PLAYWRIGHT_AVAILABLE:
        print("[compact] Playwright is vereist (pip install playwright && python -m playwright install chromium)")
    raise SystemExit(run())
