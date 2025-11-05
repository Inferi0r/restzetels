#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

if __package__ is None or __package__ == "":
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    __package__ = "pdf_scraper"

from .cli import main


if __name__ == "__main__":
    main()
