"""Unified CLI for SO-ARM and FlexiTac tactile workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path
from typing import Any

import numpy as np

from so_tactile import calibration
from so_tactile.heatmap import run_heatmap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROBOT_CALIBRATION_DIR = PROJECT_ROOT / "calibration" / "robot"
DEFAULT_PORTS_CONFIG_PATH = PROJECT_ROOT / "configs" / "ports.json"
DEFAULT_CAMERAS_CONFIG_PATH = PROJECT_ROOT / "configs" / "cameras.json"
DEFAULT_DATASET_DIR = PROJECT_ROOT / "outputs" / "datasets"
DEFAULT_CAPTURE_DATASET_DIR = DEFAULT_DATASET_DIR / "captures"
LEGACY_TRAIN_DATASET_DIR = DEFAULT_DATASET_DIR / "train"
CV2_BACKEND_CODES = {
    "ANY": 0,
    "V4L2": 200,
    "DSHOW": 700,
    "MSMF": 1400,
}
DEFAULT_HEATMAP_CELL_SIZE = 25


def run(command: list[str], *, env_overrides: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(command))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    try:
        return subprocess.run(command, env=env).returncode
    except FileNotFoundError as exc:
        print(f"Command not found: {exc.filename}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


def run_or_print(
    command: list[str],
    *,
    dry_run: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> int:
    if dry_run:
        if env_overrides:
            env_text = " ".join(f"{key}={value}" for key, value in sorted(env_overrides.items()))
            print(f"{env_text} " + "+ " + " ".join(command))
            return 0
        print("+ " + " ".join(command))
        return 0
    return run(command, env_overrides=env_overrides)


def load_ports_config(value: str | None = None) -> dict[str, Any]:
    path = Path(value) if value else DEFAULT_PORTS_CONFIG_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_cameras_config(value: str | None = None) -> list[dict[str, Any]]:
    path = Path(value) if value else DEFAULT_CAMERAS_CONFIG_PATH
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    cameras = payload.get("cameras")
    if not isinstance(cameras, list):
        raise ValueError(f"{path} must contain a 'cameras' list")
    return cameras


def config_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    section = config.get(name, {})
    return section if isinstance(section, dict) else {}


def config_value(
    explicit: Any,
    config: dict[str, Any],
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    if explicit is not None:
        return explicit
    return config_section(config, section).get(key, default)


def tactile_config_baud(ports_config: dict[str, Any]) -> int | None:
    value = config_section(ports_config, "tactile").get("baud_rate")
    return int(value) if value is not None else None


def tactile_heatmap_cell_size(ports_config: dict[str, Any]) -> int:
    value = config_section(ports_config, "tactile").get("heatmap_cell_size")
    return int(value) if value is not None else DEFAULT_HEATMAP_CELL_SIZE


def lerobot_command(command: str) -> list[str]:
    return [sys.executable, "-m", "so_tactile.lerobot_run", command]


def lerobot_env(
    ports_config: dict[str, Any],
    args: argparse.Namespace | None = None,
) -> dict[str, str]:
    cell_size = getattr(args, "heatmap_cell_size", None) or tactile_heatmap_cell_size(ports_config)
    follower_config = config_section(ports_config, "follower")
    park_on_exit = config_bool(follower_config.get("park_on_exit"), True)
    if getattr(args, "park_on_exit", None) is False:
        park_on_exit = False
    park_duration_s = getattr(args, "park_duration_s", None) or follower_config.get(
        "park_duration_s",
        3.0,
    )

    env = {
        "SO_TACTILE_HEATMAP_CELL_SIZE": str(cell_size),
        "SO101_PARK_ON_EXIT": str(park_on_exit).lower(),
        "SO101_PARK_DURATION_S": str(park_duration_s),
    }
    park_pose = follower_config.get("park_pose")
    if park_pose is not None:
        env["SO101_PARK_POSE"] = json.dumps(park_pose)
    return env


def require_value(value: Any, name: str) -> Any:
    if value in (None, ""):
        raise ValueError(f"Missing {name}. Set it in configs/ports.json or pass the CLI flag.")
    return value


def config_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def robot_calibration_dir(
    value: str | None = None,
    ports_config: dict[str, Any] | None = None,
) -> str:
    if value:
        return value
    if ports_config and ports_config.get("calibration_dir"):
        path = Path(ports_config["calibration_dir"])
        return str(path if path.is_absolute() else PROJECT_ROOT / path)
    return str(DEFAULT_ROBOT_CALIBRATION_DIR)


def dataset_root_for_repo(repo_id: str) -> Path:
    return DEFAULT_CAPTURE_DATASET_DIR


def lerobot_dataset_path(repo_id: str, dataset_root: str | None = None) -> Path:
    root = Path(dataset_root) if dataset_root else dataset_root_for_repo(repo_id)
    return root / Path(repo_id)


def remove_existing_dataset(
    repo_id: str,
    dataset_root: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    dataset_path = lerobot_dataset_path(repo_id, dataset_root).resolve()
    dataset_root_path = DEFAULT_DATASET_DIR.resolve()

    if dataset_root is not None:
        requested_root = Path(dataset_root).resolve()
        if requested_root != dataset_path and requested_root not in dataset_path.parents:
            raise RuntimeError(f"Refusing to remove path outside requested dataset root: {dataset_path}")
    elif dataset_root_path != dataset_path and dataset_root_path not in dataset_path.parents:
        raise RuntimeError(f"Refusing to remove path outside project datasets: {dataset_path}")

    if dataset_path.exists():
        if dry_run:
            print(f"Would remove existing local dataset: {dataset_path}")
            return
        print(f"Removing existing local dataset: {dataset_path}")
        shutil.rmtree(dataset_path)


def find_lerobot_dataset_path(repo_id: str) -> Path:
    preferred_path = lerobot_dataset_path(repo_id)
    if preferred_path.exists():
        return preferred_path

    candidates = [
        DEFAULT_CAPTURE_DATASET_DIR / Path(repo_id),
        LEGACY_TRAIN_DATASET_DIR / Path(repo_id),
        DEFAULT_DATASET_DIR / Path(repo_id),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return preferred_path


def tactile_sensors_arg(
    name: str,
    port: str,
    baud_rate: int,
    *,
    enable_visualization: bool = True,
) -> str:
    sensor_config = json.dumps(
        {
            "port": port,
            "baud_rate": baud_rate,
            "enable_visualization": enable_visualization,
        }
    )
    return f"{{{name}: {sensor_config}}}"


def cv2_backend_code(backend: int | str | None) -> int | None:
    if backend is None:
        return None
    if isinstance(backend, int):
        return backend

    backend_text = backend.strip().upper()
    if backend_text.isdigit():
        return int(backend_text)
    backend_text = backend_text.removeprefix("CAP_")
    if backend_text in CV2_BACKEND_CODES:
        return CV2_BACKEND_CODES[backend_text]
    raise ValueError(f"Unsupported OpenCV backend: {backend}")


def lerobot_cameras_arg(cameras: list[dict[str, Any]]) -> str | None:
    if not cameras:
        return None

    camera_items = []
    for camera in cameras:
        name = str(camera["name"])
        index_or_path = camera.get("index_or_path", camera.get("index"))
        if index_or_path is None:
            raise ValueError(f"Camera {name!r} must define 'index' or 'index_or_path'")

        fields = [
            f"type: {camera.get('type', 'opencv')}",
            f"index_or_path: {index_or_path}",
            f"width: {int(camera.get('width', 640))}",
            f"height: {int(camera.get('height', 480))}",
            f"fps: {int(camera.get('fps', 30))}",
        ]
        if camera.get("fourcc") is not None:
            fields.append(f"fourcc: {camera['fourcc']}")
        backend = cv2_backend_code(camera.get("backend"))
        if backend is not None:
            fields.append(f"backend: {backend}")
        for optional_key in ("color_mode", "rotation", "warmup_s"):
            if camera.get(optional_key) is not None:
                fields.append(f"{optional_key}: {camera[optional_key]}")

        camera_items.append(f"{name}: {{" + ", ".join(fields) + "}")

    return "{ " + ", ".join(camera_items) + " }"


def robot_cameras_arg(args: argparse.Namespace) -> str | None:
    if args.no_cameras:
        return None
    if args.robot_cameras:
        return args.robot_cameras
    return lerobot_cameras_arg(load_cameras_config(args.cameras_config))


def add_ports_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ports-config", default=str(DEFAULT_PORTS_CONFIG_PATH))


def add_cameras_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cameras-config", default=str(DEFAULT_CAMERAS_CONFIG_PATH))
    parser.add_argument("--robot-cameras")
    parser.add_argument("--no-cameras", action="store_true")


def add_robot_port_args(parser: argparse.ArgumentParser, *, include_tactile: bool = True) -> None:
    add_ports_config_arg(parser)
    parser.add_argument("--leader-port")
    parser.add_argument("--follower-port")
    parser.add_argument("--leader-id")
    parser.add_argument("--follower-id")
    parser.add_argument("--calibration-dir")
    if include_tactile:
        parser.add_argument("--tactile-port")
        parser.add_argument("--tactile-name")
        parser.add_argument("--tactile-baud-rate", type=int)
        parser.add_argument("--no-tactile", action="store_true")
        parser.add_argument("--no-heatmap", action="store_true")
        parser.add_argument("--heatmap-cell-size", type=int)
    parser.add_argument("--no-park-on-exit", action="store_false", dest="park_on_exit")
    parser.add_argument("--park-duration-s", type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(park_on_exit=True)


def base_robot_args(
    args: argparse.Namespace,
    *,
    ports_config: dict[str, Any],
    include_leader: bool,
    include_tactile: bool,
) -> list[str]:
    command = []
    calib_dir = robot_calibration_dir(args.calibration_dir, ports_config)

    if include_leader:
        leader_port = require_value(
            config_value(args.leader_port, ports_config, "leader", "port"),
            "leader port",
        )
        leader_id = config_value(args.leader_id, ports_config, "leader", "id", "leader")
        command.extend(
            [
                "--teleop.type=so101_leader",
                f"--teleop.port={leader_port}",
                f"--teleop.id={leader_id}",
                f"--teleop.calibration_dir={calib_dir}",
            ]
        )

    follower_port = require_value(
        config_value(args.follower_port, ports_config, "follower", "port"),
        "follower port",
    )
    follower_id = config_value(args.follower_id, ports_config, "follower", "id", "follower")
    command.extend(
        [
            "--robot.type=so_tactile_follower",
            f"--robot.port={follower_port}",
            f"--robot.id={follower_id}",
            f"--robot.calibration_dir={calib_dir}",
        ]
    )

    if include_tactile and not args.no_tactile:
        tactile_port = require_value(
            config_value(args.tactile_port, ports_config, "tactile", "port"),
            "tactile port",
        )
        tactile_name = config_value(args.tactile_name, ports_config, "tactile", "name", "primary")
        tactile_baud = int(
            config_value(args.tactile_baud_rate, ports_config, "tactile", "baud_rate", 2_000_000)
        )
        enable_visualization = config_bool(
            config_section(ports_config, "tactile").get("enable_visualization"),
            True,
        )
        if args.no_heatmap:
            enable_visualization = False
        command.append(
            "--robot.tactile_sensors="
            f"{tactile_sensors_arg(tactile_name, tactile_port, tactile_baud, enable_visualization=enable_visualization)}"
        )

    return command


def add_tactile_sensor_arg_from_config(
    command: list[str],
    args: argparse.Namespace,
    ports_config: dict[str, Any],
) -> None:
    if args.no_tactile:
        return

    tactile_port = require_value(
        config_value(args.tactile_port, ports_config, "tactile", "port"),
        "tactile port",
    )
    tactile_name = config_value(args.tactile_name, ports_config, "tactile", "name", "primary")
    tactile_baud = int(
        config_value(args.tactile_baud_rate, ports_config, "tactile", "baud_rate", 2_000_000)
    )
    enable_visualization = config_bool(
        config_section(ports_config, "tactile").get("enable_visualization"),
        True,
    )
    if args.no_heatmap:
        enable_visualization = False
    command.append(
        "--robot.tactile_sensors="
        f"{tactile_sensors_arg(tactile_name, tactile_port, tactile_baud, enable_visualization=enable_visualization)}"
    )


def calibrate_robot(
    role: str,
    *,
    port: str,
    robot_id: str | None = None,
    calibration_dir_value: str | None = None,
    ports_config: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> int:
    robot_id = robot_id or role
    calib_dir = robot_calibration_dir(calibration_dir_value, ports_config)

    if role == "leader":
        return run_or_print(
            [
                "lerobot-calibrate",
                "--teleop.type=so101_leader",
                f"--teleop.port={port}",
                f"--teleop.id={robot_id}",
                f"--teleop.calibration_dir={calib_dir}",
            ],
            dry_run=dry_run,
        )

    return run_or_print(
        [
            "lerobot-calibrate",
            "--robot.type=so_tactile_follower",
            f"--robot.port={port}",
            f"--robot.id={robot_id}",
            f"--robot.calibration_dir={calib_dir}",
        ],
        dry_run=dry_run,
    )


def robot_calibrate_command(args: argparse.Namespace) -> int:
    ports_config = load_ports_config(args.ports_config)
    role_config = config_section(ports_config, args.role)
    return calibrate_robot(
        args.role,
        port=require_value(args.port or role_config.get("port"), f"{args.role} port"),
        robot_id=args.id or role_config.get("id"),
        calibration_dir_value=args.calibration_dir,
        ports_config=ports_config,
        dry_run=args.dry_run,
    )


def heatmap_command(args: argparse.Namespace) -> int:
    ports_config = load_ports_config(args.ports_config)
    port = require_value(
        args.port or config_section(ports_config, "tactile").get("port"),
        "tactile port",
    )
    baud = args.baud or tactile_config_baud(ports_config) or 2_000_000
    argv = [
        "--port",
        port,
        "--rows",
        str(args.rows),
        "--cols",
        str(args.cols),
        "--baud",
        str(baud),
        "--cmap",
        args.cmap,
    ]
    return run_heatmap(argv)


def tactile_baseline_path(value: str | None = None) -> Path:
    return Path(value) if value else calibration.DEFAULT_TACTILE_BASELINE_PATH


def tactile_calibrate_command(args: argparse.Namespace) -> int:
    from flexitac import FlexiTacSensor

    ports_config = load_ports_config(args.ports_config)
    port = require_value(
        args.port or config_section(ports_config, "tactile").get("port"),
        "tactile port",
    )
    baud = args.baud or tactile_config_baud(ports_config) or 2_000_000

    if not args.no_prompt:
        input("Keep the tactile sensor unloaded/no-contact, then press Enter to calibrate... ")

    sensor = FlexiTacSensor(
        port,
        rows=args.rows,
        cols=args.cols,
        baud=baud,
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
        baud=baud,
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

    ports_config = load_ports_config(args.ports_config)
    port = require_value(
        args.port or config_section(ports_config, "tactile").get("port"),
        "tactile port",
    )
    baseline_path = tactile_baseline_path(args.baseline_path)
    saved = calibration.load_tactile_baseline(baseline_path, rows=args.rows, cols=args.cols)
    rows = args.rows or saved.rows
    cols = args.cols or saved.cols
    baud = args.baud or tactile_config_baud(ports_config) or saved.baud

    sensor = FlexiTacSensor(
        port,
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


def teleop_command(args: argparse.Namespace) -> int:
    ports_config = load_ports_config(args.ports_config)
    cameras_arg = robot_cameras_arg(args)
    command = [
        *lerobot_command("teleoperate"),
        *base_robot_args(
            args,
            ports_config=ports_config,
            include_leader=True,
            include_tactile=not args.no_tactile,
        ),
        f"--fps={args.fps}",
        f"--display_data={str(args.display_data).lower()}",
    ]
    if cameras_arg:
        command.append(f"--robot.cameras={cameras_arg}")
    if args.max_relative_target is not None:
        command.append(f"--robot.max_relative_target={args.max_relative_target}")
    return run_or_print(command, dry_run=args.dry_run, env_overrides=lerobot_env(ports_config, args))


def record_command(args: argparse.Namespace) -> int:
    ports_config = load_ports_config(args.ports_config)
    cameras_arg = robot_cameras_arg(args)
    dataset_path = lerobot_dataset_path(args.repo_id, args.dataset_root)
    if args.overwrite:
        if args.resume:
            raise ValueError("--overwrite and --resume cannot be used together")
        remove_existing_dataset(args.repo_id, args.dataset_root, dry_run=args.dry_run)
    command = [
        *lerobot_command("record"),
        *base_robot_args(
            args,
            ports_config=ports_config,
            include_leader=True,
            include_tactile=not args.no_tactile,
        ),
        f"--display_data={str(args.display_data).lower()}",
        "--play_sounds=false",
        f"--dataset.repo_id={args.repo_id}",
        f"--dataset.root={dataset_path}",
        f"--dataset.num_episodes={args.episodes}",
        f"--dataset.episode_time_s={args.episode_time_s}",
        f"--dataset.reset_time_s={args.reset_time_s}",
        f"--dataset.single_task={args.task}",
        f"--dataset.fps={args.fps}",
        f"--dataset.push_to_hub={str(args.push_to_hub).lower()}",
        f"--dataset.streaming_encoding={str(args.streaming_encoding).lower()}",
        f"--dataset.encoder_threads={args.encoder_threads}",
        f"--dataset.vcodec={args.vcodec}",
    ]
    if cameras_arg:
        command.append(f"--robot.cameras={cameras_arg}")
    if args.resume:
        command.append("--resume=true")
    return run_or_print(command, dry_run=args.dry_run, env_overrides=lerobot_env(ports_config, args))


def replay_live_command(args: argparse.Namespace) -> int:
    ports_config = load_ports_config(args.ports_config)
    command = replay_robot_command(args, ports_config)
    add_tactile_sensor_arg_from_config(command, args, ports_config)
    return run_or_print(command, dry_run=args.dry_run, env_overrides=lerobot_env(ports_config, args))


def replay_robot_command(args: argparse.Namespace, ports_config: dict[str, Any]) -> list[str]:
    follower_port = require_value(
        config_value(args.follower_port, ports_config, "follower", "port"),
        "follower port",
    )
    follower_id = config_value(args.follower_id, ports_config, "follower", "id", "follower")
    calib_dir = robot_calibration_dir(args.calibration_dir, ports_config)
    dataset_path = (
        lerobot_dataset_path(args.repo_id, args.dataset_root)
        if args.dataset_root
        else find_lerobot_dataset_path(args.repo_id)
    )
    command = [
        *lerobot_command("replay"),
        "--robot.type=so_tactile_follower",
        f"--robot.port={follower_port}",
        f"--robot.id={follower_id}",
        f"--robot.calibration_dir={calib_dir}",
        f"--dataset.repo_id={args.repo_id}",
        f"--dataset.root={dataset_path}",
        f"--dataset.episode={args.episode}",
    ]
    return command


def replay_recorded_command(args: argparse.Namespace) -> int:
    import cv2

    from lerobot.processor import make_default_robot_action_processor
    from lerobot.utils.import_utils import register_third_party_plugins
    from lerobot.utils.robot_utils import precise_sleep

    from so_tactile.lerobot_run import install_park_on_disconnect

    ports_config = load_ports_config(args.ports_config)
    follower_port = require_value(
        config_value(args.follower_port, ports_config, "follower", "port"),
        "follower port",
    )
    follower_id = config_value(args.follower_id, ports_config, "follower", "id", "follower")
    calib_dir = robot_calibration_dir(args.calibration_dir, ports_config)
    dataset_path, info, episode_row, data = load_recorded_episode(args)
    features = info.get("features", {})
    action_names = features.get("action", {}).get("names")
    if not action_names:
        raise ValueError(f"Dataset action names not found: {dataset_path / 'meta' / 'info.json'}")

    video_keys = [
        key for key, value in features.items()
        if isinstance(value, dict) and value.get("dtype") == "video"
    ]
    tactile_keys = [key for key in features if key.startswith("observation.tactile.")]
    video_key = args.video_key or (video_keys[0] if video_keys else None)
    tactile_key = args.tactile_key or (tactile_keys[0] if tactile_keys else None)
    fps = float(args.fps or info.get("fps") or 30)
    max_frames = min(len(data), args.frames) if args.frames else len(data)

    print(f"dataset: {dataset_path}")
    print(f"episode: {args.episode}")
    print(f"frames: {len(data)}")
    print(f"video: {video_key or 'none'}")
    print(f"tactile: {tactile_key or 'none'}")
    if args.dry_run:
        print(f"robot: so_tactile_follower port={follower_port} id={follower_id} calibration_dir={calib_dir}")
        print("current tactile sensor: disabled")
        return 0

    register_third_party_plugins()
    from lerobot.robots import SOTactileFollower, SOTactileFollowerConfig

    os.environ.update(lerobot_env(ports_config, args))
    install_park_on_disconnect()

    robot_action_processor = make_default_robot_action_processor()
    robot = SOTactileFollower(
        SOTactileFollowerConfig(
            port=follower_port,
            id=follower_id,
            calibration_dir=Path(calib_dir),
            tactile_sensors={},
        )
    )
    video_reader = open_episode_video_reader(dataset_path, episode_row, video_key, features, info) if video_key else None
    tactile_max = tactile_recorded_max(data, tactile_key) if tactile_key else 1.0

    robot.connect()
    try:
        for row_index in range(max_frames):
            started = time.perf_counter()
            action_array = data["action"].iloc[row_index]
            action = {
                name: float(action_array[action_index])
                for action_index, name in enumerate(action_names)
            }
            robot_obs = robot.get_observation()
            processed_action = robot_action_processor((action, robot_obs))
            robot.send_action(processed_action)

            display_index = min(max(row_index + args.media_offset_frames, 0), len(data) - 1)
            display_recorded_frame(
                args,
                data,
                display_index,
                video_reader,
                video_key,
                tactile_key,
                tactile_max,
            )

            key = cv2.waitKey(1) & 0xFF
            if key in {ord("q"), 27}:
                break
            dt_s = time.perf_counter() - started
            precise_sleep(max(1 / fps - dt_s, 0.0))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        robot.disconnect()
        if video_reader is not None:
            video_reader.close()
        cv2.destroyAllWindows()

    return 0


def load_recorded_episode(args: argparse.Namespace) -> tuple[Path, dict[str, Any], Any, Any]:
    import pandas as pd

    dataset_path = (
        lerobot_dataset_path(args.repo_id, args.dataset_root)
        if args.dataset_root
        else find_lerobot_dataset_path(args.repo_id)
    )
    info_path = dataset_path / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Dataset info not found: {info_path}")

    info = json.loads(info_path.read_text(encoding="utf-8"))
    episode_row = read_episode_row(dataset_path, args.episode)
    data_path = dataset_path / "data" / f"chunk-{int(episode_row['data/chunk_index']):03d}" / (
        f"file-{int(episode_row['data/file_index']):03d}.parquet"
    )
    data = pd.read_parquet(data_path)
    data = data[data["episode_index"] == args.episode].reset_index(drop=True)
    if data.empty:
        raise ValueError(f"No frames for episode {args.episode} in {data_path}")
    return dataset_path, info, episode_row, data


def open_episode_video_reader(
    dataset_path: Path,
    episode_row: Any,
    video_key: str,
    features: dict[str, Any],
    info: dict[str, Any],
) -> VideoReader | None:
    video_path = episode_video_path(dataset_path, episode_row, video_key)
    video_fps = video_feature_fps(features[video_key], info)
    from_timestamp = float(episode_row.get(f"videos/{video_key}/from_timestamp", 0.0))
    frame_offset = max(0, round(from_timestamp * video_fps))
    video_reader = open_video_reader(video_path, frame_offset)
    if video_reader is None:
        print(f"Failed to open video: {video_path}", file=sys.stderr)
    else:
        print(f"video: {video_key} ({video_path})")
    return video_reader


def display_recorded_frame(
    args: argparse.Namespace,
    data: Any,
    row_index: int,
    video_reader: VideoReader | None,
    video_key: str | None,
    tactile_key: str | None,
    tactile_max: float,
) -> None:
    import cv2

    if video_reader is not None and video_key is not None:
        image = video_reader.read(row_index)
        if image is not None:
            cv2.imshow(f"{args.repo_id} {video_key}", image)
    if tactile_key:
        heatmap = tactile_heatmap_image(data[tactile_key].iloc[row_index], tactile_max, args.cell_size)
        cv2.imshow(f"{args.repo_id} {tactile_key}", heatmap)


class VideoReader:
    def __init__(self, backend: Any, *, frame_offset: int = 0, uses_rgb: bool = False) -> None:
        self.backend = backend
        self.frame_offset = frame_offset
        self.uses_rgb = uses_rgb

    def read(self, row_index: int) -> Any:
        if hasattr(self.backend, "get_data"):
            try:
                image = self.backend.get_data(self.frame_offset + row_index)
            except (IndexError, RuntimeError, OSError):
                return None
            if self.uses_rgb:
                image = image[..., ::-1]
            return image

        import cv2

        self.backend.set(cv2.CAP_PROP_POS_FRAMES, self.frame_offset + row_index)
        ok, image = self.backend.read()
        return image if ok else None

    def close(self) -> None:
        if hasattr(self.backend, "close"):
            self.backend.close()
        elif hasattr(self.backend, "release"):
            self.backend.release()


def open_video_reader(video_path: Path, frame_offset: int) -> VideoReader | None:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_offset)
        return VideoReader(cap)
    cap.release()

    try:
        import imageio.v2 as imageio

        reader = imageio.get_reader(str(video_path))
        return VideoReader(reader, frame_offset=frame_offset, uses_rgb=True)
    except Exception:
        return None


def read_episode_row(dataset_path: Path, episode: int) -> Any:
    import pandas as pd

    episode_files = sorted((dataset_path / "meta" / "episodes").glob("chunk-*/file-*.parquet"))
    if not episode_files:
        raise FileNotFoundError(f"No episode metadata found under {dataset_path / 'meta' / 'episodes'}")
    episodes = pd.concat([pd.read_parquet(path) for path in episode_files], ignore_index=True)
    matches = episodes[episodes["episode_index"] == episode]
    if matches.empty:
        raise ValueError(f"Episode {episode} not found in {dataset_path}")
    return matches.iloc[0]


def episode_video_path(dataset_path: Path, episode_row: Any, video_key: str) -> Path:
    chunk_key = f"videos/{video_key}/chunk_index"
    file_key = f"videos/{video_key}/file_index"
    if chunk_key in episode_row and file_key in episode_row:
        return dataset_path / "videos" / video_key / f"chunk-{int(episode_row[chunk_key]):03d}" / (
            f"file-{int(episode_row[file_key]):03d}.mp4"
        )
    return dataset_path / "videos" / video_key / "chunk-000" / "file-000.mp4"


def video_feature_fps(feature: dict[str, Any], info: dict[str, Any]) -> float:
    video_info = feature.get("info", {})
    return float(video_info.get("video.fps") or info.get("fps") or 30)


def tactile_recorded_max(data: Any, tactile_key: str) -> float:
    values = [float(np.max(tactile_frame_array(value))) for value in data[tactile_key]]
    return max(max(values, default=1.0), 1.0)


def tactile_heatmap_image(value: Any, tactile_max: float, cell_size: int) -> Any:
    import cv2

    frame = tactile_frame_array(value)
    normalized = np.clip(frame / tactile_max, 0.0, 1.0)
    gray = (normalized * 255).astype(np.uint8)
    heatmap = cv2.applyColorMap(gray, cv2.COLORMAP_VIRIDIS)
    return cv2.resize(
        heatmap,
        (frame.shape[1] * cell_size, frame.shape[0] * cell_size),
        interpolation=cv2.INTER_NEAREST,
    )


def tactile_frame_array(value: Any) -> Any:
    frame = np.asarray(value)
    if frame.dtype == object:
        frame = np.vstack(frame)
    return np.asarray(frame, dtype=np.float32)


def dataset_path_command(args: argparse.Namespace) -> int:
    print(find_lerobot_dataset_path(args.repo_id))
    return 0


def dataset_info_command(args: argparse.Namespace) -> int:
    dataset_path = find_lerobot_dataset_path(args.repo_id)
    info_path = dataset_path / "meta" / "info.json"
    if not info_path.exists():
        print(f"Dataset info not found: {info_path}")
        return 1

    info = json.loads(info_path.read_text(encoding="utf-8"))
    features = info.get("features", {})
    tactile_keys = [key for key in features if key.startswith("observation.tactile.")]
    video_keys = [
        key for key, value in features.items()
        if isinstance(value, dict) and value.get("dtype") == "video"
    ]

    print(f"repo_id: {args.repo_id}")
    print(f"path: {dataset_path}")
    print(f"total_episodes: {info.get('total_episodes')}")
    print(f"total_frames: {info.get('total_frames')}")
    print(f"fps: {info.get('fps')}")
    print(f"features: {', '.join(features)}")
    print(f"tactile_keys: {', '.join(tactile_keys) or 'none'}")
    print(f"video_keys: {', '.join(video_keys) or 'none'}")
    return 0


def cameras_arg_command(args: argparse.Namespace) -> int:
    cameras_arg = lerobot_cameras_arg(load_cameras_config(args.cameras_config))
    if cameras_arg is None:
        print(f"No cameras configured: {args.cameras_config}")
        return 1
    print(cameras_arg)
    return 0


def cameras_check_command(args: argparse.Namespace) -> int:
    import cv2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cameras = load_cameras_config(args.cameras_config)
    if not cameras:
        print(f"No cameras configured: {args.cameras_config}")
        return 1

    failures = 0
    for camera in cameras:
        name = str(camera["name"])
        index_or_path = camera.get("index_or_path", camera.get("index"))
        backend = cv2_backend_code(camera.get("backend"))
        cap = cv2.VideoCapture(index_or_path, backend if backend is not None else cv2.CAP_ANY)
        if camera.get("fourcc") is not None:
            fourcc = str(camera["fourcc"])
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(camera.get("width", 640)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(camera.get("height", 480)))
        cap.set(cv2.CAP_PROP_FPS, int(camera.get("fps", 30)))
        ok, frame = cap.read()
        if not ok or frame is None:
            print(f"{name}: failed to read from camera {index_or_path}")
            failures += 1
            cap.release()
            continue

        image_path = output_dir / f"{name}.jpg"
        cv2.imwrite(str(image_path), frame)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"{name}: {width}x{height} @ {fps:.1f} fps, snapshot={image_path}")
        cap.release()

    return 1 if failures else 0


def add_common_tactile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rows", type=int, default=12)
    parser.add_argument("--cols", type=int, default=32)
    parser.add_argument("--baud", type=int)
    parser.add_argument("--threshold", type=float, default=25.0)
    parser.add_argument("--noise-scale", type=float, default=30.0)
    parser.add_argument("--baseline-path")


def add_replay_args(parser: argparse.ArgumentParser, *, include_tactile: bool = True) -> None:
    add_ports_config_arg(parser)
    parser.add_argument("--follower-port")
    parser.add_argument("--follower-id")
    parser.add_argument("--calibration-dir")
    if include_tactile:
        parser.add_argument("--tactile-port")
        parser.add_argument("--tactile-name")
        parser.add_argument("--tactile-baud-rate", type=int)
        parser.add_argument("--no-tactile", action="store_true")
        parser.add_argument("--no-heatmap", action="store_true")
        parser.add_argument("--heatmap-cell-size", type=int)
    parser.add_argument("--no-park-on-exit", action="store_false", dest="park_on_exit")
    parser.add_argument("--park-duration-s", type=float)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(park_on_exit=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="so-tactile")
    subparsers = parser.add_subparsers(dest="command")

    heatmap_parser = subparsers.add_parser("heatmap")
    add_ports_config_arg(heatmap_parser)
    heatmap_parser.add_argument("--port")
    heatmap_parser.add_argument("--rows", type=int, default=12)
    heatmap_parser.add_argument("--cols", type=int, default=32)
    heatmap_parser.add_argument("--baud", type=int)
    heatmap_parser.add_argument("--cmap", default="viridis")
    heatmap_parser.set_defaults(func=heatmap_command)

    robot_parser = subparsers.add_parser("robot")
    robot_subparsers = robot_parser.add_subparsers(dest="robot_command")
    robot_calibrate_parser = robot_subparsers.add_parser("calibrate")
    robot_calibrate_parser.add_argument("role", choices=["leader", "follower"])
    add_ports_config_arg(robot_calibrate_parser)
    robot_calibrate_parser.add_argument("--port")
    robot_calibrate_parser.add_argument("--id")
    robot_calibrate_parser.add_argument("--calibration-dir")
    robot_calibrate_parser.add_argument("--dry-run", action="store_true")
    robot_calibrate_parser.set_defaults(func=robot_calibrate_command)

    tactile_parser = subparsers.add_parser("tactile")
    tactile_subparsers = tactile_parser.add_subparsers(dest="tactile_command")

    tactile_calibrate_parser = tactile_subparsers.add_parser("calibrate")
    add_ports_config_arg(tactile_calibrate_parser)
    tactile_calibrate_parser.add_argument("--port")
    add_common_tactile_args(tactile_calibrate_parser)
    tactile_calibrate_parser.add_argument("--frames", type=int, default=30)
    tactile_calibrate_parser.add_argument("--no-prompt", action="store_true")
    tactile_calibrate_parser.set_defaults(func=tactile_calibrate_command)

    tactile_status_parser = tactile_subparsers.add_parser("status")
    tactile_status_parser.add_argument("--baseline-path")
    tactile_status_parser.set_defaults(func=tactile_status_command)

    tactile_check_parser = tactile_subparsers.add_parser("check")
    add_ports_config_arg(tactile_check_parser)
    tactile_check_parser.add_argument("--port")
    tactile_check_parser.add_argument("--rows", type=int)
    tactile_check_parser.add_argument("--cols", type=int)
    tactile_check_parser.add_argument("--baud", type=int)
    tactile_check_parser.add_argument("--threshold", type=float, default=25.0)
    tactile_check_parser.add_argument("--noise-scale", type=float, default=30.0)
    tactile_check_parser.add_argument("--baseline-path")
    tactile_check_parser.add_argument("--frames", type=int, default=5)
    tactile_check_parser.set_defaults(func=tactile_check_command)

    teleop_parser = subparsers.add_parser("teleop")
    add_robot_port_args(teleop_parser)
    add_cameras_config_args(teleop_parser)
    teleop_parser.add_argument("--fps", type=int, default=60)
    teleop_parser.add_argument("--max-relative-target", type=float)
    display_group = teleop_parser.add_mutually_exclusive_group()
    display_group.add_argument("--display-data", action="store_true", dest="display_data")
    display_group.add_argument("--no-display-data", action="store_false", dest="display_data")
    teleop_parser.set_defaults(display_data=False)
    teleop_parser.set_defaults(func=teleop_command)

    record_parser = subparsers.add_parser("record")
    add_robot_port_args(record_parser)
    add_cameras_config_args(record_parser)
    record_parser.add_argument("--repo-id", required=True)
    record_parser.add_argument("--task", default="Pick up the object")
    record_parser.add_argument("--dataset-root")
    record_parser.add_argument("--episodes", type=int, default=2)
    record_parser.add_argument("--episode-time-s", type=int, default=30)
    record_parser.add_argument("--reset-time-s", type=int, default=15)
    record_parser.add_argument("--fps", type=int, default=30)
    record_parser.add_argument("--encoder-threads", type=int, default=2)
    record_parser.add_argument("--vcodec", default="h264_nvenc")
    record_parser.add_argument("--push-to-hub", action="store_true")
    record_parser.add_argument("--resume", action="store_true")
    record_parser.add_argument("--overwrite", action="store_true")
    record_parser.add_argument("--no-streaming-encoding", action="store_false", dest="streaming_encoding")
    display_group = record_parser.add_mutually_exclusive_group()
    display_group.add_argument("--display-data", action="store_true", dest="display_data")
    display_group.add_argument("--no-display-data", action="store_false", dest="display_data")
    record_parser.set_defaults(display_data=True)
    record_parser.set_defaults(streaming_encoding=True)
    record_parser.set_defaults(func=record_command)

    replay_live_parser = subparsers.add_parser("replay-live-tactile")
    add_replay_args(replay_live_parser)
    replay_live_parser.set_defaults(func=replay_live_command)

    replay_recorded_parser = subparsers.add_parser("replay-recorded")
    add_replay_args(replay_recorded_parser, include_tactile=False)
    replay_recorded_parser.add_argument("--video-key")
    replay_recorded_parser.add_argument("--tactile-key")
    replay_recorded_parser.add_argument("--fps", type=float)
    replay_recorded_parser.add_argument("--frames", type=int)
    replay_recorded_parser.add_argument("--cell-size", type=int, default=25)
    replay_recorded_parser.add_argument("--media-offset-frames", type=int, default=0)
    replay_recorded_parser.set_defaults(func=replay_recorded_command)

    dataset_path_parser = subparsers.add_parser("dataset-path")
    dataset_path_parser.add_argument("--repo-id", required=True)
    dataset_path_parser.set_defaults(func=dataset_path_command)

    dataset_info_parser = subparsers.add_parser("dataset-info")
    dataset_info_parser.add_argument("--repo-id", required=True)
    dataset_info_parser.set_defaults(func=dataset_info_command)

    cameras_parser = subparsers.add_parser("cameras")
    cameras_subparsers = cameras_parser.add_subparsers(dest="cameras_command")

    cameras_arg_parser = cameras_subparsers.add_parser("arg")
    cameras_arg_parser.add_argument("--cameras-config", default=str(DEFAULT_CAMERAS_CONFIG_PATH))
    cameras_arg_parser.set_defaults(func=cameras_arg_command)

    cameras_check_parser = cameras_subparsers.add_parser("check")
    cameras_check_parser.add_argument("--cameras-config", default=str(DEFAULT_CAMERAS_CONFIG_PATH))
    cameras_check_parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "outputs" / "camera_checks"),
    )
    cameras_check_parser.set_defaults(func=cameras_check_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
