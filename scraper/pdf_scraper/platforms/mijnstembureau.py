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
            # Open Download opties / Processen (ver)verbaal when present
            for sel in [
                'a:has-text("Download opties")','button:has-text("Download opties")','[role=button]:has-text("Download opties")',
                'a:has-text("Processen verbaal")','button:has-text("Processen verbaal")','[role=button]:has-text("Processen verbaal")',
                'a:has-text("Processen-verbaal")','button:has-text("Processen-verbaal")','[role=button]:has-text("Processen-verbaal")',
            ]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click(); page.wait_for_timeout(500)
                except Exception:
                    continue
            btns = page.locator('a, button, [role=button]')
            try:
                n = btns.count()
            except Exception:
                n = 0
            def _looks_name(s: str) -> bool:
                ls = (s or '').lower()
                return ('.pdf' in ls) or any(k in ls for k in ('proces', 'verbaal', 'stembureau', 'download', 'verklaring', 'p2a gsb', 'na14'))
            def _pred(resp):
                try:
                    ct = (resp.headers or {}).get('content-type','').lower()
                    u = (resp.url or '').lower()
                    return (resp.status == 200) and (('application/pdf' in ct) or u.endswith('.pdf') or ('/uitslagen/api/view-pv' in u))
                except Exception:
                    return False
            processed = 0
            for i in range(n):
                if processed >= max_items:
                    break
                try:
                    label = (btns.nth(i).inner_text() or '').strip()
                except Exception:
                    continue
                if not _looks_name(label):
                    continue
                name = label if label.lower().endswith('.pdf') else (label + '.pdf')
                try:
                    with page.expect_response(_pred, timeout=15000) as respctx:
                        btns.nth(i).click()
                    resp = respctx.value
                except Exception:
                    continue
                u = getattr(resp, 'url', '') or ''
                if not u:
                    continue
                out.append({'remote_url': u, 'local_url': None, 'pdf_name': sanitize_filename(name), 'text': label or name, 'from': url, 'score': 8})
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

