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

    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.5, ?)", (now_str,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity_pct', 60.2, ?)", (now_str,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.4, ?)", (one_min_ago,))
    
    db_connection.commit()

    readings = repository.get_latest_sensor_readings(db_connection, 1)
    
    assert len(readings) == 2
    metrics = {r["metric_type"]: r["value"] for r in readings}
    assert metrics["temperature_c"] == 10.5
    assert metrics["humidity_pct"] == 60.2

def test_get_24h_extremes(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 20.0, ?)", (now.strftime('%Y-%m-%d %H:%M:%S'),))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 10.0, ?)", (now.strftime('%Y-%m-%d %H:%M:%S'),))
    
    twenty_five_hours_ago = (now - timedelta(hours=25)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 35.0, ?)", (twenty_five_hours_ago,)) 
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', -40.0, ?)", (twenty_five_hours_ago,))
    
    db_connection.commit()

    extremes = repository.get_24h_extremes(db_connection, 1, 'temperature_c')
    
    assert extremes["high"] == 20.0
    assert extremes["low"] == -15.5

def test_get_latest_single_metric(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    five_mins_ago = (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity', 40.0, ?)", (five_mins_ago,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity', 45.0, ?)", (now_str,))
    db_connection.commit()

    latest = repository.get_latest_single_metric(db_connection, 1, 'humidity')
    assert latest["value"] == 45.0

# --- UPDATED: Global Query Tests ---

def test_get_latest_global_metric(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    five_mins_ago = (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    # We insert pressure data across TWO different sensors (ID 1 and 2)
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'pressure_hpa', 1010.0, ?)", (five_mins_ago,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (2, 'pressure_hpa', 1015.0, ?)", (now_str,))
    db_connection.commit()

    # The global fetch should find 1015.0 because it's the newest, regardless of sensor ID
    latest = repository.get_latest_global_metric(db_connection, 'pressure_hpa')
    assert latest["value"] == 1015.0

def test_get_global_historical_trend(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    seventy_one_hours_ago = (now - timedelta(hours=71)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'pressure_hpa', 1013.0, ?)", (seventy_one_hours_ago,))
    
    seventy_three_hours_ago = (now - timedelta(hours=73)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'pressure_hpa', 999.0, ?)", (seventy_three_hours_ago,))
    
    db_connection.commit()

    trend = repository.get_global_historical_trend(db_connection, 'pressure_hpa', hours_back=72)
    
    assert len(trend) == 1
    assert trend[0]["value"] == 1013.0

def test_get_global_sustained_wind(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    for i in range(5):
        ts = (now - timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
        val = 10.0 + (i * 2) if i < 3 else 100.0
        cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_kmh', ?, ?)", (val, ts))
    
    db_connection.commit()

    sustained = repository.get_global_sustained_wind(db_connection, 'wind_kmh')
    assert sustained == 12.0

def test_get_global_max_wind_gust(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    fifty_nine_mins_ago = (now - timedelta(minutes=59)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_gust_kmh', 30.1, ?)", (fifty_nine_mins_ago,))
    
    sixty_one_mins_ago = (now - timedelta(minutes=61)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'wind_gust_kmh', 55.5, ?)", (sixty_one_mins_ago,))
    
    db_connection.commit()

    max_gust = repository.get_global_max_wind_gust(db_connection, 'wind_gust_kmh')
    assert max_gust == 30.1

def test_get_multi_metric_history(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    thirty_mins_ago = (now - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'temperature_c', 22.0, ?)", (thirty_mins_ago,))
    
    sixty_five_mins_ago = (now - timedelta(minutes=65)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'humidity_pct', 50.0, ?)", (sixty_five_mins_ago,))
    
    db_connection.commit()

    history = repository.get_multi_metric_history(db_connection, 1, 1)
    
    metrics = [row["metric_type"] for row in history]
    assert "temperature_c" in metrics
    assert "humidity_pct" not in metrics

def test_get_sensor_health(db_connection):
    health = repository.get_sensor_health(db_connection, 1)
    assert health["battery_ok"] == 1

def test_get_sensor_health_not_found(db_connection):
    health = repository.get_sensor_health(db_connection, 999)
    assert health is None

def test_get_rf_trend_data(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc)
    
    # 1. Define the timestamps for the "Current" window (0 to 3 hours ago)
    one_hour_ago = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    two_hours_ago = (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
    
    # 2. Define the timestamps for the "Past" window (3 to 6 hours ago)
    four_hours_ago = (now - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')
    five_hours_ago = (now - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    # 3. Insert mock data for the Current window (Average should be 15.0)
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'snr_db', 20.0, ?)", (one_hour_ago,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'snr_db', 10.0, ?)", (two_hours_ago,))
    
    # 4. Insert mock data for the Past window (Average should be 30.0)
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'snr_db', 25.0, ?)", (four_hours_ago,))
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'snr_db', 35.0, ?)", (five_hours_ago,))
    
    # 5. Insert an edge case: Data older than 6 hours (Should be ignored by the query)
    seven_hours_ago = (now - timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'snr_db', 99.0, ?)", (seven_hours_ago,))
    
    db_connection.commit()

    # 6. Execute the function
    results = repository.get_rf_trend_data(db_connection, 1)
    
    # 7. Assertions
    assert "snr_db" in results
    assert results["snr_db"]["current"] == 15.0
    assert results["snr_db"]["past"] == 30.0

# --- Empty State Tests ---

def test_get_all_sensors_empty():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sensors (id INTEGER PRIMARY KEY, machine_name TEXT, friendly_name TEXT, location TEXT)")
    
    sensors = repository.get_all_sensors(conn)
    assert sensors == []
    conn.close()

def test_get_latest_sensor_readings_no_data(db_connection):
    readings = repository.get_latest_sensor_readings(db_connection, 999)
    assert readings == []

def test_get_24h_extremes_no_data(db_connection):
    extremes = repository.get_24h_extremes(db_connection, 1, 'wind_speed')
    assert extremes["high"] is None
    assert extremes["low"] is None

def test_get_latest_single_metric_no_data(db_connection):
    latest = repository.get_latest_single_metric(db_connection, 1, 'non_existent_metric')
    assert latest is None
    
def test_get_latest_global_metric_no_data(db_connection):
    latest = repository.get_latest_global_metric(db_connection, 'non_existent_metric')
    assert latest is None

def test_get_global_historical_trend_no_data(db_connection):
    trend = repository.get_global_historical_trend(db_connection, 'non_existent_metric')
    assert trend == []

def test_get_global_sustained_wind_no_data(db_connection):
    sustained = repository.get_global_sustained_wind(db_connection, 'wind_kmh')
    assert sustained is None

def test_get_global_max_wind_gust_no_data(db_connection):
    max_gust = repository.get_global_max_wind_gust(db_connection, 'wind_gust_kmh')
    assert max_gust is None

def test_get_multi_metric_history_no_data(db_connection):
    history = repository.get_multi_metric_history(db_connection, 999, 1)
    assert history == []

def test_get_rf_trend_data_no_data(db_connection):
    # Query a sensor ID that has no corresponding radio data
    results = repository.get_rf_trend_data(db_connection, 999)
    
    # The function should return an empty dictionary, not a NoneType or an error
    assert results == {}

# --- Security Tests ---

def test_sql_injection_prevention(db_connection):
    cursor = db_connection.cursor()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("INSERT INTO readings (sensor_id, metric_type, value, timestamp) VALUES (1, 'secret_battery_voltage', 99.9, ?)", (now,))
    db_connection.commit()

    malicious_metric = "temperature_c' OR 1=1; --"
    leak_attempt = repository.get_latest_single_metric(db_connection, 1, malicious_metric)
    assert leak_attempt is None

    destructive_metric = "temperature_c'; DROP TABLE readings; --"
    destroy_attempt = repository.get_latest_single_metric(db_connection, 1, destructive_metric)
    assert destroy_attempt is None
    
    cursor.execute("SELECT COUNT(*) as count FROM readings")
    row_count = cursor.fetchone()["count"]
    
    assert row_count == 2

def test_get_global_sustained_wind_ignores_stale_data(db_connection):
    cursor = db_connection.cursor()
    
    # 0. Create a dummy sensor first so the database is happy
    cursor.execute("""
        INSERT INTO sensors (machine_name, friendly_name, location) 
        VALUES ('test_wind_sensor', 'Test Anemometer', 'Roof')
    """)
    sensor_id = cursor.lastrowid # Grab the ID of the sensor we just created
    
    # 1. Insert two readings from 3 weeks ago, tied to our dummy sensor
    cursor.execute("""
        INSERT INTO readings (sensor_id, metric_type, value, timestamp) 
        VALUES 
        (?, 'wind_speed', 50.0, datetime('now', '-21 days')),
        (?, 'wind_speed', 50.0, datetime('now', '-21 days'))
    """, (sensor_id, sensor_id))
    
    # 2. Insert one reading from 5 minutes ago, tied to our dummy sensor
    cursor.execute("""
        INSERT INTO readings (sensor_id, metric_type, value, timestamp) 
        VALUES (?, 'wind_speed', 10.0, datetime('now', '-5 minutes'))
    """, (sensor_id,))
    
    db_connection.commit()
    
    # 3. Execute the function
    # (Assuming you need to import get_global_sustained_wind at the top of your test file)
    result = repository.get_global_sustained_wind(db_connection, 'wind_speed')
    
    # 4. The Assertion
    assert result == 10.0

