#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageFilter


# Lightweight OCR helpers (subset from ocr_votes_pdf.py)

def _run(cmd: List[str], timeout: int = 600) -> tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
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


def render_pages(pdf_path: Path, out_dir: Path, dpi: int = 400) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page-*.png"):
        try:
            old.unlink()
        except Exception:
            pass
    prefix = out_dir / "page"
    code, out, err = _run(["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)], timeout=600)
    if code != 0:
        raise RuntimeError(f"pdftoppm failed: {err}")
    imgs = sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    return imgs


def tesseract_tsv(image_path: Path, lang: str = "nld+eng") -> List[Line]:
    code, out, err = _run(["tesseract", str(image_path), "stdout", "-l", lang, "tsv", "--psm", "6"], timeout=180)
    if code != 0:
        raise RuntimeError(f"tesseract failed: {err}")
    lines: Dict[Tuple[int, int, int, int], Line] = {}
    header = None
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
        text = (rec.get("text") or "").strip()
        conf = float(rec.get("conf", "-1"))
        key = (page, block, par, line_no)
        if level == 4:
            lines[key] = Line(page, block, par, line_no, left, top, width, height, text, [])
        elif level == 5:
            w = Word(text=text, left=left, top=top, width=width, height=height, conf=conf)
            if key not in lines:
                lines[key] = Line(page, block, par, line_no, left, top, width, height, "", [])
            lines[key].words.append(w)
    result = []
    for line in lines.values():
        if not line.text:
            line.text = " ".join(w.text for w in line.words if w.text)
        result.append(line)
    result.sort(key=lambda l: (l.page, l.top, l.left))
    return result


def tesseract_words_digits(image_path: Path) -> List[Word]:
    code, out, err = _run([
        "tesseract", str(image_path), "stdout", "tsv", "--psm", "6", "-l", "eng",
        "-c", "tessedit_char_whitelist=0123456789"
    ], timeout=180)
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


def _preprocess_crop(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.SHARPEN)
    return g


def _y_overlap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> float:
    top = max(a_top, b_top)
    bottom = min(a_bottom, b_bottom)
    if bottom <= top:
        return 0.0
    inter = bottom - top
    base = min(a_bottom - a_top, b_bottom - b_top)
    return inter / max(base, 1)


def ocr_digit_crop(img: Image.Image) -> Optional[int]:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "crop.png"
        _pre = _preprocess_crop(img)
        _pre.save(p)
        code, out, err = _run(["tesseract", str(p), "stdout", "-l", "eng", "--psm", "7",
                               "-c", "tessedit_char_whitelist=0123456789"], timeout=60)
        if code != 0:
            return None
        out = (out or "").strip()
        m = re.search(r"(\d+)$", out)
        if not m:
            code2, out2, err2 = _run(["tesseract", str(p), "stdout", "-l", "eng", "--psm", "6",
                                      "-c", "tessedit_char_whitelist=0123456789"], timeout=60)
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


def is_list_header(text: str) -> Optional[Tuple[int, str]]:
    m = re.match(r"\s*Lijst\s+(\d+)\s*-\s*(.+)", (text or ""))
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
    if "," in t and "(" in t and ")" in t:
        return True
    return bool(re.match(r"^[A-ZÀ-Ý][^0-9]{3,}\s+[A-ZÀ-Ý]", t))


def extract_numeric_on_line(line: Line) -> Optional[int]:
    nums = [w for w in line.words if re.fullmatch(r"\d+", w.text)]
    if not nums:
        return None
    w = max(nums, key=lambda x: x.left)
    try:
        return int(w.text)
    except Exception:
        return None


def extract_candidate_number_from_text(text: str) -> Optional[int]:
    m = re.match(r"\s*(\d+)\s+", (text or ""))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def split_candidate_segments(text: str) -> List[str]:
    parts = re.split(r"\)\s+(?=[A-ZÀ-Ý])", (text or "").strip())
    segs: List[str] = []
    for i, p in enumerate(parts):
        if not p:
            continue
        seg = p if i == len(parts) - 1 else (p + ")")
        segs.append(seg.strip())
    return segs


def _column_band_for_line(ln: Line, page_width: int, bands: Optional[Dict[str, Tuple[int,int]]] = None) -> Tuple[int, int]:
    """Return an x-band [x0,x1] for de stemmenkolom.
    Gekalibreerd op dezelfde waarden als ocr_votes_pdf:
      - Linkerkolom stemmenband ~ 45%–58% van paginabreedte
      - Rechterkolom stemmenband ~ 90%–100% van paginabreedte
    """
    if bands:
        if ln.left < page_width * 0.5 and 'left' in bands:
            return bands['left']
        if ln.left >= page_width * 0.5 and 'right' in bands:
            return bands['right']
    if ln.left < page_width * 0.5:
        x0 = int(page_width * 0.45)
        x1 = int(page_width * 0.58)
    else:
        x0 = int(page_width * 0.90)
        x1 = page_width - 1
    # Clamp and ensure width
    x0 = max(0, min(x0, page_width - 2))
    x1 = max(x0 + 2, min(x1, page_width - 1))
    return x0, x1


def _digits_in_band_for_line(ln: Line, digits: List[Word], x0: int, x1: int) -> List[Word]:
    return [w for w in digits if _y_overlap(ln.top, ln.bottom, w.top, w.bottom) >= 0.5 and (w.left >= x0 and (w.left + w.width) <= x1)]


def build_from_sjabloon(pdf: Path, sjabloon: dict, headers: Optional[dict]) -> dict:
    out: dict = {
        "bestand": str(pdf),
        "gemeente": None,
        "stembureau_nummer": None,
        "stembureau_naam": None,
        "paginas": [],
    }

    # Page 1 and 2 blocks (from headers if present)
    if headers:
        def to_int_or(s):
            if s is None:
                return "leeg"
            try:
                return int(str(s))
            except Exception:
                return s
        p1 = {
            "pagina": 1,
            "aantal_toegelaten_kiezers": {
                "A": {"omschrijving": "Aantal geldige stempassen", "waarde": to_int_or(headers.get("A"))},
                "B": {"omschrijving": "Aantal geldige volmachtbewijzen (schriftelijk of via ingevulde stem- of kiezerspas)", "waarde": to_int_or(headers.get("B"))},
                "C": {"omschrijving": "Aantal geldige kiezerspassen", "waarde": to_int_or(headers.get("C"))},
                "D": {"omschrijving": "Totaal aantal toegelaten kiezers (A+B+C)", "waarde": to_int_or(headers.get("D"))},
            },
            "aantal_uitgebrachte_stemmen": {
                "E": {"omschrijving": "Aantal stembiljetten met een geldige stem op een kandidaat", "waarde": to_int_or(headers.get("E"))},
                "F": {"omschrijving": "Aantal blanco stembiljetten", "waarde": to_int_or(headers.get("F"))},
                "G": {"omschrijving": "Aantal ongeldige stembiljetten", "waarde": to_int_or(headers.get("G"))},
                "H": {"omschrijving": "Totaal aantal uitgebrachte stemmen (E+F+G)", "waarde": to_int_or(headers.get("H"))},
            },
        }
        out["paginas"].append(p1)
        p2 = {
            "pagina": 2,
            "verschil_toegelaten_vs_uitgebrachte": {
                "keuze": "onleesbaar",
                "hertelling": {
                    "A2": {"omschrijving": "Aantal geldige stempassen (hertelling)", "waarde": to_int_or(headers.get("A2"))},
                    "B2": {"omschrijving": "Aantal geldige volmachtbewijzen (hertelling)", "waarde": to_int_or(headers.get("B2"))},
                    "C2": {"omschrijving": "Aantal geldige kiezerspassen (hertelling)", "waarde": to_int_or(headers.get("C2"))},
                    "D2": {"omschrijving": "Totaal aantal toegelaten kiezers (hertelling)", "waarde": to_int_or(headers.get("D2"))},
                },
            },
        }
        out["paginas"].append(p2)
        out["stembureau_nummer"] = headers.get("stembureau_nummer")
        out["stembureau_naam"] = headers.get("stembureau_naam")

    # Prepare image and OCR per page once
    tmp_img_dir = Path(tempfile.mkdtemp(prefix=f"sjfill_{pdf.stem}_"))
    page_images = render_pages(pdf, tmp_img_dir, dpi=400)
    page_lines: Dict[int, List[Line]] = {}
    page_digits: Dict[int, List[Word]] = {}
    for idx, im in enumerate(page_images, start=1):
        try:
            page_lines[idx] = tesseract_tsv(im)
            page_digits[idx] = tesseract_words_digits(im)
        except Exception:
            page_lines[idx] = []
            page_digits[idx] = []

    # Build per sjabloon page
    for pg in sjabloon.get("paginas", []):
        pnum = int(pg.get("pagina"))
        lines = page_lines.get(pnum, [])
        digits = page_digits.get(pnum, [])
        try:
            page_im = Image.open(page_images[pnum - 1])
        except Exception:
            page_im = None
        entry = {"pagina": pnum, "lijsten": []}

        # Bepaal dynamische stemmenkolom-banden per pagina uit digits-woorden
        bands: Dict[str, Tuple[int,int]] = {}
        if page_im is not None:
            W, H = page_im.size
            digs = digits
            if digs:
                # Linkerkolom cluster: grof filter 35%–70% breedte
                left_ws = [w for w in digs if (0.35*W) <= w.left <= (0.70*W) and w.top > 0.1*H and w.bottom < 0.98*H]
                if left_ws:
                    xs = sorted([w.left for w in left_ws])
                    med = xs[len(xs)//2]
                    span = int(0.06 * W)
                    x0 = max(int(med - span), int(0.40*W))
                    x1 = min(int(med + span), int(0.70*W))
                    if x1 > x0:
                        bands['left'] = (x0, x1)
                # Rechterkolom cluster: grof filter 85%–100%
                right_ws = [w for w in digs if (0.85*W) <= w.left <= (0.995*W) and w.top > 0.1*H and w.bottom < 0.98*H]
                if right_ws:
                    xs = sorted([w.left for w in right_ws])
                    med = xs[len(xs)//2]
                    span = int(0.03 * W)
                    x0 = max(int(med - span), int(0.88*W))
                    x1 = min(int(med + span), W-1)
                    if x1 > x0:
                        bands['right'] = (x0, x1)

        # Collect indices for list headers on this page
        idx_by_list: Dict[int, int] = {}
        for i, ln in enumerate(lines):
            hdr = is_list_header(ln.text)
            if hdr:
                ln_no, _party = hdr
                if ln_no not in idx_by_list:
                    idx_by_list[ln_no] = i

        for lst in pg.get("lijsten", []):
            lijstnummer = lst.get("lijstnummer", {}).get("waarde") if isinstance(lst.get("lijstnummer"), dict) else lst.get("lijstnummer")
            partijnaam = lst.get("partijnaam", {}).get("waarde") if isinstance(lst.get("partijnaam"), dict) else lst.get("partijnaam")
            kandidaten_tpl = lst.get("kandidaten", [])
            # Start/end index for this list in OCR lines
            start_i = idx_by_list.get(int(lijstnummer), None)
            # Find next header index after start
            end_i = None
            if start_i is not None:
                for j in range(start_i + 1, len(lines)):
                    nxt = is_list_header(lines[j].text)
                    if nxt:
                        end_i = j
                        break
            # Fallback: whole page
            scan_slice = lines[start_i:end_i] if start_i is not None else lines

            # Extract candidate lines within slice
            cand_lines: List[Line] = [ln for ln in scan_slice if is_candidate_line(ln.text)]
            # Extract subtotal/totaal within slice
            subtotals: List[Optional[int]] = []
            totaal_val: Optional[int] = None

            def _extract_digits_for_line(ln: Line) -> Optional[int]:
                if page_im is None:
                    return None
                W, H = page_im.size
                x0, x1 = _column_band_for_line(ln, W, bands)
                # 1) Crop‑OCR in de stemmenkolom (sterk signaal)
                crop = page_im.crop((x0, max(ln.top - 8, 0), x1, min(ln.bottom + 8, H - 1)))
                v = ocr_digit_crop(crop)
                if v is not None:
                    return v
                # 2) Digits‑woorden, maar alleen binnen band en met y‑overlap
                band_digits = _digits_in_band_for_line(ln, digits, x0, x1)
                if band_digits:
                    try:
                        return int(max(band_digits, key=lambda w: w.left).text)
                    except Exception:
                        pass
                # 3) Laatste fallback: cijfers op de regel zelf (kan ruis bevatten, maar beperkt omdat band al faalde)
                return extract_numeric_on_line(ln)

            for ln in scan_slice:
                low = (ln.text or "").strip().lower()
                if low.startswith("subtotaal"):
                    v = _extract_digits_for_line(ln)
                    subtotals.append(v if v is not None else None)
                elif low.startswith("totaal"):
                    totaal_val = _extract_digits_for_line(ln)

            # Map to sjabloon candidates
            sj_kandidaten = []
            # Build a quick index by recognized candidate number in OCR lines (when present)
            line_segments: List[Tuple[Line, List[str], Optional[int], Optional[int]]] = []
            for ln in cand_lines:
                segs = split_candidate_segments(ln.text)
                # candidate number often at start of first segment
                kn = extract_candidate_number_from_text(segs[0]) if segs else None
                val = _extract_digits_for_line(ln)
                line_segments.append((ln, segs, kn, val))

            # Initialize stemmen as "leeg"
            sj_len = len(kandidaten_tpl)
            stemmen_per_index: List[object] = ["leeg"] * sj_len

            # First pass: if we can match by candidate number, use it
            for ln, segs, kn, val in line_segments:
                if kn is None:
                    continue
                idx0 = None
                # sjabloon kandidaten have kandidaatnummer in field
                for i, k in enumerate(kandidaten_tpl):
                    knum = k.get("kandidaatnummer", {}).get("waarde") if isinstance(k.get("kandidaatnummer"), dict) else k.get("kandidaatnummer")
                    if knum == kn:
                        idx0 = i
                        break
                if idx0 is not None and 0 <= idx0 < sj_len:
                    if val is not None:
                        stemmen_per_index[idx0] = int(val)

            # Second pass (beperk risico): alleen als kandidaatnummer ontbreekt en
            # er is precies één segment (dus geen samengeplakte naamregels), vul op volgorde.
            remaining_indices = [i for i, v in enumerate(stemmen_per_index) if v == "leeg"]
            for ln, segs, kn, val in line_segments:
                if kn is not None or val is None:
                    continue
                if len(segs) != 1:
                    continue
                if not remaining_indices:
                    break
                i = remaining_indices.pop(0)
                stemmen_per_index[i] = int(val)

            # Build sjabloon list entry with ingevulde waarden
            out_list = {
                "lijstnummer": int(lijstnummer) if lijstnummer is not None else None,
                "partijnaam": partijnaam,
                "kandidaten": [],
                "subtotaal_links": (int(subtotals[0]) if len(subtotals) > 0 and subtotals[0] is not None else "leeg"),
                "subtotaal_rechts": (int(subtotals[1]) if len(subtotals) > 1 and subtotals[1] is not None else "leeg"),
                "totaal_lijst": (int(totaal_val) if isinstance(totaal_val, int) else (totaal_val if totaal_val is not None else "leeg")),
            }
            for i, k in enumerate(kandidaten_tpl):
                knum = k.get("kandidaatnummer", {}).get("waarde") if isinstance(k.get("kandidaatnummer"), dict) else k.get("kandidaatnummer")
                kname = k.get("kandidaatnaam", {}).get("waarde") if isinstance(k.get("kandidaatnaam"), dict) else k.get("kandidaatnaam")
                out_list["kandidaten"].append({
                    "kandidaatnummer": int(knum) if knum is not None else None,
                    "kandidaatnaam": kname,
                    "stemmen": stemmen_per_index[i],
                })
            entry["lijsten"].append(out_list)

        out["paginas"].append(entry)

    return out


def main():
    ap = argparse.ArgumentParser(description="Vul sjabloon‑gedreven invulwaarden uit PDF (snelle modus)")
    ap.add_argument("pdf", help="Pad naar PDF")
    ap.add_argument("--sjabloon", required=True, help="Pad naar sjabloon.json")
    ap.add_argument("--headers", default=None, help="Optioneel: pad naar headers JSON (A–H, A2–D2, stembureau)")
    ap.add_argument("--out", required=True, help="Uitvoer pad (.final.json) compatibel met make_combined_nl")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    sj = json.loads(Path(args.sjabloon).read_text(encoding="utf-8"))
    headers = None
    if args.headers and Path(args.headers).exists():
        try:
            headers = json.loads(Path(args.headers).read_text(encoding="utf-8"))
        except Exception:
            headers = None
    out = build_from_sjabloon(pdf, sj, headers)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
