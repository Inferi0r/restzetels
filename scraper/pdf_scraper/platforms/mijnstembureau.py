from __future__ import annotations

from typing import Dict, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from ..utils import sanitize_filename
import re


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
    tries = []
    # If hub_url is a uitslagen page, try that first
    tries.append(hub_url)
    for p in _candidate_paths():
        tries.append(base.rstrip('/') + p)
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
        s = BeautifulSoup(r.text, 'html.parser')
        for a in s.select('a[href]'):
            href = (a.get('href') or '').strip().split('#',1)[0]
            low = href.lower()
            # Direct pdf links
            if low.endswith('.pdf'):
                items.append({'remote_url': href if '://' in href else r.url.rsplit('/',1)[0] + '/' + href.strip('/'), 'local_url': None, 'pdf_name': href.rsplit('/',1)[-1], 'text': a.get_text(' ', strip=True) or 'mijnstembureau', 'from': r.url, 'score': 6})
            # API view-pv endpoints typically return PDFs directly
            if '/uitslagen/api/view-pv' in low:
                full = href if '://' in href else base.rstrip('/') + '/' + href.lstrip('/')
                items.append({'remote_url': full, 'local_url': None, 'pdf_name': 'pv.pdf', 'text': 'view-pv', 'from': r.url, 'score': 7})
        # Heuristic: extract view-pv endpoints from raw HTML (Nuxt apps) when anchors are not present
        if not items:
            try:
                # absolute URLs
                for m in re.finditer(r'https?://[^\s\"\']+/uitslagen/(?:api/)?view-pv[^\s\"\']*', r.text, re.I):
                    url = m.group(0)
                    items.append({'remote_url': url, 'local_url': None, 'pdf_name': 'pv.pdf', 'text': 'view-pv', 'from': r.url, 'score': 7})
                # relative URLs
                for m in re.finditer(r'(/uitslagen/(?:api/)?view-pv[^\s\"\']*)', r.text, re.I):
                    url = base.rstrip('/') + m.group(1)
                    if not any(it['remote_url'] == url for it in items):
                        items.append({'remote_url': url, 'local_url': None, 'pdf_name': 'pv.pdf', 'text': 'view-pv', 'from': r.url, 'score': 7})
            except Exception:
                pass
        # If still nothing, fetch a few Nuxt asset chunks and scan for view-pv endpoints
        if not items:
            try:
                asset_urls = []
                # link[rel=modulepreload|prefetch]
                for link in s.select('link[href]'):
                    rel = (link.get('rel') or [])
                    rels = ' '.join(rel).lower() if isinstance(rel, list) else str(rel).lower()
                    if 'modulepreload' in rels or 'prefetch' in rels or link.get('as') == 'script':
                        href = (link.get('href') or '').strip()
                        if href and '/uitslagen/_nuxt/' in href:
                            full = href if '://' in href else base.rstrip('/') + href
                            if full not in asset_urls:
                                asset_urls.append(full)
                # script[src]
                for sc in s.select('script[src]'):
                    src = (sc.get('src') or '').strip()
                    if src and '/uitslagen/_nuxt/' in src:
                        full = src if '://' in src else base.rstrip('/') + src
                        if full not in asset_urls:
                            asset_urls.append(full)
                for au in asset_urls[:5]:
                    try:
                        ar = req.get(au, purpose="platform:mijnstembureau-asset", timeout=(8,15))
                    except Exception:
                        continue
                    for m in re.finditer(r'(/uitslagen/(?:api/)?view-pv[^\s\"\']*)', ar.text, re.I):
                        url = base.rstrip('/') + m.group(1)
                        if not any(it['remote_url'] == url for it in items):
                            items.append({'remote_url': url, 'local_url': None, 'pdf_name': 'pv.pdf', 'text': 'view-pv', 'from': u, 'score': 7})
                    if items:
                        break
            except Exception:
                pass
        if items:
            break
    # If still nothing, try Playwright (async API in a background thread) to capture PDF responses on clicks
    if not items:
        try:
            import asyncio, threading, queue
            from playwright.async_api import async_playwright
        except Exception:
            return items
        def run_async(func, *a, **kw):
            q = queue.Queue()
            def _runner():
                try:
                    res = asyncio.run(func(*a, **kw))
                    q.put(res)
                except Exception as e:
                    q.put(e)
            t = threading.Thread(target=_runner, daemon=True)
            t.start(); t.join()
            val = q.get()
            if isinstance(val, Exception):
                raise val
            return val
        def _looks_hashy(name: str) -> bool:
            try:
                b = (name or '').strip().lower().split('.',1)[0]
                return bool(re.fullmatch(r"[0-9a-f]{16,}", b) or re.fullmatch(r"[0-9a-z]{24,}", b))
            except Exception:
                return False

        async def _collect(url: str):
            out = []
            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True)
                ctx = await b.new_context()
                page = await ctx.new_page()
                found = set()
                req_found = set()
                def _on_response(resp):
                    try:
                        u = (resp.url or '')
                        ct = (resp.headers or {}).get('content-type','').lower()
                        if (resp.status == 200) and (('application/pdf' in ct) or 'octet-stream' in ct or u.lower().endswith('.pdf') or '/uitslagen/api/view-pv' in u.lower()):
                            if u not in found:
                                found.add(u)
                    except Exception:
                        pass
                def _on_request(req):
                    try:
                        u = (req.url or '')
                        if '/uitslagen/api/view-pv' in u.lower():
                            req_found.add(u)
                    except Exception:
                        pass
                page.on('response', _on_response)
                page.on('request', _on_request)
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                # click likely buttons
                keys = ['Proces', 'verbaal', 'N10', 'PV', 'Download', 'bekijk', 'opties', 'pdf', 'Telling', 'Stembureau', 'Processen', 'model']
                loc = page.locator('a, button, [role=button]')
                n = min(await loc.count(), 140)
                # click some by text first
                for k in keys:
                    try:
                        await page.get_by_text(k, exact=False).first.click(timeout=800)
                    except Exception:
                        continue
                for i in range(n):
                    el = loc.nth(i)
                    try:
                        label = (await el.inner_text() or '').strip()
                    except Exception:
                        label = ''
                    try:
                        await el.click(timeout=500)
                    except Exception:
                        continue
                # small wait to allow responses
                try:
                    await page.wait_for_timeout(2500)
                except Exception:
                    pass
                # collect anchors created dynamically to use their text as names
                try:
                    anchors = await page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: (e.innerText||"").trim()}))')
                except Exception:
                    anchors = []
                await ctx.close(); await b.close()
                for u in found.union(req_found):
                    name = u.rsplit('/',1)[-1] or 'pv.pdf'
                    # prefer anchor text for naming when hashy/blob
                    label = ''
                    for a in anchors or []:
                        href = (a.get('href') or '')
                        if href and (href == u or ('view-pv' in href and 'view-pv' in u)):
                            label = (a.get('text') or '').strip()
                            break
                    if label:
                        nm = sanitize_filename(label)
                        if not nm.lower().endswith('.pdf'):
                            nm += '.pdf'
                        name = nm
                    elif _looks_hashy(name) or u.lower().startswith('blob:'):
                        name = 'Proces-verbaal.pdf'
                    out.append({'remote_url': u, 'local_url': None, 'pdf_name': name, 'text': label or 'view-pv', 'from': url, 'score': 7})
            return out
        try:
            # Prefer the download-opties page for capture
            target = base.rstrip('/') + '/uitslagen/verkiezingen/tk/download-opties'
            cap = run_async(_collect, target)
            if not cap:
                cap = run_async(_collect, hub_url)
            if cap:
                items.extend(cap)
        except Exception:
            pass
    return items
