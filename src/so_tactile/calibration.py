"""Calibration file helpers for FlexiTac tactile baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TACTILE_CALIBRATION_DIR = PROJECT_ROOT / "calibration" / "tactile"
DEFAULT_TACTILE_BASELINE_PATH = DEFAULT_TACTILE_CALIBRATION_DIR / "baseline.json"


@dataclass(frozen=True)
class TactileBaseline:
    """Saved no-contact FlexiTac baseline."""

    rows: int
    cols: int
    baud: int
    frames: int
    created_at: datetime
    baseline: NDArray[np.float32]


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def save_tactile_baseline(
    path: str | Path,
    baseline: NDArray[np.float32],
    *,
    rows: int,
    cols: int,
    baud: int,
    frames: int,
    created_at: datetime | None = None,
) -> Path:
    baseline_array = np.asarray(baseline, dtype=np.float32)
    if baseline_array.shape != (rows, cols):
        raise ValueError(
            f"baseline shape {baseline_array.shape} does not match rows/cols {(rows, cols)}"
        )

    created_at = created_at or utc_now()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    created_at = created_at.astimezone(UTC)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rows": rows,
        "cols": cols,
        "baud": baud,
        "frames": frames,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "baseline": baseline_array.tolist(),
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def load_tactile_baseline(
    path: str | Path,
    *,
    rows: int | None = None,
    cols: int | None = None,
) -> TactileBaseline:
    input_path = Path(path)
    payload: dict[str, Any] = json.loads(input_path.read_text(encoding="utf-8"))

    saved_rows = int(payload["rows"])
    saved_cols = int(payload["cols"])
    if rows is not None and saved_rows != rows:
        raise ValueError(f"baseline rows {saved_rows} do not match requested rows {rows}")
    if cols is not None and saved_cols != cols:
        raise ValueError(f"baseline cols {saved_cols} do not match requested cols {cols}")

    baseline = np.asarray(payload["baseline"], dtype=np.float32)
    if baseline.shape != (saved_rows, saved_cols):
        raise ValueError(
            "baseline shape "
            f"{baseline.shape} does not match saved rows/cols {(saved_rows, saved_cols)}"
        )

    return TactileBaseline(
        rows=saved_rows,
        cols=saved_cols,
        baud=int(payload["baud"]),
        frames=int(payload["frames"]),
        created_at=parse_timestamp(str(payload["created_at"])),
        baseline=baseline,
    )
