#!/usr/bin/env python3
"""
Specialized scraper for Amsterdam PVs (processen‑verbaal per stembureau).

Seeds:
- https://www.amsterdam.nl/verkiezingen/overzicht-proces-verbalen/

Strategy:
- Use Playwright to render the overview and any linked subpages.
- Collect every anchor whose href ends with .pdf on these pages.
- Also traverse subpages whose text/path suggests PV overview (overzicht/proces/verbaal/stembureau).
- Download PDFs to scraper/pdfs/Amsterdam and merge index.

Usage:
  python3 pdf_scraper_amsterdam.py [--start-url URL]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlparse, urljoin, urlencode

from playwright.sync_api import sync_playwright


DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
OUT_DIR = os.path.join(os.path.dirname(__file__), "pdfs", "Amsterdam")
INDEX_PATH = os.path.join(DATA_DIR, "municipality_pdfs_index.json")
API_BASE = "https://api.data.amsterdam.nl/v1/verkiezingen/processenverbaal"
PV_BASE = "https://pv-verkiezingen.amsterdam.nl/verkiezingen/procesverbalen/2025/"


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def light_merge_index(name: str, pdfs: list[dict]) -> None:
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        results = data.get('results', []) if isinstance(data, dict) else []
    except Exception:
        results = []
    name_to = {e.get('name'): e for e in results}
    cur = name_to.get(name) or {'name': name, 'start_url': None, 'pdfs': []}
    seen = set()
    for q in cur.get('pdfs', []):
        k = q.get('remote_url') or ('N:' + (q.get('pdf_name') or ''))
        if k:
            seen.add(k)
    for p in pdfs:
        k = p.get('remote_url') or ('N:' + (p.get('pdf_name') or ''))
        if not k or k in seen:
            continue
        seen.add(k)
        cur.setdefault('pdfs', []).append({
            'remote_url': p.get('remote_url'),
            'local_url': p.get('local_url'),
            'pdf_name': p.get('pdf_name') or os.path.basename(urlparse((p.get('remote_url') or '')).path) or 'unknown.pdf',
            'text': p.get('text') or p.get('pdf_name') or '',
            'from': p.get('from') or (p.get('remote_url') or 'unknown'),
            'score': int(p.get('score') or 0),
        })
    name_to[name] = cur
    out = [name_to[k] for k in sorted(name_to.keys())]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump({'results': out, 'count': len(out)}, f, ensure_ascii=False, indent=2)
    print(f"[ams] Merged {len(pdfs)} items for {name} -> {INDEX_PATH}")


HINT_PAGE = re.compile(r"overzicht|proces|verbaal|stembureaus?|stadsdeel|uitslag|verbal|pv", re.I)


def collect_pdf_links(page) -> list[dict]:
    items: list[dict] = []
    anchors = page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: e.innerText}))') or []
    seen = set()
    for a in anchors:
        href = (a.get('href') or '').strip()
        text = (a.get('text') or '').strip()
        if not href:
            continue
        try:
            parsed = urlparse(href)
        except Exception:
            continue
        if not parsed.scheme or not parsed.netloc:
            continue
        key = href.split('?', 1)[0]
        if key in seen:
            continue
        if key.lower().endswith('.pdf'):
            seen.add(key)
            fname = os.path.basename(parsed.path) or 'document.pdf'
            items.append({'remote_url': key, 'local_url': None, 'pdf_name': fname, 'text': text, 'from': page.url, 'score': 4})
    return items


def collect_subpages(page) -> list[str]:
    out: list[str] = []
    anchors = page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: e.innerText}))') or []
    seen = set()
    for a in anchors:
        href = (a.get('href') or '').strip()
        text = (a.get('text') or '').strip()
        if not href:
            continue
        try:
            parsed = urlparse(href)
        except Exception:
            continue
        if not parsed.scheme or not parsed.netloc:
            continue
        # Avoid enqueueing direct PDF links as subpages; those will be downloaded separately
        if (parsed.path or '').lower().endswith('.pdf'):
            continue
        host = (parsed.netloc or '').lower()
        path = (parsed.path or '').lower()
        s = (text + ' ' + href).lower()
        if 'amsterdam.nl' in host and HINT_PAGE.search(s):
            key = href.split('#', 1)[0]
            if key not in seen:
                seen.add(key); out.append(key)
    return out[:50]


def download_all(start_url: str) -> list[dict]:
    os.makedirs(OUT_DIR, exist_ok=True)
    items: list[dict] = []
    visited = set()
    queue = [start_url]
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale='nl-NL', user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
        req = ctx.request
        # First, try the official Amsterdam API per stadsdeel to enumerate ALL PVs
        try:
            api_items = collect_from_amsterdam_api(ctx, start_url)
            if api_items:
                items.extend(api_items)
                # API returns complete coverage; skip slower fallbacks
                ctx.close(); b.close()
                return items
        except Exception:
            pass
        # Fallbacks only if API path yielded nothing
        try:
            spec_items = collect_from_processen_verbaal_25(ctx, start_url)
            if spec_items:
                items.extend(spec_items)
        except Exception:
            pass
        while queue and len(visited) < 60:
            u = queue.pop(0)
            if u in visited:
                continue
            visited.add(u)
            # Handle direct PDF URLs without navigating a page
            if u.lower().split('?', 1)[0].endswith('.pdf'):
                try:
                    resp = req.get(u, timeout=60000)
                    if resp.ok:
                        ctype = (resp.headers.get('content-type','') or '').lower()
                        if ('pdf' in ctype) or u.lower().endswith('.pdf'):
                            fname = os.path.basename(urlparse(u).path) or 'document.pdf'
                            dest = os.path.join(OUT_DIR, sanitize_filename(fname))
                            if not os.path.exists(dest):
                                with open(dest, 'wb') as f:
                                    f.write(resp.body())
                            items.append({'remote_url': u, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': fname, 'text': '', 'from': 'queue', 'score': 5})
                    # Do not attempt to traverse further from a PDF URL
                    continue
                except Exception:
                    # Skip problematic PDF URL
                    continue
            page = ctx.new_page()
            try:
                page.goto(u, wait_until='domcontentloaded', timeout=60000)
                try:
                    page.wait_for_load_state('networkidle', timeout=60000)
                except Exception:
                    pass
                # collect PDFs on this page
                pdfs = collect_pdf_links(page)
                # download
                for it in pdfs:
                    href = it.get('remote_url') or ''
                    try:
                        resp = req.get(href, timeout=60000)
                        if not resp.ok:
                            continue
                        ctype = (resp.headers.get('content-type','') or '').lower()
                        if ('pdf' not in ctype) and (not href.lower().endswith('.pdf')):
                            continue
                        fname = it.get('pdf_name') or os.path.basename(urlparse(href).path) or 'document.pdf'
                        dest = os.path.join(OUT_DIR, sanitize_filename(fname))
                        if not os.path.exists(dest):
                            with open(dest, 'wb') as f:
                                f.write(resp.body())
                        it['local_url'] = 'file://' + os.path.abspath(dest)
                        items.append(it)
                    except Exception:
                        continue
                # enqueue subpages for further traversal
                subs = collect_subpages(page)
                for su in subs:
                    if su not in visited and su not in queue:
                        queue.append(su)
            finally:
                page.close()
        ctx.close(); b.close()
    return items


def collect_from_processen_verbaal_25(ctx, start_url: str) -> list[dict]:
    out: list[dict] = []
    # Derive the processen‑verbaal page URL
    try:
        parsed = urlparse(start_url)
        base = start_url.rstrip('/')
        if '/overzicht-proces-verbalen' in parsed.path:
            seed = base + '/processen-verbaal-25/'
        else:
            seed = 'https://www.amsterdam.nl/verkiezingen/overzicht-proces-verbalen/processen-verbaal-25/'
    except Exception:
        seed = 'https://www.amsterdam.nl/verkiezingen/overzicht-proces-verbalen/processen-verbaal-25/'
    page = ctx.new_page()
    try:
        page.goto(seed, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=60000)
        except Exception:
            pass
        # Find selects: first is stadsdeel, second is stembureau list
        sels = page.query_selector_all('select')
        if len(sels) < 2:
            return []
        stadsdeel_sel = sels[0]
        bureau_sel = sels[1]
        # Gather stadsdeel options
        stadsdelen = stadsdeel_sel.eval_on_selector_all('option', 'els => els.map(e => ({value:e.value, text:e.innerText}))') or []
        pdf_urls = set()
        for sd in stadsdelen:
            val = (sd.get('value') or '').strip()
            if not val:
                continue
            # Skip the catch‑all option to avoid duplicates; we iterate each stadsdeel separately
            if sd.get('text', '').strip().lower() == 'alle':
                continue
            # Select stadsdeel and wait a moment for the second select to populate
            try:
                stadsdeel_sel.select_option(value=val)
                page.wait_for_timeout(500)
            except Exception:
                continue
            # Read stembureau options and collect PDF urls
            # Re-query the second select in case the DOM replaced it after selection
            try:
                sels2 = page.query_selector_all('select')
                bureau_sel2 = sels2[1] if len(sels2) >= 2 else bureau_sel
            except Exception:
                bureau_sel2 = bureau_sel
            opts = bureau_sel2.eval_on_selector_all('option', 'els => els.map(e => ({value:e.value, text:e.innerText}))') or []
            for o in opts:
                href = (o.get('value') or '').strip()
                if href.lower().endswith('.pdf') and href.startswith('http'):
                    pdf_urls.add(href.split('?', 1)[0])
        # Download all discovered PDFs
        for href in sorted(pdf_urls):
            try:
                resp = ctx.request.get(href, timeout=60000)
                if not resp.ok:
                    continue
                ctype = (resp.headers.get('content-type','') or '').lower()
                if ('pdf' not in ctype) and (not href.lower().endswith('.pdf')):
                    continue
                fname = os.path.basename(urlparse(href).path) or 'document.pdf'
                dest = os.path.join(OUT_DIR, sanitize_filename(fname))
                if not os.path.exists(dest):
                    with open(dest, 'wb') as f:
                        f.write(resp.body())
                out.append({'remote_url': href, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': fname, 'text': 'Stembureau', 'from': seed, 'score': 5})
            except Exception:
                continue
    finally:
        page.close()
    return out


def _download_urls(ctx, urls: list[str], source_page: str, max_dl: int | None = None) -> list[dict]:
    out: list[dict] = []
    cap = max_dl if isinstance(max_dl, int) and max_dl > 0 else None
    for i, href in enumerate(urls):
        if cap is not None and i >= cap:
            break
        try:
            resp = ctx.request.get(href, timeout=120000)
            if not resp.ok:
                continue
            ctype = (resp.headers.get('content-type','') or '').lower()
            if ('pdf' not in ctype) and (not href.lower().endswith('.pdf')):
                continue
            fname = os.path.basename(urlparse(href).path) or 'document.pdf'
            dest = os.path.join(OUT_DIR, sanitize_filename(fname))
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(resp.body())
            out.append({'remote_url': href, 'local_url': 'file://' + os.path.abspath(dest), 'pdf_name': fname, 'text': 'Stembureau', 'from': source_page, 'score': 6})
        except Exception:
            continue
    return out


def collect_from_amsterdam_api(ctx, start_url: str) -> list[dict]:
    """Enumerate all 2025 PVs via the official API across all stadsdelen.

    This avoids relying on the front-end component and guarantees coverage
    (Centrum, Noord, Nieuw‑West, Oost, West, Zuid, Zuidoost, Weesp, ...).
    """
    seen: set[str] = set()
    urls: list[str] = []
    # Fetch every page from the API; follow `_links.next.href` until exhausted
    next_url = API_BASE + "?" + urlencode({"verkiezingsjaar": 2025, "page_size": 1000})
    while next_url:
        try:
            resp = ctx.request.get(next_url, timeout=120000)
            if not resp.ok:
                break
            data = resp.json() or {}
        except Exception:
            break
        arr = (data.get('_embedded') or {}).get('processenverbaal', []) or []
        for it in arr:
            dn = (it or {}).get('documentnaam') or ''
            uri = (it or {}).get('uri') or ''
            if not dn or not dn.lower().endswith('.pdf'):
                continue
            # Only proces‑verbaal (aka model 10S), skip other stray docs if any
            if 'proces_verbaal' not in dn.lower() and 'model_10' not in dn.lower():
                continue
            href = uri if uri.startswith('http') else (PV_BASE + dn)
            key = href.split('?', 1)[0]
            if key in seen:
                continue
            seen.add(key)
            urls.append(key)
        # Follow pagination
        nxt = (data.get('_links') or {}).get('next') or {}
        next_url = nxt.get('href') if isinstance(nxt, dict) else None
    # Cap downloads if AMS_MAX_DL env var set
    try:
        max_dl = int((os.environ.get('AMS_MAX_DL') or '').strip() or '0')
    except Exception:
        max_dl = 0
    max_dl = max_dl if max_dl > 0 else None
    return _download_urls(ctx, sorted(urls), source_page='API:processenverbaal', max_dl=max_dl)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Amsterdam PV scraper (stembureau processen‑verbaal)")
    ap.add_argument('--start-url', default='https://www.amsterdam.nl/verkiezingen/overzicht-proces-verbalen/', help='Overzichts-URL om te beginnen')
    args = ap.parse_args(argv)
    items = download_all(args.start_url)
    print(f"[ams] Collected {len(items)} PDFs")
    if items:
        light_merge_index('Amsterdam', items)
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
