#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


LABELS = {
    "gemeente": "Gemeente",
    "stembureau_nummer": "Nummer stembureau",
    "stembureau_naam": "Locatie stembureau",
    "A": "Aantal geldige stempassen",
    "B": "Aantal geldige volmachtbewijzen (schriftelijk of via ingevulde stem- of kiezerspas)",
    "C": "Aantal geldige kiezerspassen",
    "D": "Totaal aantal toegelaten kiezers (A+B+C)",
    "E": "Aantal stembiljetten met een geldige stem op een kandidaat",
    "F": "Aantal blanco stembiljetten",
    "G": "Aantal ongeldige stembiljetten",
    "H": "Totaal aantal uitgebrachte stemmen (E+F+G)",
    "A2": "Aantal geldige stempassen (hertelling)",
    "B2": "Aantal geldige volmachtbewijzen (hertelling)",
    "C2": "Aantal geldige kiezerspassen (hertelling)",
    "D2": "Totaal aantal toegelaten kiezers (hertelling)",
    "keuze": "Is er een verschil (Nee/Ja ...)",
}


def wrap(label, value, bron):
    return {"label": label, "waarde": value, "waarde_bron": bron}


def build_sjabloon(src: dict) -> dict:
    out = {
        "bron_pdf": src.get("bestand"),
        "kop": {
            # deze drie zijn invul (handgeschreven), dus geen waarde invullen
            "gemeente": wrap(LABELS["gemeente"], None, "handgeschreven"),
            "stembureau_nummer": wrap(LABELS["stembureau_nummer"], None, "handgeschreven"),
            "stembureau_naam": wrap(LABELS["stembureau_naam"], None, "handgeschreven"),
        },
        "pagina_1": {
            "toegelaten_kiezers": {k: wrap(LABELS[k], None, "handgeschreven") for k in ("A","B","C","D")},
            "uitgebrachte_stemmen": {k: wrap(LABELS[k], None, "handgeschreven") for k in ("E","F","G","H")},
        },
        "pagina_2": {
            "verschil_toegelaten_vs_uitgebrachte": {
                "keuze": wrap(LABELS["keuze"], None, "handgeschreven"),
                "hertelling": {k: wrap(LABELS[k], None, "handgeschreven") for k in ("A2","B2","C2","D2")},
            }
        },
        "paginas": [],
    }
    # Lijsten/kandidaten zijn sjabloon (geprint) op deze PDF
    for page in src.get("paginas", []):
        if not page.get("lijsten"):
            continue
        entry = {"pagina": page.get("pagina"), "lijsten": []}
        for lst in page.get("lijsten", []):
            lj = {
                "lijstnummer": wrap("Lijstnummer", lst.get("lijstnummer"), "sjabloon"),
                "partijnaam": wrap("Partijnaam", lst.get("partijnaam"), "sjabloon"),
                "kandidaten": [],
            }
            for cand in lst.get("kandidaten", []):
                lj["kandidaten"].append({
                    "kandidaatnummer": wrap("Kandidaatnummer", cand.get("kandidaatnummer"), "sjabloon"),
                    "kandidaatnaam": wrap("Kandidaatnaam", cand.get("kandidaatnaam"), "sjabloon"),
                })
            entry["lijsten"].append(lj)
        out["paginas"].append(entry)
    return out


def main():
    ap = argparse.ArgumentParser(description="Maak sjabloon.json (alleen sjabloonwaarden, geen invulwaarden)")
    ap.add_argument("final_json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src = json.loads(Path(args.final_json).read_text(encoding="utf-8"))
    dst = build_sjabloon(src)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(dst, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()

