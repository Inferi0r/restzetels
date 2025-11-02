#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def run(cmd: List[str], timeout: int = 120) -> tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def tesseract_tsv(image_path: Path, lang: str = "nld+eng") -> List[Dict]:
    cmd = [
        "tesseract",
        str(image_path),
        "stdout",
        "tsv",
        "--psm",
        "6",
        "-l",
        lang,
    ]
    code, out, err = run(cmd, timeout=180)
    if code != 0:
        raise RuntimeError(f"tesseract failed: {err}")
    header = None
    rows: List[Dict] = []
    for i, line in enumerate(out.splitlines()):
        parts = line.split("\t")
        if i == 0:
            header = parts
            continue
        if header and len(parts) == len(header):
            rec = dict(zip(header, parts))
            # normalize ints
            for k in ("level","page_num","block_num","par_num","line_num","word_num","left","top","width","height"):
                if k in rec and rec[k].isdigit():
                    rec[k] = int(rec[k])
            rows.append(rec)
    return rows


def tesseract_words_digits(image_path: Path) -> List[Dict]:
    cmd = [
        "tesseract",
        str(image_path),
        "stdout",
        "tsv",
        "--psm",
        "6",
        "-l",
        "eng",
        "-c",
        "tessedit_char_whitelist=0123456789",
    ]
    code, out, err = run(cmd, timeout=180)
    if code != 0:
        raise RuntimeError(f"tesseract digits failed: {err}")
    header = None
    rows: List[Dict] = []
    for i, line in enumerate(out.splitlines()):
        parts = line.split("\t")
        if i == 0:
            header = parts
            continue
        if header and len(parts) == len(header):
            rec = dict(zip(header, parts))
            if rec.get("level") != "5":
                continue
            text = (rec.get("text") or "").strip()
            if not text or not re.fullmatch(r"\d+", text):
                continue
            # to ints
            for k in ("left","top","width","height"):
                try:
                    rec[k] = int(rec[k])
                except Exception:
                    rec[k] = 0
            rows.append(rec)
    return rows


def _y_overlap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> float:
    top = max(a_top, b_top)
    bottom = min(a_bottom, b_bottom)
    if bottom <= top:
        return 0.0
    inter = bottom - top
    base = min(a_bottom - a_top, b_bottom - b_top)
    return inter / max(base, 1)


def render_page(pdf_path: Path, page_index0: int, out_dir: Path, dpi: int = 400) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "hdr"
    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(dpi),
        "-f",
        str(page_index0 + 1),
        "-l",
        str(page_index0 + 1),
        str(pdf_path),
        str(prefix),
    ]
    code, out, err = run(cmd, timeout=120)
    if code != 0:
        raise RuntimeError(f"pdftoppm failed: {err}")
    # resulting file: hdr-<page_index0+1>.png
    img = out_dir / f"hdr-{page_index0+1:02d}.png"
    if not img.exists():
        # fallback pattern
        matches = list(out_dir.glob("hdr-*.png"))
        if not matches:
            raise RuntimeError("render image not found")
        return matches[0]
    return img


LABELS_PAGE1 = [
    ("A", "aantal geldige stempassen"),
    ("B", "aantal geldige volmachtbewijzen"),
    ("C", "aantal geldige kiezerspassen"),
    ("D", "totaal aantal toegelaten kiezers"),
    ("E", "aantal stembiljetten met een geldige stem"),
    ("F", "aantal blanco stembiljetten"),
    ("G", "aantal ongeldige stembiljetten"),
    ("H", "totaal aantal uitgebrachte stemmen"),
]


def extract_headers_from_page(pdf_path: Path, page_index0: int, out_dir: Path) -> Dict[str, Optional[int]]:
    img = render_page(pdf_path, page_index0, out_dir)
    rows = tesseract_tsv(img)
    digits = tesseract_words_digits(img)
    # Build line-level rows (level 4 only)
    lines = [r for r in rows if str(r.get("level")) == "4" or r.get("level") == 4]
    out: Dict[str, Optional[int]] = {k: None for k, _ in LABELS_PAGE1}
    for key, label in LABELS_PAGE1:
        # Find first line containing label text
        cand = None
        for ln in lines:
            txt = (ln.get("text") or "").lower()
            if label in txt:
                cand = ln
                break
        if not cand:
            continue
        top = int(cand.get("top", 0))
        height = int(cand.get("height", 0))
        bottom = top + height
        # Prefer digits that overlap in Y, picking the rightmost
        dwords = [w for w in digits if _y_overlap(top, bottom, int(w.get("top",0)), int(w.get("top",0))+int(w.get("height",0))) >= 0.5]
        if dwords:
            val = int(max(dwords, key=lambda w: int(w.get("left",0))).get("text"))
            out[key] = val
    return out


def main():
    ap = argparse.ArgumentParser(description="OCR headers A–H (pag.1) en D2 (pag.2) uit PDF")
    ap.add_argument("pdf", help="Pad naar PDF")
    ap.add_argument("--out", required=True, help="Output JSON met velden")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    tmp = Path("data/ocr_hdr") / pdf.stem
    vals_p1 = extract_headers_from_page(pdf, 0, tmp)
    # We only implement D2 fallback via page 2 overlap with label (totaal aantal toegelaten kiezers (hertelling)) if present
    # For now, leave A2/B2/C2 as None; focus on D2 as in reference file
    vals_p2 = {}
    try:
        img2 = render_page(pdf, 1, tmp)
        rows2 = tesseract_tsv(img2)
        digits2 = tesseract_words_digits(img2)
        lines2 = [r for r in rows2 if str(r.get("level")) == "4" or r.get("level") == 4]
        # Find a line that contains both totaal + toegelaten + kiezers and (d.2|d2)
        cand = None
        for ln in lines2:
            t = (ln.get("text") or "").lower()
            if ("totaal" in t and "toegelaten" in t and "kiezers" in t) and ("d.2" in t or re.search(r"\bd2\b", t)):
                cand = ln
                break
        if cand:
            top = int(cand.get("top", 0))
            height = int(cand.get("height", 0))
            bottom = top + height
            dwords = [w for w in digits2 if _y_overlap(top, bottom, int(w.get("top",0)), int(w.get("top",0))+int(w.get("height",0))) >= 0.5]
            if dwords:
                vals_p2["D2"] = int(max(dwords, key=lambda w: int(w.get("left",0))).get("text"))
    except Exception:
        pass
    out = {"page1": vals_p1, "page2": vals_p2}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()

