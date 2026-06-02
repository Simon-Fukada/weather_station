import os
import sqlite3

from config import DB_PATH


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # Table 1: sensors
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensors (
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

    # Table 2: metric_types — normalised lookup for EAV metric names.
    # The DB is the single source of truth for all metric definitions.
    # constant_name is the Python identifier used to build the dynamic Metric enum at startup.
    # is_stored=0 marks metrics computed at the API layer (e.g. dew point) that are never written to readings.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metric_types (
            id            INTEGER PRIMARY KEY,
            name          TEXT UNIQUE NOT NULL,
            constant_name TEXT UNIQUE NOT NULL,
            is_stored     INTEGER NOT NULL DEFAULT 1
        )
    ''')

    # Table 3: readings — time-series data.
    # WITHOUT ROWID: a standard SQLite table maintains two B-trees — one for the row data
    # (keyed by a hidden rowid) and one for the PK index. WITHOUT ROWID collapses these
    # into a single B-tree keyed directly by (sensor_id, metric_type_id, timestamp).
    # Every query is a range scan on this composite key, so reads walk the clustered index
    # with no secondary lookup — more compact storage and faster for this access pattern.
    # Timestamps stored as Unix epoch integers rather than ISO strings: 4 bytes vs 19,
    # saving storage on every row and enabling fast integer arithmetic for time ranges.
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

    # Table 5: rtl_field_map — maps RTL-433 JSON field names to canonical metric_types.
    # Multiple RTL-433 fields can map to the same metric (e.g. temperature_C and temperature_F
    # both map to temperature_c; the latter applies a unit conversion via CONVERSION_REGISTRY).
    # conversion_func names a callable in weather_math.CONVERSION_REGISTRY, or NULL for no conversion.
    # To support a new RTL-433 sensor field: insert a row here, re-run init_db.py, restart sdr_reader.py.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rtl_field_map (
            id              INTEGER PRIMARY KEY,
            rtl_field       TEXT UNIQUE NOT NULL,
            metric_type_id  INTEGER NOT NULL REFERENCES metric_types(id),
            conversion_func TEXT
        )
    ''')

    # idx_sensor_metric_time is intentionally absent: the WITHOUT ROWID PRIMARY KEY
    # (sensor_id, metric_type_id, timestamp) acts as the clustered index for all
    # per-sensor queries.
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_metric_time
        ON readings (metric_type_id, timestamp DESC)
    ''')

    # Seed metric_types. To add a new metric: insert a row here, re-run init_db.py,
    # add any required processing code, then restart the API and relevant hardware scripts.
    cursor.executemany(
        "INSERT OR IGNORE INTO metric_types (name, constant_name, is_stored) VALUES (?, ?, ?)",
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

    # Seed rtl_field_map. The metric name in each tuple is resolved to its integer ID via
    # subselect — seed data stays human-readable while the stored FK is always the integer PK.
    # To support a new RTL-433 field: insert a row here and re-run init_db.py — no code changes needed.
    cursor.executemany(
        """INSERT OR IGNORE INTO rtl_field_map (rtl_field, metric_type_id, conversion_func)
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

    conn.commit()
    conn.close()
    print(f"Database initialised at {DB_PATH}.")


if __name__ == "__main__":
    init_db()
