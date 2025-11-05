#!/usr/bin/env python3
"""
Detecteer het modeltype van lokale verkiezings-PDFs en schrijf 'model' weg
in pdf_scraper_input/municipality_pdfs_index.json.

Herkenbare modellen (exacte labels):
  - N10-1
  - N10-2
  - Na 31-1
  - Na 31-2
  - overig

Detectiestrategie (snel → robuust):
  1) Heuristiek op basis van bestandsnaam, tekstvelden en URL-basename
  2) Zo nodig: eerste pagina van de lokale PDF uitlezen (indien mogelijk)

Gebruik:
  python3 detect_model.py [--only MUNICIPALITY ...] [--dry-run] [--refresh]
  python3 detect_model.py --model31
  python3 detect_model.py --model10

"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlparse, unquote
import shutil
import subprocess

DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
INDEX_PATH = os.path.join(DATA_DIR, "municipality_pdfs_index.json")
NAME_MAP_PATH = os.path.join(DATA_DIR, "municipality_name_mapping.json")


def load_index(path: str = INDEX_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data
    # legacy: list
    return {"results": data, "count": len(data)}


def save_index(data, path: str = INDEX_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_name_mapping(path: str = NAME_MAP_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def compile_regex():
    # Specifieke modellen eerst (om generieke hits te vermijden)
    # Scheidingstekens toestaan, en geen \b-grenzen gebruiken zodat _n10-2_ ook matcht
    sep = r"[-_\s–—]*"
    start = r"(?<![A-Za-z0-9])"
    end = r"(?![A-Za-z0-9])"
    rx = {
        "N10-1": re.compile(rf"{start}(?:model{sep})?n{sep}10{sep}1{end}", re.I),
        "N10-2": re.compile(rf"{start}(?:model{sep})?n{sep}10{sep}2{end}", re.I),
        "Na 31-2": re.compile(rf"{start}(?:model{sep})?na{sep}31{sep}2{end}", re.I),
        "Na 31-1": re.compile(rf"{start}(?:model{sep})?na{sep}31{sep}1{end}", re.I),
        # Generiek
        "N10": re.compile(rf"{start}(?:model{sep})?n{sep}10{end}", re.I),
        "Na31": re.compile(rf"{start}(?:model{sep})?na{sep}31{end}", re.I),
    }
    return rx


RX = compile_regex()


def norm_text(*parts: str | None) -> str:
    s = " ".join([p for p in parts if isinstance(p, str) and p])
    # URL path basenames ook meenemen gedecodeerd
    out = [s]
    for p in parts:
        if not isinstance(p, str) or not p:
            continue
        try:
            if p.startswith("http") or p.startswith("file://"):
                u = urlparse(p)
                out.append(unquote(os.path.basename(u.path)))
        except Exception:
            pass
    z = " ".join(out)
    return z


def detect_from_strings(s: str) -> str | None:
    if not s:
        return None
    # Volgorde is belangrijk
    if RX["N10-1"].search(s):
        return "N10-1"
    if RX["N10-2"].search(s):
        return "N10-2"
    if RX["Na 31-2"].search(s):
        return "Na 31-2"
    if RX["Na 31-1"].search(s):
        return "Na 31-1"
    # Default: als er wel 'N10' staat maar geen sublabel, kies N10-2 (TK-stembureaus)
    if RX.get("N10") and RX["N10"].search(s):
        return "N10-2"
    # Geen GSB-heuristiek: kan ook voorkomen in toelichtingen zonder dat het model Na31 is
    return None


def read_first_page_text(local_url: str) -> str | None:
    # Alleen file:// ondersteunen
    if not (isinstance(local_url, str) and local_url.lower().startswith("file://")):
        return None
    u = urlparse(local_url)
    path = unquote(u.path)
    # macOS paths uit file:// hebben een leading slash al; unquote is al gedaan in norm_text
    # Snelste pad: gebruik 'pdftotext' als beschikbaar om alleen pagina 1 te extraheren
    try:
        exe = shutil.which("pdftotext")
        if exe and os.path.exists(path):
            # Eerst: layout, daarna raw; neem de langste
            out_layout = subprocess.run([exe, "-q", "-f", "1", "-l", "1", "-layout", path, "-"],
                                        check=False, capture_output=True)
            txt_layout = out_layout.stdout.decode("utf-8", errors="ignore").strip()
            if txt_layout:
                return txt_layout
            out_raw = subprocess.run([exe, "-q", "-f", "1", "-l", "1", "-raw", path, "-"],
                                     check=False, capture_output=True)
            txt_raw = out_raw.stdout.decode("utf-8", errors="ignore").strip()
            if txt_raw:
                return txt_raw
    except Exception:
        pass
    try:
        # Probeer PyPDF2 – lichtgewicht en vaak aanwezig
        from PyPDF2 import PdfReader  # type: ignore
        with open(path, "rb") as f:
            reader = PdfReader(f)
            if len(reader.pages) == 0:
                return None
            page0 = reader.pages[0]
            try:
                txt = page0.extract_text() or ""
            except Exception:
                txt = ""
            return txt
    except Exception:
        # Val terug op pdfminer.six indien beschikbaar
        try:
            from pdfminer.high_level import extract_text  # type: ignore
            txt = extract_text(path, maxpages=1) or ""
            if txt:
                return txt
        except Exception:
            pass
    return None


def ocr_header_text(local_url: str) -> str | None:
    """OCR-fallback: render de kop (bovenste ~28%) van pagina 1 en lees met Tesseract (nld+eng).
    Gebruikt pdfplumber + pytesseract vergelijkbaar met ocr_methode1.
    """
    try:
        u = urlparse(local_url)
        path = unquote(u.path)
        import pdfplumber  # type: ignore
        from PIL import ImageOps, ImageFilter  # type: ignore
        from pytesseract import image_to_string  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            im = page.to_image(resolution=350).original
            h = im.height
            crop = im.crop((0, 0, im.width, int(h * 0.28)))
            g = ImageOps.grayscale(crop)
            g = ImageOps.autocontrast(g)
            g = g.filter(ImageFilter.SHARPEN)
            for langs in ("nld+eng", "eng"):
                try:
                    txt = image_to_string(g, config=f"--psm 6 -l {langs}")
                    if txt and txt.strip():
                        return txt
                except Exception:
                    continue
    except Exception:
        return None
    return None


def ocr_region_text(local_url: str, top_rel: float = 0.2, bottom_rel: float = 0.7, resolution: int = 350) -> str | None:
    """OCR een verticale strook van pagina 1 (top_rel..bottom_rel)."""
    try:
        u = urlparse(local_url)
        path = unquote(u.path)
        import pdfplumber  # type: ignore
        from PIL import ImageOps, ImageFilter  # type: ignore
        from pytesseract import image_to_string  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            im = page.to_image(resolution=resolution).original
            h = im.height
            y0 = max(0, int(h * max(0.0, min(1.0, top_rel))))
            y1 = max(y0 + 1, int(h * max(0.0, min(1.0, bottom_rel))))
            crop = im.crop((0, y0, im.width, y1))
            g = ImageOps.grayscale(crop)
            g = ImageOps.autocontrast(g)
            g = g.filter(ImageFilter.SHARPEN)
            for langs in ("nld+eng", "eng"):
                try:
                    txt = image_to_string(g, config=f"--psm 6 -l {langs}")
                    if txt and txt.strip():
                        return txt
                except Exception:
                    continue
    except Exception:
        return None
    return None


def is_bijlage_doc(local_url: str, text_hint: str | None = None, ocr_hint: str | None = None) -> bool:
    """Herken 'Bijlage 2' / 'uitkomsten per stembureau' documenten om ze te kunnen uitsluiten."""
    rx_bijlage = re.compile(r"\bbijlage\b", re.I)
    rx_bijlage2 = re.compile(r"\bbijlage\s*2\b", re.I)
    rx_uitkomsten = re.compile(r"uitkomsten\s+per\s+stembureau", re.I)
    rx_nummer = re.compile(r"nummer\s+stembureau", re.I)
    rx_locatie = re.compile(r"locatie\s+stembureau", re.I)

    for s in (text_hint or "", ocr_hint or ""):
        if not s:
            continue
        if rx_bijlage2.search(s) or (rx_bijlage.search(s) and rx_uitkomsten.search(s)) or rx_nummer.search(s) or rx_locatie.search(s):
            return True

    # Probeer uitgebreidere OCR-regio (middenstrook) om 'Bijlage 2' te vinden
    mid = ocr_region_text(local_url, 0.2, 0.7)
    if mid:
        if rx_bijlage2.search(mid) or (rx_bijlage.search(mid) and rx_uitkomsten.search(mid)) or rx_nummer.search(mid) or rx_locatie.search(mid):
            return True
    return False


def detect_model_for_item(p: dict) -> str:
    # 0) Zeer specifieke regel: als bestandsnaam duidelijk 'GSB' aangeeft,
    #    is dit bij TK2025 het gemeentelijk stembureau (Na 31-2)
    try:
        fname = (p.get("pdf_name") or "").lower()
        if ("gsb" in fname) or ("gemeentelijk stembureau" in fname):
            return "Na 31-2"
    except Exception:
        pass
    # 0b) Heuristiek: 'uitkomst' + 'tk25' in naam/URL/tekst duidt op centrale PV publicatie
    try:
        s0 = " ".join([
            (p.get("pdf_name") or "").lower(),
            (p.get("text") or "").lower(),
            (p.get("remote_url") or "").lower(),
        ])
        if ("uitkomst" in s0) and ("tk25" in s0 or "t k 25" in s0 or "tweede kamer 2025" in s0):
            return "Na 31-2"
    except Exception:
        pass
    # 1) Snelle heuristiek op strings
    s = norm_text(p.get("pdf_name"), p.get("text"), p.get("remote_url"), p.get("local_url"), p.get("from"))
    hit = detect_from_strings(s)
    if hit:
        return hit
    # 2) Eerste pagina van lokale PDF
    loc = p.get("local_url")
    t = read_first_page_text(loc) if loc else None
    if t:
        hit2 = detect_from_strings(t)
        if hit2:
            return hit2
    # 3) OCR fallback op kop als bovenstaande faalt
    if loc:
        t2 = ocr_header_text(loc)
        if t2:
            hit3 = detect_from_strings(t2)
            if hit3:
                return hit3
    return "overig"


def detect_doc_kind(p: dict) -> str | None:
    """Specifieke documentsoort naast het model, bijv. 'bijlage-2' (uitkomsten per stembureau).
    Laat 'model' ongemoeid; dit is extra metadata voor downstream filters.
    """
    loc = p.get("local_url")
    # Snelle bestandsnaam/broncheck om OCR te vermijden
    fname = (p.get("pdf_name") or "").lower()
    hint = (p.get("text") or "") + " " + (p.get("from") or "")
    if any(k in fname for k in ("bijlage",)) or ("uitkomst" in fname and "stembureau" in fname):
        return "bijlage-2"
    # Inhoudelijk checken met tekst/OCR
    t = read_first_page_text(loc) if loc else None
    o = None
    if not t:
        o = ocr_header_text(loc) if loc else None
    if is_bijlage_doc(loc or "", text_hint=t, ocr_hint=o):
        return "bijlage-2"
    return None


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detecteer model van lokale verkiezings-PDFs en update index")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen)")
    ap.add_argument("--dry-run", action="store_true", help="Geen wijzigingen schrijven, alleen tonen")
    ap.add_argument("--refresh", action="store_true", help="Herclassificeer alles (niet alleen ontbrekende modellen)")
    ap.add_argument("--model31", action="store_true", help="Genereer gemeente_model_31.json met alle gemeenten en hun Na 31-(-1/-2) PDFs")
    ap.add_argument("--model10", action="store_true", help="Vul gemeente_model_10.json met stembureau-PV's (N10-1/N10-2) op basis van bestandsnaam/anchor-tekst")
    ap.add_argument("--filename-only", action="store_true", help="In --model31 modus: alleen bestandsnaam-heuristiek toepassen (geen PDF-tekst of OCR)")
    ap.add_argument("--include-bijlage", action="store_true", help="Neem ook bijlages (bijlage 2: uitkomsten per stembureau) mee in --model31")
    ap.add_argument("--prune-bijlage", action="store_true", help="Verwijder bestaande bijlage-2/uitkomsten-per-stembureau items uit de JSON (alleen in --model31)")
    ap.add_argument("--limit", type=int, default=None, help="Beperk in --model31 modus het aantal te scannen gemeenten (voor snelle test)")
    args = ap.parse_args(argv)

    data = load_index(INDEX_PATH)
    results = data.get("results", [])

    # Speciale modus: export van alle gemeenten (afgeleid uit ./pdfs) met hun Model 31 (-1 of -2)
    if args.model31:
        name_map = load_name_mapping()
        def canonical(n: str) -> str:
            try:
                return name_map.get(n, n)
            except Exception:
                return n
        base_pdfs = os.path.join(os.path.dirname(__file__), "pdfs")
        if not os.path.isdir(base_pdfs):
            print(f"[model31] Map niet gevonden: {base_pdfs}")
            return 2

        # Verzamel gemeentenamen uit submappen van ./pdfs en sorteer A→Z
        municipalities_all = [d for d in os.listdir(base_pdfs) if os.path.isdir(os.path.join(base_pdfs, d))]
        # Ensure canonical keys exist in output space
        municipalities_all.sort(key=lambda s: s.lower())

        # Laad bestaande output (niet leegmaken!) en zorg dat alle gemeenten als key bestaan
        output_path = os.path.join(os.path.dirname(__file__), "gemeente_model_31.json")
        out = {}
        try:
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    maybe = json.load(f)
                if isinstance(maybe, dict):
                    out = maybe
        except Exception:
            out = {}
        for name in municipalities_all:
            cn = canonical(name)
            if cn not in out or not isinstance(out.get(cn), list):
                out[cn] = []

        # Optioneel beperken tot expliciet gevraagde gemeenten of een limiet (alleen voor verwerking)
        if args.only:
            only = set(args.only)
            to_process = [m for m in municipalities_all if (m in only) or (canonical(m) in only)]
        else:
            to_process = list(municipalities_all)
        if args.limit is not None:
            to_process = to_process[: max(0, int(args.limit))]

        # 1) Snelle pass: alleen bestandsnaam matchen (case-insensitive)
        #    Herken: 'na31' en 'n31' (met -, _ of spatie) en specifiek '31-1' / '31-2'
        #    Herken ook veelvoorkomende gemeentelijke naamgeving: 'uitkomst[_-]tk25' varianten
        # 'na31' moet als los 'na' voorkomen (geen deel van bv. 'Altena')
        rx_na31 = re.compile(r"(?<![A-Za-z])na[\s_\-–—]*31(?!\d)", re.I)
        rx_n31  = re.compile(r"(?<![A-Za-z])n[\s_\-–—]*31(?!\d)", re.I)
        # Vereis ten minste één scheidingsteken tussen '31' en '-1'/'-2' om '312' (stembureau-nummer) te vermijden
        rx_31_1 = re.compile(r"(?<!\d)31[\s_\-–—]+1(?!\d)", re.I)
        rx_31_2 = re.compile(r"(?<!\d)31[\s_\-–—]+2(?!\d)", re.I)
        rx_uitkomst_tk25 = re.compile(r"uitkomst[\s_\-–—]*tk[\s_\-–—]*25", re.I)

        def is_bijlage_filename(fname: str) -> bool:
            s = (fname or "").lower()
            if "bijlage" in s:
                return True
            # Heel specifiek patroon: uitkomsten per stembureau (ook met underscores/strepen)
            has_uitkomst = ("uitkomsten" in s) or ("uitkomst" in s) or ("uitslag" in s)
            if has_uitkomst and "stembureau" in s:
                return True
            # Sommige varianten gebruiken 'nummer-<n>' i.c.m. stembureau
            if "nummer" in s and "stembureau" in s:
                return True
            return False

        def merge_items(old_list, new_list):
            seen = set()
            merged = []
            for item in (list(old_list or []) + list(new_list or [])):
                if not isinstance(item, dict):
                    continue
                key = (item.get("local_url"), item.get("pdf_name"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append({
                    "pdf_name": item.get("pdf_name"),
                    "local_url": item.get("local_url"),
                })
            return merged

        # Optioneel bestaande bijlages wegfilteren (met inhoudelijke check)
        if args.prune_bijlage:
            for name in (to_process or []):
                items = out.get(name, [])
                if not isinstance(items, list):
                    continue
                new_items = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    fn = (it or {}).get("pdf_name") or ""
                    loc = (it or {}).get("local_url") or ""
                    # Snelle bestandsnaam check
                    s = fn.lower()
                    drop = False
                    if (
                        "bijlage" in s
                        or (("uitkomsten" in s or "uitkomst" in s or "uitslag" in s) and "stembureau" in s)
                        or ("nummer" in s and "stembureau" in s)
                    ):
                        drop = True
                    # Inhoudelijke check met tekst/OCR indien nog niet beslist
                    if not drop and loc:
                        t = read_first_page_text(loc) or ""
                        o = ocr_header_text(loc) or ""
                        if is_bijlage_doc(loc, text_hint=t, ocr_hint=o):
                            drop = True
                    if not drop:
                        new_items.append(it)
                out[name] = new_items

        # Altijd: snelle bijlage-prune op bestandsnaam (lichtgewicht), zodat oude bijlage-entries niet blijven hangen
        for name in (to_process or []):
            items = out.get(name, [])
            if not isinstance(items, list):
                continue
            quick = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                s = ((it or {}).get("pdf_name") or "").lower()
                is_bij = (
                    ("bijlage" in s)
                    or (("uitkomsten" in s or "uitkomst" in s or "uitslag" in s) and "stembureau" in s)
                    or ("nummer" in s and "stembureau" in s)
                )
                if not is_bij:
                    quick.append(it)
            out[name] = quick

        # Extra: verwijder bestaande items die géén Na 31-1/Na 31-2 zijn (bv. N10-2 stembureau-PV's die eerder per ongeluk zijn toegevoegd)
        # Dit maakt 'empties' vrij voor een verse inhoudelijke scan.
        for name in (to_process or []):
            items = out.get(canonical(name), [])
            if not isinstance(items, list) or not items:
                continue
            kept = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                loc = (it or {}).get("local_url") or ""
                t = read_first_page_text(loc) or ""
                label = detect_from_strings(t) if t else None
                # Als tekst geen Na31 oplevert, probeer alsnog OCR
                if label not in ("Na 31-1", "Na 31-2"):
                    txt = ocr_header_text(loc) or ""
                    if txt:
                        label = detect_from_strings(txt) or label
                if label in ("Na 31-1", "Na 31-2"):
                    kept.append(it)
            out[canonical(name)] = kept

        # Regex voor GSB in bestandsnaam
        rx_gsb_name = re.compile(r"\bgsb\b", re.I)
        rx_gemeentelijk_in_name = re.compile(r"gemeentelijk\s+stembureau", re.I)

        for name in to_process:
            gdir = os.path.join(base_pdfs, name)
            coll: list[dict] = []
            try:
                files = [f for f in os.listdir(gdir) if f.lower().endswith(".pdf")]
            except Exception:
                files = []
            for fn in files:
                s = fn
                if (rx_na31.search(s) or rx_n31.search(s) or rx_31_1.search(s) or rx_31_2.search(s) or rx_uitkomst_tk25.search(s)
                    or rx_gsb_name.search(s) or rx_gemeentelijk_in_name.search(s)) and not is_bijlage_filename(s):
                    abspath = os.path.join(gdir, fn)
                    coll.append({
                        "pdf_name": fn,
                        "local_url": f"file://{abspath}",
                    })
            if coll:
                out[canonical(name)] = merge_items(out.get(canonical(name), []), coll)

        # 2) Voor gemeenten zonder resultaten: snelle tekstextractie van pagina 1, daarna OCR‑fallback
        empties = [n for n in to_process if not out.get(canonical(n))]
        if empties and not args.filename_only:
            rx_bijlage = re.compile(r"\bbijlage\b", re.I)
            rx_bijlage2 = re.compile(r"\bbijlage\s*2\b", re.I)
            rx_uitkomsten = re.compile(r"uitkomsten\s+per\s+stembureau", re.I)
            for name in empties:
                gdir = os.path.join(base_pdfs, name)
                try:
                    files = [f for f in os.listdir(gdir) if f.lower().endswith(".pdf")]
                except Exception:
                    files = []
                coll: list[dict] = []
                for fn in files:
                    abspath = os.path.join(gdir, fn)
                    loc = f"file://{abspath}"
                    # 2a. tekst van pagina 1 (snel)
                    t = read_first_page_text(loc) or ""
                    ok_text = False
                    if t:
                        hit = detect_from_strings(t)
                        ok_text = bool((hit in ("Na 31-1", "Na 31-2")) or RX["Na31"].search(t))
                        if ok_text and (args.include_bijlage or not is_bijlage_doc(loc, text_hint=t)):
                            coll.append({
                                "pdf_name": fn,
                                "local_url": loc,
                            })
                            continue
                    # 2b. OCR van kop (fallback wanneer tekst ontbreekt of geen match vindt)
                    txt = ocr_header_text(loc) or ""
                    if txt:
                        hit = detect_from_strings(txt)
                        if (hit in ("Na 31-1", "Na 31-2") or RX["Na31"].search(txt)):
                            if args.include_bijlage or not is_bijlage_doc(loc, ocr_hint=txt):
                                coll.append({
                                    "pdf_name": fn,
                                    "local_url": loc,
                                })
                if coll:
                    out[canonical(name)] = merge_items(out.get(canonical(name), []), coll)

        # 3) Verfijn gemeenten met meerdere treffers: kies beste per variant (-1/-2) op basis van inhoud
        def refine_multi_for_muni(name: str, items: list[dict]) -> list[dict]:
            if not items or len(items) <= 1:
                return items or []
            # Filter op bestandsnaam (bijlage/per-stembureau) vooraf
            prelim = [it for it in items if not (is_bijlage_filename((it or {}).get("pdf_name") or ""))]
            if not prelim:
                prelim = list(items)

            rx_gsb = re.compile(r"(gemeentelijk\s+stembureau|\bgsb\b)", re.I)
            rx_pv = re.compile(r"proces[-\s]?verbaal", re.I)
            rx_cso = re.compile(r"centrale\s+stemopneming", re.I)
            rx_nummer = re.compile(r"nummer\s+stembureau", re.I)
            rx_locatie = re.compile(r"locatie\s+stembureau", re.I)

            scored: list[tuple[int, str, dict]] = []
            for it in prelim:
                fn = (it or {}).get("pdf_name") or ""
                loc = (it or {}).get("local_url") or ""
                text = read_first_page_text(loc) or ""
                ocr = None
                score = 0
                label = detect_from_strings(text) if text else None
                # Als tekst geen Na31 label oplevert, probeer OCR
                if label not in ("Na 31-1", "Na 31-2"):
                    ocr = ocr_header_text(loc) or ""
                    if ocr and not label:
                        label = detect_from_strings(ocr)
                s_all = (text or "") + "\n" + (ocr or "")
                # hoofd-PV kenmerken
                if rx_pv.search(s_all) and rx_gsb.search(s_all):
                    score += 5
                if rx_cso.search(s_all):
                    score += 1
                # bijlage/per-stembureau signalen
                if is_bijlage_doc(loc, text_hint=text, ocr_hint=ocr or None):
                    score -= 10
                if rx_nummer.search(s_all) or rx_locatie.search(s_all):
                    score -= 3
                if label in ("Na 31-1", "Na 31-2"):
                    score += 2
                scored.append((score, label or "", it))

            by_var: dict[str, list[tuple[int, str, dict]]] = {}
            for tpl in scored:
                by_var.setdefault(tpl[1], []).append(tpl)
            selected: list[dict] = []
            for var in ("Na 31-2", "Na 31-1"):
                if var in by_var:
                    best = sorted(by_var[var], key=lambda x: x[0], reverse=True)[0]
                    selected.append(best[2])
            if not selected and scored:
                best_overall = sorted(scored, key=lambda x: x[0], reverse=True)[0]
                selected.append(best_overall[2])
            return selected

        if not args.filename_only:
            multis = [n for n in to_process if len(out.get(canonical(n), [])) > 1]
            for name in multis:
                cn = canonical(name)
                refined = refine_multi_for_muni(cn, out.get(cn, []))
                out[cn] = merge_items([], refined)

        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, output_path)
        print(f"[model31] Geschreven: {output_path} (gemeenten={len(out)}, verwerkt={len(to_process)})")
        return 0

    # Speciale modus: vul gemeente_model_10.json met stembureau-PV's op basis van naam/anchor (geen OCR)
    if args.model10:
        # Laad index + bestaande model_10
        idx = load_index(INDEX_PATH)
        results = idx.get("results", [])
        base_pdfs = os.path.join(os.path.dirname(__file__), "pdfs")
        g10_path = os.path.join(os.path.dirname(__file__), "gemeente_model_10.json")
        try:
            with open(g10_path, "r", encoding="utf-8") as f:
                g10 = json.load(f)
        except FileNotFoundError:
            print(f"[model10] {g10_path} ontbreekt")
            return 2
        except Exception as e:
            print(f"[model10] Kan {g10_path} niet lezen: {e}")
            return 2

        # Naam-normalisatie en aliassen (om gemeente-namen te mappen tussen datasets)
        import re as _re
        def _norm(s: str) -> str:
            s = (s or "").strip()
            s = s.replace("’", "'").replace(".", "")
            s = _re.sub(r"\s+", " ", s)
            return s.lower()
        aliases = {
            "den haag": "'s-Gravenhage",
            "hengelo": "Hengelo (O.)",
            "laren": "Laren (NH.)",
            "middelburg": "Middelburg (Z.)",
            "rijswijk": "Rijswijk (ZH.)",
            "stein": "Stein (L.)",
            "beek": "Beek (L.)",
            "bergen (l)": "Bergen (L.)",
            "bergen (nh)": "Bergen (NH.)",
            "nuenen": "Nuenen, Gerwen en Nederwetten",
            "'s-gravenhage": "'s-Gravenhage",
            "'s-hertogenbosch": "'s-Hertogenbosch",
        }
        g10_keys_norm = {_norm(k): k for k in g10.keys()}

        def map_muni(name: str) -> str | None:
            if name in g10:
                return name
            n = _norm(name)
            if n in g10_keys_norm:
                return g10_keys_norm[n]
            if n in aliases and aliases[n] in g10:
                return aliases[n]
            # probeer haakjes/dubbele delen te reduceren
            m = _re.match(r"^(.*?)(\s*\([^)]*\))$", name)
            if m:
                base = m.group(1).strip()
                nb = _norm(base)
                if nb in g10_keys_norm:
                    return g10_keys_norm[nb]
            if "," in name:
                base = name.split(",", 1)[0].strip()
                nb = _norm(base)
                if nb in g10_keys_norm:
                    return g10_keys_norm[nb]
            return None

        # Heuristieken om stembureau-nummer/naam uit bestandsnaam/anchor te halen
        RX_SB_NUM = _re.compile(r"stembureau[^0-9]{0,6}(\d{1,3})", _re.I)
        # SB-prefix varianten: 'SB1', 'SB 1', 'SB-1', 'SB_1'
        RX_SB_PREFIX = _re.compile(r"\bsb[\s._-]*([0-9]{1,3})\b", _re.I)
        RX_BUREAU_NUM = _re.compile(r"\bbureau[^0-9]{0,6}(\d{1,3})\b", _re.I)
        # variant met '20' of '%20' (URL/naam-artefact) tussen 'stembureau' en nummer
        RX_SB_NUM_20 = _re.compile(r"stembureau(?:%20|20|\s|[_\-])*([0-9]{1,3})", _re.I)
        RX_UNDERSCORE_NUM = _re.compile(r"[_\-\s]([0-9]{1,3})[_\-\s]", _re.I)
        # suffix nummer direct voor extensie: ..._12.pdf
        RX_SUFFIX_NUM = _re.compile(r"[_\-\s]([0-9]{1,3})(?:\.|$)", _re.I)
        RX_TK_NUM = _re.compile(r"[_\-]([0-9]{1,3})[_\-].*?tk\s*20?25", _re.I)
        RX_LEADING_NUM = _re.compile(r"^\s*([0-9]{1,3})\s*[\.|\-_]", _re.I)

        # Ranges zoals '111 t/m 123', '111 tot en met 123', '111-123'
        RX_RANGE_TEM = _re.compile(r"(\d{1,3})\s*(?:t\s*/\s*m|tm|tot(?:\s*|[-–—])en(?:\s*|[-–—])met)\s*(\d{1,3})", _re.I)
        RX_RANGE_DASH = _re.compile(r"(\d{1,3})\s*[-–—]\s*(\d{1,3})")

        def extract_range(s: str) -> tuple[int,int] | None:
            if not s:
                return None
            for rx in (RX_RANGE_TEM, RX_RANGE_DASH):
                m = rx.search(s)
                if m:
                    try:
                        a = int(m.group(1)); b = int(m.group(2))
                        if 0 < a < 2000 and 0 < b < 2000 and a <= b and (b - a) <= 500:
                            return (a, b)
                    except Exception:
                        continue
            return None

        def extract_number(s: str) -> int | None:
            if not s:
                return None
            for rx in (RX_LEADING_NUM, RX_TK_NUM, RX_SB_PREFIX, RX_SB_NUM_20, RX_SB_NUM, RX_BUREAU_NUM, RX_SUFFIX_NUM, RX_UNDERSCORE_NUM):
                m = rx.search(s)
                if m:
                    try:
                        v = int(m.group(1))
                        if 0 < v < 1000:
                            return v
                    except Exception:
                        pass
            return None

        def extract_number_with_muni(s: str, muni_for_prefix: str | None = None) -> int | None:
            if not s or not muni_for_prefix:
                return None
            try:
                mn = norm_for_match(muni_for_prefix)
                sn = norm_for_match(s)
                import re as _re
                m = _re.search(rf"{_re.escape(mn)}\s*([0-9]{{1,3}})", sn)
                if m:
                    v = int(m.group(1))
                    if 0 < v < 1000:
                        return v
            except Exception:
                return None
            return None

        def is_probable_model10(s: str, muni_for_prefix: str | None = None) -> bool:
            if not s:
                return False
            s2 = s.lower()
            # expliciete N10 detectie
            if RX.get("N10-1").search(s) or RX.get("N10-2").search(s) or RX.get("N10").search(s):
                return True
            # gangbare naamgevingen: bevat 'stembureau' en een nummer, of TK25/TK2025 met nummer
            if ("stembureau" in s2 and extract_number(s) is not None):
                return True
            if (("tk25" in s2 or "tk2025" in s2) and extract_number(s) is not None):
                return True
            # gemeente + nummer (ook aaneengeplakt) ergens in de bestandsnaam
            if muni_for_prefix and (extract_number_with_muni(s, muni_for_prefix) is not None):
                return True
            # leidend nummer-formaat '1. Naam ...'
            if RX_LEADING_NUM.search(s or ""):
                return True
            # Bestandsnamen in vorm '<Gemeente>_<nummer>_...' (zonder TK- of 'stembureau'-vermelding)
            if muni_for_prefix:
                mn = norm_for_match(muni_for_prefix)
                sn = norm_for_match(s)
                num = extract_number(s)
                if mn and (num is not None):
                    # sta prefix of algemene aanwezigheid toe (prefix het sterkst)
                    if sn.startswith(f"{mn} {num}") or (mn in sn and f" {num} " in sn):
                        return True
                # Fallback: als nummer 'vastgeplakt' staat aan gemeentenaam (oldenzaal1...)
                # probeer direct na prefix een cijferreeks te detecteren
                if mn and (num is None):
                    import re as _re
                    m = _re.search(rf"^{_re.escape(mn)}\s*(\d{{1,3}})", sn)
                    if m:
                        return True
            return False

        def norm_for_match(x: str) -> str:
            z = (x or "").lower()
            z = _re.sub(r"[^a-z0-9]+", " ", z)
            z = _re.sub(r"\s+", " ", z).strip()
            return z

        updated = 0
        total_seen = 0
        for entry in results:
            muni = entry.get("name") or ""
            key = map_muni(muni)
            if not key or key not in g10:
                continue
            arr = g10.get(key) or []
            if not isinstance(arr, list):
                continue
            # snel indexen op nummer en naam
            by_num: dict[int, dict] = {}
            by_num_mod: dict[int, list] = {}
            by_name_norm: dict[str, dict] = {}
            for it in arr:
                try:
                    n = int(it.get("stembureau_nummer"))
                    if 0 < n < 2000:
                        by_num[n] = it
                        by_num_mod.setdefault(n % 100, []).append(it)
                except Exception:
                    pass
                nm = norm_for_match(str(it.get("stembureau_naam") or ""))
                if nm:
                    by_name_norm[nm] = it

            for p in (entry.get("pdfs") or []):
                loc = p.get("local_url")
                if not loc:
                    continue
                # alleen op naam/anchor/url; geen inhoudelijke OCR
                s = norm_text(p.get("pdf_name"), p.get("text"), p.get("remote_url"))
                s_low = s.lower()
                # Vroege naam-match fallback: als exact één stembureaunaam in bestandsnaam zit, accepteer ook zonder 'probable' hints
                s_match = norm_for_match(s)
                pre_cands = [it for nm,it in by_name_norm.items() if nm and nm in s_match]
                pre_target = pre_cands[0] if len(pre_cands) == 1 else None
                if (not pre_target) and (not is_probable_model10(s, muni_for_prefix=muni)):
                    continue
                total_seen += 1
                # Arnhem-achtig: 'stembureaus 111 t/m 123' → koppel hetzelfde bestand aan alle nummers in range
                rng = extract_range(s)
                if rng and (('proces' in s_low and 'verbaal' in s_low) or RX.get('N10').search(s)):
                    a,b = rng
                    for rn in range(a, b+1):
                        tgt = by_num.get(rn)
                        if not tgt:
                            cands = by_num_mod.get(rn) or []
                            if len(cands) == 1:
                                tgt = cands[0]
                        if not tgt:
                            continue
                        # schrijf hoofdvariant (niet 'eerste')
                        fname = p.get('pdf_name') or (p.get('text') or '')
                        if (not tgt.get('local_url')):
                            tgt['local_url'] = loc
                            tgt['pdf_name'] = fname
                            updated += 1
                    continue
                nr = extract_number(s)
                if nr is None:
                    nr = extract_number_with_muni(s, muni)
                target = pre_target
                if (nr is not None):
                    if nr in by_num:
                        target = by_num[nr]
                    else:
                        # Heuristiek: sommige gemeenten nummeren WMS als 101.. en bestanden als _1..; koppel op mod 100 indien uniek
                        cands = by_num_mod.get(nr) or []
                        if len(cands) == 1:
                            target = cands[0]
                else:
                    # probeer naam-match (als pre_target niet al is gezet)
                    if not target:
                        cands = [it for nm,it in by_name_norm.items() if nm and nm in s_match]
                        if len(cands) == 1:
                            target = cands[0]
                if not target:
                    # Single-bureau fallback: als deze gemeente precies één stembureau heeft
                    # en het document duidelijk een N10‑proces‑verbaal is, koppel het aan dat ene bureau.
                    if (len(arr) == 1) and is_probable_model10(s, muni_for_prefix=muni):
                        target = arr[0]
                if not target:
                    continue
                # kies preferente bestanden (kandidaatniveau zonder 'eerste'/'tussentijdse')
                fname = p.get("pdf_name") or ""
                f_low = (fname or "").lower()
                # Bepaal variant: 'eerste telling' (of tussentijds/voorlopig) vs kandidaatniveau; en 'aanpassing'-varianten
                is_eerste = ("eerste" in f_low) or ("tussentijd" in f_low) or ("voorlop" in f_low)
                is_adj = ("aanpassing" in f_low) or ("aanpass" in f_low)

                # Sla beide varianten op: voorkeursvelden voor kandidaatniveau (local_url/pdf_name)
                # en aparte velden voor de eerste telling (local_url_eerste/pdf_name_eerste)
                if is_eerste:
                    if (not target.get("local_url_eerste")):
                        target["local_url_eerste"] = loc
                        target["pdf_name_eerste"] = fname or (p.get("text") or "")
                        updated += 1
                else:
                    already = target.get("local_url")
                    if (already is None) or (already == ""):
                        target["local_url"] = loc
                        target["pdf_name"] = fname or (p.get("text") or "")
                        updated += 1
                    else:
                        # alleen overschrijven als huidig bestand waarschijnlijk minder geschikt is
                        cur = (target.get("pdf_name") or "").lower()
                        cur_is_eerste = ("eerste" in cur) or ("tussentijd" in cur) or ("voorlop" in cur)
                        cur_is_adj = ("aanpassing" in cur) or ("aanpass" in cur)
                        if cur_is_eerste or (cur_is_adj and not is_adj):
                            target["local_url"] = loc
                            target["pdf_name"] = fname or (p.get("text") or "")
                            updated += 1

            # Fallback: scan ook de lokale map 'pdfs/<Gemeente>' om missende koppelingen bij te vullen
            try:
                base_dir = os.path.join(os.path.dirname(__file__), "pdfs")
                # Probeer zowel de gemapte sleutel (bijv. 'Middelburg (Z.)') als de indexnaam (bijv. 'Middelburg')
                candidate_dirs = [
                    os.path.join(base_dir, key),
                    os.path.join(base_dir, muni),
                ]
                files = []
                gdir = None
                for d in candidate_dirs:
                    if os.path.isdir(d):
                        gdir = d
                        files = [f for f in os.listdir(d) if f.lower().endswith('.pdf')]
                        if files:
                            break
            except Exception:
                files = []
            for fn in files:
                try:
                    abspath = os.path.join(gdir or os.path.join(os.path.dirname(__file__), "pdfs", key), fn)
                    loc = f"file://{abspath}"
                    s = fn
                    # snelle naam-heuristiek
                    nr = extract_number(s)
                    if nr is None:
                        nr = extract_number_with_muni(s, muni)
                    s_norm = norm_for_match(s)
                    # OCR/tekst fallback om N10 te bevestigen
                    probable_name = is_probable_model10(s, muni_for_prefix=muni)
                    probable_text = False
                    if not probable_name:
                        t = read_first_page_text(loc) or ""
                        if not t:
                            t = ocr_header_text(loc) or ""
                        if t:
                            probable_text = bool(detect_from_strings(t)) or ("proces" in t.lower() and "verbaal" in t.lower())
                    if not (probable_name or probable_text):
                        continue
                    target = None
                    if (nr is not None) and (nr in by_num):
                        target = by_num.get(nr)
                    if not target and len(arr) == 1:
                        target = arr[0]
                    if not target:
                        cands = [it for nm,it in by_name_norm.items() if nm and nm in s_norm]
                        if len(cands) == 1:
                            target = cands[0]
                    if not target:
                        continue
                    low = s.lower()
                    is_eerste = ("eerste" in low) or ("tussentijd" in low) or ("voorlop" in low)
                    if is_eerste:
                        if not target.get("local_url_eerste"):
                            target["local_url_eerste"] = loc
                            target["pdf_name_eerste"] = fn
                            updated += 1
                    else:
                        if not target.get("local_url"):
                            target["local_url"] = loc
                            target["pdf_name"] = fn
                            updated += 1
                except Exception:
                    # bij fouten in individuele bestanden, ga door met de volgende
                    continue
            # einde folder fallback

            # Post-processing: rangebestanden zoals 'stembureaus 111 t/m 123' → vul voor alle nummers in de range
            try:
                for it in arr:
                    fn = (it or {}).get('pdf_name') or ''
                    lu = (it or {}).get('local_url') or ''
                    if not fn or not lu:
                        continue
                    rng = extract_range(fn)
                    if not rng:
                        rng = extract_range((it or {}).get('stembureau_naam') or '')
                    if not rng:
                        continue
                    a,b = rng
                    for rn in range(a,b+1):
                        tgt = by_num.get(rn)
                        if not tgt:
                            cands = by_num_mod.get(rn) or []
                            if len(cands) == 1:
                                tgt = cands[0]
                        if not tgt:
                            continue
                        if not tgt.get('local_url'):
                            tgt['local_url'] = lu
                            tgt['pdf_name'] = fn
                            updated += 1
            except Exception:
                pass

        if args.dry_run:
            print(f"[model10] Done (dry-run). matched={total_seen}, updated={updated}")
            return 0

        # schrijf terug
        tmp = g10_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(g10, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, g10_path)
        print(f"[model10] Done. matched={total_seen}, updated={updated} -> {g10_path}")
        return 0

    # Subset bepalen
    if args.only:
        only = set(args.only)
        todo = [e for e in results if e.get("name") in only]
    else:
        todo = list(results)

    updated = 0
    total = 0
    for entry in todo:
        name = entry.get("name") or ""
        pdfs = entry.get("pdfs") or []
        for p in pdfs:
            # Alleen lokale bestanden classificeren
            if not p.get("local_url"):
                continue
            # Default: alleen ontbrekende modellen aanvullen, behalve als --refresh is gezet
            if not args.refresh and p.get("model"):
                continue
            total += 1
            new_model = detect_model_for_item(p)
            old_model = p.get("model")
            if old_model != new_model:
                p["model"] = new_model
                updated += 1
            # Extra annotatie: documentsoort (bijlage-2) indien herkend
            try:
                kind = detect_doc_kind(p)
                if kind:
                    p["doc_kind"] = kind
            except Exception:
                pass
        # einde entry

    if args.dry_run:
        print(f"[detect] Done (dry-run). to_classify={total}, updated={updated}")
        return 0

    # Schrijf terug
    data["count"] = len(results)
    save_index(data, INDEX_PATH)
    print(f"[detect] Done. classified={total}, updated={updated} -> {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
