# CLAUDE.md

This file provides guidance to LLMs when working with code in this repository.

## What this is

A Home Assistant custom component (HACS) that integrates with Bestway cloud APIs to control devices like Lay-Z-Spa hot tubs and Flowclear pool filters. It supports two distinct hardware generations with different backends.

## Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run all tests:

```bash
pytest -qq --timeout=10 --durations=10 -n auto --cov custom_components.bestway -o console_output_style=count -p no:sugar tests
```

Run a single test file:

```bash
pytest tests/test_aws_iot_api.py
```

Type check:

```bash
mypy custom_components/
```

Lint and auto-fix with ruff (version is pinned in `.pre-commit-config.yaml`, not `requirements.txt`, so always run it via `pre-commit` rather than a separately-installed `ruff` binary):

```bash
pre-commit run ruff-check --all-files
pre-commit run ruff-format --all-files
```

`ruff-check` runs with `--fix` (see `.pre-commit-config.yaml`), so it rewrites files in place where it can; rule ignores live in `pyproject.toml` under `[tool.ruff.lint]`.

Set up pre-commit hooks (required before contributing):

```bash
pre-commit install
```

Run pre-commit manually:

```bash
pre-commit run --all-files
```

## Architecture

### Two backends, one coordinator

The integration supports two completely separate cloud backends, selected at config flow time:

- **Gizwits** (`BACKEND_GIZWITS`) — V1 devices (up to ~2024). Uses `custom_components/bestway/bestway/` subpackage. Auth via username/password. WebSocket via `GizwitsWebSocket`.
- **AWS IoT** (`BACKEND_AWS_IOT`) — V2 devices (2025+, UltraFit pumps). Uses `custom_components/bestway/aws_iot/` subpackage. Auth via QR code scan (visitor ID). WebSocket via `AwsIotWebSocket`.

`__init__.py` branches on `entry.data["backend"]` to call `_async_setup_gizwits` or `_async_setup_aws_iot`. Both paths create a `BestwayUpdateCoordinator`, which accepts either `BestwayApi` or `AwsIotApi` — these share the same interface so entities are backend-agnostic.

### Update flow

The coordinator polls every 30 seconds by default. When a WebSocket connects successfully, polling drops to 5 minutes (`set_websocket_active()`). WebSocket updates call `handle_websocket_update()`, which merges the partial delta into `api._state_cache` and immediately pushes via `async_set_updated_data()`.

### State cache pattern

Both API classes maintain `_state_cache: dict[str, BestwayDeviceStatus]`. After sending a control command (e.g. `airjet_spa_set_power`), the API immediately updates the cache with the new value and a fresh timestamp. On the next poll, if the API response timestamp is older than the local cache, the poll result is discarded. This works around the Gizwits API's latency in reflecting POSTed changes.

### Entity structure

All entities extend `BestwayEntity` (in `entity.py`), which extends `CoordinatorEntity`. It exposes:

- `self.status` → `BestwayDeviceStatus | None` (current attribute snapshot)
- `self.bestway_device` → `BestwayDevice | None` (device metadata)
- `available` returns `True` as long as coordinator has data and the device is known — the `is_online` flag from the API is explicitly ignored as unreliable.

Platform files (`switch.py`, `climate.py`, `sensor.py`, etc.) each define entities and an `async_setup_entry` that iterates `coordinator.api.devices` to create per-device entities.

### Linting

Pre-commit runs: `ruff` (lint + format), `mypy`, `codespell`, `yamllint`, `prettier`, `actionlint`. Ruff replaces black/flake8/isort. mypy is strict for `custom_components/` but relaxed for `tests/`.
