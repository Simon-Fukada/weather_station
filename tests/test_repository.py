import pytest
import sqlite3
from datetime import datetime, timedelta, timezone
import repository

def test_get_all_sensors(db_connection):
    sensors = repository.get_all_sensors(db_connection)
    assert len(sensors) == 1
    assert sensors[0]["machine_name"] == "rtl_433_outdoor"
    assert sensors[0]["friendly_name"] == "Outdoor Fence"

def test_get_latest_sensor_readings(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    one_min_ago = (now - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    # Latest reading (multiple metrics at same time)
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.5, ?)", (now_str,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity_pct', 60.2, ?)", (now_str,))
    
    # Boundary: Inject reading 1 minute before the latest (should be filtered)
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.4, ?)", (one_min_ago,))
    
    db_connection.commit()

    readings = repository.get_latest_sensor_readings(db_connection, 1)
    
    # Should only return the 2 metrics from the *exact* latest timestamp
    assert len(readings) == 2
    metrics = {r["metric_type"]: r["value"] for r in readings}
    assert metrics["temperature_c"] == 10.5
    assert metrics["humidity_pct"] == 60.2

def test_get_24h_extremes(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    # 1. Insert valid data within the 24-hour window
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 20.0, ?)", (now.strftime('%Y-%m-%d %H:%M:%S'),))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.0, ?)", (now.strftime('%Y-%m-%d %H:%M:%S'),))
    
    # 2. THE BOUNDARY TEST: Insert extreme data 25 hours ago (must be filtered out)
    twenty_five_hours_ago = (now - timedelta(hours=25)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 35.0, ?)", (twenty_five_hours_ago,)) 
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', -40.0, ?)", (twenty_five_hours_ago,))
    
    db_connection.commit()

    extremes = repository.get_24h_extremes(db_connection, 1, 'temperature_c')
    
    # High should be 20.0, low should be -15.5 (from conftest 2h ago)
    assert extremes["high"] == 20.0
    assert extremes["low"] == -15.5

def test_get_latest_single_metric(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    five_mins_ago = (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Boundary: Multiple readings for the same metric, must get newest
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity', 40.0, ?)", (five_mins_ago,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity', 45.0, ?)", (now_str,))
    db_connection.commit()

    latest = repository.get_latest_single_metric(db_connection, 1, 'humidity')
    assert latest["value"] == 45.0

def test_get_historical_trend(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    # Within 72h window
    seventy_one_hours_ago = (now - timedelta(hours=71)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'pressure', 1013.0, ?)", (seventy_one_hours_ago,))
    
    # Boundary: Just outside 72h window (73h ago)
    seventy_three_hours_ago = (now - timedelta(hours=73)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'pressure', 999.0, ?)", (seventy_three_hours_ago,))
    
    db_connection.commit()

    trend = repository.get_historical_trend(db_connection, 1, 'pressure', hours_back=72)
    
    # Should only find the 1013.0 reading
    assert len(trend) == 1
    assert trend[0]["value"] == 1013.0

def test_get_sustained_wind(db_connection):
    cursor = db_connection.cursor()
    # Boundary: Inject 5 readings. Sustained wind query uses LIMIT 3.
    # We want to prove only the latest 3 are averaged.
    # Using specific timestamps to guarantee order.
    now = datetime.now(timezone.utc)
    for i in range(5):
        ts = (now - timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
        # i=0 (now): 10.0
        # i=1 (1m ago): 12.0
        # i=2 (2m ago): 14.0
        # i=3 (3m ago): 100.0 (Should be ignored)
        # i=4 (4m ago): 100.0 (Should be ignored)
        val = 10.0 + (i * 2) if i < 3 else 100.0
        cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_kmh', ?, ?)", (val, ts))
    
    db_connection.commit()

    sustained = repository.get_sustained_wind(db_connection, 1, 'wind_kmh')
    # Average of 10.0, 12.0, 14.0 = 12.0
    assert sustained == 12.0

def test_get_max_wind_gust(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    # Within 1h window
    fifty_nine_mins_ago = (now - timedelta(minutes=59)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_gust_kmh', 30.1, ?)", (fifty_nine_mins_ago,))
    
    # Boundary: 61 minutes ago (just outside the 1h window)
    sixty_one_mins_ago = (now - timedelta(minutes=61)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_gust_kmh', 55.5, ?)", (sixty_one_mins_ago,))
    
    db_connection.commit()

    max_gust = repository.get_max_wind_gust(db_connection, 1, 'wind_gust_kmh')
    # Should ignore the 55.5 gust from 61 mins ago
    assert max_gust == 30.1

def test_get_multi_metric_history(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    # Inside 1h window
    thirty_mins_ago = (now - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 22.0, ?)", (thirty_mins_ago,))
    
    # Boundary: 65 mins ago (outside 1h window)
    sixty_five_mins_ago = (now - timedelta(minutes=65)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity_pct', 50.0, ?)", (sixty_five_mins_ago,))
    
    db_connection.commit()

    history = repository.get_multi_metric_history(db_connection, 1, 1)
    
    # Should only contain temperature_c, NOT humidity_pct
    metrics = [row["metric_type"] for row in history]
    assert "temperature_c" in metrics
    assert "humidity_pct" not in metrics

def test_get_sensor_health(db_connection):
    health = repository.get_sensor_health(db_connection, 1)
    assert health["battery_ok"] == 1

def test_get_sensor_health_not_found(db_connection):
    health = repository.get_sensor_health(db_connection, 999)
    assert health is None

# --- Empty State Tests ---

def test_get_all_sensors_empty():
    """Verify get_all_sensors returns an empty list when the table is empty."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sensors (id INTEGER PRIMARY KEY, machine_name TEXT, friendly_name TEXT, location TEXT)")
    
    sensors = repository.get_all_sensors(conn)
    assert sensors == []
    conn.close()

def test_get_latest_sensor_readings_no_data(db_connection):
    """Verify get_latest_sensor_readings returns empty list for non-existent sensor."""
    readings = repository.get_latest_sensor_readings(db_connection, 999)
    assert readings == []

def test_get_24h_extremes_no_data(db_connection):
    """Verify get_24h_extremes returns None values for a metric that hasn't been recorded."""
    extremes = repository.get_24h_extremes(db_connection, 1, 'wind_speed')
    assert extremes["high"] is None
    assert extremes["low"] is None

def test_get_latest_single_metric_no_data(db_connection):
    """Verify get_latest_single_metric returns None for non-existent metric or sensor."""
    latest = repository.get_latest_single_metric(db_connection, 1, 'non_existent_metric')
    assert latest is None
    
    latest = repository.get_latest_single_metric(db_connection, 999, 'temperature_c')
    assert latest is None

def test_get_historical_trend_no_data(db_connection):
    """Verify get_historical_trend returns an empty list when no data is found."""
    trend = repository.get_historical_trend(db_connection, 1, 'non_existent_metric')
    assert trend == []

def test_get_sustained_wind_no_data(db_connection):
    """Verify get_sustained_wind returns None when no wind readings exist."""
    sustained = repository.get_sustained_wind(db_connection, 1, 'wind_kmh')
    assert sustained is None

def test_get_max_wind_gust_no_data(db_connection):
    """Verify get_max_wind_gust returns None when no gust readings exist within the window."""
    max_gust = repository.get_max_wind_gust(db_connection, 1, 'wind_gust_kmh')
    assert max_gust is None

def test_get_multi_metric_history_no_data(db_connection):
    """Verify get_multi_metric_history returns an empty list for a sensor with no data."""
    history = repository.get_multi_metric_history(db_connection, 999, 1)
    assert history == []


# --- Security Tests ---

def test_sql_injection_prevention(db_connection):
    """
    Proves that the repository safely parameterizes inputs and is immune 
    to classic SQL injection attacks (both data leakage and destructive payloads).
    """
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    # 1. ARRANGE: Insert a valid, secret reading that the attacker shouldn't see
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'secret_battery_voltage', 99.9, ?)", (now,))
    db_connection.commit()

    # 2. ACT (Attack 1): The "Always True" Data Leak
    # An attacker tries to trick the WHERE clause into returning everything by adding OR 1=1
    malicious_metric = "temperature_c' OR 1=1; --"
    leak_attempt = repository.get_latest_single_metric(db_connection, 1, malicious_metric)
    
    # ASSERT: The database treated the string literally. It didn't find a metric named "temperature_c' OR 1=1; --"
    assert leak_attempt is None

    # 3. ACT (Attack 2): The Destructive Payload
    # An attacker tries to delete the entire readings table
    destructive_metric = "temperature_c'; DROP TABLE readings; --"
    destroy_attempt = repository.get_latest_single_metric(db_connection, 1, destructive_metric)
    
    # ASSERT: It should return None, because the metric doesn't exist
    assert destroy_attempt is None
    
    # 4. FINAL VERIFICATION: Prove the table survived the attack
    # If the DROP TABLE command executed, this query would crash with a "no such table" error.
    cursor.execute("SELECT COUNT(*) as count FROM readings")
    row_count = cursor.fetchone()["count"]
    
    # We inserted 1 secret reading, PLUS the 1 reading injected by the conftest.py fixture.
    # Therefore, 2 rows should still be safely intact.
    assert row_count == 2