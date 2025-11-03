#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter
from typing import List, Dict, Tuple, Optional


def run(cmd: List[str], timeout: int = 600, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class Line:
    page: int
    block: int
    par: int
    line: int
    left: int
    top: int
    width: int
    height: int
    text: str
    words: List[Word]

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def tesseract_tsv(image_path: Path, lang: str = "nld+eng") -> List[Line]:
    cmd = [
        "tesseract",
        str(image_path),
        "stdout",
        "-l",
        lang,
        "tsv",
        "--psm",
        "6",
    ]
    code, out, err = run(cmd, timeout=180)
    if code != 0:
        raise RuntimeError(f"tesseract failed: {err}")
    lines: Dict[Tuple[int, int, int, int], Line] = {}
    header = None
    for i, row in enumerate(out.splitlines()):
        if i == 0:
            header = row.split("\t")
            continue
        cols = row.split("\t")
        if len(cols) != len(header):
            continue
        rec = dict(zip(header, cols))
        try:
            level = int(rec["level"])  # 1=page,2=block,3=par,4=line,5=word
        except Exception:
            continue
        if level not in (4, 5):
            continue
        page = int(rec.get("page_num", 1))
        block = int(rec.get("block_num", 0))
        par = int(rec.get("par_num", 0))
        line_no = int(rec.get("line_num", 0))
        left = int(rec.get("left", 0))
        top = int(rec.get("top", 0))
        width = int(rec.get("width", 0))
        height = int(rec.get("height", 0))
        text = rec.get("text", "").strip()
        conf = float(rec.get("conf", "-1"))
        key = (page, block, par, line_no)
        if level == 4:
            lines[key] = Line(page, block, par, line_no, left, top, width, height, text, [])
        elif level == 5:
            w = Word(text=text, left=left, top=top, width=width, height=height, conf=conf)
            if key not in lines:
                # Create placeholder line
                lines[key] = Line(page, block, par, line_no, left, top, width, height, "", [])
            lines[key].words.append(w)
    # Compose texts for lines from words if empty
    result = []
    for line in lines.values():
        if not line.text:
            line.text = " ".join(w.text for w in line.words if w.text)
        result.append(line)
    # Sort
    result.sort(key=lambda l: (l.page, l.top, l.left))
    return result


def tesseract_words_digits(image_path: Path) -> List[Word]:
    """Digits-focused OCR over full page. Returns numeric words with positions."""
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
    words: List[Word] = []
    for i, row in enumerate(out.splitlines()):
        if i == 0:
            header = row.split("\t")
            continue
        cols = row.split("\t")
        if header is None or len(cols) != len(header):
            continue
        rec = dict(zip(header, cols))
        try:
            level = int(rec.get("level", "0"))
        except Exception:
            continue
        if level != 5:
            continue
        text = (rec.get("text") or "").strip()
        if not text or not re.fullmatch(r"\d+", text):
            continue
        try:
            left = int(rec.get("left", 0))
            top = int(rec.get("top", 0))
            width = int(rec.get("width", 0))
            height = int(rec.get("height", 0))
            conf = float(rec.get("conf", "-1"))
        except Exception:
            continue
        words.append(Word(text=text, left=left, top=top, width=width, height=height, conf=conf))
    return words


def _y_overlap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> float:
    top = max(a_top, b_top)
    bottom = min(a_bottom, b_bottom)
    if bottom <= top:
        return 0.0
    inter = bottom - top
    base = min(a_bottom - a_top, b_bottom - b_top)
    return inter / max(base, 1)


def render_pages(pdf_path: Path, out_dir: Path, dpi: int = 400) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Cleanup previous renders to avoid mixing pages across runs
    for old in out_dir.glob("page-*.png"):
        try:
            old.unlink()
        except Exception:
            pass
    prefix = out_dir / "page"
    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(dpi),
        str(pdf_path),
        str(prefix),
    ]
    code, out, err = run(cmd, timeout=600)
    if code != 0:
        raise RuntimeError(f"pdftoppm failed: {err}")
    imgs = sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    return imgs


def is_list_header(text: str) -> Optional[Tuple[int, str]]:
    m = re.match(r"\s*Lijst\s+(\d+)\s*-\s*(.+)", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None


def is_candidate_line(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if t.lower().startswith("naam kandidaat"):
        return False
    if t.lower().startswith("vervolg:"):
        return False
    if t.lower().startswith("zet in elk vakje"):
        return False
    if t.lower().startswith("subtotaal"):
        return False
    if t.lower().startswith("totaal"):
        return False
    if re.match(r"^Lijst\s+\d+\s*-", t):
        return False
    # likely a candidate: contains comma and parentheses or typical name chars
    if "," in t and "(" in t and ")" in t:
        return True
    # fallback: start with capital letter and has at least two words
    return bool(re.match(r"^[A-ZÀ-Ý][^0-9]{3,}\s+[A-ZÀ-Ý]", t))


def extract_numeric_on_line(line: Line) -> Optional[int]:
    nums = [w for w in line.words if re.fullmatch(r"\d+", w.text)]
    if not nums:
        return None
    # pick rightmost numeric word
    w = max(nums, key=lambda x: x.left)
    try:
        return int(w.text)
    except Exception:
        return None


def extract_candidate_number(line: Line) -> Optional[int]:
    # candidate number often at the start of the line
    words = [w for w in line.words if w.text]
    if not words:
        return None
    # first numeric word left of first comma is likely the candidate number
    for w in words[:4]:
        if re.fullmatch(r"\d+", w.text):
            try:
                return int(w.text)
            except Exception:
                return None
    return None


def split_candidate_segments(text: str) -> List[str]:
    # If OCR fused two candidates on one line, split at pattern ") <Capital>"
    parts = re.split(r"\)\s+(?=[A-ZÀ-Ý])", text.strip())
    # Add back the ')' to all but last
    segs: List[str] = []
    for i, p in enumerate(parts):
        if not p:
            continue
        seg = p if i == len(parts) - 1 else (p + ")")
        segs.append(seg.strip())
    return segs


def clean_candidate_name(text: str) -> str:
    # Remove trailing numeric at end
    t = re.sub(r"\s+\d+\s*$", "", text).strip()
    return t


def _preprocess_crop(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.SHARPEN)
    return g


def ocr_digit_crop(img: Image.Image) -> Optional[int]:
    """OCR a small crop for digits only. Returns int or None."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "crop.png"
        _pre = _preprocess_crop(img)
        _pre.save(p)
        cmd = [
            "tesseract",
            str(p),
            "stdout",
            "-l",
            "eng",
            "--psm",
            "7",
            "-c",
            "tessedit_char_whitelist=0123456789",
        ]
        code, out, err = run(cmd, timeout=60)
        if code != 0:
            return None
        out = (out or "").strip()
        m = re.search(r"(\d+)$", out)
        if not m:
            # try psm 6 fallback
            cmd2 = [
                "tesseract",
                str(p),
                "stdout",
                "-l",
                "eng",
                "--psm",
                "6",
                "-c",
                "tessedit_char_whitelist=0123456789",
            ]
            code2, out2, err2 = run(cmd2, timeout=60)
            if code2 != 0:
                return None
            out2 = (out2 or "").strip()
            m = re.search(r"(\d+)$", out2)
            if not m:
                return None
        try:
            return int(m.group(1))
        except Exception:
            return None


def parse_page_lines(lines: List[Line], digits_words: List[Word], page_image: Image.Image) -> List[dict]:
    """Return list entries for lijsten on a page."""
    results: List[dict] = []
    current = None
    subtotals_on_page: List[int] = []
    for ln in lines:
        header = is_list_header(ln.text)
        if header:
            if current:
                # finalize current, attach subtotals
                if subtotals_on_page:
                    current["subtotaal_links"] = subtotals_on_page[0] if len(subtotals_on_page) > 0 else "leeg"
                    current["subtotaal_rechts"] = subtotals_on_page[1] if len(subtotals_on_page) > 1 else "leeg"
                results.append(current)
            list_no, party = header
            current = {
                "lijstnummer": list_no,
                "partijnaam": party,
                "kandidaten": [],
                "subtotaal_links": "leeg",
                "subtotaal_rechts": "leeg",
                "totaal_lijst": "leeg",
            }
            subtotals_on_page = []
            continue
        if current is None:
            continue
        low = ln.text.strip().lower()
        if low.startswith("subtotaal"):
            # Prefer digits pass
            v = None
            for w in digits_words:
                if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5:
                    v = int(w.text)
            if v is None:
                v = extract_numeric_on_line(ln)
            if v is None:
                # Try crop OCR on the appropriate column band (left/right)
                W, H = page_image.size
                if ln.left < W * 0.5:
                    x0 = int(W * 0.45)
                    x1 = int(W * 0.58)
                else:
                    x0 = int(W * 0.90)
                    x1 = W - 1
                crop = page_image.crop((x0, max(ln.top - 4, 0), x1, ln.bottom + 4))
                v = ocr_digit_crop(crop)
            subtotals_on_page.append(v if v is not None else "onleesbaar")
            continue
        if low.startswith("totaal"):
            v = None
            for w in digits_words:
                if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5:
                    v = int(w.text)
            if v is None:
                v = extract_numeric_on_line(ln)
            if v is None:
                W, H = page_image.size
                if ln.left < W * 0.5:
                    x0 = int(W * 0.45)
                    x1 = int(W * 0.58)
                else:
                    x0 = int(W * 0.90)
                    x1 = W - 1
                crop = page_image.crop((x0, max(ln.top - 4, 0), x1, ln.bottom + 4))
                v = ocr_digit_crop(crop)
            current["totaal_lijst"] = v if v is not None else "onleesbaar"
            continue
        if is_candidate_line(ln.text):
            # Prefer digits pass for stemmen; pick rightmost numeric overlapping in Y
            stemmen = None
            cand_words = [w for w in digits_words if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5]
            if cand_words:
                stemmen = int(max(cand_words, key=lambda w: w.left).text)
            if stemmen is None:
                stemmen = extract_numeric_on_line(ln)
            if stemmen is None:
                # Per-candidate crop on right side band
                W, H = page_image.size
                if ln.left < W * 0.5:
                    x0 = int(W * 0.45)
                    x1 = int(W * 0.58)
                else:
                    x0 = int(W * 0.90)
                    x1 = W - 1
                crop = page_image.crop((x0, max(ln.top - 3, 0), x1, ln.bottom + 3))
                stemmen = ocr_digit_crop(crop)
            kandnr_line = extract_candidate_number(ln)
            # Possibly contains multiple candidates; split into segments
            segs = split_candidate_segments(ln.text)
            for idx, seg in enumerate(segs):
                name = clean_candidate_name(seg)
                # Try to extract candidate number from segment text itself
                kandnum = None
                m = re.match(r"\s*(\d+)\s+", seg)
                if m:
                    try:
                        kandnum = int(m.group(1))
                    except Exception:
                        kandnum = None
                if kandnum is None and idx == 0 and kandnr_line is not None:
                    kandnum = kandnr_line
                current["kandidaten"].append({
                    "kandidaatnummer": kandnum if kandnum is not None else "leeg",
                    "kandidaatnaam": name,
                    "stemmen": (stemmen if (stemmen is not None and len(segs) == 1) else "leeg"),
                })
    if current:
        if subtotals_on_page:
            current["subtotaal_links"] = subtotals_on_page[0] if len(subtotals_on_page) > 0 else "leeg"
            current["subtotaal_rechts"] = subtotals_on_page[1] if len(subtotals_on_page) > 1 else "leeg"
        results.append(current)
    return results


def build_pages_from_pdf(pdf_path: Path, out_dir: Path) -> List[dict]:
    imgs = render_pages(pdf_path, out_dir)
    pages_out: List[dict] = []
    next_num: Dict[int, int] = {}  # lijstnummer -> next candidate number
    for idx, img in enumerate(imgs, start=1):
        try:
            lines = tesseract_tsv(img)
            digits = tesseract_words_digits(img)
            page_im = Image.open(img)
        except Exception as e:
            print(f"[WARN] OCR TSV failed on page {idx}: {e}")
            continue
        lijsten = parse_page_lines(lines, digits, page_im)
        if not lijsten:
            # Skip empty pages
            continue
        # Assign sequential candidate numbers per lijst across pages
        for lst in lijsten:
            ln = lst.get("lijstnummer")
            start = next_num.get(ln, 1)
            for idx, k in enumerate(lst.get("kandidaten", []), start=start):
                if k.get("kandidaatnummer") == "leeg":
                    k["kandidaatnummer"] = idx
            next_num[ln] = start + len(lst.get("kandidaten", []))
        pages_out.append({
            "pagina": idx,
            "lijsten": lijsten,
        })
    return pages_out


def main():
    ap = argparse.ArgumentParser(description="OCR van PDF-kandidaten en stemmen (NL)")
    ap.add_argument("pdf", help="Pad naar PDF")
    ap.add_argument("--out", default=None, help="Uitvoer JSON")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    out_dir = Path("data/ocr_png") / pdf.stem
    pages = build_pages_from_pdf(pdf, out_dir)
    out = {
        "bestand": str(pdf),
        "paginas": pages,
    }
    out_path = Path(args.out) if args.out else Path("data/extracted_nl") / (pdf.stem + ".ocr.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
