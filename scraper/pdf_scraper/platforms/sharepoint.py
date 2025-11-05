from __future__ import annotations

from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _is_pdf_like(href: str) -> bool:
    l = (href or '').lower()
    return l.endswith('.pdf') or 'download.aspx' in l or 'sourceurl=' in l or 'download=1' in l


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    try:
        r = req.get(hub_url, purpose="platform:sharepoint")
    except Exception:
        return items
    tracer.record_discovery("platform", r.url, "sharepoint")
    s = BeautifulSoup(r.text, 'html.parser')
    seen = set()
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        if not _is_pdf_like(href):
            continue
        full = href if '://' in href else urljoin(r.url, href)
        key = full.split('#', 1)[0]
        if key in seen:
            continue
        seen.add(key)
        name = key.rsplit('/', 1)[-1]
        items.append({'remote_url': key, 'local_url': None, 'pdf_name': name or 'document.pdf', 'text': a.get_text(' ', strip=True) or 'sharepoint', 'from': r.url, 'score': 5})
    return items

