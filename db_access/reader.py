import sqlite3
import time


def get_latest_global_metric(conn: sqlite3.Connection, metric_type_id: int):
    """Fetches the most recent reading for a metric, regardless of which sensor provided it."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sensor_id, value, timestamp FROM readings
        WHERE metric_type_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (metric_type_id,))
    return cursor.fetchone()


def get_sensor_elevation(conn: sqlite3.Connection, sensor_id: int):
    """Returns elevation_m for the given sensor, or None if not configured."""
    row = conn.execute(
        "SELECT elevation_m FROM sensors WHERE id = ?", (sensor_id,)
    ).fetchone()
    return row["elevation_m"] if row else None


def get_export_readings(conn: sqlite3.Connection, ts_from: int, ts_to: int):
    """Returns a cursor of denormalized readings for CSV export.
    Caller is responsible for iterating and closing the connection."""
    return conn.execute("""
        SELECT
            r.timestamp,
            s.id           AS sensor_id,
            s.machine_name AS sensor_name,
            s.location,
            s.latitude,
            s.longitude,
            s.elevation_m,
            s.timezone,
            mt.name        AS metric,
            r.value
        FROM readings r
        JOIN sensors      s  ON s.id  = r.sensor_id
        JOIN metric_types mt ON mt.id = r.metric_type_id
        WHERE r.timestamp >= ? AND r.timestamp <= ?
        ORDER BY r.timestamp ASC, s.id ASC, mt.name ASC
    """, (ts_from, ts_to))


def get_pivoted_trend(conn: sqlite3.Connection, metrics: dict, hours_back: int = 72, sensor_id: int = None):
    """Fetches a time-series trend for one or more metrics, pivoted into one row per timestamp.
    metrics must be a dict of {metric_name: metric_type_id}.
    sensor_id=None queries globally; pass an int to scope to one sensor."""
    cursor = conn.cursor()
    cutoff = int(time.time()) - hours_back * 3600

    # Integer IDs embedded directly — no injection risk. Names used only as column aliases.
    cases = ", ".join(
        f"AVG(CASE WHEN metric_type_id = {mid} THEN value END) AS {getattr(name, 'value', name)}"
        for name, mid in metrics.items()
    )
    id_list = ", ".join(str(mid) for mid in metrics.values())
    sensor_filter = "sensor_id = ? AND " if sensor_id is not None else ""
    params = ((sensor_id,) if sensor_id is not None else ()) + (cutoff,)

    cursor.execute(f"""
        SELECT timestamp, {cases}
        FROM readings
        WHERE {sensor_filter}metric_type_id IN ({id_list})
        AND timestamp >= ?
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, params)
    return cursor.fetchall()


def get_global_max_wind_gust(conn: sqlite3.Connection, metric_type_id: int):
    cursor = conn.cursor()
    cutoff = int(time.time()) - 3600
    cursor.execute("""
        SELECT MAX(value) as max_gust
        FROM readings
        WHERE metric_type_id = ?
        AND timestamp >= ?
    """, (metric_type_id, cutoff))
    row = cursor.fetchone()
    return round(row["max_gust"], 1) if row and row["max_gust"] is not None else None


def get_all_sensors(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("SELECT id, machine_name, friendly_name, location FROM sensors")
    return cursor.fetchall()


def get_latest_sensor_readings(conn: sqlite3.Connection, sensor_id: int):
    """Returns all metrics at the sensor's most recent timestamp.
    JOINs metric_types so callers receive metric_type as a name string, not an ID."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT mt.name AS metric_type, r.value, r.timestamp
        FROM readings r
        JOIN metric_types mt ON mt.id = r.metric_type_id
        WHERE r.sensor_id = ?
        AND r.timestamp = (
            SELECT MAX(timestamp) FROM readings WHERE sensor_id = ?
        )
    """, (sensor_id, sensor_id))
    return cursor.fetchall()


def get_24h_extremes(conn: sqlite3.Connection, sensor_id: int, metric_type_id: int):
    cursor = conn.cursor()
    cutoff = int(time.time()) - 86400
    cursor.execute("""
        SELECT MAX(value) as high, MIN(value) as low FROM readings
        WHERE sensor_id = ?
        AND metric_type_id = ?
        AND timestamp >= ?
    """, (sensor_id, metric_type_id, cutoff))
    return cursor.fetchone()


def get_latest_single_metric(conn: sqlite3.Connection, sensor_id: int, metric_type_id: int):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT value, timestamp FROM readings
        WHERE sensor_id = ?
        AND metric_type_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (sensor_id, metric_type_id))
    return cursor.fetchone()


def get_sensor_health(conn: sqlite3.Connection, sensor_id: int):
    """Fetches the latest battery health status for a specific sensor."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT battery_ok FROM sensor_health WHERE sensor_id = ?
    """, (sensor_id,))
    return cursor.fetchone()


def get_rf_trend_data(conn: sqlite3.Connection, sensor_id: int, rssi_id: int, noise_id: int, snr_id: int):
    """Calculates the current 3-hour average and the previous 3-hour baseline for RF metrics.
    JOINs metric_types so the result dict is keyed by name string, not ID."""
    cursor = conn.cursor()
    now = int(time.time())
    cutoff_3h = now - 10800
    cutoff_6h = now - 21600

    cursor.execute("""
        SELECT
            mt.name AS metric_type,
            AVG(CASE WHEN r.timestamp >= ? THEN r.value END) AS current_avg,
            AVG(CASE WHEN r.timestamp < ? AND r.timestamp >= ? THEN r.value END) AS past_avg
        FROM readings r
        JOIN metric_types mt ON mt.id = r.metric_type_id
        WHERE r.sensor_id = ?
        AND r.metric_type_id IN (?, ?, ?)
        AND r.timestamp >= ?
        GROUP BY r.metric_type_id
    """, (cutoff_3h, cutoff_3h, cutoff_6h, sensor_id, rssi_id, noise_id, snr_id, cutoff_6h))

    results = {}
    for row in cursor.fetchall():
        results[row["metric_type"]] = {
            "current": row["current_avg"],
            "past":    row["past_avg"],
        }
    return results


def get_recent_wind_vectors(conn: sqlite3.Connection, wind_speed_id: int, wind_dir_id: int, minutes_back: int = 15):
    """Fetches paired wind speed and direction readings from the same time bucket."""
    cursor = conn.cursor()
    cutoff = int(time.time()) - minutes_back * 60

    cursor.execute("""
        SELECT s.timestamp, s.value AS speed, d.value AS direction
        FROM readings s
        JOIN readings d ON s.sensor_id = d.sensor_id AND s.timestamp = d.timestamp
        WHERE s.metric_type_id = ?
        AND d.metric_type_id = ?
        AND s.timestamp >= ?
        ORDER BY s.timestamp DESC
    """, (wind_speed_id, wind_dir_id, cutoff))
    return cursor.fetchall()


def get_global_rain_total(conn: sqlite3.Connection, metric_type_id: int, hours_back: int = 24):
    """Calculates the cumulative sum of rain deltas over a time period."""
    cursor = conn.cursor()
    cutoff = int(time.time()) - hours_back * 3600

    cursor.execute("""
        SELECT SUM(value) as total_rain
        FROM readings
        WHERE metric_type_id = ?
        AND timestamp >= ?
    """, (metric_type_id, cutoff))

    row = cursor.fetchone()
    return round(row["total_rain"], 2) if row and row["total_rain"] is not None else 0.0
