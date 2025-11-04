#!/usr/bin/env python3
"""
Zandvoort-specific helper to fetch PVs from the external 'Documenten' hub (Pleio-like).
Once verified, the heuristics can be folded back generically.
"""
import os
import sys
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import pdf_scraper as ps


START = "https://zandvoort.nl/tweede-kamerverkiezingen"


def find_external_hub(url: str) -> str | None:
    try:
        r = ps.http_get(url, timeout=20)
    except Exception:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select('a[href]'):
        href = a.get('href'); full = urljoin(r.url, href or '')
        txt = (a.get_text(' ', strip=True) or '').lower()
        low = (txt + ' ' + full.lower())
        if 'proces' in low and 'verbaal' in low and 'http' in full:
            return full
    return None


def ensure_dir(dirpath: str):
    os.makedirs(dirpath, exist_ok=True)


def save_if_new(dl, dest_dir: str) -> str | None:
    try:
        fn = dl.suggested_filename or 'download.pdf'
        if not fn.lower().endswith('.pdf'):
            fn += '.pdf'
        if not ps._is_current_year_pdf(fn):
            return None
        out = os.path.join(dest_dir, ps.sanitize_filename(fn))
        if os.path.exists(out):
            return None
        dl.save_as(out)
        return out
    except Exception:
        return None


def download_pleio_like(muni: str, hub_url: str) -> int:
    out_dir = os.path.join(os.getcwd(), 'pdfs', ps.sanitize_filename(muni))
    ensure_dir(out_dir)
    saved = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36',
            locale='nl-NL',
            viewport={'width': 1280, 'height': 900},
        )
        page = ctx.new_page()
        # Capture any network response that is a PDF and save it (attach at context level)
        def on_response(res):
            nonlocal saved
            try:
                ct = (res.headers or {}).get('content-type', '')
            except Exception:
                ct = ''
            if not ct:
                try:
                    ct = (res.headers_array() or {}).get('content-type','')  # type: ignore
                except Exception:
                    ct = ''
            if 'application/pdf' in (ct or '').lower():
                try:
                    body = res.body()
                    # filename from Content-Disposition or URL
                    cd = res.headers.get('content-disposition', '') if hasattr(res, 'headers') else ''
                    fname = None
                    if cd:
                        m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
                        if m:
                            from urllib.parse import unquote
                            fname = unquote(m.group(1))
                        else:
                            m2 = re.search(r"filename=\"?([^\"]+)\"?", cd)
                            if m2:
                                fname = m2.group(1)
                    if not fname:
                        from urllib.parse import urlparse
                        fname = os.path.basename(urlparse(res.url).path) or 'document.pdf'
                    if not fname.lower().endswith('.pdf'):
                        fname += '.pdf'
                    if not ps._is_current_year_pdf(fname):
                        return
                    dest = os.path.join(out_dir, ps.sanitize_filename(fname))
                    if os.path.exists(dest):
                        return
                    with open(dest, 'wb') as f:
                        f.write(body)
                    saved += 1
                except Exception:
                    pass
        ctx.on('response', on_response)
        page.goto(hub_url, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=10000)
        except Exception:
            pass

        # Try directly on hub page first (some variants list files immediately)
        try:
            hrefs = page.eval_on_selector_all('a[href]', 'els => els.map(e => e.getAttribute("href"))')
        except Exception:
            hrefs = []
        direct_views = [urljoin(page.url, h) for h in hrefs or [] if h and '/files/view/' in h]
        print(f"[zandvoort] hub view_links: {len(direct_views)}")
        for vu in direct_views:
            try:
                page.goto(vu, wait_until='domcontentloaded', timeout=30000)
                btn = page.locator('a[download], a:has-text("Download"), button:has-text("Download"), a[href*="/download"], a:has-text("download")')
                print(f"[zandvoort] hub try {vu} buttons: {btn.count()}")
                if btn.count() > 0:
                    with page.expect_download(timeout=30000) as dlctx:
                        btn.first.click()
                    dl = dlctx.value
                    dest = save_if_new(dl, out_dir)
                    if dest:
                        saved += 1
            except Exception:
                pass

        # Click into both PV folders explicitly
        tried = 0
        tile_loc = page.locator('a:has-text("processen-verbaal")')
        count = tile_loc.count()
        print(f"[zandvoort] tile candidates: {count}")
        for i in range(count):
            tried += 1
            with page.expect_navigation(timeout=20000):
                tile_loc.nth(i).click()
            try:
                page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            # Prefer Files tab if present
            files_tab = page.locator('a[href$="/files"], a:has-text("Bestanden")')
            print(f"[zandvoort] files_tab count: {files_tab.count()}")
            if files_tab.count() > 0:
                try:
                    with page.expect_navigation(timeout=15000):
                        files_tab.first.click()
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
            # Gather view links
            page.wait_for_timeout(1000)
            try:
                hrefs2 = page.eval_on_selector_all('a[href]', 'els => els.map(e => e.getAttribute("href"))')
            except Exception:
                hrefs2 = []
            view_links = [urljoin(page.url, h) for h in hrefs2 or [] if h and '/files/view/' in h]
            print(f"[zandvoort] view_links: {len(view_links)}")
            # Download per view link by clicking the Download button (auto redirect is flaky)
            for vu in view_links:
                try:
                    page.goto(vu, wait_until='domcontentloaded', timeout=30000)
                    btn = page.locator('a[download], a:has-text("Download"), button:has-text("Download"), a[href*="/download"], a:has-text("download")')
                    print(f"[zandvoort] try {vu} buttons: {btn.count()}")
                    if btn.count() > 0:
                        with page.expect_download(timeout=30000) as dlctx:
                            btn.first.click()
                        dl = dlctx.value
                        dest = save_if_new(dl, out_dir)
                        if dest:
                            saved += 1
                    else:
                        # try auto-download on navigation as last resort
                        with page.expect_download(timeout=15000) as dlctx:
                            page.goto(vu, wait_until='domcontentloaded', timeout=30000)
                        dl = dlctx.value
                        dest = save_if_new(dl, out_dir)
                        if dest:
                            saved += 1
                except Exception:
                    pass
            # Go back to hub for next folder
            try:
                page.goto(hub_url, wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(500)
            except Exception:
                pass
        if tried == 0:
            # Last resort: click any link with both 'proces' and 'verbaal'
            anchors = page.query_selector_all('a[href]')
            for a in anchors:
                try:
                    txt = (a.inner_text() or '').lower()
                except Exception:
                    txt = ''
                href = a.get_attribute('href') or ''
                if 'proces' in txt and 'verbaal' in txt:
                    try:
                        with page.expect_navigation(timeout=20000):
                            a.click()
                        page.wait_for_timeout(800)
                    except Exception:
                        continue
                    # then try files tab + downloads as above
                    files_tab = page.locator('a[href$="/files"], a:has-text("Bestanden")')
                    if files_tab.count() > 0:
                        try:
                            with page.expect_navigation(timeout=15000):
                                files_tab.first.click()
                            page.wait_for_timeout(800)
                        except Exception:
                            pass
                    try:
                        hrefs3 = page.eval_on_selector_all('a[href]', 'els => els.map(e => e.getAttribute("href"))')
                    except Exception:
                        hrefs3 = []
                    view_links = [urljoin(page.url, h) for h in hrefs3 or [] if h and '/files/view/' in h]
                    print(f"[zandvoort] fallback view_links: {len(view_links)}")
                    for vu in view_links:
                        try:
                            page.goto(vu, wait_until='domcontentloaded', timeout=30000)
                            btn = page.locator('a[download], a:has-text("Download"), button:has-text("Download"), a[href*="/download"], a:has-text("download")')
                            print(f"[zandvoort] fallback try {vu} buttons: {btn.count()}")
                            if btn.count() > 0:
                                with page.expect_download(timeout=30000) as dlctx:
                                    btn.first.click()
                                dl = dlctx.value
                                dest = save_if_new(dl, out_dir)
                                if dest:
                                    saved += 1
                        except Exception:
                            pass
                    try:
                        page.goto(hub_url, wait_until='domcontentloaded', timeout=15000)
                    except Exception:
                        pass

        ctx.close(); browser.close()
    return saved


def run() -> int:
    muni = 'Zandvoort'
    hub = find_external_hub(START)
    if not hub:
        print('[zandvoort] No external hub found on start page')
        return 1
    print('[zandvoort] Hub:', hub)
    got = download_pleio_like(muni, hub)
    # Fallback: if nothing saved, try a known GUID seed list via direct download endpoints
    if got == 0:
        print('[zandvoort] Fallback: try direct GUID downloads')
        known_guids = [
            'd6c91a7f-7ff8-44f3-910c-ae5db10b2889',
            '6c22bdfb-7793-4e3e-ad1d-12af2cd61997',
            'c9b5aa33-b194-4e0e-acbe-0bd10b4ad026',
            '3a7318be-399f-45fa-9b06-45aa3a0fd5b4',
            '98336186-e909-4933-ad93-4c6f002a767e',
            '3d1a760f-3ec7-4bf2-808f-b0b37a5bede2',
            '75aedd0a-5633-43c0-9fa4-9c528bcce4da',
            '7c461435-59bd-4129-a73e-ad7092c9226a',
            'c270ed58-8302-4cc9-8fe0-b0a26c4604af',
            'ed7f1765-a3c1-48db-8005-698d64e4f41b',
            '9d537dbc-eed1-487f-bb81-34eee48f2c7d',
            'e1c32b80-310a-4fec-a749-499ecb72040b',
            'a5762b00-8abc-4cc5-bfc7-f1aabcdb3788',
            '73884791-7476-486e-aa00-2392d69658d8',
        ]
        sess = requests.Session()
        sess.headers.update({'User-Agent':'Mozilla/5.0'})
        out_dir = os.path.join(os.getcwd(), 'pdfs', ps.sanitize_filename(muni))
        ensure_dir(out_dir)
        extra_saved = 0
        for guid in known_guids:
            try:
                url = f'https://haarlem.pleio.nl/file/download/{guid}'
                r = sess.get(url, timeout=60)
                if r.status_code != 200 or 'application/pdf' not in (r.headers.get('Content-Type','').lower()):
                    continue
                # filename from Content-Disposition else default guid.pdf
                cd = r.headers.get('Content-Disposition','')
                fname = None
                if cd:
                    m = re.search(r"filename\*=(?:UTF-8''|)[^;]*?([^;]+)", cd)
                    if m:
                        from urllib.parse import unquote
                        try:
                            fname = unquote(m.group(1).strip().strip('"'))
                        except Exception:
                            fname = m.group(1).strip().strip('"')
                    else:
                        m2 = re.search(r"filename=([^;]+)", cd)
                        if m2:
                            fname = m2.group(1).strip().strip('"')
                if not fname:
                    fname = f'{guid}.pdf'
                if not fname.lower().endswith('.pdf'):
                    fname += '.pdf'
                if not ps._is_current_year_pdf(fname):
                    continue
                dest = os.path.join(out_dir, ps.sanitize_filename(fname))
                if os.path.exists(dest):
                    continue
                with open(dest, 'wb') as f:
                    f.write(r.content)
                extra_saved += 1
            except Exception:
                continue
        got += extra_saved
    print(f"[zandvoort] Saved {got} PDFs")
    # merge into index quickly
    # reuse pdf_scraper merge_from_disk for just this municipality
    try:
        # Quick in-process merge similar to --merge-from-disk --only
        # Load existing index, add local files, write back
        idx_path = os.path.join(ps.DATA_DIR, "municipality_pdfs_index.json")
        existing = []
        try:
            import json
            with open(idx_path,'r',encoding='utf-8') as f:
                d=json.load(f)
                existing = d.get('results', []) if isinstance(d, dict) else (d or [])
        except Exception:
            existing = []
        # synthesize pdf entries from disk
        entries = []
        out_dir = os.path.join(os.getcwd(), 'pdfs', ps.sanitize_filename(muni))
        for root, _, files in os.walk(out_dir):
            for fn in files:
                if not fn.lower().endswith('.pdf'):
                    continue
                if not ps._is_current_year_pdf(fn):
                    continue
                entries.append({
                    'remote_url': None,
                    'local_url': 'file://' + os.path.abspath(os.path.join(root, fn)),
                    'pdf_name': fn,
                    'text': fn,
                    'from': 'pleio',
                    'score': 1,
                })
        # merge replace
        new_entry = {'name': muni, 'start_url': START, 'pdfs': entries}
        out = []
        placed = False
        for it in existing:
            if it.get('name') == muni:
                out.append(new_entry); placed=True
            else:
                out.append(it)
        if not placed:
            out.append(new_entry)
        with open(idx_path,'w',encoding='utf-8') as f:
            import json
            json.dump({'results': out, 'count': len(out)}, f, ensure_ascii=False, indent=2)
        print('[zandvoort] Index merged')
    except Exception as e:
        print('[zandvoort] Index merge skipped:', e)
    return 0


if __name__ == '__main__':
    sys.exit(run())
