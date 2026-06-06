# SO-ARM x Tactile Sensing

SO-ARM visuo-tactile sensing with [FlexiTac](https://flexitac.github.io/).

This repository focuses on wiring the SO-ARM follower, USB camera, and FlexiTac
sensor into a simple capture and replay workflow. It records synchronized
visual and tactile observations, shows live heatmaps while operating the arm,
and lets you replay the saved visual/tactile data afterward for screenshots or
short demo clips. Model training is left as future work.

## Setup

Set up the FlexiTac hardware, Arduino CLI, and firmware prerequisites by
following the LeFlexiTac/PyFlexiTac docs linked below.

```powershell
uv sync
```

Create a local port config:

```powershell
New-Item -ItemType Directory -Force configs
Copy-Item configs/ports.example.json configs/ports.json
Copy-Item configs/cameras.example.json configs/cameras.json
```

Edit `configs/ports.json` for your leader, follower, and tactile sensor ports.
All hardware commands read this file by default. You can still override any port
with CLI flags such as `--leader-port`, `--follower-port`, or `--tactile-port`.
Set `tactile.enable_visualization` to `false` if you do not want the live
tactile heatmap window by default.
Adjust `tactile.heatmap_cell_size` if the heatmap window is too large or too
small.
Set `follower.park_on_exit` to `true` to return the follower arm to the park
pose before torque is disabled on exit. The default command behavior enables
this and uses `follower.park_duration_s` seconds.

Edit `configs/cameras.json` for your USB camera indices and names. `teleop` and
`record` read this file by default and pass it to LeRobot as `--robot.cameras`.
Use `--no-cameras` for a robot/tactile-only run.

## Runbook

### 1. Find Tactile Port

```powershell
uv run flexitac-find-port
```

Replace `COM5` below with the detected port.

### 2. Flash Tactile Firmware

Only needed when the board has not been flashed with the FlexiTac firmware yet.

For my current Nano V3.0-compatible ATMEGA328PB board, the working target was:

```powershell
uv run flexitac-flash --port COM5 --fqbn arduino:avr:nano:cpu=atmega328old
```

For other boards or FQBNs, check the LeFlexiTac/PyFlexiTac docs and Arduino CLI
docs linked above.

### 3. Calibrate Robot Arms

Find the leader and follower ports, then calibrate both arms:

```powershell
uv run so-tactile robot calibrate leader --port COM4
uv run so-tactile robot calibrate follower --port COM3
```

Robot calibration files are written to `calibration/robot/` by default.

### 4. Calibrate Tactile Baseline

Always run a no-contact baseline read before recording. The tactile map drifts
with temperature, so recalibrate if the sensor has been powered on for more than
30 minutes.

```powershell
uv run so-tactile tactile calibrate --port COM5
uv run so-tactile tactile status
```

Tactile baseline calibration is written to `calibration/tactile/baseline.json`
by default.

### 5. Check Tactile Readings

Use the saved baseline to read a few frames and print live stats:

```powershell
uv run so-tactile tactile check --port COM5
```

`so-tactile tactile check` prints stats such as `raw_max` and `norm_max`.

You can still run the upstream stream command when you want a one-off baseline
inside that process:

```powershell
uv run flexitac-stream --port COM5 --frames 5
```

### 6. Heatmap

```powershell
uv run so-tactile heatmap --port COM5
```

This local command wraps PyFlexiTac's heatmap command and sets the matplotlib
cache directory automatically for Windows.

### 7. Teleoperate

With `configs/ports.json` configured:

```powershell
uv run so-tactile teleop
```

With `configs/cameras.json` present, teleop attaches the configured cameras to
the robot. Pass `--display-data` only when you want LeRobot/Rerun display; by
default, teleop keeps LeRobot's joint-value table hidden.

To override ports at the command line:

```powershell
uv run so-tactile teleop --leader-port COM4 --follower-port COM3 --tactile-port COM5
```

### 8. Record A Visuo-Tactile Dataset

```powershell
uv run so-tactile record `
  --repo-id local/tactile-smoke `
  --task "Pick up the object" `
  --episodes 1 `
  --episode-time-s 10 `
  --reset-time-s 5
```

The command uses LeFlexiTac's `so_tactile_follower` robot and writes
`observation.tactile.primary` by passing `--robot.tactile_sensors` to
`lerobot-record`.

`teleop`, `record`, and `replay-live-tactile` show a live tactile heatmap from the same
LeRobot tactile stream by default. Add `--no-heatmap` to disable the preview for
one run, or `--heatmap-cell-size 20` to change its size for one run.

On exit, the follower arm moves back to the park pose before disconnecting. Use
`--park-duration-s 5` for a slower return, or `--no-park-on-exit` if you need
the old immediate disconnect behavior.

With `configs/cameras.json` present, `record` also saves camera video features.
Check the camera config before recording:

```powershell
uv run so-tactile cameras arg
uv run so-tactile cameras check
```

Inspect the dataset:

```powershell
uv run so-tactile dataset-path --repo-id local/tactile-smoke
uv run so-tactile dataset-info --repo-id local/tactile-smoke
```

Datasets are stored under `outputs/datasets/captures/`.

### 9. Replay With Saved Visual/Tactile Data

```powershell
uv run so-tactile replay-recorded --repo-id local/tactile-smoke --episode 0
```

`replay-recorded` drives the follower arm from the recorded episode and shows
the saved camera video and tactile heatmap from the dataset. The robot action,
image, and tactile frame are advanced in the same loop, so their frame indices
stay aligned.

`replay-recorded` does not connect the current tactile sensor or show the live
tactile stream. It only shows tactile values saved in the dataset.

Replay an episode on the follower with the live tactile stream:

```powershell
uv run so-tactile replay-live-tactile --repo-id local/tactile-smoke --episode 0
```

`replay-live-tactile` drives the follower arm and shows the current tactile stream from
the sensor. `replay-recorded` drives the follower arm and shows the visual and
tactile data saved in the dataset.

## Development

```powershell
uv run pre-commit install
uv run pre-commit run --all-files
```

## Links

- [LeFlexiTac docs](https://tna001-ai.github.io/LeFlexiTac/docs.html)
- [WT-MM/PyFlexiTac](https://github.com/WT-MM/PyFlexiTac)
- [Arduino CLI installation](https://arduino.github.io/arduino-cli/latest/installation/)
