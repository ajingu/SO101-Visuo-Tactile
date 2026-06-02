# SO Tactile

Minimal `uv` project for FlexiTac-based tactile sensing experiments with SO-ARM.

## Setup

Set up the FlexiTac hardware, Arduino CLI, and firmware prerequisites by
following the LeFlexiTac/PyFlexiTac docs linked below.

```powershell
uv sync
```

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

## Development

```powershell
uv run pre-commit install
uv run pre-commit run --all-files
```

## Links

- [LeFlexiTac docs](https://tna001-ai.github.io/LeFlexiTac/docs.html)
- [WT-MM/PyFlexiTac](https://github.com/WT-MM/PyFlexiTac)
- [Arduino CLI installation](https://arduino.github.io/arduino-cli/latest/installation/)
