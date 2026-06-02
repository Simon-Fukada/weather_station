# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
## Project Context

- **Platform:** Runs on a Raspberry Pi. Avoid heavyweight dependencies
  (no pandas/numpy unless already present; prefer stdlib).
- **Frontend compatibility:** Must work on iOS 12 Safari (for repurposed
  iPad display). This means: no optional chaining (?.), no nullish
  coalescing (??), no ES2020+ features, no modern CSS like :has().
  Verify any new frontend code against iOS 12 compatibility before
  suggesting it.
- **Dynamic sensors:** The database is intentionally EAV-structured so
  new sensors can be added without migrations. Preserve this design —
  don't propose "simplifications" that hardcode specific sensor types.
- **Network-only access:** The dashboard is LAN-only. No auth needed,
  no HTTPS concerns, no external API exposure.
## Commands

```bash
# Activate the virtual environment first
source venv/bin/activate

# Install (editable, includes root-level modules weather_math.py and config.py)
# Note: metrics.py has been removed — metric configuration now lives in db_access/metrics.py
pip install -e .

# Run the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Initialise a fresh database
python init_db.py

# Hardware scripts (run from project root)
python hardware/bme280_reader.py   # runs once and exits; use cron for repeated execution
python hardware/sdr_reader.py      # long-running process; use systemd

# Backend tests (pytest, from project root)
pytest tests/
pytest tests/test_reader.py::test_get_all_sensors   # single test

# Frontend tests (Jest, from frontend/)
cd frontend && npm test
npx jest app.test.js --no-coverage   # skip coverage report
```

## Architecture

The system is intentionally decoupled so each layer can fail independently:

```
hardware/bme280_reader.py  ──┐
hardware/sdr_reader.py     ──┤──► data/weather_data.db ──► api/main.py ──► frontend/
```

**Data flow**

- Both hardware scripts snap timestamps to the nearest 5-minute bucket before writing, so all data aligns to a uniform grid.
- `sdr_reader.py` is a long-running process wrapping the `rtl_433` CLI. It uses an in-memory `SensorBuffer` to accumulate all packets that arrive within a bucket and flushes averaged/aggregated values once the bucket closes. Duplicate packets are suppressed via a `seen_packets` set.
- `bme280_reader.py` is a one-shot script (run once, exit). Cron re-invokes it every 5 minutes. It auto-registers its sensor via `WeatherWriter.get_or_create_sensor`.
- SDR sensors must be **manually pre-registered** in the `sensors` table. Packets from unknown IDs are silently dropped.

**Database — `data/weather_data.db`**

SQLite with WAL mode. Uses an EAV (Entity-Attribute-Value) schema: each row in `readings` stores a single metric (e.g. `temperature_c`, `wind_kmh`). This lets new sensors and metrics be added without schema changes.

Key design decisions in `readings`:
- `metric_type` is normalised to a `metric_type_id` integer FK into the `metric_types` lookup table. The `metric_types` table is the single source of truth for all metrics — seeded exclusively by `init_db.py`. To add a new metric, insert rows into `metric_types` (and `rtl_field_map` if it is an SDR field), re-run `init_db.py`, then restart the API and relevant hardware scripts.
- `metric_types` has three key columns: `name` (the canonical DB string, e.g. `temperature_c`), `constant_name` (the Python identifier used to build the `Metric` enum, e.g. `TEMPERATURE_C`), and `is_stored` (0 for computed-only metrics like dew point that are never written to `readings`).
- `rtl_field_map` maps RTL-433 JSON field names to `metric_types.name`, with an optional `conversion_func` name (resolved at startup via `getattr(weather_math, func_name)`). Multiple RTL-433 fields can map to the same metric (e.g. `temperature_C` and `temperature_F` both map to `temperature_c`).
- `timestamp` is stored as a Unix epoch integer (not ISO text) for compact storage and fast arithmetic.
- The table is `WITHOUT ROWID` with a composite `PRIMARY KEY (sensor_id, metric_type_id, timestamp)`. This makes the PK the clustered B-tree, eliminating a separate rowid index and enforcing uniqueness (one reading per sensor/metric/bucket).
- `idx_sensor_metric_time` is intentionally absent — the WITHOUT ROWID PK covers per-sensor queries. Only `idx_metric_time` on `(metric_type_id, timestamp DESC)` is needed for global (cross-sensor) queries.

`init_db.py` is the authoritative schema source.

> **Direct DB access:** When connecting via the `sqlite3` CLI, foreign key enforcement is off by default. Always run `PRAGMA foreign_keys = ON;` before making any changes, otherwise FK violations will silently succeed and leave the schema in an inconsistent state.

Rain is stored as a **delta per bucket** (not a cumulative total). `SensorBuffer` maintains an odometer and writes only the increment each flush. Wind speed and direction are stored as two separate rows with the same timestamp and are reconstructed with a self-JOIN in `reader.get_recent_wind_vectors`.

**DB access layer — `db_access/`**

- `reader.py` — stateless functions, each accepts a `sqlite3.Connection`. Called by the API via FastAPI's `Depends(get_db)` pattern.
- `writer.py` — `WeatherWriter` class. Opens and holds a connection. Used directly by hardware scripts. `_get_metric_id` resolves metric name strings to their integer IDs (cached per connection lifetime); raises `ValueError` for unregistered metrics — run `init_db.py` first.
- `metrics.py` — startup helpers: `build_metric_enum(conn)` builds a `Metric(str, Enum)` from the `metric_types` table (members have `.id` and `.is_stored` properties); `build_metric_dispatch(conn)` builds the RTL-433 field dispatch table from `rtl_field_map`.

**API — `api/main.py`**

FastAPI app. Key endpoints:
- `GET /api/sensors` — list registered sensors
- `GET /api/readings/current/{sensor_id}` — latest readings + dew point, 24 h extremes, RF signal health trends
- `GET /api/fixed_sensors` — MSLP-corrected pressure, 72 h trend, wind vectors (live + 3 h history), rain total
- `GET /api/readings/history/{sensor_id}` — 72 h temperature + dew point series

Business logic lives in `main.py`: MSLP calculation, dew-point formula, `get_quantized_grid` (snaps raw rows into 5-min averaged buckets for charting), `process_wind_history` (O(N) bucketing of wind vectors into 15-min intervals). The static frontend is mounted at `/` by the same uvicorn process.

**Shared utilities**

- `config.py` — `DB_PATH` and `FRONTEND_PATH`, resolved relative to the project root.
- `weather_math.py` — pure functions: `calculate_vector_average` (true vector average from speed/direction tuples), plus unit-conversion helpers (`convert_f_to_c`, `convert_mph_to_kmh`, `convert_inches_to_mm`) referenced by name in `rtl_field_map.conversion_func`.

**Backend tests**

pytest. `tests/conftest.py` provides a `db_connection` fixture that builds an in-memory SQLite database with a pre-seeded sensor and a reading from 2 hours ago. All tests run against this in-memory DB — there is no test data written to disk.

**Frontend tests**

Jest 30 + `jest-environment-jsdom`. `frontend/app.test.js` loads `app.js` via `eval` in a jsdom context with `fetch`, `Chart`, `canvas`, and `localStorage` all mocked. Tests cover pure helpers (`safeFallback`, `formatDateTime`, `calculateChartBounds`) and DOM-manipulation functions (`updateFixedSensorData`, `updateSelectedSensorData`). `node_modules` is already present — no install step needed. **Note:** 
