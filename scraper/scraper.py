#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import unicodedata
import shutil
import urllib.parse
from typing import Tuple
from typing import Any

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


BASE_URL = "https://www.kiesraad.nl/verkiezingen/tweede-kamer/uitslagen/uitslagen-per-gemeente-tweede-kamer"
# Prefer data alongside this script (scraper/data), fallback to CWD/data for existing setups
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR_PRIMARY = os.path.join(SCRIPT_DIR, "data")
DATA_DIR_FALLBACK = os.path.join(os.getcwd(), "data")
DATA_DIR = DATA_DIR_FALLBACK  # default for historical behavior when writing new files
HEURISTICS_PATH = os.path.join(DATA_DIR, "learned_heuristics.json")


def ensure_data_dir() -> None:
    # Ensure both commonly-used data locations exist
    os.makedirs(DATA_DIR_PRIMARY, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def find_data_file(name: str, for_write: bool = False) -> str:
    """Locate a data file, preferring scraper/data, then CWD/data. For writes, use DATA_DIR (legacy)."""
    p1 = os.path.join(DATA_DIR_PRIMARY, name)
    p2 = os.path.join(DATA_DIR_FALLBACK, name)
    if not for_write:
        if os.path.exists(p1):
            return p1
        if os.path.exists(p2):
            return p2
    # default write location follows historic DATA_DIR
    ensure_data_dir()
    return os.path.join(DATA_DIR, name)


def http_get(url: str, timeout: float = 20.0, headers: dict | None = None) -> requests.Response:
    default_headers = {
        "User-Agent": "restzetels-scraper/0.1 (+https://example.local)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    resp = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def scrape_municipalities(save_path: str = os.path.join(DATA_DIR, "municipalities.json")) -> list[dict]:
    ensure_data_dir()
    print(f"[phase1] Fetching index page: {BASE_URL}")
    r = http_get(BASE_URL)
    soup = BeautifulSoup(r.text, "html.parser")

    # Find accordion section titled "A tot en met Z uitslagen per gemeente"
    accordion_title = soup.find("h2", class_="accordion__title", string=lambda s: s and "A tot en met Z" in s)
    if not accordion_title:
        raise RuntimeError("Kon de accordion met gemeenten niet vinden.")

    accordion = accordion_title.find_parent("div", class_="accordion")
    if not accordion:
        # Fallback: sometimes body wrapper structure changes, search globally
        accordion = soup

    items: list[dict] = []
    seen = set()
    for content in accordion.select("div.accordion__item-content"):
        for a in content.select("a[href]"):
            name = a.get_text(strip=True)
            href = a.get("href")
            if not name or not href:
                continue
            # Only keep external or absolute links; prepend scheme if protocol-relative
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = urljoin("https://www.kiesraad.nl", href)

            key = (name, href)
            if key in seen:
                continue
            seen.add(key)
            items.append({"name": name, "url": href})

    if not items:
        raise RuntimeError("Geen gemeenten gevonden in de accordion.")

    # Persist to JSON
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"source": BASE_URL, "count": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    print(f"[phase1] Saved {len(items)} municipalities to {save_path}")
    return items


def verify_municipality_links(
    municipalities: list[dict],
    save_path: str = os.path.join(DATA_DIR, "municipality_links_verified.json"),
    limit: int | None = None,
    delay: float = 0.2,
) -> list[dict]:
    ensure_data_dir()
    # Load existing verified to merge instead of rebuilding from scratch
    existing_verified: list[dict] = []
    try:
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                existing_verified = data.get("verified", []) or []
            elif isinstance(data, list):
                existing_verified = data
    except FileNotFoundError:
        existing_verified = []
    except Exception:
        existing_verified = []

    existing_map: dict[str, dict] = {}
    for v in existing_verified:
        n = v.get("name")
        if n:
            existing_map[n] = v

    output: list[dict] = []
    for i, item in enumerate(municipalities):
        if limit is not None and i >= limit:
            break
        name = item["name"]
        url = item["url"]
        try:
            r = http_get(url, timeout=25.0)
            final_url = str(r.url)
            status = r.status_code
            output.append({
                "name": name,
                "start_url": url,
                "final_url": final_url,
                "status": status,
            })
            print(f"[phase2] {name}: {status} -> {final_url}")
        except Exception as e:
            output.append({
                "name": name,
                "start_url": url,
                "final_url": None,
                "status": None,
                "error": str(e),
            })
            print(f"[phase2] {name}: ERROR {e}")
        time.sleep(delay)

    # Merge: update/insert only processed entries; keep the rest
    for v in output:
        existing_map[v.get("name")] = v
    merged = list(existing_map.values())

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"verified": merged, "count": len(merged)}, f, ensure_ascii=False, indent=2)
    print(f"[phase2] Verified {len(output)} municipalities (merged -> total {len(merged)}) -> {save_path}")
    return merged


PDF_HINT_PATTERNS = [
    r"proces[-\s]?verbaal",
    r"processen[-\s]?verbaal",
    r"stembureau",
    r"model\s*N\s*10",
    r"model\s*Na\s*31",
    r"n10\b",
    r"na31\b",
    r"verkiezing",
    r"verkiezingen",
]

PDF_HINT_RE = re.compile("|".join(PDF_HINT_PATTERNS), re.IGNORECASE)


def is_same_site(url: str, origin: str) -> bool:
    pu = urlparse(url)
    po = urlparse(origin)
    return pu.netloc == po.netloc or (not pu.netloc and pu.path)


def find_pdfs_for_municipality(
    start_url: str,
    max_pages: int = 30,
    max_depth: int = 2,
    delay: float = 0.2,
    domain_patients: dict | None = None,
    extra_seeds: list[str] | None = None,
    use_sitemap: bool = False,
    render: bool = False,
) -> list[dict]:
    seen_urls: set[str] = set()
    # Prioritize extra seeds ahead of the generic start_url
    queue: list[tuple[str, int]] = []
    if extra_seeds:
        for seed in extra_seeds:
            if seed:
                queue.append((seed, 0))
    queue.append((start_url, 0))

    # Optionally discover more seeds via sitemap
    if use_sitemap:
        try:
            seeds = discover_urls_via_sitemap(start_url)
            # prioritize seeds that look relevant
            for s in seeds:
                queue.append((s, 0))
        except Exception:
            pass
        try:
            s2 = discover_urls_via_site_search(start_url)
            for s in s2:
                queue.append((s, 0))
        except Exception:
            pass
    pdfs: list[dict] = []

    def norm(u: str) -> str:
        if u.startswith("//"):
            return "https:" + u
        return u

    # Prepare queue with prioritization using learned domain patterns
    while queue and len(seen_urls) < max_pages:
        url, depth = queue.pop(0)
        url = norm(url)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # Fetch page (static first)
        r = None
        try:
            r = http_get(url, timeout=25.0)
            html = r.text
        except Exception:
            html = ""

        soup = BeautifulSoup(html or "", "html.parser")
        found_pdfs_before = 0
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(r.url, href)
            classes = " ".join(a.get("class", []))
            pth = urlparse(full).path.lower()
            is_pdf_like = (
                pth.endswith(".pdf") or (".pdf" in pth)
                or "type-document-pdf" in classes
                or "type=pdf" in full.lower()
                or (a.get_text(" ", strip=True).lower().endswith("pdf") and "http" in full.lower())
            )
            if is_pdf_like:
                text = a.get_text(" ", strip=True)
                title_attr = a.get("title") or ""
                context_text = (text or title_attr)
                score = 1
                if PDF_HINT_RE.search(context_text) or PDF_HINT_RE.search(full):
                    score += 3
                # derive original file name from URL, with fallback from link text for generic endpoints
                try:
                    orig_name = os.path.basename(urlparse(full).path)
                except Exception:
                    orig_name = ""
                # Fallback: if endpoint looks generic (e.g. dsresource), try using link text
                if (not orig_name or orig_name.lower() in {"dsresource", "download", "document", "file"}):
                    if text:
                        t = text.strip()
                        # if link text ends with .pdf use it
                        if t.lower().endswith('.pdf'):
                            orig_name = t
                        # else if it contains an obvious file stem, append .pdf
                        elif any(k in t.lower() for k in ("stembureau", "n10", "na ")):
                            orig_name = f"{t}.pdf"
                pdfs.append({
                    "url": full,
                    "text": text,
                    "preview_text": text,
                    "pdf_name": orig_name,
                    "score": score,
                    "from": r.url,
                })
                found_pdfs_before += 1

        # If we didn't find PDFs and rendering is enabled, try headless rendering
        if render and PLAYWRIGHT_AVAILABLE and found_pdfs_before == 0:
            try:
                html2, final_url = render_page_content(url)
                r_url = final_url or url
                soup2 = BeautifulSoup(html2 or "", "html.parser")
                for a in soup2.select("a[href]"):
                    href = a.get("href")
                    if not href:
                        continue
                    full = urljoin(r_url, href)
                    classes = " ".join(a.get("class", []))
                    pth = urlparse(full).path.lower()
                    is_pdf_like = (
                        pth.endswith(".pdf") or (".pdf" in pth)
                        or "type-document-pdf" in classes
                        or "type=pdf" in full.lower()
                        or (a.get_text(" ", strip=True).lower().endswith("pdf") and "http" in full.lower())
                    )
                    if not is_pdf_like:
                        continue
                    text = a.get_text(" ", strip=True)
                    title_attr = a.get("title") or ""
                    context_text = (text or title_attr)
                    score = 1
                    if PDF_HINT_RE.search(context_text) or PDF_HINT_RE.search(full):
                        score += 3
                    try:
                        orig_name = os.path.basename(urlparse(full).path)
                    except Exception:
                        orig_name = ""
                    if (not orig_name or orig_name.lower() in {"dsresource", "download", "document", "file"}):
                        if text:
                            t = text.strip()
                            if t.lower().endswith('.pdf'):
                                orig_name = t
                            elif any(k in t.lower() for k in ("stembureau", "n10", "na ")):
                                orig_name = f"{t}.pdf"
                    pdfs.append({
                        "url": full,
                        "text": text,
                        "preview_text": text,
                        "pdf_name": orig_name,
                        "score": score,
                        "from": r_url,
                    })

                # Also enqueue internal links discovered via rendered HTML
                if depth < max_depth:
                    scored_links: list[tuple[float, str]] = []
                    for a in soup2.select("a[href]"):
                        href = a.get("href")
                        if not href:
                            continue
                        full = urljoin(r_url, href)
                        if not is_same_site(full, r_url):
                            continue
                        text = a.get_text(" ", strip=True)
                        title_attr = a.get("title") or ""
                        hint_text = f"{text} {title_attr} {href}"
                        score = 0.0
                        if PDF_HINT_RE.search(hint_text):
                            score += 1.0
                        if domain_patients:
                            for pat, w in domain_patients.items():
                                if pat and pat.lower() in hint_text.lower():
                                    try:
                                        score += float(w)
                                    except Exception:
                                        score += 0.5
                        if score > 0:
                            scored_links.append((score, full))
                    for _, link in sorted(scored_links, key=lambda x: -x[0]):
                        queue.append((link, depth + 1))
            except Exception:
                pass

        # Enqueue same-site links that look relevant
        if depth < max_depth:
            scored_links: list[tuple[float, str]] = []
            for a in soup.select("a[href]"):
                href = a.get("href")
                if not href:
                    continue
                full = urljoin(r.url, href)
                if not is_same_site(full, r.url):
                    continue
                text = a.get_text(" ", strip=True)
                title_attr = a.get("title") or ""
                hint_text = f"{text} {title_attr} {href}"
                score = 0.0
                if PDF_HINT_RE.search(hint_text):
                    score += 1.0
                # Boost based on learned domain patterns
                if domain_patients:
                    for pat, w in domain_patients.items():
                        if pat and pat.lower() in hint_text.lower():
                            try:
                                score += float(w)
                            except Exception:
                                score += 0.5
                if score > 0:
                    scored_links.append((score, full))

            # Push higher score first
            for _, link in sorted(scored_links, key=lambda x: -x[0]):
                queue.append((link, depth + 1))

        time.sleep(delay)

    # Dedupe PDFs by URL
    seen_pdf = set()
    deduped: list[dict] = []
    for p in sorted(pdfs, key=lambda x: (-x["score"], x["url"])):
        if p["url"] in seen_pdf:
            continue
        seen_pdf.add(p["url"])
        deduped.append(p)
    return deduped


def render_page_content(url: str, timeout_ms: int = 30000) -> Tuple[str, str]:
    """Render a page with Playwright to capture dynamically injected links.
    Returns (html, final_url). Requires playwright + browser installed.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # Give time for client-side content
        page.wait_for_timeout(2000)
        # If there's a loader-heavy app, allow extra idle
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        html = page.content()
        final_url = page.url
        context.close()
        browser.close()
        return html, final_url


def discover_urls_via_sitemap(start_url: str, max_urls: int = 200) -> list[str]:
    """Fetch sitemap(s) for a domain and return candidate content URLs likely about elections.
    """
    origin = urlparse(start_url)
    base = f"{origin.scheme}://{origin.netloc}"
    robots_url = urljoin(base, "/robots.txt")
    sitemap_urls: list[str] = []
    try:
        r = http_get(robots_url, timeout=10)
        for line in r.text.splitlines():
            if line.lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc:
                    sitemap_urls.append(loc)
    except Exception:
        pass
    # Common fallbacks
    for cand in ["/sitemap.xml", "/sitemap_index.xml", "/sitemapindex.xml", "/Sitemap.xml"]:
        sitemap_urls.append(urljoin(base, cand))
    # Dedup
    sitemap_urls = list(dict.fromkeys(sitemap_urls))

    def parse_sitemap(url: str, depth: int = 0) -> list[str]:
        try:
            rr = http_get(url, timeout=20)
        except Exception:
            return []
        soup = BeautifulSoup(rr.text, "xml")
        out: list[str] = []
        # sitemap index
        for sm in soup.select("sitemap > loc"):
            loc = sm.get_text(strip=True)
            if loc and depth < 2:
                out.extend(parse_sitemap(loc, depth + 1))
        # url set
        for loc in soup.select("url > loc"):
            u = loc.get_text(strip=True)
            if not u:
                continue
            pu = urlparse(u)
            if pu.netloc != origin.netloc:
                continue
            out.append(u)
        return out

    urls: list[str] = []
    for smurl in sitemap_urls:
        urls.extend(parse_sitemap(smurl))

    # Filter for likely relevant content
    KEY_RE = re.compile(
        r"verkiez|uitslag|voorlopige|resultaten|tweede.*kamer|stembur|proces|verbaal|n10|n10-1|na\s*31|na31|na\s*14|na14",
        re.I,
    )
    candidates = [u for u in urls if KEY_RE.search(u)]
    # Dedup and cap
    dedup = list(dict.fromkeys(candidates))
    return dedup[:max_urls]


def discover_urls_via_site_search(start_url: str, terms: list[str] | None = None, max_urls: int = 100) -> list[str]:
    origin = urlparse(start_url)
    base = f"{origin.scheme}://{origin.netloc}"
    if terms is None:
        terms = [
            "processen-verbaal",
            "proces-verbaal",
            "stembureau",
            "N10",
            "N10-1",
            "Na 31",
            "Na 14-1",
            "uitslag",
            "uitslagen",
            "voorlopige resultaten",
            "uitslag tweede kamer 2025",
            "tweede kamer 2025",
            "uitslag tweede-kamerverkiezing 2025",
        ]
    paths = ["zoeken", "search"]
    params = ["q", "query", "zoek", "search"]
    found: list[str] = []
    for term in terms:
        for path in paths:
            for param in params:
                url = f"{base}/{path}?{param}={requests.utils.quote(term)}"
                try:
                    r = http_get(url, timeout=12)
                except Exception:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href]"):
                    href = a.get("href")
                    if not href:
                        continue
                    full = urljoin(r.url, href)
                    pu = urlparse(full)
                    if pu.netloc != origin.netloc:
                        continue
                    found.append(full)
    # Dedup + filter with keywords
    KEY_RE = re.compile(
        r"verkiez|uitslag|voorlopige|resultaten|tweede.*kamer|stembur|proces|verbaal|n10|n10-1|na\s*31|na31|na\s*14|na14",
        re.I,
    )
    candidates = [u for u in dict.fromkeys(found).keys() if KEY_RE.search(u)]
    return candidates[:max_urls]


# ---------- Learning heuristics ----------

def load_heuristics(path: str = HEURISTICS_PATH) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"domains": {}}
    return {"domains": {}}


def save_heuristics(data: dict, path: str = HEURISTICS_PATH) -> None:
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_domain_patterns(domain: str, tokens: list[str], weight: float = 1.0) -> None:
    heur = load_heuristics()
    dom = heur.setdefault("domains", {}).setdefault(domain, {"patterns": {}, "last_updated": int(time.time())})
    pats = dom.setdefault("patterns", {})
    for t in tokens:
        if not t:
            continue
        pats[t] = float(pats.get(t, 0.0)) + float(weight)
    dom["last_updated"] = int(time.time())
    save_heuristics(heur)


def domain_learned_patterns(domain: str) -> dict:
    heur = load_heuristics()
    dom = heur.get("domains", {}).get(domain)
    if not dom:
        return {}
    return dom.get("patterns", {})


def tokenize_for_learning(text: str) -> list[str]:
    # Keep simple tokens likely useful as cues
    base = re.sub(r"[\s\-_/]+", " ", text.lower())
    keep = [
        "proces-verbaal",
        "processen-verbaal",
        "stembureau",
        "uitslag",
        "definitieve",
        "verkiezing",
        "pv",
        "n10",
        "na31",
        "proces",
        "verbaal",
        "model",
    ]
    return [k for k in keep if k in base]


# ---------- Cross-ref and matching ----------

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[\s_\-]+", " ", s)
    s = re.sub(r"[^0-9a-zà-öø-ÿ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


GENERIC_TOKENS = {
    "stembureau", "wijkcentrum", "buurthuis", "sporthal", "gebouw", "dorpshuis", "zorgcentrum",
    "raadhuis", "parochiehuis", "clubgebouw", "school", "obs", "kc", "ikc", "nh", "rk", "r.k.",
    "mbo", "de", "het", "'t", "het", "nh wijkcentrum",
}


def derive_aliases(name: str) -> list[str]:
    nn = normalize_text(name)
    tokens = [t for t in nn.split() if t not in GENERIC_TOKENS]
    core = " ".join(tokens)
    # initialisms
    initials = "".join([t[0] for t in tokens if t and t[0].isalpha()])
    aliases = {nn, core, initials}
    # Also keep without spaces
    aliases.add(core.replace(" ", ""))
    return [a for a in aliases if a]


def match_pdf_to_stembureau(pdf_entry: dict, stembureaus: list[dict]) -> tuple[dict | None, float]:
    # Try to match by name present in anchor text or URL
    ctx = (pdf_entry.get("text") or "") + " " + pdf_entry.get("url", "")
    nctx = normalize_text(ctx)
    best = None
    best_score = 0.0
    for sb in stembureaus:
        name = sb.get("Naam stembureau") or sb.get("naam") or sb.get("Naam")
        if not name:
            continue
        aliases = derive_aliases(name)
        score = 0.0
        for al in aliases:
            if al and al in nctx:
                # core/alias direct matches
                score = max(score, 3.0 if " " in al else 2.2)
        # Token overlap weighting
        nn = normalize_text(name)
        tokens = set(nn.split())
        common = tokens.intersection(set(nctx.split()))
        score += 0.15 * len(common)
        if score > best_score:
            best_score = score
            best = sb
    return best, best_score


def load_stemlokalen(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        return data["result"].get("records", [])
    if isinstance(data, list):
        return data
    raise ValueError("Onbekend formaat voor alle_stemlokalen.json")


def get_first_n_municipalities(n: int = 5) -> list[dict]:
    data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
    items = data.get("items", [])
    return items[:n]


def get_verified_url_for_municipality(name: str) -> str | None:
    verified = load_json(find_data_file("municipality_links_verified.json"))
    for v in verified.get("verified", []):
        if v.get("name") == name and v.get("status") == 200:
            return v.get("final_url") or v.get("start_url")
    return None


def filter_stemlokalen_for_muni(stemlokalen: list[dict], municipality_name: str) -> list[dict]:
    return [r for r in stemlokalen if (r.get("Gemeente") == municipality_name or r.get("gemeente") == municipality_name)]


def cmd_first5(args: argparse.Namespace) -> None:
    ensure_data_dir()
    # Load or create verified URLs
    verified_path = os.path.join(DATA_DIR, "municipality_links_verified.json")
    if not os.path.exists(verified_path):
        data = load_json(os.path.join(DATA_DIR, "municipalities.json"))
        verify_municipality_links(data.get("items", []))

    # Load stemlokalen
    stemlokalen = load_stemlokalen(args.stemlokalen)

    # Determine first 5 municipalities
    first5 = get_first_n_municipalities(5)
    names = [m["name"] for m in first5]
    if getattr(args, "only", None):
        names = [n for n in names if n in set(args.only)]
    print(f"[first5] Target municipalities: {', '.join(names)}")

    # Clean existing dirs for the first5 (remove incorrect files)
    for n in names:
        d = os.path.join(os.getcwd(), sanitize_filename(n))
        if os.path.isdir(d):
            print(f"[first5] Removing existing directory: {d}")
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

    # Process each municipality
    summary: dict[str, dict] = {}
    for n in names:
        start_url = get_verified_url_for_municipality(n)
        if not start_url:
            print(f"[first5] Geen geldige URL voor {n}, overslaan")
            summary[n] = {"start_url": None, "found": 0, "expected": 0, "missing": []}
            continue

        domain = urlparse(start_url).netloc
        learned = domain_learned_patterns(domain)
        # Collect stembureaus for this municipality
        sbs = filter_stemlokalen_for_muni(stemlokalen, n)
        expected = len(sbs)
        print(f"[first5] {n}: {expected} stembureaus, crawling {start_url}")
        use_sm = n in ("Aalten", "Achtkarspelen") or args.use_sitemap
        seeds_map = load_extra_seeds()
        extra = seeds_map.get(n, [])
        pdfs = find_pdfs_for_municipality(
            start_url,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            delay=0.2,
            domain_patients=learned,
            use_sitemap=use_sm,
            extra_seeds=extra,
            render=True,
        )

        muni_dir = os.path.join(os.getcwd(), sanitize_filename(n))
        matched_ids: set[str] = set()
        found = 0

        # Try to match PDFs to stembureaus; for dynamic sites (Aalten/Achtkarspelen), download all
        dynamic_force_all = n in ("Aalten", "Achtkarspelen")
        for pdf in pdfs:
            sb, score = match_pdf_to_stembureau(pdf, sbs)
            if (not sb or score < 2.0) and not dynamic_force_all:
                continue
            sid = (sb.get("UUID") or sb.get("ID") or sb.get("id")) if sb else None
            sname = (sb.get("Naam stembureau") or sb.get("naam") or "stembureau") if sb else "stembureau"
            if not dynamic_force_all:
                if not sid or sid in matched_ids:
                    continue
            # Learn from successful context
            toks = tokenize_for_learning((pdf.get("text") or "") + " " + pdf.get("url", ""))
            if toks:
                update_domain_patterns(domain, toks, weight=1.0)

            # Download using original pdf name from URL (or Content-Disposition later)
            pdf_name = pdf.get("pdf_name") or os.path.basename(urlparse(pdf["url"]).path) or "document.pdf"
            if not pdf_name.lower().endswith('.pdf'):
                pdf_name = f"{pdf_name}.pdf"
            out_path = os.path.join(muni_dir, sanitize_filename(pdf_name))
            basep, extp = os.path.splitext(out_path)
            k = 1
            final_path = out_path
            while os.path.exists(final_path):
                final_path = f"{basep}_{k}{extp}"
                k += 1
            try:
                r = requests.get(pdf["url"], headers={"User-Agent": "restzetels-scraper/0.1"}, timeout=40)
                r.raise_for_status()
                if "application/pdf" not in r.headers.get("Content-Type", "").lower() and not urlparse(pdf["url"]).path.lower().endswith(".pdf"):
                    print(f"[first5] Skip non-PDF: {pdf['url']}")
                    continue
                cd = r.headers.get("Content-Disposition", "")
                fname_from_cd = None
                if cd:
                    m = re.search(r"filename\*=(?:UTF-8''|)[^;]*?([^;]+)", cd, re.I)
                    if m:
                        val = m.group(1).strip().strip('"')
                        try:
                            fname_from_cd = urllib.parse.unquote(val)
                        except Exception:
                            fname_from_cd = val
                    else:
                        m2 = re.search(r"filename=([^;]+)", cd, re.I)
                        if m2:
                            fname_from_cd = m2.group(1).strip().strip('"')
                if fname_from_cd:
                    candidate = os.path.join(muni_dir, sanitize_filename(fname_from_cd))
                    basec, extc = os.path.splitext(candidate)
                    n = 1; use = candidate
                    while os.path.exists(use):
                        use = f"{basec}_{n}{extc}"; n += 1
                    final_path = use
                with open(final_path, "wb") as f:
                    f.write(r.content)
                if sid:
                    matched_ids.add(sid)
                found += 1
                print(f"[first5] Saved: {final_path}")
            except Exception as e:
                print(f"[first5] Error downloading {pdf['url']}: {e}")

        def sb_uid(sb: dict) -> str | None:
            return sb.get("UUID") or sb.get("ID")
        missing = [sb_uid(sb) for sb in sbs if (sb_uid(sb) not in matched_ids)]
        summary[n] = {"start_url": start_url, "found": found, "expected": expected, "missing": missing}

    # Save summary and heuristics snapshot
    with open(os.path.join(DATA_DIR, "first5_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[first5] Summary saved -> {os.path.join(DATA_DIR, 'first5_summary.json')}")


def cmd_fetch_one(args: argparse.Namespace) -> None:
    name = args.name
    start_url = get_verified_url_for_municipality(name)
    if not start_url:
        print(f"[fetch-one] Geen geldige URL voor {name}. Draai eerst phase1/phase2 of vul verified JSON aan.")
        return
    seeds_map = load_extra_seeds(find_data_file("extra_seeds.json"))
    seeds = seeds_map.get(name, []) if isinstance(seeds_map, dict) else []
    print(f"[fetch-one] {name}: start={start_url}")
    if seeds:
        print(f"[fetch-one] {name}: using {len(seeds)} extra seed(s)")

    # Crawl with priorities for seeds
    pdfs = find_pdfs_for_municipality(
        start_url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=0.15,
        domain_patients=domain_learned_patterns(urlparse(start_url).netloc),
        extra_seeds=seeds,
        use_sitemap=False,
        render=True,
    )
    print(f"[fetch-one] {name}: gevonden {len(pdfs)} PDF-links")
    # Download to the folder of this script (scraper/<Gemeente>) for consistency
    download_pdfs([{"name": name, "pdfs": pdfs}], base_dir=SCRIPT_DIR, limit_per_municipality=args.limit_per_municipality)


def scrape_pdfs(
    verified: list[dict],
    save_path: str = os.path.join(DATA_DIR, "municipality_pdfs_index.json"),
    limit: int | None = None,
    max_pages: int = 30,
    max_depth: int = 2,
    delay: float = 0.2,
    use_sitemap: bool = False,
    render: bool = False,
    extra_seeds_map: dict | None = None,
) -> list[dict]:
    ensure_data_dir()
    # Load existing index for merge
    existing_results: list[dict] = []
    try:
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                existing_results = data.get("results", []) or []
            elif isinstance(data, list):
                existing_results = data
    except FileNotFoundError:
        existing_results = []
    except Exception:
        existing_results = []
    existing_map: dict[str, dict] = {}
    for e in existing_results:
        n = e.get("name")
        if n:
            existing_map[n] = e

    results: list[dict] = []
    for i, entry in enumerate(verified):
        if limit is not None and i >= limit:
            break
        name = entry.get("name")
        start_url = entry.get("final_url") or entry.get("start_url")
        if not start_url:
            continue
        print(f"[phase3] Crawling {name} -> {start_url}")
        try:
            seeds = []
            if extra_seeds_map and name in extra_seeds_map:
                seeds = extra_seeds_map[name]
            pdfs = find_pdfs_for_municipality(
                start_url,
                max_pages=max_pages,
                max_depth=max_depth,
                delay=delay,
                use_sitemap=use_sitemap,
                extra_seeds=seeds,
                render=render,
            )
            # Merge per municipality: union PDFs by URL
            new_entry = {"name": name, "start_url": start_url, "pdfs": pdfs}
            old = existing_map.get(name)
            if old and isinstance(old.get("pdfs"), list):
                by_url: dict[str, dict] = {}
                for p in old.get("pdfs", []):
                    u = p.get("url")
                    if u:
                        by_url[u] = p
                for p in pdfs:
                    u = p.get("url")
                    if u:
                        by_url[u] = p  # prefer fresh copy
                new_entry["pdfs"] = list(by_url.values())
            existing_map[name] = new_entry
            results.append(new_entry)
            print(f"[phase3] {name}: found {len(pdfs)} pdfs (merged -> {len(existing_map[name]['pdfs'])})")
        except Exception as e:
            # Preserve existing entry on error; if none, save an error entry
            if name not in existing_map:
                results.append({"name": name, "start_url": start_url, "error": str(e), "pdfs": []})
            print(f"[phase3] {name}: ERROR {e} (kept existing if present)")
        time.sleep(delay)

    # Build final list: include unchanged municipalities too
    for n, e in list(existing_map.items()):
        # ensure any municipalities we didn't process this run are preserved
        if not any(r.get("name") == n for r in results):
            results.append(e)

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "count": len(results)}, f, ensure_ascii=False, indent=2)
    print(f"[phase3] Saved pdf index (merged) for {len(results)} municipalities -> {save_path}")
    return results


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def download_pdfs(
    pdf_index: list[dict],
    base_dir: str = os.getcwd(),
    delay: float = 0.1,
    limit_per_municipality: int | None = None,
) -> None:
    for entry in pdf_index:
        name = entry.get("name") or "onbekend"
        muni_dir = os.path.join(base_dir, sanitize_filename(name))
        os.makedirs(muni_dir, exist_ok=True)
        pdfs: list[dict] = entry.get("pdfs", [])
        if not pdfs:
            print(f"[phase4] {name}: no pdfs to download")
            continue
        count = 0
        for p in pdfs:
            if limit_per_municipality is not None and count >= limit_per_municipality:
                break
            url = p["url"]
            filename = p.get("pdf_name") or os.path.basename(urlparse(url).path) or "document.pdf"
            if not filename.lower().endswith('.pdf'):
                filename = f"{filename}.pdf"
            out_path = os.path.join(muni_dir, sanitize_filename(filename))
            # Avoid overwrite collisions by adding index
            base, ext = os.path.splitext(out_path)
            j = 1
            final_path = out_path
            while os.path.exists(final_path):
                final_path = f"{base}_{j}{ext}"
                j += 1
            try:
                r = requests.get(url, headers={"User-Agent": "restzetels-scraper/0.1"}, timeout=40)
                r.raise_for_status()
                if "application/pdf" not in r.headers.get("Content-Type", "").lower() and not urlparse(url).path.lower().endswith(".pdf"):
                    # Skip non-PDF content silently
                    print(f"[phase4] Skip non-PDF: {url}")
                    continue
                # Try to use server-provided filename via Content-Disposition
                cd = r.headers.get("Content-Disposition", "")
                fname_from_cd = None
                if cd:
                    # RFC 5987 filename*
                    m = re.search(r"filename\*=(?:UTF-8''|)[^;]*?([^;]+)", cd, re.I)
                    if m:
                        val = m.group(1).strip().strip('"')
                        try:
                            fname_from_cd = urllib.parse.unquote(val)
                        except Exception:
                            fname_from_cd = val
                    else:
                        m2 = re.search(r"filename=([^;]+)", cd, re.I)
                        if m2:
                            fname_from_cd = m2.group(1).strip().strip('"')
                if fname_from_cd:
                    candidate = os.path.join(muni_dir, sanitize_filename(fname_from_cd))
                    basec, extc = os.path.splitext(candidate)
                    n = 1; use = candidate
                    while os.path.exists(use):
                        use = f"{basec}_{n}{extc}"; n += 1
                    final_path = use
                with open(final_path, "wb") as f:
                    f.write(r.content)
                count += 1
                print(f"[phase4] Saved {name}: {final_path}")
            except Exception as e:
                print(f"[phase4] Error downloading {url}: {e}")
            time.sleep(delay)


def load_json(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_extra_seeds(path: str | None = None) -> dict:
    if path is None:
        path = find_data_file("extra_seeds.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def cmd_phase1(args: argparse.Namespace) -> None:
    out = find_data_file("municipalities.json", for_write=False)
    if not getattr(args, "force_rebuild", False) and os.path.exists(out):
        print(f"[phase1] {out} bestaat al; skip (use --force-rebuild om opnieuw te bouwen)")
        return
    scrape_municipalities()


def cmd_phase2(args: argparse.Namespace) -> None:
    data = load_json(find_data_file("municipalities.json"))
    verify_municipality_links(data["items"], limit=args.limit)


def cmd_phase3(args: argparse.Namespace) -> None:
    verified = load_json(find_data_file("municipality_links_verified.json"))
    extra = load_extra_seeds(find_data_file("extra_seeds.json"))
    scrape_pdfs(
        verified=[v for v in verified.get("verified", []) if v.get("status") == 200],
        limit=args.limit,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        use_sitemap=True,
        render=True,
        extra_seeds_map=extra,
    )


def cmd_phase4(args: argparse.Namespace) -> None:
    idx = load_json(find_data_file("municipality_pdfs_index.json"))
    base_dir = args.base_dir or os.getcwd()
    download_pdfs(idx.get("results", []), base_dir=base_dir, limit_per_municipality=args.limit_per_municipality)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scraper voor processen-verbaal per stembureau (gemeenten)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("phase1", help="Scrape lijst gemeenten + urls naar JSON (bewaart bestaande tenzij --force-rebuild)")
    s1.add_argument("--force-rebuild", action="store_true", help="Overschrijf municipalities.json i.p.v. skippen")
    s1.set_defaults(func=cmd_phase1)

    s2 = sub.add_parser("phase2", help="Verifieer gemeente-links (status + redirects)")
    s2.add_argument("--limit", type=int, default=None, help="Beperk aantal te verifiëren gemeenten (test)")
    s2.set_defaults(func=cmd_phase2)

    s3 = sub.add_parser("phase3", help="Zoek PDF-links per gemeente (heuristiek)")
    s3.add_argument("--limit", type=int, default=None, help="Beperk aantal gemeenten (test)")
    s3.add_argument("--max-pages", type=int, default=30, help="Max pagina's per gemeente crawlen")
    s3.add_argument("--max-depth", type=int, default=2, help="Crawl diepte binnen zelfde site")
    s3.set_defaults(func=cmd_phase3)

    s4 = sub.add_parser("phase4", help="Download gevonden PDF's per gemeente")
    s4.add_argument("--limit-per-municipality", type=int, default=None, help="Max aantal pdfs per gemeente (test)")
    s4.add_argument("--base-dir", type=str, default=None, help="Basisdir voor gemeenten (default: CWD)")
    s4.set_defaults(func=cmd_phase4)

    s5 = sub.add_parser("first5", help="Voer end-to-end uit voor eerste 5 gemeenten m.b.v. alle_stemlokalen.json")
    s5.add_argument("--stemlokalen", type=str, default="alle_stemlokalen.json", help="Pad naar alle_stemlokalen.json")
    s5.add_argument("--max-pages", type=int, default=40, help="Max pagina's per gemeente crawlen")
    s5.add_argument("--max-depth", type=int, default=3, help="Crawl diepte binnen zelfde site")
    s5.add_argument("--use-sitemap", action="store_true", help="Forceer sitemap discovery voor alle 5 gemeenten")
    s5.add_argument("--only", nargs='*', help="Alleen deze gemeenten uitvoeren (subset van eerste 5)")
    s5.set_defaults(func=cmd_first5)

    # Convenience: fetch a single municipality and download immediately (v2 parity)
    s6 = sub.add_parser("fetch-one", help="Haal PDF's op voor één gemeente en download direct")
    s6.add_argument("--name", required=True, help="Naam van de gemeente, exact zoals in verified JSON (bijv. 'Aalten')")
    s6.add_argument("--max-pages", type=int, default=60)
    s6.add_argument("--max-depth", type=int, default=2)
    s6.add_argument("--limit-per-municipality", type=int, default=None)
    s6.set_defaults(func=cmd_fetch_one)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_argparser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
