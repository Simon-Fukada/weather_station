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
- `metric_type` is normalised to a `metric_type_id` integer FK into the `metric_types` lookup table. New metric types self-register on first write via `WeatherWriter._get_or_create_metric` — no manual migration needed.
- `timestamp` is stored as a Unix epoch integer (not ISO text) for compact storage and fast arithmetic.
- The table is `WITHOUT ROWID` with a composite `PRIMARY KEY (sensor_id, metric_type_id, timestamp)`. This makes the PK the clustered B-tree, eliminating a separate rowid index and enforcing uniqueness (one reading per sensor/metric/bucket).
- `idx_sensor_metric_time` is intentionally absent — the WITHOUT ROWID PK covers per-sensor queries. Only `idx_metric_time` on `(metric_type_id, timestamp DESC)` is needed for global (cross-sensor) queries.

`init_db.py` is the authoritative schema source; `schema.sql` mirrors it — keep them in sync.

Rain is stored as a **delta per bucket** (not a cumulative total). `SensorBuffer` maintains an odometer and writes only the increment each flush. Wind speed and direction are stored as two separate rows with the same timestamp and are reconstructed with a self-JOIN in `reader.get_recent_wind_vectors`.

**DB access layer — `db_access/`**

- `reader.py` — stateless functions, each accepts a `sqlite3.Connection`. Called by the API via FastAPI's `Depends(get_db)` pattern.
- `writer.py` — `WeatherWriter` class. Opens and holds a connection. Used directly by hardware scripts.

**API — `api/main.py`**

FastAPI app. Key endpoints:
- `GET /api/sensors` — list registered sensors
- `GET /api/readings/current/{sensor_id}` — latest readings + dew point, 24 h extremes, RF signal health trends
- `GET /api/fixed_sensors` — MSLP-corrected pressure, 72 h trend, wind vectors (live + 3 h history), rain total
- `GET /api/readings/history/{sensor_id}` — 72 h temperature + dew point series

Business logic lives in `main.py`: MSLP calculation, dew-point formula, `get_quantized_grid` (snaps raw rows into 5-min averaged buckets for charting), `process_wind_history` (O(N) bucketing of wind vectors into 15-min intervals). The static frontend is mounted at `/` by the same uvicorn process.

**Shared utilities**

- `config.py` — `DB_PATH` and `FRONTEND_PATH`, resolved relative to the project root.
- `metrics.py` — `Metric(str, Enum)` — canonical source of truth for all metric name strings used across hardware scripts, the DB access layer, and the API. Use this instead of bare string literals. Note: `Metric.DEW_POINT_C` is calculated at the API layer and never stored in `readings`.
- `weather_math.py` — pure functions: `calculate_vector_average` (true vector average from speed/direction tuples), plus unit-conversion helpers used by both the SDR dispatch table and the API.

**Backend tests**

pytest. `tests/conftest.py` provides a `db_connection` fixture that builds an in-memory SQLite database with a pre-seeded sensor and a reading from 2 hours ago. All tests run against this in-memory DB — there is no test data written to disk.

**Frontend tests**

Jest 30 + `jest-environment-jsdom`. `frontend/app.test.js` loads `app.js` via `eval` in a jsdom context with `fetch`, `Chart`, `canvas`, and `localStorage` all mocked. Tests cover pure helpers (`safeFallback`, `formatDateTime`, `calculateChartBounds`) and DOM-manipulation functions (`updateFixedSensorData`, `updateSelectedSensorData`). `node_modules` is already present — no install step needed. **Note:** 
