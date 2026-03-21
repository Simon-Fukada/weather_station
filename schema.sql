-- SQLite Database Schema for Weather Station

-- Table 1: sensors
CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_name TEXT UNIQUE NOT NULL,
    friendly_name TEXT,
    location TEXT
);

-- Table 2: readings (Time-Series Data)
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sensor_id INTEGER NOT NULL,
    metric_type TEXT NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id)
);

-- Table 3: sensor_health (State Data / Upsert Pattern)
CREATE TABLE IF NOT EXISTS sensor_health (
    sensor_id INTEGER PRIMARY KEY,
    battery_ok INTEGER,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id)
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_sensor_metric_time 
ON readings (sensor_id, metric_type, timestamp DESC);