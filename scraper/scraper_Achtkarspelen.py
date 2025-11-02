#!/usr/bin/env python3
import os
import re
import sys
import json
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


DATA_DIR = os.path.join(os.getcwd(), "data")
DEFAULT_SEED = "https://www.achtkarspelen.nl/uitslag-tweede-kamerverkiezing-2025"
TARGET_DIR = os.path.join(os.getcwd(), "Achtkarspelen")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def http_get(url: str, timeout: float = 25.0, headers: dict | None = None) -> requests.Response:
    default_headers = {
        "User-Agent": "restzetels-scraper/0.1 (+https://example.local)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    r = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def load_extra_seeds(path: str = os.path.join(DATA_DIR, "extra_seeds.json")) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def extract_pdf_links_from_page(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    pdfs: list[dict] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        pth = urlparse(full).path.lower()
        if not (pth.endswith(".pdf") or ".pdf" in pth):
            continue
        text = a.get_text(" ", strip=True)
        try:
            pdf_name = os.path.basename(urlparse(full).path)
        except Exception:
            pdf_name = "document.pdf"
        if not pdf_name.lower().endswith(".pdf"):
            pdf_name += ".pdf"
        pdfs.append({
            "url": full,
            "pdf_name": pdf_name,
            "text": text,
            "from": base_url,
        })

    # deduplicate by URL
    seen = set()
    out = []
    for p in pdfs:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        out.append(p)
    return out


def discover_achtkarspelen_seeds() -> list[str]:
    seeds_map = load_extra_seeds()
    seeds = seeds_map.get("Achtkarspelen", []) or []
    # ensure the default seed is present (first for priority)
    if DEFAULT_SEED not in seeds:
        seeds = [DEFAULT_SEED] + seeds
    return seeds


def download(url: str, out_dir: str, suggested_name: str | None = None) -> str | None:
    ensure_dir(out_dir)
    try:
        r = requests.get(url, headers={"User-Agent": "restzetels-scraper/0.1"}, timeout=45)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").lower()
        # be permissive: accept if content-type is pdf or url path ends with .pdf
        if "application/pdf" not in ct and not urlparse(url).path.lower().endswith(".pdf"):
            print(f"[achtkarspelen] Skip non-PDF: {url} ({ct})")
            return None
        filename = suggested_name or os.path.basename(urlparse(url).path) or "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        final_path = os.path.join(out_dir, sanitize_filename(filename))
        base, ext = os.path.splitext(final_path)
        i = 1
        use = final_path
        while os.path.exists(use):
            use = f"{base}_{i}{ext}"
            i += 1
        with open(use, "wb") as f:
            f.write(r.content)
        return use
    except Exception as e:
        print(f"[achtkarspelen] Error downloading {url}: {e}")
        return None


def run() -> int:
    ensure_dir(TARGET_DIR)
    seeds = discover_achtkarspelen_seeds()
    all_pdfs: list[dict] = []
    print(f"[achtkarspelen] Using {len(seeds)} seed(s)")
    for i, seed in enumerate(seeds, start=1):
        try:
            resp = http_get(seed)
            pdfs = extract_pdf_links_from_page(resp.text, resp.url)
            print(f"[achtkarspelen] Seed {i}/{len(seeds)}: {seed} -> {len(pdfs)} pdf links")
            all_pdfs.extend(pdfs)
        except Exception as e:
            print(f"[achtkarspelen] Error fetching seed {seed}: {e}")

    # dedup across seeds
    seen = set()
    unique_pdfs: list[dict] = []
    for p in all_pdfs:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        unique_pdfs.append(p)
    print(f"[achtkarspelen] Total unique PDFs: {len(unique_pdfs)}")

    saved = 0
    for p in unique_pdfs:
        out = download(p["url"], TARGET_DIR, p.get("pdf_name"))
        if out:
            saved += 1
            print(f"[achtkarspelen] Saved: {out}")
    print(f"[achtkarspelen] Done. Saved {saved} PDFs to {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(run())

