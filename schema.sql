-- SQLite Database Schema for Weather Station

-- Table 1: sensors
CREATE TABLE IF NOT EXISTS sensors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_name  TEXT UNIQUE NOT NULL,
    friendly_name TEXT,
    location      TEXT
);

-- Table 2: metric_types — normalised lookup for EAV metric names.
-- Populated automatically by WeatherWriter._get_or_create_metric on first write.
-- Adding a new metric type requires no schema change — it self-registers on first write.
CREATE TABLE IF NOT EXISTS metric_types (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

-- Table 3: readings — time-series data.
-- WITHOUT ROWID: the composite PRIMARY KEY (sensor_id, metric_type_id, timestamp)
-- is the clustered B-tree, eliminating the hidden rowid B-tree entirely.
-- Per-sensor queries (sensor_id + metric_type_id + timestamp range) use the PK directly.
-- Timestamps are Unix epoch integers: 4 bytes vs 19-byte ISO strings, faster arithmetic.
CREATE TABLE IF NOT EXISTS readings (
    sensor_id      INTEGER NOT NULL,
    metric_type_id INTEGER NOT NULL,
    timestamp      INTEGER NOT NULL,
    value          REAL    NOT NULL,
    PRIMARY KEY (sensor_id, metric_type_id, timestamp),
    FOREIGN KEY (sensor_id)      REFERENCES sensors(id),
    FOREIGN KEY (metric_type_id) REFERENCES metric_types(id)
) WITHOUT ROWID;

-- Table 4: sensor_health — latest battery state per sensor (upsert pattern).
CREATE TABLE IF NOT EXISTS sensor_health (
    sensor_id    INTEGER PRIMARY KEY,
    battery_ok   INTEGER,
    last_updated INTEGER,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id)
);

-- Covers global (no sensor_id) queries: get_latest_global_metric, get_global_max_wind_gust,
-- get_global_rain_total, get_recent_wind_vectors.
-- idx_sensor_metric_time is intentionally absent: the WITHOUT ROWID PRIMARY KEY
-- (sensor_id, metric_type_id, timestamp) serves as the clustered index for per-sensor queries.
CREATE INDEX IF NOT EXISTS idx_metric_time
ON readings (metric_type_id, timestamp DESC);
