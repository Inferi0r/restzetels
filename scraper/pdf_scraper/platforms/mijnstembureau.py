from __future__ import annotations

from typing import Dict, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from ..utils import sanitize_filename


def _origin(u: str) -> str:
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"


def _candidate_paths() -> List[str]:
    return [
        "/uitslagen/verkiezingen/tk/download-opties",
        "/uitslagen/",
        "/uitslagen/live",
    ]


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    base = _origin(hub_url)
    tries = [hub_url] + [base.rstrip('/') + p for p in _candidate_paths()]

    def _sync_capture_labels(url: str, max_items: int = 300) -> List[Dict]:
        """Open the mijnstembureau download page and capture PV PDFs with UI names.

        Strategy (kept simple and robust):
        - Open the page, expand the 2025 election block if shown.
        - Click "Download opties" and then "Processen verbaal" to reveal the list.
        - Iterate all button elements whose text ends with ".pdf" (these are the visible filenames).
        - For each, click and wait for the underlying HTTP response to /uitslagen/api/view-pv/... (ignore blob: URLs).
        - Record the response URL together with the exact UI filename.
        """
        out: List[Dict] = []
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return out
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context()
            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass

            # Expand the election block if it's collapsed (contains the 2025 date)
            try:
                blk = page.locator('text=/29-10-2025/').first
                if blk and blk.count() > 0:
                    blk.click(timeout=1500)
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Open Download opties then Processen-verbaal list
            for sel in [
                'a:has-text("Download opties")', 'button:has-text("Download opties")', '[role=button]:has-text("Download opties")',
            ]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click()
                        page.wait_for_timeout(400)
                        break
                except Exception:
                    pass
            for sel in [
                'a:has-text("Processen verbaal")', 'button:has-text("Processen verbaal")', '[role=button]:has-text("Processen verbaal")',
                'a:has-text("Processen-verbaal")', 'button:has-text("Processen-verbaal")', '[role=button]:has-text("Processen-verbaal")',
            ]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click()
                        page.wait_for_timeout(600)
                        break
                except Exception:
                    pass

            # Ensure content is loaded
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except Exception:
                pass

            # Collect all visible filename buttons (text ends with .pdf)
            all_buttons = page.locator('button')
            try:
                total = all_buttons.count()
            except Exception:
                total = 0

            def looks_filename(txt: str) -> bool:
                t = (txt or '').strip()
                return t.lower().endswith('.pdf')

            seen_urls: set[str] = set()
            processed = 0

            def is_target_response(resp) -> bool:
                try:
                    u = resp.url or ''
                    if not (u.startswith('http://') or u.startswith('https://')):
                        return False  # ignore blob: and data:
                    ct = (resp.headers or {}).get('content-type', '').lower()
                    return (resp.status == 200) and ('/uitslagen/api/view-pv' in u) and ('application/pdf' in ct) and (u not in seen_urls)
                except Exception:
                    return False

            for i in range(total):
                if processed >= max_items:
                    break
                try:
                    btn = all_buttons.nth(i)
                    label = (btn.inner_text() or '').strip()
                except Exception:
                    continue
                if not looks_filename(label):
                    continue
                name = label
                try:
                    with page.expect_response(is_target_response, timeout=15000) as respctx:
                        btn.click()
                    resp = respctx.value
                except Exception:
                    # As a fallback, give the page a brief moment and scan recent responses
                    try:
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
                    continue

                u = getattr(resp, 'url', '') or ''
                if not u:
                    continue
                seen_urls.add(u)
                out.append({
                    'remote_url': u,
                    'local_url': None,
                    'pdf_name': sanitize_filename(name),
                    'text': label or name,
                    'from': url,
                    'score': 9,
                })
                processed += 1

            ctx.close(); b.close()
        return out

    seen = set()
    for u in tries:
        if u in seen:
            continue
        seen.add(u)
        try:
            r = req.get(u, purpose="platform:mijnstembureau")
        except Exception:
            continue
        tracer.record_discovery("platform", r.url, "mijnstembureau")
        # Quick direct .pdf anchors (rare on portals)
        try:
            s = BeautifulSoup(r.text or '', 'html.parser')
            for a in s.select('a[href]'):
                href = (a.get('href') or '').strip()
                if not href:
                    continue
                full = href if '://' in href else r.url.rstrip('/') + '/' + href.lstrip('/')
                if full.lower().endswith('.pdf'):
                    items.append({'remote_url': full, 'local_url': None, 'pdf_name': full.rsplit('/',1)[-1], 'text': a.get_text(' ', strip=True) or 'mijnstembureau', 'from': r.url, 'score': 4})
        except Exception:
            pass
        # Prefer the label-based capture on download-opties or general uitslagen pages
        if ('/verkiezingen/tk/download-opties' in (r.url or '')) or ('/uitslagen/' in (r.url or '')):
            cap = _sync_capture_labels(r.url)
            if not cap and '/uitslagen/' in (r.url or ''):
                cap = _sync_capture_labels(base.rstrip('/') + '/uitslagen/verkiezingen/tk/download-opties')
            if cap:
                items.extend(cap)
                break
    return items
