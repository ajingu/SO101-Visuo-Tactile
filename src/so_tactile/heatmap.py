"""Run the upstream FlexiTac heatmap with a local matplotlib cache."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    """Set a writable matplotlib cache directory, then delegate to PyFlexiTac."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib"))

    from examples.visualize_heatmap import main as heatmap_main

    return heatmap_main()
