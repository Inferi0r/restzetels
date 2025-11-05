from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
import requests

from .config import (
    LIMITS,
    EXTRA_SEEDS,
    PDF_PAGE_HINT_RE,
    OVERVIEW_HINT_RE,
    SITE_SEARCH_QUERIES,
    BANNED_ELECTION_KEYWORDS,
    BANNED_NAME_RES,
)
from .http_client import Requester
from .utils import (
    is_current_year_pdf,
    registrable_origin,
    same_registrable_domain,
    normalize_source_url,
)
from .platforms import detect as detect_platform, REGISTRY as PLATFORM_HANDLERS
from .fallback_playwright import playwright_collect_pdfs_network
from .fetch_gemeente_urls import kiesraad_url_for


def extract_pdf_links_from_html(html: str, base_url: str) -> List[Dict]:
    out: List[Dict] = []
    seen: set[str] = set()
    s = BeautifulSoup(html or "", "html.parser")
    for a in s.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        low_href = href.lower()
        # Skip social/share hosts entirely
        try:
            link_host = (urlparse(full_url).netloc or '').lower()
        except Exception:
            link_host = ''
        if any(soc in link_host for soc in (
            'pinterest.com', 'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com', 'wa.me', 'whatsapp.com'
        )):
            continue
        # Unwrap common viewers (docreader/pdf.js/Viewer.aspx)
        if ("docreader" in low_href or "viewer" in low_href) and ("file=" in low_href or "url=" in low_href or "doc=" in low_href):
            try:
                qs = parse_qs(urlparse(full_url).query)
                url_param = qs.get("file") or qs.get("url") or qs.get("doc") or []
                if url_param:
                    full_url = urljoin(base_url, url_param[0])
            except Exception:
                pass
        path_lower = (urlparse(full_url).path or '').lower()
        txt = a.get_text(" ", strip=True) or a.get('aria-label') or a.get('title') or a.get('data-filename') or ""
        looks_like_pdf = (
            (".pdf" in path_lower)
            or ("/file/" in path_lower)
            or ("/download" in path_lower)
            or ("dsresource" in path_lower)  # only accept dsresource in path, not as a param of a share URL
            or ("type=pdf" in full_url.lower())
            or ("eid=dumpfile" in full_url.lower())
        )
        if not looks_like_pdf:
            continue
        key = full_url
        if key in seen:
            continue
        seen.add(key)
        name = os.path.basename(urlparse(full_url).path) or "document.pdf"
        # Prefer a clean name based on link text when endpoint is generic
        if (not name.lower().endswith('.pdf')) or (name.lower() in {"document.pdf","download.pdf","file.pdf","dsresource.pdf"}):
            from .utils import clean_pdf_name_from_text
            cleaned = clean_pdf_name_from_text(txt or '')
            if cleaned:
                name = cleaned
        # Exclude obvious non-PDF file types by tokens in name/text/url (e.g., csv/xlsx)
        combo_low = (name + ' ' + (txt or '') + ' ' + full_url).lower()
        if any(ext in combo_low for ext in ('.csv', ' csv', '.xlsx', ' xlsx', '.xls', ' xls', '.xml', ' xml', '.json', ' json')):
            continue
        # Also include the referring page URL in the filter so EP/other-election pages are excluded.
        # Treat Bijlage 2 (uitkomsten per stembureau) as relevant election PDFs as well.
        _combo = name + " " + (txt or "") + " " + full_url + " " + (base_url or "")
        _allow_bijlage = ("bijlage" in _combo.lower())
        if not (is_current_year_pdf(_combo) or _allow_bijlage):
            continue
        out.append({
            "remote_url": full_url,
            "local_url": None,
            "pdf_name": name,
            "text": txt,
            "from": base_url,
            "score": 1,
        })
    return out


def extract_pdf_links_from_raw(html: str, base_url: str) -> List[Dict]:
    """Regex-based catch-all for PDF URLs present in raw HTML/JS text."""
    out: List[Dict] = []
    if not html:
        return out
    seen: set[str] = set()
    # Absolute .pdf URLs
    for m in re.finditer(r"https?://[^\s'\"]+\.pdf(?:\?[^\s'\"]*)?", html, re.I):
        u = m.group(0)
        key = u.split('#', 1)[0]
        if key in seen:
            continue
        seen.add(key)
        name = os.path.basename(urlparse(key).path) or 'document.pdf'
        _combo2 = name + ' ' + key + ' ' + (base_url or '')
        _allow_bijlage2 = ('bijlage' in _combo2.lower())
        if not (is_current_year_pdf(_combo2) or _allow_bijlage2):
            continue
        out.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': name, 'from': base_url, 'score': 2})
    # Relative .pdf URLs (common CMS paths like /fileadmin/..., /media/..., /downloads/...)
    try:
        from urllib.parse import urljoin as _uj
    except Exception:
        _uj = None  # type: ignore
    for m in re.finditer(r"/(?:fileadmin|media|downloads|documenten|bestanden)[^'\"\s]+\.pdf(?:\?[^'\"\s]*)?", html, re.I):
        rel = m.group(0)
        if _uj:
            u = _uj(str(base_url), rel)
        else:
            u = rel
        key = u.split('#', 1)[0]
        if key in seen:
            continue
        seen.add(key)
        name = os.path.basename(urlparse(key).path) or 'document.pdf'
        combo = name + ' ' + key + ' ' + (base_url or '')
        allow_bijlage = ('bijlage' in combo.lower())
        if not (is_current_year_pdf(combo) or allow_bijlage):
            continue
        out.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': name, 'from': base_url, 'score': 2})

    # CMS download endpoints that don't end in .pdf (e.g., eID=dumpFile, dsresource, ?download=)
    for m in re.finditer(r"https?://[^\s'\"]+?(?:eID=dumpFile|dsresource|\?download=)[^\s'\"]*", html, re.I):
        u = m.group(0)
        key = u.split('#', 1)[0]
        if key in seen:
            continue
        seen.add(key)
        name = os.path.basename(urlparse(key).path) or 'document.pdf'
        # Exclude obvious non-PDFs first
        low = (name + ' ' + key).lower()
        if any(ext in low for ext in ('.csv', ' csv', '.xlsx', ' xlsx', '.xls', ' xls', '.xml', ' xml', '.json', ' json')):
            continue
        # Allow when URL suggests a file download even if name lacks .pdf
        _combo3 = name + ' ' + key + ' ' + (base_url or '')
        _allow_bijlage3 = ('bijlage' in _combo3.lower())
        if not (is_current_year_pdf(_combo3) or _allow_bijlage3):
            continue
        # Only coerce name to .pdf if query explicitly indicates PDF
        if not name.lower().endswith('.pdf') and ('type=pdf' in key.lower()):
            name = name + '.pdf'
        out.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': name, 'from': base_url, 'score': 2})
    return out


CENTRAL_PV_TEXT_RE = re.compile(r"proces.*verbaal.*(centrale.*stemo|gemeentelijk\s+stembureau|na\s*31)", re.I)


def extract_central_pv_links(html: str, base_url: str) -> List[Dict]:
    out: List[Dict] = []
    seen: set[str] = set()
    s = BeautifulSoup(html or "", "html.parser")
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        full = urljoin(base_url, href)
        if not full.lower().endswith('.pdf'):
            continue
        txt = (a.get_text(' ', strip=True) or '')
        if not CENTRAL_PV_TEXT_RE.search(txt):
            continue
        if full in seen:
            continue
        seen.add(full)
        name = os.path.basename(urlparse(full).path) or 'document.pdf'
        if not is_current_year_pdf(name + ' ' + txt + ' ' + full + ' ' + (base_url or '')):
            continue
        out.append({'remote_url': full, 'local_url': None, 'pdf_name': name, 'text': txt or name, 'from': base_url, 'score': 3})
    return out


def find_overview_pages_from_html(html: str, base_url: str) -> List[str]:
    s = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen: set[str] = set()
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        # Ignore pure fragment/skip links
        if not href or href.startswith('#'):
            continue
        if 'skip' in href.lower():
            # common accessibility anchors like #skip-links-content
            continue
        full = urljoin(base_url, href).split('#', 1)[0]
        low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
        # Skip overview links that clearly refer to other elections (e.g., Europees)
        if any(k in low for k in BANNED_ELECTION_KEYWORDS):
            continue
        if any(rx.search(low) for rx in BANNED_NAME_RES):
            continue
        if OVERVIEW_HINT_RE.search(low):
            if full not in seen:
                seen.add(full); out.append(full)
    return out


def rank_overview_candidates_from_html(html: str, base_url: str) -> List[str]:
    s = BeautifulSoup(html or "", "html.parser")
    scored: List[tuple[int, str]] = []
    seen: set[str] = set()
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        if not href or href.startswith('#'):
            continue
        if 'skip' in href.lower():
            continue
        full = urljoin(base_url, href).split('#', 1)[0]
        if full in seen:
            continue
        seen.add(full)
        # Normalize text and URL for hyphen/underscore separation (tweede-kamer → tweede kamer)
        txt_raw = (a.get_text(' ', strip=True) or '')
        txt = txt_raw.lower()
        txt_norm = txt.replace('-', ' ').replace('_', ' ')
        url_low = full.lower()
        url_norm = url_low.replace('-', ' ').replace('_', ' ')
        # Use only the URL path (exclude scheme to avoid 'https' -> 'ps' false positives)
        try:
            from urllib.parse import urlparse as _up
            path_norm = (_up(full).path or '').lower().replace('-', ' ').replace('_', ' ')
        except Exception:
            path_norm = url_norm
        # Drop pages that are clearly about other elections
        s_all = (path_norm + ' ' + txt_norm)
        if any(k in s_all for k in BANNED_ELECTION_KEYWORDS):
            continue
        if any(rx.search(s_all) for rx in BANNED_NAME_RES):
            continue
        score = 0
        # Strong indicators on URL or text
        strong_kws = ("proces-verbaal", "processen-verbaal", "proces verbaal", "proces-verbalen", "proces verbal", "n10", "na31", "na 31")
        for kw in strong_kws:
            if kw in url_norm:
                score += 4
            if kw in txt_norm:
                score += 3
        # 'pv' is too ambiguous due to 'kinderopvang/opvoeden'; only count when token-like
        def _has_token(s: str, token: str) -> bool:
            return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", s) is not None
        if _has_token(url_norm, 'pv') or _has_token(txt_norm, 'pv'):
            score += 3
        # General overview hints
        for kw in ("verkiez", "tweede kamer", "uitslag", "uitkomst", "stembureau", "gestemd"):
            if kw in url_norm:
                score += 2
            if kw in txt_norm:
                score += 1
        # Strongly prefer explicit TK2025 overview pages
        if ("tweede kamer" in url_norm and "2025" in url_norm) or ("tweede kamer" in txt_norm and "2025" in txt_norm):
            score += 3
        if score >= 3:
            scored.append((score, full))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [u for _, u in scored]


def candidate_overview_paths_for_origin(origin: str) -> List[str]:
    # Compact set of common paths across municipalities
    candidates = [
        # Put the most explicit TK2025 overview first
        "/tweede-kamerverkiezingen-2025/",
        "/uitslagen-tweede-kamerverkiezingen",
        "/uitslag-tweede-kamerverkiezingen",
        "/uitslagen-tweede-kamer-2025",
        "/uitslag-tweede-kamer-2025",
        "/verkiezingen/",
        "/verkiezingen/tweede-kamer/",
        "/verkiezingen/tweede-kamer-2025/",
        "/verkiezingen/uitslagen/",
        "/documenten",
        "/bestanden",
        "/downloads",
        "/zo-is-er-gestemd",
        "/tweedekamerverkiezingen2025/",
        "/tweedekamerverkiezingen2025/uitslag_verkiezingen/",
        "/verkiezingen/uitslag-verkiezingen/",
    ]
    out: List[str] = []
    seen: set[str] = set()
    def add(u: str):
        if u in seen:
            return
        seen.add(u); out.append(u)
    for path in candidates:
        add(origin.rstrip("/") + path)
        # A‑tot‑Z variant
        if not path.startswith("/a-tot-z/"):
            add(origin.rstrip("/") + "/a-tot-z" + path)
        # -2025 variant on last segment
        seg = path.rstrip("/")
        if seg:
            if "/" in seg:
                head, tail = seg.rsplit("/", 1)
                tail_2025 = tail + "-2025"
                add(origin.rstrip("/") + head + "/" + tail_2025)
                if not head.startswith("/a-tot-z"):
                    add(origin.rstrip("/") + "/a-tot-z" + head + "/" + tail_2025)
            else:
                add(origin.rstrip("/") + "/" + seg + "-2025")
                add(origin.rstrip("/") + "/a-tot-z/" + seg + "-2025")
    return out[: LIMITS.max_candidate_overview_pages]


def site_search_endpoints(start_url: str) -> List[str]:
    try:
        pu = urlparse(start_url)
        origin = f"{pu.scheme}://{pu.netloc}"
    except Exception:
        return []
    candidates = [
        "/zoeken", "/zoek", "/zoekresultaten", "/search", "/site-search",
        "/zoeken?search=", "/zoeken?q=", "/search?q=", "/?s=",
    ]
    out: List[str] = []
    seen: set[str] = set()
    for path in candidates:
        u = origin.rstrip('/') + path
        if u in seen:
            continue
        seen.add(u); out.append(u)
    return out


def site_search_discover_pages(req: Requester, start_url: str, queries: List[str]) -> List[str]:
    endpoints = site_search_endpoints(start_url)
    found: List[str] = []
    seen: set[str] = set()
    for ep in endpoints:
        for q in queries:
            try:
                if '?' in ep:
                    url = ep + requests.utils.requote_uri(q)  # type: ignore[name-defined]
                else:
                    for key in ("search", "q", "s"):
                        url = f"{ep}?{key}=" + requests.utils.requote_uri(q)  # type: ignore[name-defined]
                        break
                r = req.get(url, purpose="search", timeout=(8, 15))
            except Exception:
                continue
            try:
                s = r.text.lower()
                if ("verkiez" in s or "stembureau" in s) and ("proces" in s or "verbaal" in s or "pv" in s):
                    base = str(r.url)
                    pages = find_overview_pages_from_html(r.text, base)
                    for p in pages:
                        if p not in seen:
                            seen.add(p); found.append(p)
            except Exception:
                pass
            if len(found) >= LIMITS.max_site_search_tries:
                return found
    return found


def discover_pdfs(req: Requester, tracer, municipality: str, start_url: str) -> List[Dict]:
    tracer.record_meta(start_url=start_url)
    found: List[Dict] = []
    visited_pages: set[str] = set()
    found_urls: set[str] = set()
    probed_urls: set[str] = set()

    # 1) Fetch start page and look for obvious overview and PDFs
    try:
        r = req.get(start_url, purpose="start")
    except Exception:
        r = None
    platform_hubs: List[str] = []
    if r is not None:
        base = str(r.url)
        tracer.record_discovery("start", base)
        try:
            visited_pages.add(normalize_source_url(base))
        except Exception:
            visited_pages.add(base)
        # If start URL is itself a PDF, record immediately
        items: List[Dict] = []
        try:
            ct0 = (r.headers.get('content-type') or '').lower()
        except Exception:
            ct0 = ''
        if ('application/pdf' in ct0) or ((urlparse(base).path or '').lower().endswith('.pdf')):
            name = os.path.basename(urlparse(base).path) or 'document.pdf'
            if is_current_year_pdf(name + ' ' + base):
                items.append({'remote_url': base, 'local_url': None, 'pdf_name': name, 'text': name, 'from': base, 'score': 4})
        else:
            items = extract_pdf_links_from_html(r.text, base)
            if not items:
                regex_items = extract_pdf_links_from_raw(r.text, base)
                # Defer tracing to the unified logging below
                items.extend(regex_items)
        for it in items:
            u = it.get("remote_url") or ""
            if not u or u in found_urls:
                continue
            found_urls.add(u)
            tracer.record_found_pdf(u, it.get("from") or base, it.get("pdf_name") or "", int(it.get("score") or 0))
            found.append(it)
        # Prefer ranking links on the start page rather than site search
        pages = rank_overview_candidates_from_html(r.text, base)
        # Always append a few common candidate paths on the same host (ensures obvious TK pages are probed)
        try:
            pu0 = urlparse(base)
            origin0 = f"{pu0.scheme}://{pu0.netloc}"
            cand = candidate_overview_paths_for_origin(origin0)
            # Prioritize explicit TK 2025 pages first
            def _rank(u: str) -> int:
                ul = u.lower()
                if "tweede-kamerverkiezingen-2025" in ul:
                    return 0
                if "tweede" in ul and "kamer" in ul and "2025" in ul:
                    return 1
                if "tweede-kamer" in ul:
                    return 2
                if "verkiez" in ul:
                    return 3
                return 4
            cand_sorted = sorted(cand, key=_rank)
            # Keep ranked links first; append common candidates that aren't already present
            tail = [c for c in cand_sorted if c not in pages]
            pages = pages + tail
        except Exception:
            pass
        # If start was a direct PDF (often file host), also add Kiesraad municipality page to explore
        try:
            if items and len(items) == 1 and (('application/pdf' in ct0) or base.lower().endswith('.pdf')):
                kr = kiesraad_url_for(municipality)
                if kr:
                    pages.append(kr)
        except Exception:
            pass
        # Detect platform hubs on the start page
        try:
            ssp = BeautifulSoup(r.text or "", "html.parser")
            seen_h = set()
            for a in ssp.select('a[href]'):
                href = (a.get('href') or '').strip()
                if not href or href in seen_h:
                    continue
                seen_h.add(href)
                sysname = detect_platform(href)
                if sysname and href not in platform_hubs:
                    platform_hubs.append(href)
            # Also treat the start URL itself as a platform hub if applicable (mijnstembureau, etc.)
            sysname0 = detect_platform(base)
            if sysname0 and base not in platform_hubs:
                platform_hubs.insert(0, base)
                tracer.record_discovery("platform", base, sysname0)
        except Exception:
            pass
    else:
        pages = []

    # 2) Known extra seeds per municipality
    for seed in EXTRA_SEEDS.get(municipality, []):
        pages.append(seed)

    # 3) (kept for symmetry) If nothing yet, also try common paths on the host
    if not pages:
        try:
            pu = urlparse(start_url)
            origin = f"{pu.scheme}://{pu.netloc}"
        except Exception:
            origin = None
        if origin:
            pages.extend(candidate_overview_paths_for_origin(origin))

    # 4) Try site-search only if nothing obvious yet
    if not found and not pages:
        pages.extend(site_search_discover_pages(req, start_url, SITE_SEARCH_QUERIES))

    # Deduplicate and constrain to same registrable domain
    seenp: set[str] = set()
    pages2: List[str] = []
    for p in pages:
        # Normalize away fragments for dedupe
        p = p.split('#', 1)[0]
        if p in seenp:
            continue
        # Allow same-domain pages relative to either the original start URL or the first resolved page (base),
        # and also recognized platform hubs (e.g., mediafiler)
        allow_same = False
        try:
            allow_same = same_registrable_domain(start_url, p)
        except Exception:
            allow_same = False
        try:
            # 'base' is set when the initial GET succeeded
            if not allow_same:
                allow_same = same_registrable_domain(base, p)  # type: ignore[name-defined]
        except Exception:
            pass
        if allow_same or detect_platform(p):
            seenp.add(p); pages2.append(p)
    # Prefer likely result overview pages early (uitslag/uitkomst/gestemd)
    def _pref_overview(u: str) -> int:
        ul = (u or '').lower()
        if ('verkiezingsuitslag' in ul) or ('uitslag-vaststelling' in ul) or ('verkiezingsuitslagen' in ul) or ('gestemd' in ul) or ('uitkomst' in ul):
            return 0
        return 1
    pages2 = sorted(pages2, key=_pref_overview)

    # 5) Try platform-specific handlers for detected hubs (limited)
    plat_items: List[Dict] = []
    for hub in platform_hubs[: LIMITS.max_platform_hubs]:
        sysname = detect_platform(hub)
        handler = PLATFORM_HANDLERS.get(sysname or "")
        if not handler:
            continue
        try:
            # Skip hub if already visited
            try:
                norm_hub = normalize_source_url(hub)
            except Exception:
                norm_hub = hub
            if norm_hub in visited_pages:
                continue
            visited_pages.add(norm_hub)
            its = handler(hub, req, tracer, municipality)
            if its:
                for it in its:
                    u = it.get("remote_url") or ""
                    if not u or u in found_urls:
                        continue
                    found_urls.add(u)
                    tracer.record_found_pdf(u, it.get("from") or hub, it.get("pdf_name") or "", int(it.get("score") or 0))
                    plat_items.append(it)
        except Exception:
            continue
    if plat_items:
        found.extend(plat_items)

    # 6) Visit up to N overview pages (ranked first) and extract PDFs
    pivot_seen = False
    # Prioritize ranked pages: take only a small number when ranking was non-empty
    max_pages = LIMITS.max_candidate_overview_pages
    if pages and LIMITS.max_ranked_overview_pages < max_pages:
        max_pages = LIMITS.max_ranked_overview_pages
    i = 0
    while i < len(pages2) and i < max_pages:
        p = pages2[i]
        # Skip visiting same page twice in one run
        try:
            norm_p = normalize_source_url(p)
        except Exception:
            norm_p = p
        if norm_p in visited_pages:
            i += 1
            continue
        visited_pages.add(norm_p)
        try:
            rr = req.get(p, purpose="overview")
        except Exception:
            i += 1
            continue
        tracer.record_discovery("overview", str(rr.url))
        # If this URL is itself a direct PDF, record and stop
        try:
            ct = (rr.headers.get('content-type') or '').lower()
        except Exception:
            ct = ''
        if ('application/pdf' in ct) or ((urlparse(str(rr.url)).path or '').lower().endswith('.pdf')):
            name = os.path.basename(urlparse(str(rr.url)).path) or 'document.pdf'
            item = {'remote_url': str(rr.url), 'local_url': None, 'pdf_name': name, 'text': name, 'from': p, 'score': 4}
            label = name + ' ' + item['remote_url']
            if is_current_year_pdf(label) or ('bijlage' in label.lower()):
                found.append(item)
                tracer.record_found_pdf(item['remote_url'], item['from'], item['pdf_name'], item['score'])
                # Do not break; allow scanning remaining candidate pages to collect more
        html = rr.text
        items = extract_pdf_links_from_html(html, rr.url)
        if not items:
            regex_items = extract_pdf_links_from_raw(html, rr.url)
            # Defer tracing to the unified logging below
            items.extend(regex_items)
        # If the page looks like a stembureau list with PDFs but anchors are missing, try a light Playwright network capture
        try:
            low_html = (html or '').lower()
            if (len(items) < 10) and ('stembureau' in low_html) and ('pdf' in low_html):
                extra = playwright_collect_pdfs_network(tracer, municipality, str(rr.url), max_items=200,
                                                       click_selectors=['a[download]', 'a', 'button', '[role=button]'])
                if extra:
                    for it in extra:
                        it['score'] = max(5, int(it.get('score') or 0))
                    items.extend(extra)
        except Exception:
            pass
        # Probe wrapper .htm links that actually serve PDFs (e.g., Oss CMS pages)
        if len(items) < LIMITS.pivot_pdf_threshold:
            try:
                ssp = BeautifulSoup(html or "", "html.parser")
                existing = set(x.get('remote_url') for x in items)
                for a in ssp.select('a[href]'):
                    href = (a.get('href') or '').strip()
                    if not href or href.startswith('#'):
                        continue
                    full = urljoin(str(rr.url), href).split('#', 1)[0]
                    if full in existing:
                        continue
                    low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
                    if not full.lower().endswith(('.htm', '.html')):
                        continue
                    # Strong hints that this .htm anchor could be a PV file when requested directly
                    if (('/tonen-op-pagina-standaard/' in full.lower())
                        or ('tk25' in low)
                        or (('proces' in low) and ('verbaal' in low))
                        or ('stembureau' in low)
                        or ('uitslag' in low)
                        or ('uitkomst' in low)):
                        try:
                            # Avoid probing the same wrapper URL twice
                            if full in probed_urls:
                                continue
                            probed_urls.add(full)
                            if req.probe_pdf_exists(full):
                                name = os.path.basename(urlparse(full).path) or 'document.pdf'
                                # Normalize wrapper names like Oss-xx-....htm to .pdf
                                try:
                                    from .utils import ensure_pdf_extension as _ensure_pdf
                                    name = _ensure_pdf(name)
                                except Exception:
                                    pass
                                it = {'remote_url': full, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or name, 'from': str(rr.url), 'score': 4}
                                items.append(it)
                                existing.add(full)
                        except Exception:
                            continue
            except Exception:
                pass
        # Boost central PVs if present
        items += extract_central_pv_links(html, rr.url)
        if items:
            # De-duplicate logging per run
            seen_urls: set[str] = set(x.get('remote_url') for x in found if isinstance(x, dict))
            for it in items:
                u = it.get("remote_url") or ""
                if not u or u in seen_urls:
                    continue
                seen_urls.add(u)
                tracer.record_found_pdf(u, it.get("from") or str(rr.url), it.get("pdf_name") or "", int(it.get("score") or 0))
                print(f"[CANDIDATE] {u} <- {p}")
                found.append(it)
            if len(items) >= LIMITS.pivot_pdf_threshold:
                pivot_seen = True
                print(f"[PIVOT] {p} yielded {len(items)} PDFs; focusing here.")
        # If this page yielded nothing or only a few items, also enqueue its best nested candidates (one hop)
        if pages and (not items or len(items) < LIMITS.pivot_pdf_threshold):
            try:
                nested = rank_overview_candidates_from_html(html, rr.url)
                # Prefer 'gestemd/uitkomst/uitslag' links among ties
                def _pref(u: str) -> int:
                    ul = u.lower()
                    if ('gestemd' in ul or 'uitkomst' in ul or 'uitslag' in ul
                        or 'proces-verbaal' in ul or 'proces_verbaal' in ul or 'stembureau' in ul):
                        return 0
                    return 1
                nested = sorted(nested, key=_pref)
                added = 0
                for np in nested:
                    if added >= 6:
                        break
                    if (np not in pages2) and (same_registrable_domain(start_url, np) or detect_platform(np)):
                        # Insert immediately after current index so we visit it next
                        pages2.insert(i + 1 + added, np)
                        added += 1
                        print(f"[DISCOVER.NEXT] {np} (from {p})")
            except Exception:
                pass
            i += 1
            continue
        if pivot_seen:
            # Only stop early if no unvisited manual seed pages remain.
            try:
                from .config import EXTRA_SEEDS as _EXTRA
                seeds = set(( _EXTRA.get(municipality) or [] ))
                # simple normalization: strip fragment and trailing slash
                def _norm(u: str) -> str:
                    return (u or '').split('#', 1)[0].rstrip('/')
                remaining = set(_norm(x) for x in seeds) & set(_norm(u) for u in pages2[i+1:])
                if not remaining:
                    break
            except Exception:
                break
        i += 1

    return dedupe_found(found)


def dedupe_found(found: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen: set[str] = set()
    for it in found:
        key = it.get("remote_url") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
