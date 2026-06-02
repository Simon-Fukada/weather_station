import pytest
import sqlite3
import time


@pytest.fixture
def db_connection():
    """
    Fresh in-memory SQLite database matching the production schema.
    Uses epoch integer timestamps and metric_type_id FKs throughout.
    Seeds one sensor, all metric_types, rtl_field_map, and one temperature reading 2 hours ago.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE sensors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name  TEXT UNIQUE NOT NULL,
            friendly_name TEXT,
            location      TEXT,
            latitude      REAL,
            longitude     REAL,
            elevation_m   REAL,
            timezone      TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE metric_types (
            id            INTEGER PRIMARY KEY,
            name          TEXT UNIQUE NOT NULL,
            constant_name TEXT UNIQUE NOT NULL,
            is_stored     INTEGER NOT NULL DEFAULT 1
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
    cursor.execute('''
        CREATE TABLE rtl_field_map (
            id              INTEGER PRIMARY KEY,
            rtl_field       TEXT UNIQUE NOT NULL,
            metric_type_id  INTEGER NOT NULL REFERENCES metric_types(id),
            conversion_func TEXT
        )
    ''')

    cursor.executemany(
        "INSERT INTO metric_types (name, constant_name, is_stored) VALUES (?, ?, ?)",
        [
            ("temperature_c",         "TEMPERATURE_C", 1),
            ("pressure_hpa",          "PRESSURE_HPA",  1),
            ("relative_humidity_pct", "HUMIDITY_PCT",  1),
            ("dew_point_c",           "DEW_POINT_C",   0),
            ("wind_speed_kmh",        "WIND_KMH",      1),
            ("wind_dir_deg",          "WIND_DIR_DEG",  1),
            ("wind_gust_kmh",         "WIND_GUST_KMH", 1),
            ("rain_mm",               "RAIN_MM",       1),
            ("rssi_dbm",              "RSSI_DBM",      1),
            ("snr_db",                "SNR_DB",        1),
            ("noise_dbm",             "NOISE_DBM",     1),
        ]
    )

    cursor.executemany(
        """INSERT INTO rtl_field_map (rtl_field, metric_type_id, conversion_func)
           VALUES (?, (SELECT id FROM metric_types WHERE name = ?), ?)""",
        [
            ("temperature_C",  "temperature_c",         None),
            ("temperature_F",  "temperature_c",         "convert_f_to_c"),
            ("humidity",       "relative_humidity_pct", None),
            ("wind_avg_km_h",  "wind_speed_kmh",        None),
            ("wind_avg_mi_h",  "wind_speed_kmh",        "convert_mph_to_kmh"),
            ("wind_max_km_h",  "wind_gust_kmh",         None),
            ("wind_max_mi_h",  "wind_gust_kmh",         "convert_mph_to_kmh"),
            ("rain_mm",        "rain_mm",               None),
            ("rain_in",        "rain_mm",               "convert_inches_to_mm"),
            ("rssi",           "rssi_dbm",              None),
            ("snr",            "snr_db",                None),
            ("noise",          "noise_dbm",             None),
        ]
    )

    cursor.execute("""
        INSERT INTO sensors (id, machine_name, friendly_name, location)
        VALUES (1, 'rtl_433_outdoor', 'Outdoor Fence', 'Backyard')
    """)

    temp_id = cursor.execute(
        "SELECT id FROM metric_types WHERE name = ?", ("temperature_c",)
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
