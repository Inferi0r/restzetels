#!/usr/bin/env python3
"""
Compact scraper om snel PDF's (processen-verbaal/uitslagen) per gemeente te vinden
en te downloaden voor de eerste 5 gemeenten uit data/municipalities.json.

Output: compact/<GemeenteNaam>/*.pdf

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

import requests
from bs4 import BeautifulSoup


DATA_DIR = os.path.join(os.getcwd(), "data")
OUT_BASE = os.path.join(os.getcwd(), "compact")


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


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: list[str] = []
    maybes: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        p = urlparse(full).path.lower()
        classes = " ".join(a.get("class", []))
        text = a.get_text(" ", strip=True).lower()
        is_pdf_like = (
            (".pdf" in p)
            or ("type=pdf" in full.lower())
            or ("type-document-pdf" in classes)
            or (text.endswith("pdf"))
        )
        if is_pdf_like:
            urls.append(full)
        else:
            if any(k in full.lower() for k in ("dsresource", "download", "document", "/file/")) or any(k in text for k in ("pdf", "proces", "stembureau", "uitslag")):
                maybes.append(full)

    # Light probe: check headers for suspected endpoints
    def probe_is_pdf(u: str) -> bool:
        try:
            r = requests.get(u, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=10, stream=True)
            ct = r.headers.get("Content-Type", "").lower()
            r.close()
            return "application/pdf" in ct
        except Exception:
            return False

    for u in maybes[:12]:  # cap probes
        if probe_is_pdf(u):
            urls.append(u)

    # dedup while preserving order
    seen = set(); out = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def quick_site_search(start_url: str) -> list[str]:
    """Probeer 1-2 eenvoudige zoek-url varianten om extra pagina's te vinden.
    Retourneert een lijst pagina-URLs (geen PDFs) om daarna PDF-links uit te halen.
    """
    pu = urlparse(start_url)
    base = f"{pu.scheme}://{pu.netloc}"
    terms = ["verkiez", "uitslag", "proces-verbaal", "processen-verbaal", "stembureau"]
    paths = ["zoeken", "search"]
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
                    if any(k in full.lower() for k in ("verkiez", "uitslag", "proces", "stembur")):
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
        soup = BeautifulSoup(rr.text, "xml")
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


def get_first5_names() -> list[str]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    return [it.get("name") for it in items[:5] if it.get("name")]


def get_verified_url(name: str) -> str | None:
    data = load_json(os.path.join(DATA_DIR, "municipality_links_verified.json"))
    for v in data.get("verified", []):
        if v.get("name") == name and v.get("status") == 200:
            return v.get("final_url") or v.get("start_url")
    return None


def collect_pdfs_for_municipality(name: str, extra: dict) -> list[str]:
    urls: list[str] = []
    start = get_verified_url(name)
    seeds = list(extra.get(name, [])) if extra else []
    if start:
        seeds.append(start)
    # fetch seeds and extract pdfs + discover a small set of relevant internal pages
    discover_pages: list[str] = []
    KEY_RE = re.compile(r"verkiez|uitslag|proces|stembur|tweede.*kamer|n10|na\s*31|na31|model", re.I)
    for s in seeds[:5]:  # cap seeds processed
        try:
            r = http_get(s)
            urls += extract_pdf_links(r.text, r.url)
            # collect relevant internal pages for 1-hop expansion
            soup = BeautifulSoup(r.text, "html.parser")
            pu = urlparse(r.url)
            base = f"{pu.scheme}://{pu.netloc}"
            for a in soup.select("a[href]"):
                href = a.get("href"); full = urljoin(r.url, href or "")
                if not full or ".pdf" in urlparse(full).path.lower():
                    continue
                if urlparse(full).netloc != pu.netloc or not full.startswith(base):
                    continue
                if KEY_RE.search(full):
                    discover_pages.append(full)
        except Exception:
            pass
    # process a few discovered pages
    for p in list(dict.fromkeys(discover_pages))[:10]:
        try:
            r2 = http_get(p, timeout=12)
            urls += extract_pdf_links(r2.text, r2.url)
        except Exception:
            pass
    # quick site search as a fallback if still nothing
    if not urls and start:
        for p in quick_site_search(start):
            try:
                r3 = http_get(p, timeout=12)
                urls += extract_pdf_links(r3.text, r3.url)
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
    # dedup
    seen = set(); out = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compacte scraper voor eerste 5 gemeenten")
    ap.add_argument("--only", nargs='*', help="Alleen deze gemeenten (subset van eerste 5)")
    args = ap.parse_args(argv)

    names = get_first5_names()
    if args.only:
        names = [n for n in names if n in set(args.only)]
    extra = load_extra_seeds()

    print(f"[cleaned] Target: {', '.join(names)}")
    total_saved = 0
    for n in names:
        out_dir = os.path.join(OUT_BASE, sanitize_filename(n))
        pdfs = collect_pdfs_for_municipality(n, extra)
        print(f"[cleaned] {n}: {len(pdfs)} pdf links")
        saved = 0
        for u in pdfs:
            dest = download_pdf(u, out_dir)
            if dest:
                saved += 1
        total_saved += saved
        print(f"[cleaned] {n}: saved {saved} PDFs -> {out_dir}")
    print(f"[cleaned] Done. Total saved: {total_saved}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
