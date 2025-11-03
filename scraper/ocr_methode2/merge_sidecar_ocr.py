#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def merge_page_lists(side_lijsten, ocr_lijsten):
    # Merge by lijstnummer + partijnaam; fallback to position if no exact match
    used = set()
    for i, sl in enumerate(side_lijsten):
        match = None
        for j, ol in enumerate(ocr_lijsten):
            if j in used:
                continue
            if sl.get("lijstnummer") == ol.get("lijstnummer") and sl.get("partijnaam") == ol.get("partijnaam"):
                match = (j, ol)
                break
        if match is None:
            # fallback by index
            for j, ol in enumerate(ocr_lijsten):
                if j not in used:
                    match = (j, ol)
                    break
        if match is None:
            continue
        j, ol = match
        used.add(j)
        # Kandidaten stemmen: align by index
        sk = sl.get("kandidaten", [])
        ok = ol.get("kandidaten", [])
        m = min(len(sk), len(ok))
        for k in range(m):
            val = ok[k].get("stemmen", "leeg")
            # alleen overschrijven als het getal is of expliciet "0"; laat "leeg" staan anders
            if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                sk[k]["stemmen"] = int(val)
            elif val == "onleesbaar":
                # indien onleesbaar in OCR, laat bestaande staan
                pass
        # Subtotalen/totaal
        for key in ("subtotaal_links", "subtotaal_rechts", "totaal_lijst"):
            v = ol.get(key)
            if isinstance(v, int):
                sl[key] = v
            elif v == "leeg":
                sl.setdefault(key, "leeg")
            elif v == "onleesbaar":
                sl.setdefault(key, "onleesbaar")


def merge(sidecar_path: Path, ocr_path: Path, out_path: Path):
    side = load_json(sidecar_path)
    ocr = load_json(ocr_path)
    side_pages = side.get("paginas", [])
    ocr_pages = ocr.get("paginas", [])
    oi = 0
    for sp in side_pages:
        if "lijsten" in sp and oi < len(ocr_pages):
            op = ocr_pages[oi]
            if "lijsten" in op:
                merge_page_lists(sp["lijsten"], op["lijsten"])
            oi += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(side, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Merge sidecar-JSON met OCR-JSON (vul stemmen/subtotalen)")
    ap.add_argument("sidecar_json")
    ap.add_argument("ocr_json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    merge(Path(args.sidecar_json), Path(args.ocr_json), Path(args.out))
    print(args.out)


if __name__ == "__main__":
    main()

