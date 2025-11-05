from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlparse
from .utils import same_registrable_domain


def playwright_collect_pdfs(tracer, municipality: str, page_url: str, max_items: int = 200) -> List[Dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[FALLBACK] Playwright not available: {e}")
        return []

    tracer.record_discovery("fallback", page_url, "playwright")
    items: List[Dict] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context()
            page = ctx.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            anchors = page.eval_on_selector_all(
                'a[href]',
                'els => els.map(e => ({href: e.href, text: (e.innerText||"").trim()}))'
            ) or []
            seen = set()
            for a in anchors:
                href = (a.get('href') or '').strip()
                text = (a.get('text') or '').strip()
                if not href or not href.lower().endswith('.pdf'):
                    continue
                key = href.split('?', 1)[0]
                if key in seen:
                    continue
                seen.add(key)
                name = key.rsplit('/', 1)[-1] or 'document.pdf'
                item = {'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': text, 'from': page.url, 'score': 4}
                items.append(item)
                tracer.record_found_pdf(key, page.url, name, 4)
                if len(items) >= max_items:
                    break
            ctx.close(); b.close()
    except Exception as e:
        print(f"[FALLBACK] Playwright failed: {e}")
        return []
    return items


def _score_candidate(url: str, text: str) -> int:
    low_u = (url or '').lower(); low_t = (text or '').lower()
    score = 0
    for kw in ("proces-verbaal", "processen-verbaal", "proces verbaal", "proces-verbalen", "pv", "n10", "na31", "na 31"):
        if kw in low_u:
            score += 4
        if kw in low_t:
            score += 3
    for kw in ("verkiez", "tweede kamer", "uitslag", "stembureau"):
        if kw in low_u:
            score += 2
        if kw in low_t:
            score += 1
    return score


def _looks_overview(url: str, text: str) -> bool:
    low_u = (url or '').lower(); low_t = (text or '').lower()
    keys = ["uitslag", "uitslagen", "overzicht", "proces", "verbaal", "verbalen", "stembureau", "pv", "n10", "na31", "na 31", "verkiez"]
    return any(k in low_u for k in keys) or any(k in low_t for k in keys)


def playwright_discover_and_collect(tracer, municipality: str, start_url: str, max_pages: int = 3, max_items: int = 250) -> List[Dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[FALLBACK] Playwright not available: {e}")
        return []
    items: List[Dict] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context()
            page = ctx.new_page()
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            anchors = page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: (e.innerText||"").trim()}))') or []
            # If the start page itself looks like an overview, just collect PDFs from it and stop
            if _looks_overview(start_url, ''):
                ctx.close(); b.close()
                return playwright_collect_pdfs(tracer, municipality, start_url, max_items=max_items)

            # Else pick the best same-domain, non-PDF candidate and collect PDFs from that single page
            host = urlparse(start_url).netloc
            best_u = None; best_t = '';
            best_s = -1
            seen = set()
            for a in anchors:
                href = (a.get('href') or '').strip(); text = (a.get('text') or '').strip()
                if not href or href in seen:
                    continue
                seen.add(href)
                if href.lower().endswith('.pdf'):
                    continue
                if not same_registrable_domain(start_url, href):
                    continue
                s = _score_candidate(href, text)
                if s > best_s:
                    best_s = s; best_u = href; best_t = text
            if best_u:
                tracer.record_discovery("fallback-cand", best_u, best_t)
                ctx.close(); b.close()
                return playwright_collect_pdfs(tracer, municipality, best_u, max_items=max_items)
            ctx.close(); b.close()
    except Exception as e:
        print(f"[FALLBACK] Playwright failed: {e}")
        return []
    return items


def playwright_collect_pdfs_network(tracer, municipality: str, page_url: str, max_items: int = 250, click_selectors: list[str] | None = None) -> List[Dict]:
    """Render a dynamic page and capture PDF responses via network events.

    - Listens for responses with Content-Type containing 'pdf'.
    - Optionally clicks elements to trigger downloads (anchors/buttons).
    - Returns synthetic items for each captured PDF URL.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[FALLBACK] Playwright not available: {e}")
        return []

    tracer.record_discovery("fallback", page_url, "playwright-network")
    items: List[Dict] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(accept_downloads=True)
            page = ctx.new_page()
            seen = set()
            # Capture PDF-like responses and also track requests to reconstruct URLs even if downloads are triggered
            request_urls = set()
            name_from_download: dict[str, str] = {}
            def on_download(d):
                try:
                    url = d.url or ''
                    name = d.suggested_filename or ''
                    if url and name:
                        from .utils import clean_pdf_name_from_text as _clean_nm  # type: ignore[attr-defined]
                        nm = _clean_nm(name) or name
                        name_from_download[url] = nm
                except Exception:
                    pass
            def on_request(req):
                try:
                    u = req.url or ''
                except Exception:
                    u = ''
                ul = u.lower()
                # Only collect clear PDF endpoints; avoid generic pages like '/download-opties'
                if ('/uitslagen/api/view-pv' in ul) or ul.endswith('.pdf') or ('type=pdf' in ul):
                    request_urls.add(u)
            def on_response(resp):
                try:
                    headers = resp.headers or {}
                    ct = (headers.get('content-type') or '').lower()
                except Exception:
                    ct = ''
                if 'pdf' in ct:
                    u = resp.url
                    key = u.split('?',1)[0]
                    if key in seen:
                        return
                    seen.add(key)
                    # Prefer filename from Content-Disposition
                    try:
                        cd = headers.get('content-disposition') or ''
                        import re as _re
                        m = _re.search(r'filename\*=UTF-8\'\'([^;]+)', cd) or _re.search(r'filename="?([^";]+)"?', cd)
                        if m:
                            from .utils import clean_pdf_name_from_text as _clean_cd  # type: ignore[attr-defined]
                            name = _clean_cd(m.group(1)) or (key.rsplit('/', 1)[-1] or 'document.pdf')
                        else:
                            name = key.rsplit('/', 1)[-1] or 'document.pdf'
                    except Exception:
                        name = key.rsplit('/', 1)[-1] or 'document.pdf'
                    item = {'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': 'network', 'from': page_url, 'score': 7}
                    items.append(item)
                    try:
                        tracer.record_found_pdf(key, page.url, name, 7)
                    except Exception:
                        pass
            page.on('response', on_response)
            page.on('request', on_request)
            try:
                page.on('download', on_download)
            except Exception:
                pass
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # Try to click common download triggers if provided/known
            sels = click_selectors or ['a[download]', 'button', 'a[href*="pdf"]']
            try:
                for sel in sels:
                    # Use evaluate to click a limited number of elements per selector
                    page.evaluate(
                        "(sel, limit) => { const els = Array.from(document.querySelectorAll(sel)).slice(0, limit); els.forEach(e => e.click()); }",
                        sel, 200
                    )
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    if len(items) >= max_items:
                        break
            except Exception:
                pass
            # Build items from any captured request URLs as well (fallback if response headers hid content-type)
            for u in list(request_urls):
                try:
                    key = u.split('?', 1)[0]
                    if any(it.get('remote_url') == key for it in items):
                        continue
                    name = name_from_download.get(u) or (key.rsplit('/', 1)[-1] or 'document.pdf')
                    items.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': 'network-req', 'from': page_url, 'score': 6})
                except Exception:
                    continue
            ctx.close(); b.close()
    except Exception as e:
        print(f"[FALLBACK] Playwright failed: {e}")
        return items
    return items
