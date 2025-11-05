from __future__ import annotations

from typing import Dict, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from ..utils import sanitize_filename
from ..fallback_playwright import playwright_collect_pdfs
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
    # Helper: targeted async capture that clicks per visible filename and binds it to view-pv requests
    def _capture_by_names(url: str) -> List[Dict]:
        try:
            import asyncio
            from playwright.async_api import async_playwright
        except Exception:
            return []
        async def _ac():
            out = []
            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True)
                ctx = await b.new_context()
                page = await ctx.new_page()
                found = set(); req_found = set(); name_by_url = {}; seq = []
                def _on_response(resp):
                    try:
                        u = (resp.url or '')
                        ct = (resp.headers or {}).get('content-type','').lower()
                        if (resp.status == 200) and (('application/pdf' in ct) or 'octet-stream' in ct or u.lower().endswith('.pdf') or '/uitslagen/api/view-pv' in u.lower()):
                            if u not in found:
                                found.add(u); seq.append(u)
                    except Exception:
                        pass
                def _on_request(rq):
                    try:
                        u = (rq.url or '')
                        if '/uitslagen/api/view-pv' in u.lower():
                            if u not in req_found:
                                req_found.add(u); seq.append(u)
                    except Exception:
                        pass
                page.on('response', _on_response)
                page.on('request', _on_request)
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                # Collect names from DOM (broad; filter in Python)
                try:
                    names_raw = await page.evaluate(
                        "() => { const out=[]; const els = Array.from(document.querySelectorAll('a,button,li,div,p,span'));\n"
                        "for (const e of els){ const t=(e.innerText||'').trim(); if (t) out.push(t); }\n"
                        "return out; }"
                    )
                except Exception:
                    names_raw = []
                from ..utils import clean_pdf_name_from_text as _clean_txt
                names_queue = []
                seen_nm = set()
                import re as _re2
                for t in names_raw or []:
                    nm = None
                    m = _re2.search(r'(Rijssen-?Holten[^\n]*?)(?:\.pdf)?\b', t, _re2.I)
                    if m:
                        nm = m.group(1)
                    else:
                        for patt in (r'Verklaring\s*B&?W[^\n]*', r'P2a\s*GSB[^\n]*', r'Na14[^\n]*'):
                            mm = _re2.search(patt, t, _re2.I)
                            if mm:
                                nm = mm.group(0)
                                break
                    if nm:
                        try:
                            nm2 = _clean_txt(nm)
                        except Exception:
                            nm2 = None
                        if nm2 and nm2 not in seen_nm:
                            seen_nm.add(nm2); names_queue.append(nm2)
                # Click each name's nearest control and bind to ensuing view-pv request
                click_js = """
                    (text) => {
                      const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                      const match = Array.from(document.querySelectorAll('a,button,div,li,span,p'))
                        .find(e => norm(e.innerText||'').includes(norm(text)));
                      if (!match) return false;
                      const root = match.closest('li, tr, .row, .download, .download-option, .v-list-item, .item, .wrapper, .container') || match;
                      const btn = root.querySelector('a[download], a[href*="view-pv"], a[href*="pdf"], button, [role=button]');
                      if (btn) { btn.scrollIntoView({block:'center'}); btn.click(); return true; }
                      match.scrollIntoView({block:'center'}); match.click();
                      return true;
                    }
                """
                for nm in list(names_queue):
                    try:
                        await page.evaluate(click_js, nm)
                        try:
                            reqv = await page.wait_for_request(lambda r: '/uitslagen/api/view-pv' in (r.url or '').lower(), timeout=6000)
                            if reqv:
                                u = reqv.url
                                if u and (u not in name_by_url):
                                    name_by_url[u] = nm
                                    if u not in req_found:
                                        req_found.add(u); seq.append(u)
                        except Exception:
                            pass
                    except Exception:
                        continue
                # If no names discovered, or still missing many, iterate clickable elements and extract name from container text
                try:
                    loc = page.locator('a[download], a[href*="view-pv"], a[href*="pdf"], button, [role=button]')
                    total = min(await loc.count(), 400)
                except Exception:
                    total = 0
                def _extract_name_js():
                    return """
                        (el) => {
                          const root = el.closest('li, tr, .row, .download, .download-option, .v-list-item, .item, .wrapper, .container') || el;
                          return (root.innerText||'').trim();
                        }
                    """
                import re as _re
                for i in range(total):
                    try:
                        el = loc.nth(i)
                        try:
                            txt = await page.evaluate(_extract_name_js(), el)
                        except Exception:
                            txt = ''
                        nm = None
                        if txt:
                            m = _re.search(r'(Rijssen-?Holten[^\n]*?\.pdf|Verklaring\s*B&?W[^\n]*?\.pdf|P2a\s*GSB[^\n]*?\.pdf|Na14[^\n]*?\.pdf)', txt, _re.I)
                            if m:
                                from ..utils import clean_pdf_name_from_text as _clean2
                                nm = _clean2(m.group(1))
                        try:
                            await el.click(timeout=800)
                        except Exception:
                            continue
                        try:
                            reqv = await page.wait_for_request(lambda r: '/uitslagen/api/view-pv' in (r.url or '').lower(), timeout=4000)
                        except Exception:
                            reqv = None
                        if reqv:
                            u = reqv.url
                            if u:
                                if nm and (u not in name_by_url):
                                    name_by_url[u] = nm
                                if u not in req_found:
                                    req_found.add(u); seq.append(u)
                    except Exception:
                        # ensure the outer try has a corresponding except clause
                        pass
                ordered = []
                for u in seq:
                    if u in req_found:
                        ordered.append(u)
                for u in ordered:
                    name = name_by_url.get(u) or 'Proces-verbaal.pdf'
                    out.append({'remote_url': u, 'local_url': None, 'pdf_name': name, 'text': 'view-pv', 'from': url, 'score': 8})
                await ctx.close(); await b.close()
            return out
        try:
            return asyncio.run(_ac())
        except Exception:
            return []

    # Synchronous Playwright capture modeled after compact scraper: use label text + expect_response
    def _sync_capture_labels(url: str, max_items: int = 250) -> List[Dict]:
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
            # Open Download opties and PV section if present
            try:
                for sel in [
                    'a:has-text("Download opties")','button:has-text("Download opties")','[role=button]:has-text("Download opties")',
                    'a:has-text("Processen verbaal")','button:has-text("Processen verbaal")','[role=button]:has-text("Processen verbaal")',
                    'a:has-text("Processen-verbaal")','button:has-text("Processen-verbaal")','[role=button]:has-text("Processen-verbaal")',
                ]:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.click(); page.wait_for_timeout(600)
                    except Exception:
                        continue
            except Exception:
                pass
            # Iterate candidate controls
            btns = page.locator('a, button, [role=button]')
            try:
                n = btns.count()
            except Exception:
                n = 0
            def _looks_name(s: str) -> bool:
                ls = (s or '').lower()
                if '.pdf' in ls:
                    return True
                for kw in ['rijssen-holten_', 'verklaring', 'p2a gsb', 'na14']:
                    if kw in ls:
                        return True
                return False
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
                name = label.strip()
                if not name.lower().endswith('.pdf'):
                    name = name + '.pdf'
                try:
                    with page.expect_response(_pred, timeout=15000) as respctx:
                        btns.nth(i).click()
                    resp = respctx.value
                except Exception:
                    continue
                try:
                    u = resp.url
                except Exception:
                    u = ''
                if not u:
                    continue
                out.append({'remote_url': u, 'local_url': None, 'pdf_name': sanitize_filename(name), 'text': label or name, 'from': url, 'score': 8})
                processed += 1
            ctx.close(); b.close()
        return out

    for u in tries:
        if u in seen:
            continue
        seen.add(u)
        try:
            r = req.get(u, purpose="platform:mijnstembureau")
        except Exception:
            continue
        tracer.record_discovery("platform", r.url, "mijnstembureau")
        # If this is the download options page, use targeted capture immediately
        try:
            if '/verkiezingen/tk/download-opties' in (r.url or ''):
                cap = _capture_by_names(r.url)
                if cap:
                    for it in cap:
                        items.append(it)
                # Fallback: sync capture by labels (expect_response)
                if len(items) < 10:
                    sync_cap = _sync_capture_labels(r.url, max_items=300)
                    if sync_cap:
                        items.extend(sync_cap)
                # do not break; continue to allow backups as well
        except Exception:
            pass
        s = BeautifulSoup(r.text, 'html.parser')
        # Collect declared download filenames from DOM (a[download]) for later naming
        declared_names: list[str] = []
        try:
            from ..utils import clean_pdf_name_from_text as _clean
            seen_nm = set()
            for a in s.select('a[download], button[download]'):
                dl = (a.get('download') or '').strip()
                if not dl:
                    continue
                nm = _clean(dl)
                if nm and nm not in seen_nm:
                    seen_nm.add(nm); declared_names.append(nm)
        except Exception:
            pass
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
                for au in asset_urls[:12]:
                    try:
                        ar = req.get(au, purpose="platform:mijnstembureau-asset", timeout=(8,15))
                    except Exception:
                        continue
                    for m in re.finditer(r'(/uitslagen/(?:api/)?view-pv[^\s\"\']*)', ar.text, re.I):
                        url = base.rstrip('/') + m.group(1)
                        if not any(it['remote_url'] == url for it in items):
                            items.append({'remote_url': url, 'local_url': None, 'pdf_name': 'pv.pdf', 'text': 'view-pv', 'from': u, 'score': 7})
                    # Try to collect declared filenames from embedded JSON/config in Nuxt chunks
                    try:
                        from ..utils import clean_pdf_name_from_text as _clean_asset
                        seen_nm = set(declared_names)
                        for m in re.finditer(r'([\wÀ-ÖØ-öø-ÿ _\-().]+?\.pdf)', ar.text, re.I):
                            nm = _clean_asset(m.group(1))
                            if nm and nm not in seen_nm:
                                declared_names.append(nm); seen_nm.add(nm)
                    except Exception:
                        pass
                    if items:
                        break
            except Exception:
                pass
        # If this is the download options page and we still have few items, render with Playwright to collect dynamically injected anchors
        try:
            if ('/verkiezingen/tk/download-opties' in (r.url or '')) and len(items) < 20:
                # First try DOM anchors; if still small, use network capture to catch PDF responses
                extra = playwright_collect_pdfs(tracer, municipality, r.url, max_items=250)
                if extra:
                    # prefer higher score for mijnstembureau
                    for it in extra:
                        it['score'] = max(6, int(it.get('score') or 0))
                    items.extend(extra)
                # Playwright DOM: collect anchors that point to view-pv or explicit downloads (even if not .pdf)
                if len(items) < 20:
                    try:
                        from playwright.sync_api import sync_playwright
                        with sync_playwright() as p:
                            b = p.chromium.launch(headless=True)
                            ctx = b.new_context()
                            page = ctx.new_page()
                            page.goto(r.url, wait_until="domcontentloaded", timeout=60000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception:
                                pass
                            anchors = page.eval_on_selector_all(
                                'a[href], button',
                                'els => els.map(e => ({href: e.href || "", text: (e.innerText||""), download: e.getAttribute("download") || "", dataFilename: e.getAttribute("data-filename") || "", dataFile: e.getAttribute("data-file") || "", title: e.getAttribute("title") || "", aria: e.getAttribute("aria-label") || ""}))'
                            ) or []
                            # Gather declared download names from dynamic DOM as well
                            try:
                                from ..utils import clean_pdf_name_from_text as _clean_dyn
                                seen_dyn = set()
                                for aobj in anchors:
                                    dl = (aobj.get('download') or '').strip()
                                    if not dl:
                                        continue
                                    nm = _clean_dyn(dl)
                                    if nm and nm not in seen_dyn:
                                        seen_dyn.add(nm); declared_names.append(nm)
                            except Exception:
                                pass
                            for aobj in anchors:
                                href = (aobj.get('href') or '').strip()
                                text = (aobj.get('text') or '').strip()
                                if not href:
                                    continue
                                low = href.lower()
                                meta_name = (aobj.get('download') or aobj.get('dataFilename') or aobj.get('dataFile') or aobj.get('title') or aobj.get('aria') or '').strip()
                                if ('view-pv' in low) or low.endswith('.pdf') or meta_name:
                                    full = href
                                    from ..utils import clean_pdf_name_from_text as _clean_meta
                                    name = _clean_meta(meta_name) if meta_name else (full.rsplit('/', 1)[-1] or 'document.pdf')
                                    if not name.lower().endswith('.pdf'):
                                        # normalize name from text or append .pdf
                                        name = sanitize_filename((text or name))
                                        if not name.lower().endswith('.pdf'):
                                            name += '.pdf'
                                    items.append({'remote_url': full, 'local_url': None, 'pdf_name': name, 'text': text or 'mijnstembureau', 'from': r.url, 'score': 6})
                            ctx.close(); b.close()
                    except Exception:
                        pass
                if len(items) < 20:
                    from ..fallback_playwright import playwright_collect_pdfs_network
                    extra2 = playwright_collect_pdfs_network(tracer, municipality, r.url, max_items=250,
                                                             click_selectors=['a[download]', 'a', 'button'])
                    if extra2:
                        for it in extra2:
                            it['score'] = max(7, int(it.get('score') or 0))
                        # If we have declared filenames, assign them in order to unnamed items
                        if declared_names:
                            q = list(declared_names)
                            for it in extra2:
                                nm = (it.get('pdf_name') or '').strip().lower()
                                if nm in ('proces-verbaal.pdf', 'document.pdf', 'pv.pdf') and q:
                                    it['pdf_name'] = q.pop(0)
                        items.extend(extra2)
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
                name_by_url: dict[str, str] = {}
                seq: list[str] = []
                def _on_response(resp):
                    try:
                        u = (resp.url or '')
                        ct = (resp.headers or {}).get('content-type','').lower()
                        if (resp.status == 200) and (('application/pdf' in ct) or 'octet-stream' in ct or u.lower().endswith('.pdf') or '/uitslagen/api/view-pv' in u.lower()):
                            if u not in found:
                                found.add(u)
                                seq.append(u)
                            # Extract filename from Content-Disposition when present
                            try:
                                cd = (resp.headers or {}).get('content-disposition') or ''
                                import re as _re
                                m = _re.search(r'filename\*=UTF-8\'\'([^;]+)', cd) or _re.search(r'filename="?([^";]+)"?', cd)
                                if m:
                                    from ..utils import clean_pdf_name_from_text as _clean_cd
                                    nm = _clean_cd(m.group(1))
                                    if nm:
                                        name_by_url[u] = nm
                            except Exception:
                                pass
                    except Exception:
                        pass
                def _on_request(req):
                    try:
                        u = (req.url or '')
                        if '/uitslagen/api/view-pv' in u.lower():
                            if u not in req_found:
                                req_found.add(u)
                                seq.append(u)
                    except Exception:
                        pass
                page.on('response', _on_response)
                page.on('request', _on_request)
                # Capture download events to map blob URLs to filenames
                try:
                    def _on_download(d):
                        try:
                            u = getattr(d, 'url', '') or ''
                            nm = getattr(d, 'suggested_filename', '') or ''
                            if u and nm:
                                from ..utils import clean_pdf_name_from_text as _clean_nm
                                cn = _clean_nm(nm) or nm
                                name_by_url[u] = cn
                        except Exception:
                            pass
                    page.on('download', _on_download)
                except Exception:
                    pass
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                # Collect potential names visible on the page (e.g., "Rijssen-Holten_001_...pdf")
                try:
                    names_raw = await page.evaluate(
                        "() => { const out=[]; const els = Array.from(document.querySelectorAll('a,button,li,div,p,span'));\n"
                        "for (const e of els){ const t=(e.innerText||'').trim(); if (t && /\\.pdf/i.test(t)) out.push(t); }\n"
                        "return out; }"
                    )
                except Exception:
                    names_raw = []
                # Deduplicate and sanitize names
                names_seen = set(); names_queue: list[str] = []
                from ..utils import clean_pdf_name_from_text as _clean_txt
                for t in names_raw or []:
                    try:
                        nm = _clean_txt(t)
                    except Exception:
                        nm = None
                    if nm and nm not in names_seen:
                        names_seen.add(nm); names_queue.append(nm)

                # click likely buttons
                keys = ['Proces', 'verbaal', 'N10', 'PV', 'Download', 'Downloaden', 'bekijk', 'opties', 'pdf', 'Telling', 'Stembureau', 'Processen', 'model', 'Uitkomst', 'Verklaring', 'corrigendum', 'Na14', 'P2a', 'GSB', 'B&W']
                loc = page.locator('a, button, [role=button], [role=link]')
                n = min(await loc.count(), 400)
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
                    if i % 15 == 0 and i > 0:
                        try:
                            await page.evaluate('window.scrollBy(0, 1200)')
                        except Exception:
                            pass
                        try:
                            await page.wait_for_timeout(600)
                        except Exception:
                            pass
                # If we discovered explicit filenames on the page, try to trigger each by clicking a nearby control
                if names_queue:
                    # Browser-side helper clicks nearest clickable for a given filename-like text
                    click_js = """
                        (text) => {
                          const norm = (s) => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                          const match = Array.from(document.querySelectorAll('a,button,div,li,span,p'))
                            .find(e => norm(e.innerText||'').includes(norm(text)));
                          if (!match) return false;
                          const root = match.closest('li, tr, .row, .download, .download-option, .v-list-item, .item, .wrapper, .container') || match;
                          const btn = root.querySelector('a[download], a[href*="view-pv"], a[href*="pdf"], button, [role=button]');
                          if (btn) { btn.scrollIntoView({block:'center'}); btn.click(); return true; }
                          match.scrollIntoView({block:'center'}); match.click();
                          return true;
                        }
                    """
                    for nm in list(names_queue):
                        try:
                            ok = await page.evaluate(click_js, nm)
                            # Wait for the corresponding API request (more reliable here) and bind name
                            try:
                                req = await page.wait_for_request(lambda r: '/uitslagen/api/view-pv' in (r.url or '').lower(), timeout=6000)
                                if req:
                                    u = req.url
                                    if u and (u not in name_by_url):
                                        name_by_url[u] = nm
                                        if u not in req_found:
                                            req_found.add(u); seq.append(u)
                            except Exception:
                                pass
                        except Exception:
                            continue
                # small wait to allow responses
                try:
                    await page.wait_for_timeout(7000)
                except Exception:
                    pass
                # collect anchors created dynamically to use their text as names
                try:
                    anchors = await page.eval_on_selector_all('a[href]', 'els => els.map(e => ({href: e.href, text: (e.innerText||"").trim()}))')
                except Exception:
                    anchors = []
                await ctx.close(); await b.close()
                ordered = []
                # Preserve event order as best-effort
                for u in seq:
                    if (u in found) or (u in req_found):
                        ordered.append(u)
                seen_u = set()
                for u in ordered:
                    if u in seen_u:
                        continue
                    seen_u.add(u)
                    name = name_by_url.get(u) or (u.rsplit('/',1)[-1] or 'pv.pdf')
                    # prefer anchor text for naming when hashy/blob
                    label = ''
                    for a in anchors or []:
                        href = (a.get('href') or '')
                        if href and (href == u or ('view-pv' in href and 'view-pv' in u)):
                            label = (a.get('text') or '').strip()
                            break
                    if label:
                        from ..utils import clean_pdf_name_from_text
                        nm = clean_pdf_name_from_text(label)
                        if nm:
                            name = nm
                    elif names_queue:
                        # Assign next visible name from the page list
                        name = names_queue.pop(0)
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
