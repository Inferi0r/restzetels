from __future__ import annotations

import os
from typing import List, Dict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http_client import Requester
from ..utils import same_registrable_domain
from ..utils import is_current_year_pdf


def handle(hub_url: str, req: Requester, tracer, municipality: str) -> List[Dict]:
    """Generic handler for verkiezingen.<domain> portals.

    Strategy:
    - Fetch the hub URL and extract PDFs directly (anchors and raw).
    - BFS crawl within the same host following links that look like PV/uitslag pages
      (proces/verbaal/stembureau/uitslag/uitkomst/tk25/na31/n10) up to a small budget.
    - Return collected items, letting discovery de-dup downstream.
    """
    out: List[Dict] = []
    seen_urls: set[str] = set()
    def add_items(items: List[Dict]):
        nonlocal out, seen_urls
        for it in items or []:
            u = it.get('remote_url') or ''
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            out.append(it)

    # Simple BFS within same host
    q: List[str] = [hub_url]
    visited: set[str] = set()
    max_pages = 25
    i = 0
    while q and i < max_pages:
        url = q.pop(0)
        if not url or url in visited:
            continue
        visited.add(url)
        try:
            r = req.get(url, purpose="platform:verkiezingen")
        except Exception:
            continue
        tracer.record_discovery("platform", str(r.url), "verkiezingen-portal")
        html = r.text or ""
        # Extract PDFs from this page (inline implementation to avoid circular import)
        add_items(_extract_pdfs_from_html(html, str(r.url)))
        # If we already have many PVs, stop early
        if len(out) >= 6:
            # Still enqueue a few likely children once to catch the main PV table page
            pass
        # Discover child links likely to contain PVs
        try:
            s = BeautifulSoup(html, 'html.parser')
        except Exception:
            s = None
        if not s:
            i += 1
            continue
        # Handle meta refresh pointing to actual app path (e.g., /v2/)
        try:
            for m in s.select('meta[http-equiv]'):
                hv = (m.get('http-equiv') or '').strip().lower()
                if hv != 'refresh':
                    continue
                content = (m.get('content') or '')
                # formats like '1; URL=https://host/path'
                parts = [x.strip() for x in content.split(';')]
                for p in parts:
                    if p.lower().startswith('url='):
                        tgt = p.split('=', 1)[-1].strip().strip('"').strip("'")
                        if tgt:
                            full = urljoin(r.url, tgt)
                            if same_registrable_domain(hub_url, full) and (full not in visited) and (full not in q):
                                q.append(full)
        except Exception:
            pass
        def _looks_pv_link(href: str, text: str) -> bool:
            low = (href + ' ' + text).lower()
            return any(k in low for k in (
                'proces', 'verbaal', 'stembureau', 'uitslag', 'uitkomst', 'tk25', 'tk-25', 'tk 25', 'na31', 'n10'
            ))
        # anchors
        for a in s.select('a[href]'):
            href = (a.get('href') or '').strip()
            if not href:
                continue
            full = urljoin(r.url, href).split('#', 1)[0]
            if not same_registrable_domain(hub_url, full):
                continue
            if full in visited or full in q:
                continue
            if _looks_pv_link(full, a.get_text(' ', strip=True) or ''):
                q.append(full)
        # iframes sometimes hold embedded PV pages
        for f in s.select('iframe[src]'):
            src = (f.get('src') or '').strip()
            if not src:
                continue
            full = urljoin(r.url, src).split('#', 1)[0]
            if same_registrable_domain(hub_url, full) and (full not in visited) and (full not in q):
                q.append(full)
        # Detect dynamic loader endpoints referenced in inline scripts (e.g., 'gegevens.php?verkiezing=TK2025')
        try:
            for sc in s.select('script'):
                if sc.get('src'):
                    continue
                txt = sc.string or sc.get_text() or ''
                if not txt:
                    continue
                if 'gegevens.php' in txt:
                    # default to TK2025; also try TK25 as fallback
                    for k in ('TK2025', 'TK25'):
                        rel = f"gegevens.php?verkiezing={k}"
                        full = urljoin(r.url, rel)
                        if same_registrable_domain(hub_url, full) and (full not in visited) and (full not in q):
                            q.append(full)
        except Exception:
            pass
        # As a last resort on the first page, probe a few common candidate paths under the same origin
        if i == 0 and len(q) < 3:
            cand = _candidate_paths_for_portal(str(r.url))
            for cu in cand:
                if cu not in visited and cu not in q:
                    q.append(cu)
        i += 1
        # modest cap on total items from this handler
        if len(out) >= 450:
            break
    return out


def _extract_pdfs_from_html(html: str, base_url: str) -> List[Dict]:
    out: List[Dict] = []
    seen: set[str] = set()
    if not html:
        return out
    try:
        s = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return out
    # Anchors
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        low = full.lower()
        # common CMS endpoints or direct PDFs
        looks_pdf = ('.pdf' in low) or ('/file/' in low) or ('dsresource' in low) or ('eid=dumpfile' in low) or ('?download=' in low)
        if not looks_pdf:
            continue
        if full in seen:
            continue
        seen.add(full)
        name = os.path.basename(urlparse(full).path) or 'document.pdf'
        txt = a.get_text(' ', strip=True) or ''
        combo = name + ' ' + txt + ' ' + full + ' ' + (base_url or '')
        if not is_current_year_pdf(combo):
            continue
        if not name.lower().endswith('.pdf'):
            try:
                from ..utils import clean_pdf_name_from_text as _clean_name
                cleaned = _clean_name(txt or '')
            except Exception:
                cleaned = None
            pdf_name = cleaned or (name + '.pdf')
        else:
            pdf_name = name
        out.append({'remote_url': full, 'local_url': None, 'pdf_name': pdf_name, 'text': txt, 'from': base_url, 'score': 4})
    # Raw URLs inside scripts/text
    import re as _re
    for m in _re.finditer(r"https?://[^\s'\"]+\.pdf(?:\?[^\s'\"]*)?", html, _re.I):
        u = m.group(0)
        key = u.split('#', 1)[0]
        if key in seen:
            continue
        seen.add(key)
        name = os.path.basename(urlparse(key).path) or 'document.pdf'
        combo = name + ' ' + key + ' ' + (base_url or '')
        if not is_current_year_pdf(combo):
            continue
        out.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': name, 'from': base_url, 'score': 3})
    return out


def _candidate_paths_for_portal(base: str) -> List[str]:
    try:
        u = urlparse(base)
        origin = f"{u.scheme}://{u.netloc}"
    except Exception:
        return []
    paths = [
        "/verkiezing",
        "/verkiezingen",
        "/verkiezingsuitslagen",
        "/uitslag",
        "/uitslagen",
        "/tweede-kamer-2025",
        "/tweede-kamerverkiezingen-2025",
        "/verkiezing-tweede-kamer-2025",
        "/proces-verbaal",
        "/processen-verbaal",
        "/proces-verbaal-stembureaus",
        "/processen-verbaal-stembureaus",
    ]
    out = []
    seen = set()
    for p in paths:
        url = origin.rstrip('/') + p
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
