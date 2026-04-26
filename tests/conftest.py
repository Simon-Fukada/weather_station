import pytest
import sqlite3
import time

from metrics import Metric


@pytest.fixture
def db_connection():
    """
    Fresh in-memory SQLite database matching the production schema.
    Uses epoch integer timestamps and metric_type_id FKs throughout.
    Seeds one sensor, all metric_types, one temperature reading 2 hours ago.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE sensors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name  TEXT UNIQUE NOT NULL,
            friendly_name TEXT,
            location      TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE metric_types (
            id   INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE readings (
            sensor_id      INTEGER NOT NULL,
            metric_type_id INTEGER NOT NULL,
            timestamp      INTEGER NOT NULL,
            value          REAL    NOT NULL,
            PRIMARY KEY (sensor_id, metric_type_id, timestamp),
            FOREIGN KEY (sensor_id)      REFERENCES sensors(id),
            FOREIGN KEY (metric_type_id) REFERENCES metric_types(id)
        ) WITHOUT ROWID
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_metric_time
        ON readings (metric_type_id, timestamp DESC)
    ''')
    cursor.execute('''
        CREATE TABLE sensor_health (
            sensor_id    INTEGER PRIMARY KEY,
            battery_ok   INTEGER,
            last_updated INTEGER,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')

    # Seed all metric_types from the Metric enum (mirrors init_db.py)
    stored = [(m.value,) for m in Metric if m is not Metric.DEW_POINT_C]
    cursor.executemany("INSERT OR IGNORE INTO metric_types (name) VALUES (?)", stored)

    cursor.execute("""
        INSERT INTO sensors (id, machine_name, friendly_name, location)
        VALUES (1, 'rtl_433_outdoor', 'Outdoor Fence', 'Backyard')
    """)

    temp_id = cursor.execute(
        "SELECT id FROM metric_types WHERE name = ?", (Metric.TEMPERATURE_C,)
    ).fetchone()[0]

    two_hours_ago = int(time.time()) - 7200
    cursor.execute(
        "INSERT INTO readings (sensor_id, metric_type_id, timestamp, value) VALUES (1, ?, ?, -15.5)",
        (temp_id, two_hours_ago),
    )
    cursor.execute(
        "INSERT INTO sensor_health (sensor_id, battery_ok, last_updated) VALUES (1, 1, ?)",
        (two_hours_ago,),
    )

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def metric_ids(db_connection):
    """Returns a {metric_name: id} dict for use in reader and writer tests."""
    rows = db_connection.execute("SELECT id, name FROM metric_types").fetchall()
    return {row["name"]: row["id"] for row in rows}
