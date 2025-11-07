#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

def _run_main_via_alias() -> None:
    """Load the CLI and its sibling modules under a temporary package alias.
    This makes the script runnable even if the folder name changed or when
    importing the original package name is disallowed.
    """
    import importlib.util
    import types

    pkg_dir = os.path.dirname(__file__)
    alias = "_rz_scraper"

    # Create a fake package at runtime that points to this directory
    if alias not in sys.modules:
        pkg = types.ModuleType(alias)
        # Mark as package by adding __path__
        pkg.__path__ = [pkg_dir]  # type: ignore[attr-defined]
        sys.modules[alias] = pkg

    # Load the cli.py as alias.cli so that its relative imports (e.g. .discovery) resolve
    cli_path = os.path.join(pkg_dir, "cli.py")
    spec = importlib.util.spec_from_file_location(f"{alias}.cli", cli_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load CLI module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{alias}.cli"] = mod
    spec.loader.exec_module(mod)
    # Call its main()
    if not hasattr(mod, "main"):
        raise RuntimeError("CLI module has no main()")
    mod.main()  # type: ignore[attr-defined]


if __name__ == "__main__":
    try:
        # Prefer normal intra-package import when executed via `python -m pdf_scraper.pdf_scraper`
        if __package__:
            from .cli import main  # type: ignore
            main()
        else:
            raise ImportError("force alias load")
    except Exception:
        # Fallback: run via runtime alias (robust to folder renames)
        _run_main_via_alias()
