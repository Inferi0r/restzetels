#!/usr/bin/env python3
import os
import json
import string
import subprocess
import sys
from datetime import datetime


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "pdf_scraper_input")
MUNI_JSON = os.path.join(DATA_DIR, "municipalities.json")


def load_municipalities():
    with open(MUNI_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    return [it.get("name") for it in items if it.get("name")]


def by_letter(names):
    d = {ch: [] for ch in string.ascii_uppercase}
    for n in names:
        if not n:
            continue
        ch = n[:1].upper()
        if ch in d:
            d[ch].append(n)
    return d


def main():
    names = load_municipalities()
    groups = by_letter(names)
    # Letters G..Z inclusive
    letters = list("GHIJKLMNOPQRSTUVWXYZ")
    procs = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for letter in letters:
        if not groups.get(letter):
            # Skip if no gemeenten for this letter
            continue
        log_path = os.path.join(ROOT, f"pdf_scraper_{letter}.log")
        idx_path = os.path.join(DATA_DIR, f"municipality_pdfs_index_{letter}.json")
        cmd = [sys.executable, "-u", os.path.join(ROOT, "pdf_scraper.py"),
               "--starts-with", letter,
               "--index-path", idx_path]
        lf = open(log_path, "w", encoding="utf-8")
        lf.write(f"# Started {letter} at {ts}\n")
        lf.flush()
        print(f"Launching {letter}: log={os.path.basename(log_path)}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT)
        procs.append((letter, p, lf))

    # Wait for all
    failed = []
    for letter, p, lf in procs:
        code = p.wait()
        lf.write(f"\n# Exit code: {code}\n")
        lf.close()
        if code != 0:
            failed.append((letter, code))
        print(f"Finished {letter}: exit={code}")

    # Final index build from disk to aggregate all results
    print("Rebuilding merged index from disk ...")
    merge_cmd = [sys.executable, "-u", os.path.join(ROOT, "pdf_scraper.py"), "--merge-from-disk"]
    subprocess.run(merge_cmd, cwd=ROOT, check=False)

    if failed:
        print("Some letter jobs failed:")
        for letter, code in failed:
            print(f"  {letter}: exit {code}")
        sys.exit(1)
    print("All letter jobs completed.")


if __name__ == "__main__":
    main()

