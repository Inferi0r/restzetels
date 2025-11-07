from __future__ import annotations

from typing import Dict, List

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ..utils import sanitize_filename


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    # First pass: try simple HTML extraction of direct .pdf anchors
    try:
        r = req.get(hub_url, purpose="platform:pleio")
    except Exception:
        r = None
    if r is not None:
        tracer.record_discovery("platform", r.url, "pleio")
        try:
            s = BeautifulSoup(r.text or '', 'html.parser')
            for a in s.select('a[href]'):
                href = (a.get('href') or '').strip()
                if not href:
                    continue
                full = urljoin(r.url, href)
                low = full.lower()
                if low.endswith('.pdf') or ('/download/' in low) or ('?download=' in low):
                    name = sanitize_filename((a.get_text(' ', strip=True) or '').strip() or full.rsplit('/', 1)[-1] or 'document.pdf')
                    if not name.lower().endswith('.pdf'):
                        name = name + '.pdf'
                    items.append({'remote_url': full, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or 'Pleio', 'from': r.url, 'score': 5})
        except Exception:
            pass
        # If we already found items, return early
        if items:
            return items
    # Second pass: Use Playwright to visit file view pages and click Download, capturing PDF responses
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return items
    view_links: List[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent='Mozilla/5.0')
        page = ctx.new_page()
        try:
            page.goto(hub_url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass
            # collect view links on the hub
            try:
                loc = page.locator("a[href*='/files/view/']")
                cnt = loc.count()
                for i in range(min(cnt, 200)):
                    href = loc.nth(i).get_attribute('href') or ''
                    if '/files/view/' in href:
                        view_links.append(urljoin(page.url, href))
            except Exception:
                pass
            # Also try Files/Bestanden tab if present
            for sel in ['a[href$="/files"]', 'a:has-text("Bestanden")']:
                try:
                    tab = page.locator(sel)
                    if tab.count() > 0:
                        with page.expect_navigation(timeout=15000):
                            tab.first.click()
                        page.wait_for_timeout(400)
                        try:
                            loc2 = page.locator("a[href*='/files/view/']")
                            cnt2 = loc2.count()
                            for i in range(min(cnt2, 200)):
                                href = loc2.nth(i).get_attribute('href') or ''
                                if '/files/view/' in href:
                                    u = urljoin(page.url, href)
                                    if u not in view_links:
                                        view_links.append(u)
                        except Exception:
                            pass
                except Exception:
                    pass
            # Visit each view link and capture the PDF via Download action or direct download anchors
            seen_urls = set()
            def is_pdf_response(resp) -> bool:
                try:
                    u = (resp.url or '').lower()
                    ct = (resp.headers or {}).get('content-type', '').lower()
                    return (resp.status == 200) and ('application/pdf' in ct or u.endswith('.pdf')) and (resp.url not in seen_urls)
                except Exception:
                    return False
            for v in view_links[:120]:
                try:
                    page.goto(v, wait_until='domcontentloaded', timeout=20000)
                    try:
                        page.wait_for_load_state('networkidle', timeout=6000)
                    except Exception:
                        pass
                    # filename candidates
                    fname = ''
                    try:
                        fname = page.locator('h1, h2').first.inner_text().strip()
                    except Exception:
                        pass
                    # Try direct anchor to pdf
                    try:
                        a_pdf = page.locator('a[href$=".pdf"], a[href*=".pdf?"]')
                        if a_pdf.count() > 0:
                            href = a_pdf.first.get_attribute('href') or ''
                            full = urljoin(page.url, href)
                            nm = sanitize_filename(fname or href.rsplit('/',1)[-1] or 'Pleio-document.pdf')
                            if not nm.lower().endswith('.pdf'):
                                nm += '.pdf'
                            items.append({'remote_url': full, 'local_url': None, 'pdf_name': nm, 'text': nm, 'from': v, 'score': 6})
                            continue
                    except Exception:
                        pass
                    # Try direct Pleio download link anchors
                    try:
                        a_dl = page.locator("a[href*='/file/download/'], a[href*='/files/download/']")
                        if a_dl.count() > 0:
                            href = a_dl.first.get_attribute('href') or ''
                            full = urljoin(page.url, href)
                            nm = sanitize_filename(fname or href.rsplit('/',1)[-1] or 'Pleio-document.pdf')
                            if not nm.lower().endswith('.pdf'):
                                nm += '.pdf'
                            items.append({'remote_url': full, 'local_url': None, 'pdf_name': nm, 'text': nm, 'from': v, 'score': 6})
                            continue
                    except Exception:
                        pass
                    # Click a Download button and capture the PDF response
                    for sel in ['a:has-text("Download")', 'button:has-text("Download")', '[role=button]:has-text("Download")', 'a[href*="download"]']:
                        try:
                            dl = page.locator(sel)
                            if dl.count() == 0:
                                continue
                            with page.expect_response(is_pdf_response, timeout=10000) as respctx:
                                dl.first.click()
                            resp = respctx.value
                            seen_urls.add(resp.url)
                            nm = sanitize_filename(fname or 'Pleio-document.pdf')
                            if not nm.lower().endswith('.pdf'):
                                nm += '.pdf'
                            items.append({'remote_url': resp.url, 'local_url': None, 'pdf_name': nm, 'text': nm, 'from': v, 'score': 7})
                            break
                        except Exception:
                            continue
                except Exception:
                    continue
        finally:
            try:
                ctx.close(); b.close()
            except Exception:
                pass
    return items
