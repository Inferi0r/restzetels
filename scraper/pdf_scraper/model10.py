from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Set

from .config import REPO_ROOT


MODEL10_PATH = os.path.join(REPO_ROOT, "gemeente_model_10.json")


def load_model10() -> Dict[str, List[dict]]:
    try:
        with open(MODEL10_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def extract_stembureau_numbers_from_text(s: str) -> Set[int]:
    out: Set[int] = set()
    s = (s or "").replace("_", " ")
    # patterns like: "123 Stembureau ..." or "stembureau 123"
    for m in re.finditer(r"\b(\d{1,4})\b", s):
        try:
            n = int(m.group(1))
            if 1 <= n <= 9999:
                out.add(n)
        except Exception:
            pass
    return out


def log_model10_progress(municipality: str, items: List[dict]) -> None:
    data = load_model10()
    want = data.get(municipality)
    if not want:
        print(f"[MODEL10] No reference for {municipality}")
        return
    expected_numbers: Set[int] = set()
    for it in want:
        n = it.get('stembureau_nummer')
        if isinstance(n, int):
            expected_numbers.add(n)
    found_numbers: Set[int] = set()
    for it in items:
        label = (it.get('pdf_name') or '') + ' ' + (it.get('text') or '') + ' ' + (it.get('remote_url') or '')
        nums = extract_stembureau_numbers_from_text(label)
        found_numbers.update(nums)
    have = expected_numbers & found_numbers
    print(f"[MODEL10] {municipality}: PV coverage {len(have)}/{len(expected_numbers)} stembureaus")
    if expected_numbers:
        missing = sorted(list(expected_numbers - have))[:20]
        if missing:
            print(f"[MODEL10] Missing example numbers: {missing}")

