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
