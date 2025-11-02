#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
import subprocess


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)
    return p.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Runner: 1 PDF → 1 meest complete NL JSON (per pagina)")
    ap.add_argument("pdf", help="Pad naar de PDF")
    ap.add_argument("sidecar", help="Pad naar de sidecar .txt behorend bij de PDF")
    ap.add_argument("--gemeente", default=None, help="Gemeentenaam (anders uit mapnaam)")
    ap.add_argument("--outdir", default=None, help="Uitvoer directory (default: map van deze runner)")
    ap.add_argument("--basename", default=None, help="Bestandsbasisnaam voor outputs (zonder extensie)")
    ap.add_argument("--keep-intermediate", action="store_true", help="Bewaar tussenbestanden (.json, .ocr.json)")
    args = ap.parse_args()

    pdf = Path(args.pdf).resolve()
    sidecar = Path(args.sidecar).resolve()
    here = Path(__file__).resolve().parent

    # Standaard outputdir naast deze runner
    if args.outdir:
        outdir = Path(args.outdir).resolve()
    else:
        outdir = here.parent  # pakket/clubgebouw_vzod

    gemeente = args.gemeente or pdf.parent.name
    outdir.mkdir(parents=True, exist_ok=True)

    base = args.basename or pdf.stem
    sidecar_json = outdir / (base + ".json")
    ocr_json = outdir / (base + ".ocr.json")
    final_json = outdir / (base + ".final.json")

    # Stap 1: sidecar → NL JSON
    run([
        sys.executable,
        str(here / "sidecar_to_json_nl.py"),
        str(sidecar),
        "--gemeente",
        gemeente,
        "--pdf-pad",
        str(pdf),
        "--out",
        str(sidecar_json),
    ])

    # Stap 2: beeld‑OCR
    run([
        sys.executable,
        str(here / "ocr_votes_pdf.py"),
        str(pdf),
        "--out",
        str(ocr_json),
    ])

    # Stap 3: merge → final
    run([
        sys.executable,
        str(here / "merge_sidecar_ocr.py"),
        str(sidecar_json),
        str(ocr_json),
        "--out",
        str(final_json),
    ])

    # Stap 4: header OCR (A–H, D2) → bijvullen waar leeg/onleesbaar
    header_json = outdir / (base + ".headers.json")
    # Probeer eerst tekst-gebaseerde headers (zoals referentie-aanpak), fallback op beeld-headers
    rc_text = run([
        sys.executable,
        str(here / "headers_from_text.py"),
        str(pdf),
        "--out",
        str(header_json),
    ])
    if rc_text is None:
        # compat: run() returns stdout; ignore
        pass
    # Patch final_json in-place
    try:
        import json as _json
        data = _json.loads(final_json.read_text(encoding="utf-8"))
        hdr = _json.loads(header_json.read_text(encoding="utf-8"))
        p1 = next((p for p in data.get("paginas", []) if p.get("pagina") == 1), None)
        if p1:
            for sec, keys in (("aantal_toegelaten_kiezers", ("A","B","C","D")), ("aantal_uitgebrachte_stemmen", ("E","F","G","H"))):
                if sec in p1 and isinstance(p1[sec], dict):
                    for k in keys:
                        v = hdr.get(k)
                        if v is not None:
                            cur = p1[sec].get(k, {}).get("waarde")
                            if not isinstance(cur, int):
                                try:
                                    p1[sec][k]["waarde"] = int(v)
                                except Exception:
                                    p1[sec][k]["waarde"] = v
        p2 = next((p for p in data.get("paginas", []) if p.get("pagina") == 2), None)
        if p2:
            d2 = hdr.get("D2")
            if d2 is not None:
                v = p2.get("verschil_toegelaten_vs_uitgebrachte", {}).get("hertelling", {}).get("D2", {}).get("waarde")
                if not isinstance(v, int):
                    try:
                        p2["verschil_toegelaten_vs_uitgebrachte"]["hertelling"]["D2"]["waarde"] = int(d2)
                    except Exception:
                        p2["verschil_toegelaten_vs_uitgebrachte"]["hertelling"]["D2"]["waarde"] = d2
        final_json.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Optioneel: tussenbestanden opruimen
    if not args.keep_intermediate:
        try:
            if sidecar_json.exists():
                sidecar_json.unlink()
        except Exception:
            pass
        try:
            if ocr_json.exists():
                ocr_json.unlink()
        except Exception:
            pass
        try:
            if header_json.exists():
                header_json.unlink()
        except Exception:
            pass

    print(final_json)


if __name__ == "__main__":
    main()
