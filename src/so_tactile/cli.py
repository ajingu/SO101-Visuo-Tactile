"""Unified CLI for SO-ARM and FlexiTac tactile workflows."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC
from pathlib import Path

import numpy as np

from so_tactile import calibration
from so_tactile.heatmap import run_heatmap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROBOT_CALIBRATION_DIR = PROJECT_ROOT / "calibration" / "robot"


def run(command: list[str]) -> int:
    print("+ " + " ".join(command))
    try:
        return subprocess.run(command).returncode
    except FileNotFoundError as exc:
        print(f"Command not found: {exc.filename}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


def robot_calibration_dir(value: str | None = None) -> str:
    return value or str(DEFAULT_ROBOT_CALIBRATION_DIR)


def calibrate_robot(
    role: str,
    *,
    port: str,
    robot_id: str | None = None,
    calibration_dir_value: str | None = None,
) -> int:
    robot_id = robot_id or role
    calib_dir = robot_calibration_dir(calibration_dir_value)

    if role == "leader":
        return run(
            [
                "lerobot-calibrate",
                "--teleop.type=so101_leader",
                f"--teleop.port={port}",
                f"--teleop.id={robot_id}",
                f"--teleop.calibration_dir={calib_dir}",
            ]
        )

    return run(
        [
            "lerobot-calibrate",
            "--robot.type=so101_follower",
            f"--robot.port={port}",
            f"--robot.id={robot_id}",
            f"--robot.calibration_dir={calib_dir}",
        ]
    )


def robot_calibrate_command(args: argparse.Namespace) -> int:
    return calibrate_robot(
        args.role,
        port=args.port,
        robot_id=args.id,
        calibration_dir_value=args.calibration_dir,
    )


def heatmap_command(args: argparse.Namespace) -> int:
    argv = [
        "--port",
        args.port,
        "--rows",
        str(args.rows),
        "--cols",
        str(args.cols),
        "--baud",
        str(args.baud),
        "--cmap",
        args.cmap,
    ]
    return run_heatmap(argv)


def tactile_baseline_path(value: str | None = None) -> Path:
    return Path(value) if value else calibration.DEFAULT_TACTILE_BASELINE_PATH


def tactile_calibrate_command(args: argparse.Namespace) -> int:
    from flexitac import FlexiTacSensor

    if not args.no_prompt:
        input("Keep the tactile sensor unloaded/no-contact, then press Enter to calibrate... ")

    sensor = FlexiTacSensor(
        args.port,
        rows=args.rows,
        cols=args.cols,
        baud=args.baud,
        threshold=args.threshold,
        noise_scale=args.noise_scale,
        init_frames=args.frames,
    )
    with sensor:
        baseline = sensor.calibrate(args.frames)

    output_path = calibration.save_tactile_baseline(
        tactile_baseline_path(args.baseline_path),
        baseline,
        rows=args.rows,
        cols=args.cols,
        baud=args.baud,
        frames=args.frames,
    )
    print(f"Saved tactile baseline: {output_path}")
    print(f"baseline_min={float(np.min(baseline)):.2f} baseline_max={float(np.max(baseline)):.2f}")
    return 0


def tactile_status_command(args: argparse.Namespace) -> int:
    baseline_path = tactile_baseline_path(args.baseline_path)
    if not baseline_path.exists():
        print(f"No tactile baseline found: {baseline_path}")
        return 0

    saved = calibration.load_tactile_baseline(baseline_path)
    created_at = saved.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    print(f"Tactile baseline: {baseline_path}")
    print(f"created_at={created_at}")
    print(f"rows={saved.rows} cols={saved.cols} baud={saved.baud} frames={saved.frames}")
    return 0


def tactile_check_command(args: argparse.Namespace) -> int:
    from flexitac import FlexiTacSensor

    baseline_path = tactile_baseline_path(args.baseline_path)
    saved = calibration.load_tactile_baseline(baseline_path, rows=args.rows, cols=args.cols)
    rows = args.rows or saved.rows
    cols = args.cols or saved.cols
    baud = args.baud or saved.baud

    sensor = FlexiTacSensor(
        args.port,
        rows=rows,
        cols=cols,
        baud=baud,
        threshold=args.threshold,
        noise_scale=args.noise_scale,
        baseline=saved.baseline,
    )
    raw_max = 0.0
    norm_max = 0.0
    with sensor:
        for _ in range(args.frames):
            frame = sensor.read_latest()
            raw_max = max(raw_max, float(np.max(frame.raw)))
            norm_max = max(norm_max, float(np.max(frame.normalized)))

    print(f"frames={args.frames} raw_max={raw_max:.2f} norm_max={norm_max:.4f}")
    return 0


def add_common_tactile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rows", type=int, default=12)
    parser.add_argument("--cols", type=int, default=32)
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--threshold", type=float, default=25.0)
    parser.add_argument("--noise-scale", type=float, default=30.0)
    parser.add_argument("--baseline-path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="so-tactile")
    subparsers = parser.add_subparsers(dest="command")

    heatmap_parser = subparsers.add_parser("heatmap")
    heatmap_parser.add_argument("--port", required=True)
    heatmap_parser.add_argument("--rows", type=int, default=12)
    heatmap_parser.add_argument("--cols", type=int, default=32)
    heatmap_parser.add_argument("--baud", type=int, default=2_000_000)
    heatmap_parser.add_argument("--cmap", default="viridis")
    heatmap_parser.set_defaults(func=heatmap_command)

    robot_parser = subparsers.add_parser("robot")
    robot_subparsers = robot_parser.add_subparsers(dest="robot_command")
    robot_calibrate_parser = robot_subparsers.add_parser("calibrate")
    robot_calibrate_parser.add_argument("role", choices=["leader", "follower"])
    robot_calibrate_parser.add_argument("--port", required=True)
    robot_calibrate_parser.add_argument("--id")
    robot_calibrate_parser.add_argument("--calibration-dir")
    robot_calibrate_parser.set_defaults(func=robot_calibrate_command)

    tactile_parser = subparsers.add_parser("tactile")
    tactile_subparsers = tactile_parser.add_subparsers(dest="tactile_command")

    tactile_calibrate_parser = tactile_subparsers.add_parser("calibrate")
    tactile_calibrate_parser.add_argument("--port", required=True)
    add_common_tactile_args(tactile_calibrate_parser)
    tactile_calibrate_parser.add_argument("--frames", type=int, default=30)
    tactile_calibrate_parser.add_argument("--no-prompt", action="store_true")
    tactile_calibrate_parser.set_defaults(func=tactile_calibrate_command)

    tactile_status_parser = tactile_subparsers.add_parser("status")
    tactile_status_parser.add_argument("--baseline-path")
    tactile_status_parser.set_defaults(func=tactile_status_command)

    tactile_check_parser = tactile_subparsers.add_parser("check")
    tactile_check_parser.add_argument("--port", required=True)
    tactile_check_parser.add_argument("--rows", type=int)
    tactile_check_parser.add_argument("--cols", type=int)
    tactile_check_parser.add_argument("--baud", type=int)
    tactile_check_parser.add_argument("--threshold", type=float, default=25.0)
    tactile_check_parser.add_argument("--noise-scale", type=float, default=30.0)
    tactile_check_parser.add_argument("--baseline-path")
    tactile_check_parser.add_argument("--frames", type=int, default=5)
    tactile_check_parser.set_defaults(func=tactile_check_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
