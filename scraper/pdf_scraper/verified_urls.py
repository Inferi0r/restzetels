from __future__ import annotations

import json
import os
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .config import DATA_DIR, REPO_ROOT

NEW_DIR = os.path.join(REPO_ROOT, "pdf_scraper")
VERIFIED_PATH = os.path.join(NEW_DIR, "gemeente_urls_verified.json")
OLD_VERIFIED_PATH = os.path.join(DATA_DIR, "gemeente_urls_verified.json")


def _today() -> str:
    return date.today().isoformat()


def _days_since(day_str: str) -> Optional[int]:
    try:
        d = date.fromisoformat(day_str)
        return (date.today() - d).days
    except Exception:
        return None


def _normalize_entry(ent: dict) -> dict:
    # Convert any known legacy shapes to the new schema:
    # new schema keys: 'kiesraad_urls' and 'pdf_urls' (lists of {url,last_updated})
    kr_list = []
    pdf_list = []
    day = ent.get('last_kiesraad_check') or _today()
    # legacy: { 'kiesraad': [{'url','date'}], 'scraped_sources': [{'url','date'}] }
    for kr in ent.get('kiesraad') or []:
        u = kr.get('url')
        d = kr.get('date') or day
        if u:
            kr_list.append({'url': u, 'last_updated': d})
    for src in ent.get('scraped_sources') or ent.get('sources') or []:
        u = src.get('url') if isinstance(src, dict) else src
        d = (src.get('date') if isinstance(src, dict) else None) or day
        if u:
            pdf_list.append({'url': u, 'last_updated': d})
    # already-new schema (plural arrays)
    for kr in ent.get('kiesraad_urls') or []:
        u = kr.get('url')
        d = kr.get('last_updated') or day
        if u:
            kr_list.append({'url': u, 'last_updated': d})
    for pv in ent.get('pdf_urls') or []:
        u = pv.get('url')
        d = pv.get('last_updated') or day
        if u:
            pdf_list.append({'url': u, 'last_updated': d})
    # already-new schema (single kiesraad_url object)
    kr_single = ent.get('kiesraad_url')
    if isinstance(kr_single, dict):
        u = kr_single.get('url')
        d = kr_single.get('last_updated') or day
        if u:
            kr_list.append({'url': u, 'last_updated': d})
    elif isinstance(kr_single, str) and kr_single:
        kr_list.append({'url': kr_single, 'last_updated': day})
    # Move any kiesraad.nl URLs incorrectly stored under pdf_urls into kiesraad_url
    cleaned_pdf_list: list[dict] = []
    for it in pdf_list:
        try:
            host = urlparse(it.get('url') or '').netloc.lower()
        except Exception:
            host = ''
        if 'kiesraad.nl' in host:
            kr_list.append({'url': it.get('url'), 'last_updated': it.get('last_updated') or day})
        else:
            cleaned_pdf_list.append(it)
    pdf_list = cleaned_pdf_list
    # pick most recent kiesraad as single object
    if kr_list:
        kr_list = sorted(kr_list, key=lambda x: x.get('last_updated') or '', reverse=True)
        kiesraad_url = kr_list[0]
    else:
        kiesraad_url = None
    out = {
        'kiesraad_url': kiesraad_url,
        'pdf_urls': _dedupe_urls(pdf_list),
        'last_kiesraad_check': day,
    }
    return out


def _dedupe_urls(lst: list[dict]) -> list[dict]:
    seen = set(); out = []
    for it in lst:
        u = it.get('url')
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def load_map() -> Dict[str, dict]:
    # Prefer new path under pdf_scraper/
    if os.path.exists(VERIFIED_PATH):
        # Try JSON first
        try:
            with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {k: _normalize_entry(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            # Fallback to tight text format
            try:
                with open(VERIFIED_PATH, 'r', encoding='utf-8') as f:
                    txt = f.read()
                parsed = _parse_tight_text(txt)
                if parsed:
                    return parsed
            except Exception:
                pass
    # Migrate from old path if available
    if os.path.exists(OLD_VERIFIED_PATH):
        try:
            with open(OLD_VERIFIED_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data = {k: _normalize_entry(v) for k, v in data.items() if isinstance(v, dict)}
                    save_map(data)
                    return data
        except Exception:
            pass
    return {}


def save_map(m: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(VERIFIED_PATH), exist_ok=True)
    # Real JSON format, compact (one line objects)
    norm = {k: _normalize_entry(v) for k, v in (m or {}).items() if isinstance(v, dict)}
    # custom pretty: Exactly three lines per municipality
    # 1) "Gemeente":{
    # 2) "kiesraad_url":{...},
    # 3) "pdf_urls":[{...}]}[,|}] (close top-level on last)
    names = sorted(norm.keys())
    out_lines: list[str] = []
    for idx, name in enumerate(names):
        entry = norm[name] or {}
        kr = entry.get('kiesraad_url') or {}
        pdfs = entry.get('pdf_urls') or []
        kr_json = json.dumps(kr, ensure_ascii=False, separators=(',', ':')) if kr else 'null'
        pdf_array = '[' + ','.join(json.dumps(p, ensure_ascii=False, separators=(',', ':')) for p in pdfs) + ']'
        prefix = '{' if idx == 0 else ''
        # Line 1: Gemeente with opening brace
        out_lines.append(prefix + f'"{name}":{{')
        # Line 2: kiesraad_url
        out_lines.append(f'"kiesraad_url":{kr_json},')
        # Line 3: pdf_urls and close this object (and top-level if last)
        tail = '}}' if idx == len(names) - 1 else '},'
        out_lines.append(f'"pdf_urls":{pdf_array}{tail}')
    content = '\n'.join(out_lines) + '\n'
    with open(VERIFIED_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def _parse_tight_text(txt: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not txt:
        return out
    blocks: List[List[str]] = []
    cur: List[str] = []
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(raw.rstrip("\n"))
    if cur:
        blocks.append(cur)
    for blk in blocks:
        if len(blk) < 2:
            continue
        name = blk[0].strip()
        day = blk[1].strip()
        urls = [b.strip() for b in blk[2:] if b.strip()]
        ent = {"kiesraad_url": None, "pdf_urls": [], "last_kiesraad_check": day}
        for u in urls:
            try:
                host = urlparse(u).netloc.lower()
            except Exception:
                host = ''
            if 'kiesraad.nl' in host:
                ent['kiesraad_url'] = {'url': u, 'last_updated': day}
            else:
                ent['pdf_urls'].append({'url': u, 'last_updated': day})
        out[name] = ent
    return out


def get_entry(name: str) -> dict:
    return load_map().get(name) or {}


def record_kiesraad_url(name: str, url: str) -> None:
    m = load_map()
    ent = _normalize_entry(m.get(name) or {})
    if url:
        ent['kiesraad_url'] = {'url': url, 'last_updated': _today()}
    # update last check date
    ent['last_kiesraad_check'] = _today()
    m[name] = ent
    save_map(m)


def add_source_url(name: str, url: str) -> None:
    if not url:
        return
    m = load_map()
    ent = _normalize_entry(m.get(name) or {})
    # Never store Kiesraad links under pdf_urls; keep them in kiesraad_url instead
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ''
    if 'kiesraad.nl' in host:
        record_kiesraad_url(name, url)
        return
    if url not in [x.get('url') for x in (ent.get('pdf_urls') or [])]:
        ent.setdefault('pdf_urls', []).append({'url': url, 'last_updated': _today()})
    m[name] = ent
    save_map(m)


def latest_source_url(entry: dict) -> Optional[str]:
    try:
        entry = _normalize_entry(entry or {})
        srcs = entry.get('pdf_urls') or []
        if not srcs:
            return None
        srcs = sorted(srcs, key=lambda x: x.get('last_updated') or '', reverse=True)
        return srcs[0].get('url')
    except Exception:
        return None


def latest_kiesraad_url(entry: dict) -> Optional[str]:
    try:
        entry = _normalize_entry(entry or {})
        # Prefer singular object if present
        kr = entry.get('kiesraad_url')
        if isinstance(kr, dict) and kr.get('url'):
            return kr.get('url')
        # Legacy plural shape
        ks = entry.get('kiesraad_urls') or []
        if ks:
            ks = sorted(ks, key=lambda x: x.get('last_updated') or '', reverse=True)
            return ks[0].get('url')
        return None
    except Exception:
        return None


def needs_kiesraad_refresh(entry: dict, max_age_days: int = 30) -> bool:
    last = entry.get('last_kiesraad_check')
    if not last:
        return True
    days = _days_since(last)
    if days is None:
        return True
    return days > max_age_days
