# SO Tactile

Minimal `uv` project for FlexiTac-based tactile sensing experiments with SO-ARM.

## Setup

Set up the FlexiTac hardware, Arduino CLI, and firmware prerequisites by
following the LeFlexiTac/PyFlexiTac docs linked below.

```powershell
uv sync
```

## Runbook

### 1. Find Port

```powershell
uv run flexitac-find-port
```

Replace `COM5` below with the detected port.

### 2. Flash Firmware

Only needed when the board has not been flashed with the FlexiTac firmware yet.

For my current Nano V3.0-compatible ATMEGA328PB board, the working target was:

```powershell
uv run flexitac-flash --port COM5 --fqbn arduino:avr:nano:cpu=atmega328old
```

For other boards or FQBNs, check the LeFlexiTac/PyFlexiTac docs and Arduino CLI
docs linked above.

### 3. Stream

```powershell
uv run flexitac-stream --port COM5
```

`flexitac-stream` reads frames from the sensor, calibrates a baseline, and prints
live stats such as `fps`, `raw_max`, and `norm_max`.

Use a short smoke test with:

```powershell
uv run flexitac-stream --port COM5 --frames 5
```

### 4. Heatmap

```powershell
uv run so-tactile-heatmap --port COM5
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
