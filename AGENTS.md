# CLAUDE.md

This file provides guidance to LLMs when working with code in this repository.

## What this is

A Home Assistant custom component (HACS) that integrates with Bestway cloud APIs to control devices like Lay-Z-Spa hot tubs and Flowclear pool filters. It supports two distinct hardware generations with different backends.

## Commands

Install dependencies:

```bash
uv sync
```

Run all tests:

```bash
uv run pytest -qq --timeout=10 --durations=10 -n auto --cov custom_components.bestway -o console_output_style=count -p no:sugar tests
```

Run a single test file:

```bash
uv run pytest tests/test_aws_iot_api.py
```

Type check:

```bash
uv run mypy custom_components/
```

Lint and auto-fix with ruff (version is pinned in `.pre-commit-config.yaml`, not `pyproject.toml`, so always run it via `pre-commit` rather than a separately-installed `ruff` binary):

```bash
uv run pre-commit run ruff-check --all-files
uv run pre-commit run ruff-format --all-files
```

`ruff-check` runs with `--fix` (see `.pre-commit-config.yaml`), so it rewrites files in place where it can; rule ignores live in `pyproject.toml` under `[tool.ruff.lint]`.

Set up pre-commit hooks (required before contributing):

```bash
uv run pre-commit install
```

Run pre-commit manually:

```bash
uv run pre-commit run --all-files
```

## Architecture

### Multiple backends, one coordinator

The integration supports three completely separate cloud backends, selected at config flow time:

- **Gizwits** (`BACKEND_GIZWITS`) — V1 devices (up to ~2024). Uses `custom_components/bestway/bestway/` subpackage. Auth via username/password. WebSocket via `GizwitsWebSocket`.
- **AWS IoT** (`BACKEND_AWS_IOT`) — V2 devices (2025+). Uses `custom_components/bestway/aws_iot/` subpackage. Auth via QR code scan (visitor ID). WebSocket via `AwsIotWebSocket`. Note: "UltraFit" is a pump name Bestway uses on both V1 and V2 hardware, so it does not imply this backend — see `docs/supported-devices.md`.
- **SmartSpa** (`BACKEND_SMARTSPA`) — post-July-2026 Bestway Connect app. Uses `custom_components/bestway/smartspa/` subpackage. Auth via account/password. No WebSocket.

`__init__.py` branches on `entry.data["backend"]` to call `_async_setup_gizwits`, `_async_setup_aws_iot` or `_async_setup_smartspa`. Every path creates a `BestwayUpdateCoordinator`, which accepts any `BackendApi` (`backend.py`) — the structural `Protocol` all three API classes satisfy, so entities are backend-agnostic. Add a fourth backend by implementing that `Protocol`, not by widening a union.

### Update flow

The coordinator polls every 30 seconds by default. When a WebSocket connects successfully, polling drops to 5 minutes (`set_websocket_active()`). WebSocket updates call `handle_websocket_update()`, which merges the partial delta into `api._state_cache` and immediately pushes via `async_set_updated_data()`.

### State cache pattern

Each API class maintains `_state_cache: dict[str, BestwayDeviceStatus]`. After sending a control command (e.g. `airjet_spa_set_power`), the API immediately updates the cache with the new value and a fresh timestamp. On the next poll, if the API response timestamp is older than the local cache, the poll result is discarded. This works around the Gizwits API's latency in reflecting POSTed changes.

### Entity structure

All entities extend `BestwayEntity` (in `entity.py`), which extends `CoordinatorEntity`. It exposes:

- `self.status` → `BestwayDeviceStatus | None` (current attribute snapshot)
- `self.bestway_device` → `BestwayDevice | None` (device metadata)
- `available` returns `True` as long as coordinator has data and the device is known — the `is_online` flag from the API is explicitly ignored as unreliable.

Platform files (`switch.py`, `climate.py`, `sensor.py`, etc.) each define entities and an `async_setup_entry` that iterates `coordinator.api.devices` to create per-device entities.

### Linting

Pre-commit runs: `ruff` (lint + format), `mypy`, `codespell`, `yamllint`, `prettier`, `actionlint`. Ruff replaces black/flake8/isort. mypy is strict for `custom_components/` but relaxed for `tests/`.

### Comments

Don't write comments that just restate what an IDE derives on demand — lists of a type's implementers or subclasses, a function's callers, "used by X/Y/Z", "see also <module>". They rot silently when code moves. Comment the _why_ and any non-obvious contract, not the _where-used_.
