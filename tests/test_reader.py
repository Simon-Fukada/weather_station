import pytest
import sqlite3
import time

from db_access import reader
from db_access.metrics import build_metric_enum


@pytest.fixture
def Metric(db_connection):
    return build_metric_enum(db_connection)


def test_get_all_sensors(db_connection):
    sensors = reader.get_all_sensors(db_connection)
    assert len(sensors) == 1
    assert sensors[0]["machine_name"] == "rtl_433_outdoor"
    assert sensors[0]["friendly_name"] == "Outdoor Fence"


def test_get_latest_sensor_readings(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())

    temp_id = metric_ids[Metric.TEMPERATURE_C]
    hum_id  = metric_ids[Metric.HUMIDITY_PCT]
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 10.5)", (temp_id, now))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 60.2)", (hum_id,  now))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 10.4)", (temp_id, now - 60))
    db_connection.commit()

    readings = reader.get_latest_sensor_readings(db_connection, 1)
    assert len(readings) == 2
    metrics = {r["metric_type"]: r["value"] for r in readings}
    assert metrics["temperature_c"] == 10.5
    assert metrics["relative_humidity_pct"] == 60.2


def test_get_24h_extremes(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    temp_id = metric_ids[Metric.TEMPERATURE_C]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 20.0)", (temp_id, now))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 10.0)", (temp_id, now - 1))

    # Outside 24 h window — must be excluded
    old = now - 90000
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 35.0)",  (temp_id, old))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, -40.0)", (temp_id, old - 1))
    db_connection.commit()

    extremes = reader.get_24h_extremes(db_connection, 1, temp_id)
    assert extremes["high"] == 20.0
    assert extremes["low"] == -15.5   # seeded in conftest, within 24 h


def test_get_latest_single_metric(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    hum_id = metric_ids[Metric.HUMIDITY_PCT]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 40.0)", (hum_id, now - 300))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 45.0)", (hum_id, now))
    db_connection.commit()

    latest = reader.get_latest_single_metric(db_connection, 1, hum_id)
    assert latest["value"] == 45.0


def test_get_latest_global_metric(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    pressure_id = metric_ids[Metric.PRESSURE_HPA]

    cursor.execute("INSERT INTO sensors (id, machine_name) VALUES (2, 'sensor_2')")
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 1010.0)", (pressure_id, now - 300))
    cursor.execute("INSERT INTO readings VALUES (2, ?, ?, 1015.0)", (pressure_id, now))
    db_connection.commit()

    latest = reader.get_latest_global_metric(db_connection, pressure_id)
    assert latest["value"] == 1015.0


def test_get_global_max_wind_gust(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    gust_id = metric_ids[Metric.WIND_GUST_KMH]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 30.1)", (gust_id, now - 3540))  # 59 min
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 55.5)", (gust_id, now - 3660))  # 61 min — excluded
    db_connection.commit()

    max_gust = reader.get_global_max_wind_gust(db_connection, gust_id)
    assert max_gust == 30.1


def test_get_pivoted_trend_per_sensor(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    ts = int(time.time()) - 1800
    temp_id = metric_ids[Metric.TEMPERATURE_C]
    hum_id  = metric_ids[Metric.HUMIDITY_PCT]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 22.0)", (temp_id, ts))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 55.0)", (hum_id,  ts))
    db_connection.commit()

    rows = reader.get_pivoted_trend(
        db_connection,
        {Metric.TEMPERATURE_C: temp_id, Metric.HUMIDITY_PCT: hum_id},
        hours_back=1, sensor_id=1,
    )
    assert len(rows) == 1
    assert rows[0]["temperature_c"] == 22.0
    assert rows[0]["relative_humidity_pct"] == 55.0


def test_get_pivoted_trend_global(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    pressure_id = metric_ids[Metric.PRESSURE_HPA]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 1013.0)", (pressure_id, int(time.time()) - 1800))
    db_connection.commit()

    rows = reader.get_pivoted_trend(
        db_connection,
        {Metric.PRESSURE_HPA: pressure_id},
        hours_back=1,
    )
    assert len(rows) == 1
    assert rows[0]["pressure_hpa"] == 1013.0


def test_get_pivoted_trend_excludes_old_data(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    temp_id = metric_ids[Metric.TEMPERATURE_C]

    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 22.0)", (temp_id, now - 1800))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 5.0)",  (temp_id, now - 90000))
    db_connection.commit()

    rows = reader.get_pivoted_trend(
        db_connection,
        {Metric.TEMPERATURE_C: temp_id},
        hours_back=1, sensor_id=1,
    )
    assert len(rows) == 1
    assert rows[0]["temperature_c"] == 22.0


def test_get_sensor_health(db_connection):
    health = reader.get_sensor_health(db_connection, 1)
    assert health["battery_ok"] == 1


def test_get_sensor_health_not_found(db_connection):
    assert reader.get_sensor_health(db_connection, 999) is None


def test_get_rf_trend_data(db_connection, metric_ids, Metric):
    cursor = db_connection.cursor()
    now = int(time.time())
    snr_id = metric_ids[Metric.SNR_DB]

    # Current window (0–3 h): avg should be 15.0
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 20.0)", (snr_id, now - 3600))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 10.0)", (snr_id, now - 7200))
    # Past window (3–6 h): avg should be 30.0
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 25.0)", (snr_id, now - 14400))
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 35.0)", (snr_id, now - 18000))
    # Beyond 6 h — must be ignored
    cursor.execute("INSERT INTO readings VALUES (1, ?, ?, 99.0)", (snr_id, now - 25200))
    db_connection.commit()

    results = reader.get_rf_trend_data(
        db_connection, 1,
        metric_ids[Metric.RSSI_DBM],
        metric_ids[Metric.NOISE_DBM],
        metric_ids[Metric.SNR_DB],
    )
    assert "snr_db" in results
    assert results["snr_db"]["current"] == 15.0
    assert results["snr_db"]["past"]    == 30.0


# --- Empty / no-data tests ---

def test_get_all_sensors_empty():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE sensors (id INTEGER PRIMARY KEY, machine_name TEXT, friendly_name TEXT, location TEXT)")
    assert reader.get_all_sensors(conn) == []
    conn.close()


def test_get_latest_sensor_readings_no_data(db_connection):
    assert reader.get_latest_sensor_readings(db_connection, 999) == []


def test_get_24h_extremes_no_data(db_connection, metric_ids, Metric):
    extremes = reader.get_24h_extremes(db_connection, 1, metric_ids[Metric.WIND_KMH])
    assert extremes["high"] is None
    assert extremes["low"]  is None


def test_get_latest_single_metric_no_data(db_connection):
    assert reader.get_latest_single_metric(db_connection, 1, 99999) is None


def test_get_latest_global_metric_no_data(db_connection):
    assert reader.get_latest_global_metric(db_connection, 99999) is None


def test_get_global_max_wind_gust_no_data(db_connection, metric_ids, Metric):
    assert reader.get_global_max_wind_gust(db_connection, metric_ids[Metric.WIND_GUST_KMH]) is None


def test_get_pivoted_trend_no_data(db_connection, metric_ids, Metric):
    rows = reader.get_pivoted_trend(
        db_connection,
        {Metric.TEMPERATURE_C: metric_ids[Metric.TEMPERATURE_C],
         Metric.HUMIDITY_PCT:  metric_ids[Metric.HUMIDITY_PCT]},
        hours_back=1, sensor_id=999,
    )
    assert rows == []


def test_get_rf_trend_data_no_data(db_connection, metric_ids, Metric):
    results = reader.get_rf_trend_data(
        db_connection, 999,
        metric_ids[Metric.RSSI_DBM],
        metric_ids[Metric.NOISE_DBM],
        metric_ids[Metric.SNR_DB],
    )
    assert results == {}


# --- Security ---

def test_sql_injection_prevention(db_connection, metric_ids):
    """Reader functions accept integer IDs — the string injection vector no longer exists.
    Verify a non-existent ID returns None and leaves the table intact."""
    assert reader.get_latest_single_metric(db_connection, 1, 99999) is None

    count = db_connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    assert count == 1   # only the conftest seed row
