"""
Modular PDF scraper package for municipal PV (N10) discovery.

Goals:
- Compact, modular code with pluggable strategies per municipality/platform.
- Minimize HTTP requests with targeted heuristics and early stopping.
- Clear console logging of actions and a per-municipality trace log for learning.
"""

from . import config as _config  # re-export common config

__all__ = [
    "_config",
]

