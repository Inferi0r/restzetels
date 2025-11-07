#!/usr/bin/env python3
from __future__ import annotations

import sys

try:
    from pdf_scraper.cli import main
except Exception as e:
    print(f"Failed to import modular scraper: {e}")
    sys.exit(1)


if __name__ == "__main__":
    main()
