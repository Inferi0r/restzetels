#!/usr/bin/env python3
"""
MijnStembureau scraper (PV downloads)

Targets municipal MijnStembureau portals like:
  https://mijnstembureau-<slug>.nl/uitslagen/verkiezingen/tk/download-opties

Flow (generic for similar portals):
  1) Discover the MijnStembureau link starting from municipal pages
     like '/verkiezingen', '/tweede-kamerverkiezingen-2025', '/uitslagen-verkiezingen'.
  2) Open the download-options page
  3) Click the "Processen verbaal" section to reveal PV list
  4) For each PV entry (rendered as a button with ".pdf" in the label),
     click and capture the application/pdf network response, then save
     the bytes to scraper/pdfs/<Gemeente>/<filename>.

Requires: playwright, requests, beautifulsoup4
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
OUT_BASE = os.path.join(os.path.dirname(__file__), "pdfs")


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def http_get(url: str, timeout: float = 20.0) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": "restzetels-cleaned/0.1"}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def find_mijnstembureau_link_for_municipality(name: str) -> str | None:
    """Try a few known municipal pages and return the MijnStembureau link if present."""
    # Minimal lookup: use verified links if available to build base
    verified_path = os.path.join(DATA_DIR, "municipality_links_verified.json")
    seeds: list[str] = []
    try:
        import json
        with open(verified_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for v in data.get("verified", []):
            if v.get("name") == name:
                if v.get("final_url"):
                    seeds.append(v["final_url"])
                if v.get("start_url"):
                    seeds.append(v["start_url"])
                break
    except Exception:
        pass
    # Add common content paths
    uniq = []
    seen = set()
    for s in seeds:
        if s and s not in seen:
            uniq.append(s); seen.add(s)
    seeds = uniq
    extra_paths = [
        "/verkiezingen",
        "/tweede-kamerverkiezingen-2025",
        "/uitslagen-verkiezingen",
    ]
    # Expand seeds with common pages on the same host
    more: list[str] = []
    for s in list(seeds):
        try:
            pu = urlparse(s)
            base = f"{pu.scheme}://{pu.netloc}"
            for p in extra_paths:
                more.append(urljoin(base + "/", p.lstrip("/")))
        except Exception:
            pass
    seeds += more

    for s in seeds:
        try:
            r = http_get(s, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href]"):
                href = a.get("href")
                if not href:
                    continue
                full = urljoin(r.url, href)
                up = urlparse(full)
                if up.netloc.startswith("mijnstembureau-") and "/uitslagen/verkiezingen" in up.path:
                    # Prefer the explicit download options if present
                    if not up.path.rstrip("/").endswith("download-opties"):
                        full = urljoin(full.rstrip("/") + "/", "download-opties")
                    return full
        except Exception:
            continue
    return None


def scrape_mijnstembureau_downloads(muni: str, start_url: str) -> int:
    """Open the MijnStembureau download options and download all PV PDFs.
    Returns the number of saved PDFs.
    """
    out_dir = os.path.join(OUT_BASE, sanitize_filename(muni))
    os.makedirs(out_dir, exist_ok=True)

    saved = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass

        # Click Processen verbaal
        clicked = False
        for t in ("Processen verbaal", "Proces-verbaal", "Proces", "verbaal"):
            try:
                el = page.get_by_text(t, exact=False).first
                if el and el.is_visible():
                    el.click(timeout=15000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            print(f"[mijnstembureau] {muni}: kon 'Processen verbaal' niet vinden op {start_url}")
            ctx.close(); browser.close()
            return 0

        # Wait briefly for list
        try:
            page.wait_for_timeout(800)
        except Exception:
            pass

        # The PV list renders as buttons with labels ending in .pdf
        pdf_buttons = page.locator('button:has-text(".pdf")')
        count = pdf_buttons.count()
        print(f"[mijnstembureau] {muni}: gevonden {count} PV-items")

        # Iterate and capture application/pdf responses on click
        for i in range(count):
            try:
                btn = page.locator('button:has-text(".pdf")').nth(i)
                label = sanitize_filename((btn.inner_text() or "").strip()) or f"pv_{i+1}.pdf"
                if not label.lower().endswith('.pdf'):
                    label += '.pdf'
                dest = os.path.join(out_dir, label)
                if os.path.exists(dest):
                    continue

                def is_pdf(resp):
                    try:
                        ct = (resp.headers.get('content-type') or '').lower()
                        return 'application/pdf' in ct and '/uitslagen/api/' in resp.url
                    except Exception:
                        return False

                with page.expect_response(is_pdf, timeout=45000) as resp_info:
                    btn.click(timeout=15000)
                resp = resp_info.value
                data = resp.body()
                with open(dest, 'wb') as f:
                    f.write(data)
                saved += 1
                if saved % 10 == 0:
                    print(f"[mijnstembureau] {muni}: saved {saved}/{count}")
            except Exception as e:
                print(f"[mijnstembureau] {muni}: fout bij item {i+1}: {e}")
                continue
        ctx.close(); browser.close()
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MijnStembureau PV scraper")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen). Default: Emmen")
    args = ap.parse_args(argv)

    names = args.only if args.only else ["Emmen"]

    total = 0
    for name in names:
        url = find_mijnstembureau_link_for_municipality(name)
        if not url:
            print(f"[mijnstembureau] {name}: geen MijnStembureau-link gevonden op gemeentelijke pagina's")
            continue
        print(f"[mijnstembureau] {name}: start {url}")
        saved = scrape_mijnstembureau_downloads(name, url)
        print(f"[mijnstembureau] {name}: saved {saved} PDFs")
        total += saved
    print(f"[mijnstembureau] Done. Total saved: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

