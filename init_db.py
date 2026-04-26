import os
import sqlite3

from config import DB_PATH
from metrics import Metric


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # Table 1: sensors
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensors (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name TEXT UNIQUE NOT NULL,
            friendly_name TEXT,
            location     TEXT
        )
    ''')

    # Table 2: metric_types — normalised lookup for EAV metric names.
    # Populated automatically by WeatherWriter._get_or_create_metric on first write.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metric_types (
            id   INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # Table 3: readings — time-series data.
    # WITHOUT ROWID: the composite PRIMARY KEY (sensor_id, metric_type_id, timestamp)
    # is the clustered B-tree, eliminating the hidden rowid B-tree entirely.
    # Timestamps are Unix epoch integers (4 bytes vs 19-byte ISO strings).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            sensor_id      INTEGER NOT NULL,
            metric_type_id INTEGER NOT NULL,
            timestamp      INTEGER NOT NULL,
            value          REAL    NOT NULL,
            PRIMARY KEY (sensor_id, metric_type_id, timestamp),
            FOREIGN KEY (sensor_id)      REFERENCES sensors(id),
            FOREIGN KEY (metric_type_id) REFERENCES metric_types(id)
        ) WITHOUT ROWID
    ''')

    # Table 4: sensor_health — latest battery state per sensor (upsert pattern).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_health (
            sensor_id    INTEGER PRIMARY KEY,
            battery_ok   INTEGER,
            last_updated INTEGER,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')

    # idx_sensor_metric_time is intentionally absent: the WITHOUT ROWID PRIMARY KEY
    # (sensor_id, metric_type_id, timestamp) acts as the clustered index for all
    # per-sensor queries.
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_metric_time
        ON readings (metric_type_id, timestamp DESC)
    ''')

    # Pre-seed metric_types from the Metric enum so the API startup cache is always
    # populated even before the first hardware reading is written.
    # DEW_POINT_C is excluded — it is calculated at the API layer, never stored.
    stored = [(m.value,) for m in Metric if m is not Metric.DEW_POINT_C]
    cursor.executemany("INSERT OR IGNORE INTO metric_types (name) VALUES (?)", stored)

    conn.commit()
    conn.close()
    print(f"Database initialised at {DB_PATH}.")


if __name__ == "__main__":
    init_db()
