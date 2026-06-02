"""Run the upstream FlexiTac heatmap with a local matplotlib cache."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def run_heatmap(argv: list[str] | None = None) -> int:
    """Set a writable matplotlib cache directory, then delegate to PyFlexiTac."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib"))

    from examples.visualize_heatmap import main as heatmap_main

    if argv is None:
        return heatmap_main()

    old_argv = sys.argv
    sys.argv = [old_argv[0], *argv]
    try:
        return heatmap_main()
    finally:
        sys.argv = old_argv


def main() -> int:
    return run_heatmap()
