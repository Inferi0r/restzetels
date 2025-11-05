from __future__ import annotations

from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    try:
        r = req.get(hub_url, purpose="platform:decos")
    except Exception:
        return items
    tracer.record_discovery("platform", r.url, "decos")
    s = BeautifulSoup(r.text, 'html.parser')
    seen = set()
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        low = href.lower()
        if low.endswith('.pdf') or 'dsresource' in low or '/file/' in low or '/document' in low:
            full = href if '://' in href else urljoin(r.url, href)
            key = full.split('#', 1)[0]
            if key in seen:
                continue
            seen.add(key)
            name = key.rsplit('/', 1)[-1] or 'document.pdf'
            items.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or 'decos', 'from': r.url, 'score': 4})
    return items

