#!/usr/bin/env python3

"""
Deterministic VZOD extractor
- OCR: ocrmypdf + Tesseract (nld+eng+snum), --force-ocr --optimize 0
- Parsing: sidecar + pdftotext -layout merge
- ROI-OCR: only for hertelling (A2/B2/C2/D2) and candidate vote cells
- No derivation: never compute D=A+B+C or E=H−F−G; unreadable stays onleesbaar
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Dict

import pdfplumber
from PIL import Image, ImageOps, ImageFilter


# Input/output defaults (single JSON acts as base + output)
PDF_PATH = Path("Aalsmeer/2-aal-vzod.pdf")
JSON_PATH = Path(__file__).with_name("Clubgebouw VZOD.filled.json")

# Deterministic OCR
OCR_LANGS = "nld+eng+snum"
OCR_OPTS = ["--force-ocr", "--optimize", "0"]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ocr_sidecar(pdf: Path) -> tuple[str, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="vzod_"))
    outpdf = tmpdir / "vzod_ocr.pdf"
    side = tmpdir / "vzod_sidecar.txt"
    langs = run(["tesseract", "--list-langs"]).stdout
    for req in OCR_LANGS.split("+"):
        if req not in langs:
            raise RuntimeError(f"Missing Tesseract language '{req}'. Install tesseract-lang.")
    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--language", OCR_LANGS,
        *OCR_OPTS,
        str(pdf), str(outpdf),
        "--sidecar", str(side),
    ]
    cp = run(cmd)
    if cp.returncode != 0:
        raise RuntimeError(f"ocrmypdf failed: {cp.stderr.strip()}")
    text = side.read_text(encoding="utf-8", errors="ignore")
    return text, outpdf


def norm_digits(s: str) -> str:
    table = str.maketrans({
        "O": "0", "o": "0", "Q": "0", "D": "0",
        "I": "1", "l": "1", "|": "1", "!": "1",
        "Z": "2", "z": "2",
        "S": "5", "s": "5", "§": "5",
        "B": "8",
    })
    s = s.translate(table)
    return re.sub(r"[^0-9]", "", s)


def take_tail_digits(line: str) -> Optional[str]:
    if '|' in line:
        tail = line.split('|')[-1].strip()
        d = norm_digits(tail)
        return d or None
    if '=' in line:
        tail = line.split('=')[-1].strip()
        d = norm_digits(tail)
        return d or None
    tokens = line.strip().split()
    for tok in reversed(tokens):
        if len(tok) > 6:
            continue
        cleaned = norm_digits(tok)
        if cleaned:
            return cleaned
    return None


def find_value(lines: List[str], label: str, window: int = 2) -> Optional[str]:
    for i, ln in enumerate(lines):
        if label in ln:
            if ('|' in ln) or ('=' in ln):
                v = take_tail_digits(ln)
                if v:
                    return v
            for j in range(1, window + 1):
                if i + j < len(lines):
                    v = take_tail_digits(lines[i + j])
                    if v:
                        return v
    return None


def extract_fields(text: str) -> dict:
    lines = text.splitlines()
    out: dict[str, str] = {}
    m = re.search(r"Nummer\s+stembureau\s+([0-9OIl|!]+)", text)
    if m:
        out["stembureau_nummer"] = norm_digits(m.group(1))
    m = re.search(r"Locatie stembureau.*?\)\s+(.+)", text)
    if m:
        out["stembureau_naam"] = m.group(1).strip()
    A = find_value(lines, "Aantal geldige stempassen")
    B = find_value(lines, "Aantal geldige volmachtbewijzen")
    C = find_value(lines, "Aantal geldige kiezerspassen")
    D = find_value(lines, "Totaal aantal toegelaten kiezers")
    E = find_value(lines, "Aantal stembiljetten met een geldige stem op een kandidaat")
    F = find_value(lines, "Aantal blanco stembiljetten")
    G = find_value(lines, "Aantal ongeldige stembiljetten")
    H = find_value(lines, "Totaal aantal uitgebrachte stemmen")
    return {"A": A, "B": B, "C": C, "D": D, "E": E, "F": F, "G": G, "H": H, **out}


def _find_word_positions(pdf_path: Path, page_index: int) -> List[dict]:
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_index]
        return page.extract_words(use_text_flow=True)


def roi_read_digits(pdf_path: Path, page_index: int, token: str) -> Optional[str]:
    words = _find_word_positions(pdf_path, page_index)
    candidates = [w for w in words if w.get('text') == token]
    if not candidates:
        return None
    t = candidates[0]
    top, bottom = t['top'], t['bottom']
    y0, y1 = max(0, top - 12), bottom + 12
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_index]
        x0 = t['x1'] + 8
        x1 = x0 + 160
        im = page.to_image(resolution=400).original
        scale = im.width / page.width
        box = (int(x0*scale), int(y0*scale), int(x1*scale), int(y1*scale))
        crop = im.crop(box)
        g = ImageOps.grayscale(crop)
        g = ImageOps.autocontrast(g)
        g = g.filter(ImageFilter.SHARPEN)
        from pytesseract import image_to_string
        cfg = f"--psm 7 -l {OCR_LANGS} -c tessedit_char_whitelist=0123456789"
        txt = image_to_string(g, config=cfg).strip()
        digits = norm_digits(txt)
        if not digits:
            cfg2 = f"--psm 6 -l {OCR_LANGS} -c tessedit_char_whitelist=0123456789"
            txt = image_to_string(g, config=cfg2).strip()
            digits = norm_digits(txt)
        return digits or None


def parse_hertelling(text: str, ocr_pdf: Path) -> dict:
    lines = text.splitlines()
    out: dict[str, Optional[str]] = {k: None for k in ("A2","B2","C2","D2")}
    def find_after_token(token: str) -> Optional[str]:
        for idx, ln in enumerate(lines):
            if token in ln:
                if token == "A2":
                    v = take_tail_digits(ln)
                    if v:
                        return v
                if ('|' in ln) or ('=' in ln):
                    v = take_tail_digits(ln)
                    if v:
                        return v
                for j in range(1,3):
                    if idx+j < len(lines):
                        nxt = lines[idx+j]
                        if ('|' in nxt) or ('=' in nxt):
                            v = take_tail_digits(nxt)
                            if v:
                                return v
        return None
    def accept(val: Optional[str], max_len: int) -> Optional[str]:
        if not val or not val.isdigit() or len(val) == 0 or len(val) > max_len:
            return None
        return val
    out["A2"] = accept(find_after_token("A2"), 2)
    out["B2"] = accept(find_after_token("B2"), 2)
    out["C2"] = accept(find_after_token("C2"), 2)
    out["D2"] = accept(find_after_token("D.2") or find_after_token("D2"), 3)
    for token, max_len in (("A2",2),("B2",2),("C2",2),("D2",3)):
        if not out[token]:
            rv = roi_read_digits(ocr_pdf, 1, token)
            rv = accept(rv, max_len)
            if rv:
                out[token] = rv
    return out


def _lines_from_page(pdf_path: Path, page_index: int) -> List[dict]:
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(use_text_flow=True)
        lines: List[dict] = []
        if not words:
            return lines
        words.sort(key=lambda w: (w["top"], w["x0"]))
        current: Optional[dict] = None
        for w in words:
            if current is None:
                current = {"top": w["top"], "bottom": w["bottom"], "text": w["text"]}
            else:
                if abs(w["top"] - current["top"]) <= 2.5:
                    current["bottom"] = max(current["bottom"], w["bottom"])
                    current["text"] += (" " + w["text"]) if current["text"] else w["text"]
                else:
                    lines.append(current)
                    current = {"top": w["top"], "bottom": w["bottom"], "text": w["text"]}
        if current is not None:
            lines.append(current)
        return lines


def _candidate_rows(pdf_path: Path, page_index: int) -> List[dict]:
    lines = _lines_from_page(pdf_path, page_index)
    rows: List[dict] = []
    in_block = False
    for ln in lines:
        t = ln["text"]
        if not in_block and t.startswith("Lijst "):
            in_block = True
            continue
        if in_block:
            if t.startswith("Stembureau "):
                break
            if "Naam kandidaat" in t:
                continue
            if "," in t and ")" in t:
                rows.append(ln)
    return rows


def _ocr_band_right(pdf_path: Path, page_index: int, y0: float, y1: float) -> Optional[str]:
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_index]
        x0 = page.width * 0.90
        x1 = page.width - 5
        im = page.to_image(resolution=400).original
        scale = im.width / page.width
        box = (int(x0*scale), int((y0-3)*scale), int(x1*scale), int((y1+3)*scale))
        crop = im.crop(box)
        g = ImageOps.grayscale(crop)
        g = ImageOps.autocontrast(g)
        g = g.filter(ImageFilter.SHARPEN)
        from pytesseract import image_to_string
        cfg = f"--psm 7 -l {OCR_LANGS} -c tessedit_char_whitelist=0123456789"
        txt = image_to_string(g, config=cfg).strip()
        digits = norm_digits(txt)
        if not digits:
            cfg2 = f"--psm 6 -l {OCR_LANGS} -c tessedit_char_whitelist=0123456789"
            txt = image_to_string(g, config=cfg2).strip()
            digits = norm_digits(txt)
        if digits and len(digits) == 1:
            return digits
        return None


def extract_candidate_votes(pdf_path: Path) -> Dict[int, List[Optional[str]]]:
    """Fallback light extractor: per page returns list of votes found in right band, aligned to candidate rows.
    This is less accurate than full TSV, but deterministic and improves coverage without derivation.
    """
    page_votes: Dict[int, List[Optional[str]]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            if "Lijst " not in txt:
                continue
            rows = _candidate_rows(pdf_path, i)
            votes: List[Optional[str]] = []
            for ln in rows:
                v = _ocr_band_right(pdf_path, i, ln["top"], ln["bottom"])
                votes.append(v)
            if votes:
                page_votes[i+1] = votes
    return page_votes


# --- Full TSV-based extraction for more complete/accurate results ---
class Word:
    def __init__(self, text: str, left: int, top: int, width: int, height: int, conf: float):
        self.text = text
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.conf = conf

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


class Line:
    def __init__(self, page: int, block: int, par: int, line: int, left: int, top: int, width: int, height: int, text: str, words: List[Word]):
        self.page = page
        self.block = block
        self.par = par
        self.line = line
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.text = text
        self.words = words

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def _render_pages(pdf_path: Path, out_dir: Path, dpi: int = 400) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # cleanup previous renders
    for old in out_dir.glob("page-*.png"):
        try:
            old.unlink()
        except Exception:
            pass
    prefix = out_dir / "page"
    cp = _run(["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)], timeout=600)
    if cp.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {cp.stderr}")
    imgs = sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    return imgs


def _tesseract_tsv(image_path: Path, lang: str = "nld+eng") -> List[Line]:
    cp = _run(["tesseract", str(image_path), "stdout", "-l", lang, "tsv", "--psm", "6"], timeout=180)
    if cp.returncode != 0:
        raise RuntimeError(f"tesseract tsv failed: {cp.stderr}")
    lines: Dict[tuple, Line] = {}
    header = None
    for i, row in enumerate(cp.stdout.splitlines()):
        if i == 0:
            header = row.split("\t")
            continue
        cols = row.split("\t")
        if not header or len(cols) != len(header):
            continue
        rec = dict(zip(header, cols))
        try:
            level = int(rec.get("level", "0"))
        except Exception:
            continue
        if level not in (4, 5):
            continue
        page = int(rec.get("page_num", 1))
        block = int(rec.get("block_num", 0))
        par = int(rec.get("par_num", 0))
        ln = int(rec.get("line_num", 0))
        left = int(rec.get("left", 0))
        top = int(rec.get("top", 0))
        width = int(rec.get("width", 0))
        height = int(rec.get("height", 0))
        text = (rec.get("text") or "").strip()
        conf = float(rec.get("conf", "-1"))
        key = (page, block, par, ln)
        if level == 4:
            lines[key] = Line(page, block, par, ln, left, top, width, height, text, [])
        else:
            w = Word(text, left, top, width, height, conf)
            lines.setdefault(key, Line(page, block, par, ln, left, top, width, height, "", [])).words.append(w)
    result = []
    for line in lines.values():
        if not line.text:
            line.text = " ".join(w.text for w in line.words if w.text)
        result.append(line)
    result.sort(key=lambda l: (l.page, l.top, l.left))
    return result


def _tesseract_digits(image_path: Path) -> List[Word]:
    cp = _run(["tesseract", str(image_path), "stdout", "tsv", "--psm", "6", "-l", "eng", "-c", "tessedit_char_whitelist=0123456789"], timeout=180)
    if cp.returncode != 0:
        raise RuntimeError(f"tesseract digits failed: {cp.stderr}")
    header = None
    words: List[Word] = []
    for i, row in enumerate(cp.stdout.splitlines()):
        if i == 0:
            header = row.split("\t")
            continue
        cols = row.split("\t")
        if not header or len(cols) != len(header):
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
        words.append(Word(text, left, top, width, height, conf))
    return words


def _y_overlap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> float:
    top = max(a_top, b_top)
    bottom = min(a_bottom, b_bottom)
    if bottom <= top:
        return 0.0
    inter = bottom - top
    base = min(a_bottom - a_top, b_bottom - b_top)
    return inter / max(base, 1)


def _is_list_header(text: str) -> Optional[tuple[int, str]]:
    m = re.match(r"\s*Lijst\s+(\d+)\s*-\s*(.+)", text)
    if m:
        try:
            return int(m.group(1)), m.group(2).strip()
        except Exception:
            return None
    return None


def _is_candidate_line(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    low = t.lower()
    if low.startswith("naam kandidaat"):
        return False
    if low.startswith("vervolg:"):
        return False
    if low.startswith("zet in elk vakje"):
        return False
    if low.startswith("subtotaal"):
        return False
    if low.startswith("totaal"):
        return False
    if re.match(r"^Lijst\s+\d+\s*-", t):
        return False
    if "," in t and "(" in t and ")" in t:
        return True
    return bool(re.match(r"^[A-ZÀ-Ý][^0-9]{3,}\s+[A-ZÀ-Ý]", t))


def _extract_numeric_on_line(line: Line) -> Optional[int]:
    nums = [w for w in line.words if re.fullmatch(r"\d+", w.text)]
    if not nums:
        return None
    w = max(nums, key=lambda x: x.left)
    try:
        return int(w.text)
    except Exception:
        return None


def _ocr_digit_crop(img: Image.Image) -> Optional[int]:
    # Use a small crop on right and OCR digits only
    from pytesseract import image_to_string
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.SHARPEN)
    txt = image_to_string(g, config=f"--psm 7 -l eng -c tessedit_char_whitelist=0123456789").strip()
    m = re.search(r"(\d+)$", txt)
    if not m:
        txt = image_to_string(g, config=f"--psm 6 -l eng -c tessedit_char_whitelist=0123456789").strip()
        m = re.search(r"(\d+)$", txt)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def extract_lists_candidates_with_tsv(pdf_path: Path) -> Dict[int, List[dict]]:
    """Return per page a list of lijsten with kandidaten and per-list totals/subtotals using TSV OCR."""
    out: Dict[int, List[dict]] = {}
    out_dir = Path(tempfile.mkdtemp(prefix="vzod_png_")) / pdf_path.stem
    imgs = _render_pages(pdf_path, out_dir, dpi=400)
    for idx, img in enumerate(imgs, start=1):
        try:
            lines = _tesseract_tsv(img)
            digits = _tesseract_digits(img)
            page_im = Image.open(img)
        except Exception:
            continue
        lijsten: List[dict] = []
        current: Optional[dict] = None
        subtotals: List[Optional[int]] = []
        for ln in lines:
            header = _is_list_header(ln.text)
            if header:
                if current:
                    if subtotals:
                        current["subtotaal_links"] = subtotals[0] if len(subtotals) > 0 else "leeg"
                        current["subtotaal_rechts"] = subtotals[1] if len(subtotals) > 1 else "leeg"
                    lijsten.append(current)
                list_no, party = header
                current = {
                    "lijstnummer": list_no,
                    "partijnaam": party,
                    "kandidaten": [],
                    "subtotaal_links": "leeg",
                    "subtotaal_rechts": "leeg",
                    "totaal_lijst": "leeg",
                }
                subtotals = []
                continue
            if current is None:
                continue
            low = (ln.text or "").strip().lower()
            if low.startswith("subtotaal"):
                val = None
                cand_words = [w for w in digits if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5]
                if cand_words:
                    val = int(max(cand_words, key=lambda w: w.left).text)
                if val is None:
                    val = _extract_numeric_on_line(ln)
                if val is None:
                    W, H = page_im.size
                    x0 = int(W * 0.62)
                    crop = page_im.crop((x0, max(ln.top - 4, 0), W - 1, ln.bottom + 4))
                    val = _ocr_digit_crop(crop)
                subtotals.append(val if val is not None else "onleesbaar")
                continue
            if low.startswith("totaal"):
                val = None
                cand_words = [w for w in digits if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5]
                if cand_words:
                    val = int(max(cand_words, key=lambda w: w.left).text)
                if val is None:
                    val = _extract_numeric_on_line(ln)
                if val is None:
                    W, H = page_im.size
                    x0 = int(W * 0.62)
                    crop = page_im.crop((x0, max(ln.top - 4, 0), W - 1, ln.bottom + 4))
                    val = _ocr_digit_crop(crop)
                current["totaal_lijst"] = val if val is not None else "onleesbaar"
                continue
            if _is_candidate_line(ln.text or ""):
                # stemmen: prefer digits words on same y band; else numeric on line; else crop
                stemmen = None
                cand_words = [w for w in digits if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5]
                if cand_words:
                    stemmen = int(max(cand_words, key=lambda w: w.left).text)
                if stemmen is None:
                    stemmen = _extract_numeric_on_line(ln)
                if stemmen is None:
                    W, H = page_im.size
                    x0 = int(W * 0.62)
                    crop = page_im.crop((x0, max(ln.top - 3, 0), W - 1, ln.bottom + 3))
                    stemmen = _ocr_digit_crop(crop)
                # naamsegmenten (als tesseract twee regels plakte)
                parts = re.split(r"\)\s+(?=[A-ZÀ-Ý])", (ln.text or "").strip())
                segs: List[str] = []
                for i, ptxt in enumerate(parts):
                    if not ptxt:
                        continue
                    seg = ptxt if i == len(parts) - 1 else (ptxt + ")")
                    segs.append(seg.strip())
                if not segs:
                    segs = [ln.text or ""]
                for seg in segs:
                    name = re.sub(r"\s+\d+\s*$", "", seg).strip()
                    current["kandidaten"].append({
                        "kandidaatnummer": "leeg",  # we vullen geen nummer afgeleid
                        "kandidaatnaam": name,
                        "stemmen": stemmen if (stemmen is not None and len(segs) == 1) else "leeg",
                    })
        if current:
            if subtotals:
                current["subtotaal_links"] = subtotals[0] if len(subtotals) > 0 else "leeg"
                current["subtotaal_rechts"] = subtotals[1] if len(subtotals) > 1 else "leeg"
            lijsten.append(current)
        if lijsten:
            out[idx] = lijsten
    return out


def fill_template(template: dict, values: dict) -> dict:
    if values.get("stembureau_nummer"):
        v = values["stembureau_nummer"]
        template["stembureau_nummer"] = int(v) if v.isdigit() else v
    if values.get("stembureau_naam"):
        template["stembureau_naam"] = values["stembureau_naam"]
    p1 = next((p for p in template.get("paginas", []) if p.get("pagina") == 1), None)
    if p1 and "aantal_toegelaten_kiezers" in p1:
        for key in ("A", "B", "C", "D"):
            v = values.get(key)
            if v and str(p1["aantal_toegelaten_kiezers"][key]["waarde"]).lower() in {"onleesbaar", "leeg", "", "null", "none"}:
                try:
                    p1["aantal_toegelaten_kiezers"][key]["waarde"] = int(v)
                except Exception:
                    p1["aantal_toegelaten_kiezers"][key]["waarde"] = v
    if p1 and "aantal_uitgebrachte_stemmen" in p1:
        for key in ("E", "F", "G", "H"):
            v = values.get(key)
            if v and str(p1["aantal_uitgebrachte_stemmen"][key]["waarde"]).lower() in {"onleesbaar", "leeg", "", "null", "none"}:
                try:
                    p1["aantal_uitgebrachte_stemmen"][key]["waarde"] = int(v)
                except Exception:
                    p1["aantal_uitgebrachte_stemmen"][key]["waarde"] = v
    p2 = next((p for p in template.get("paginas", []) if p.get("pagina") == 2), None)
    if p2 and p2.get("verschil_toegelaten_vs_uitgebrachte") and p2["verschil_toegelaten_vs_uitgebrachte"].get("hertelling"):
        h = p2["verschil_toegelaten_vs_uitgebrachte"]["hertelling"]
        for key in ("A2","B2","C2","D2"):
            v = values.get(key)
            if v and v.isdigit() and str(h[key]["waarde"]).lower() in {"onleesbaar", "leeg", "", "null", "none"}:
                try:
                    h[key]["waarde"] = int(v)
                except Exception:
                    h[key]["waarde"] = v
    # candidate votes per list on subsequent pages
    page_votes: Dict[int, List[Optional[str]]] = values.get("_page_votes", {})  # {page_index_1based: [str|None,...]}
    if isinstance(page_votes, dict):
        for page_obj in template.get("paginas", []):
            pnum = page_obj.get("pagina")
            if not isinstance(pnum, int):
                continue
            votes = page_votes.get(pnum)
            if not votes:
                continue
            for lst in page_obj.get("lijsten", []) or []:
                cands = lst.get("kandidaten", []) or []
                for i, cand in enumerate(cands):
                    if i >= len(votes):
                        break
                    v = votes[i]
                    if v and (str(cand.get("stemmen")).lower() in {"leeg", "onleesbaar", "", "none", "null"}):
                        try:
                            cand["stemmen"] = int(v)
                        except Exception:
                            cand["stemmen"] = v
    return template


def main() -> int:
    pdf = PDF_PATH
    base_json = JSON_PATH
    out_path = JSON_PATH
    if not pdf.exists():
        print(f"PDF not found: {pdf}", file=sys.stderr)
        return 1
    if not base_json.exists():
        print(f"Base JSON not found: {base_json}", file=sys.stderr)
        return 1
    side_text, outpdf = ocr_sidecar(pdf)
    layout_text = ""
    cp = run(["pdftotext", "-layout", "-q", str(outpdf), "-"])
    if cp.returncode == 0 and cp.stdout:
        layout_text = cp.stdout
    merged_text = side_text + "\n" + layout_text
    vals = extract_fields(merged_text)
    hvals = parse_hertelling(merged_text, outpdf)
    vals.update(hvals)
    # Full TSV extraction for lists/candidates/subtotal/totaal
    tsv_pages = extract_lists_candidates_with_tsv(outpdf)
    tmpl = json.loads(base_json.read_text(encoding="utf-8"))
    # Merge TSV into vals as _page_votes (candidate stemmen per page per position)
    # Build mapping page -> flat list of stemmen aligned to candidate order
    page_votes: Dict[int, List[Optional[str]]] = {}
    for pnum, lij in tsv_pages.items():
        flat: List[Optional[str]] = []
        for lst in lij:
            for kand in lst.get("kandidaten", []):
                v = kand.get("stemmen")
                flat.append(str(v) if isinstance(v, int) else (v if v else None))
        page_votes[pnum] = flat
    vals["_page_votes"] = page_votes
    filled = fill_template(tmpl, vals)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(filled, ensure_ascii=False, indent=2), encoding="utf-8")
    # Summary
    keys = ("A","B","C","D","E","F","G","H","A2","B2","C2","D2","stembureau_nummer","stembureau_naam")
    print(json.dumps({k: vals.get(k) for k in keys}, ensure_ascii=False))
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
