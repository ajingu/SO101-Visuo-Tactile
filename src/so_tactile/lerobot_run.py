"""Run LeRobot scripts with local tactile visualization defaults."""

from __future__ import annotations

import json
import logging
import os
import queue
import sys
import time
from typing import Any

DEFAULT_PARK_POSE = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -102.5,
    "elbow_flex": 94.0,
    "wrist_flex": 71.0,
    "wrist_roll": -1.0,
    "gripper": 1.2,
}


def _visualization_worker(frame_queue, window_name: str, shape: tuple[int, int]) -> None:
    import cv2

    cell_size = int(os.environ.get("SO_TACTILE_HEATMAP_CELL_SIZE", "25"))
    window_width = shape[1] * cell_size
    window_height = shape[0] * cell_size
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, window_width, window_height)
    while True:
        try:
            frame = frame_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        if frame is None:
            break
        cv2.imshow(window_name, frame)
        cv2.waitKey(1)
    cv2.destroyAllWindows()


def install_tactile_visualization_patch() -> None:
    from lerobot.sensors import tactile_sensor

    tactile_sensor._visualization_worker = _visualization_worker


def install_park_on_disconnect() -> None:
    if os.environ.get("SO101_PARK_ON_EXIT", "true").lower() != "true":
        return

    from lerobot.robots.so_follower.so_follower import SOFollower

    original_disconnect = SOFollower.disconnect

    def disconnect_with_park(self: SOFollower, *args: Any, **kwargs: Any) -> Any:
        if self.bus.is_connected:
            _park_follower(self)
        return original_disconnect(self, *args, **kwargs)

    SOFollower.disconnect = disconnect_with_park


def _park_follower(robot: Any) -> None:
    pose = _load_park_pose()
    duration_s = float(os.environ.get("SO101_PARK_DURATION_S", "3.0"))
    steps = max(1, int(duration_s * 20))

    try:
        present = robot.bus.sync_read("Present_Position")
    except Exception:
        logging.exception("Failed to read follower pose before parking.")
        return

    motors = [motor for motor in robot.bus.motors if motor in pose and motor in present]
    if not motors:
        return

    logging.info("Parking follower before disconnect.")
    for step in range(1, steps + 1):
        ratio = step / steps
        target = {
            motor: present[motor] + (float(pose[motor]) - present[motor]) * ratio
            for motor in motors
        }
        try:
            robot.bus.sync_write("Goal_Position", target)
        except Exception:
            logging.exception("Failed to send follower park pose.")
            return
        time.sleep(duration_s / steps)


def _load_park_pose() -> dict[str, float]:
    pose_text = os.environ.get("SO101_PARK_POSE")
    if not pose_text:
        return DEFAULT_PARK_POSE

    try:
        pose = json.loads(pose_text)
    except json.JSONDecodeError:
        logging.exception("Invalid SO101_PARK_POSE JSON; using default park pose.")
        return DEFAULT_PARK_POSE

    return {str(key): float(value) for key, value in pose.items()}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: python -m so_tactile.lerobot_run {teleoperate,record,replay} ...")
        return 2

    command = argv.pop(0)
    sys.argv = [f"lerobot-{command}", *argv]
    install_tactile_visualization_patch()
    install_park_on_disconnect()

    if command == "teleoperate":
        from lerobot.scripts.lerobot_teleoperate import main as run_main
    elif command == "record":
        from lerobot.scripts.lerobot_record import main as run_main
    elif command == "replay":
        from lerobot.scripts.lerobot_replay import main as run_main
    else:
        print(f"Unsupported LeRobot command: {command}", file=sys.stderr)
        return 2

    run_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
