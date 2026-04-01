import sqlite3

def get_latest_global_metric(conn: sqlite3.Connection, metric_type: str): 
    """Fetches the most recent reading for a specific metric, regardless of which sensor provided it."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT value, timestamp FROM readings 
        WHERE metric_type = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (metric_type,))
    return cursor.fetchone()

def get_global_historical_trend(conn: sqlite3.Connection, metric_type: str, hours_back: int = 72): 
    """Fetches a time-series trend for a specific metric across all sensors."""
    cursor = conn.cursor()
    time_modifier = f"-{hours_back} hours"
    cursor.execute("""
        SELECT timestamp, metric_type, value FROM readings
        WHERE metric_type = ?
        AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    """, (metric_type, time_modifier))
    return cursor.fetchall()

def get_global_sustained_wind(conn: sqlite3.Connection, metric_type: str): 
    cursor = conn.cursor()
    
    # The inner query now strictly bounds the search to the last 20 minutes
    # BEFORE taking the limit of 3.
    cursor.execute("""
        SELECT AVG(value) as sustained_wind 
        FROM (
            SELECT value FROM readings 
            WHERE metric_type = ? 
            AND timestamp >= datetime('now', '-20 minutes')
            ORDER BY timestamp DESC LIMIT 3
        )
    """, (metric_type,))
    
    row = cursor.fetchone()
    return round(row["sustained_wind"], 1) if row and row["sustained_wind"] is not None else None

def get_global_max_wind_gust(conn: sqlite3.Connection, metric_type: str): 
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MAX(value) as max_gust 
        FROM readings 
        WHERE metric_type = ? 
        AND timestamp >= datetime('now', '-1 hour')
    """, (metric_type,))
    row = cursor.fetchone()
    return round(row["max_gust"], 1) if row and row["max_gust"] is not None else None

def get_all_sensors(conn: sqlite3.Connection): ###
    cursor = conn.cursor()
    cursor.execute("SELECT id, machine_name, friendly_name, location FROM sensors")
    return cursor.fetchall()

def get_latest_sensor_readings(conn: sqlite3.Connection, sensor_id: int): 
    cursor = conn.cursor()
    cursor.execute("""
        SELECT metric_type, value, timestamp 
        FROM readings
        WHERE sensor_id = ? 
        AND timestamp = (
            SELECT MAX(timestamp) 
            FROM readings 
            WHERE sensor_id = ?
        )
    """, (sensor_id, sensor_id))
    return cursor.fetchall()

def get_24h_extremes(conn: sqlite3.Connection, sensor_id: int, metric_type: str): 
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MAX(value) as high, MIN(value) as low FROM readings
        WHERE sensor_id = ? 
        AND metric_type = ? 
        AND timestamp >= datetime('now', '-24 hours')
    """, (sensor_id, metric_type))
    return cursor.fetchone()

def get_latest_single_metric(conn: sqlite3.Connection, sensor_id: str, metric_type: str): 
    cursor = conn.cursor()
    cursor.execute("""
        SELECT value, timestamp FROM readings 
        WHERE sensor_id = ?
        AND metric_type = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (sensor_id, metric_type))
    return cursor.fetchone()

def get_multi_metric_history(conn: sqlite3.Connection, sensor_id: int, hours_back: int): 
    cursor = conn.cursor()
    time_modifier = f"-{hours_back} hours"
    cursor.execute("""
        SELECT timestamp, metric_type, value FROM readings
        WHERE sensor_id = ? AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    """, (sensor_id, time_modifier))
    return cursor.fetchall()

def get_sensor_health(conn: sqlite3.Connection, sensor_id: int): 
    """Fetches the latest battery health status for a specific sensor."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT battery_ok FROM sensor_health
        WHERE sensor_id = ?
    """, (sensor_id,))
    return cursor.fetchone()