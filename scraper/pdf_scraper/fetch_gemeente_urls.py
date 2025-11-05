from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


KIESRAAD_URL = "https://www.kiesraad.nl/verkiezingen/tweede-kamer/uitslagen/uitslagen-per-gemeente-tweede-kamer"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36"


def _normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s'`’\-]+", "", s)
    s = s.replace("’", "").replace("‘", "").replace("´", "")
    return s


@lru_cache(maxsize=1)
def get_kiesraad_links() -> Dict[str, str]:
    d: Dict[str, str] = {}
    try:
        r = requests.get(KIESRAAD_URL, headers={"User-Agent": UA, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.6"}, timeout=30)
        r.raise_for_status()
    except Exception:
        return d
    s = BeautifulSoup(r.text, "html.parser")
    for a in s.select('a[href]'):
        text = (a.get_text(" ", strip=True) or "").strip()
        href = (a.get('href') or '').strip()
        if not text or not href:
            continue
        # Only store links that look like municipal domains, not internal anchors
        if href.startswith('/'):
            continue
        key = _normalize(text)
        if not key:
            continue
        # Prefer links that contain election paths
        if ('verkiez' in href.lower()) or ('stembureau' in href.lower()):
            d[key] = href
        else:
            d.setdefault(key, href)
    return d


def kiesraad_url_for(name: str) -> Optional[str]:
    m = _normalize(name)
    links = get_kiesraad_links()
    return links.get(m)

