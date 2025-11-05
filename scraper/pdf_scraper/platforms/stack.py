from __future__ import annotations

from typing import Dict, List
from bs4 import BeautifulSoup


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    try:
        r = req.get(hub_url, purpose="platform:stack")
    except Exception:
        return items
    tracer.record_discovery("platform", r.url, "stackstorage")
    s = BeautifulSoup(r.text, 'html.parser')
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        if href.lower().endswith('.pdf'):
            name = href.rsplit('/', 1)[-1]
            items.append({'remote_url': href, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or 'stack', 'from': r.url, 'score': 4})
    return items

