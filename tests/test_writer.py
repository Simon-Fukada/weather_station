import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from db_access.writer import WeatherWriter


def _iso_to_epoch(iso: str) -> int:
    return int(datetime.strptime(iso, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def writer(db_connection):
    """WeatherWriter wired to the shared in-memory connection from conftest."""
    with patch('db_access.writer.sqlite3.connect', return_value=db_connection):
        db_writer = WeatherWriter(":memory:")
        yield db_writer


# --- Tests ---

def test_get_or_create_sensor(writer, db_connection):
    existing_id = writer.get_or_create_sensor("rtl_433_outdoor", "Outdoor Fence", "Backyard")
    assert existing_id == 1

    new_id = writer.get_or_create_sensor("BME280-01", "Patio Sensor", "Patio")
    assert new_id == 2

    count = db_connection.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]
    assert count == 2


def test_get_sensor_map(writer):
    writer.get_or_create_sensor("SDR-XYZ", "Ambient", "Roof")
    sensor_map = writer.get_sensor_map()
    assert sensor_map == {"rtl_433_outdoor": 1, "SDR-XYZ": 2}


def test_insert_reading(writer, db_connection):
    writer.insert_reading(1, "pressure_hpa", 1012.5, "2026-04-18 12:00:00")

    row = db_connection.execute("""
        SELECT r.sensor_id, mt.name AS metric_type, r.value, r.timestamp
        FROM readings r
        JOIN metric_types mt ON mt.id = r.metric_type_id
        WHERE r.sensor_id = 1 AND mt.name = 'pressure_hpa'
    """).fetchone()

    assert row["sensor_id"]    == 1
    assert row["metric_type"]  == "pressure_hpa"
    assert row["value"]        == 1012.5
    assert row["timestamp"]    == _iso_to_epoch("2026-04-18 12:00:00")


def test_insert_readings_bulk(writer, db_connection):
    payload = [
        (1, "temperature_c", 15.0, "2026-04-18 12:00:00"),
        (1, "humidity_pct",  50.0, "2026-04-18 12:00:00"),
        (1, "pressure_hpa", 1010.0, "2026-04-18 12:00:00"),
    ]
    writer.insert_readings_bulk(payload)

    count = db_connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    assert count == 4   # 1 seed from conftest + 3 new


def test_update_health_upsert(writer, db_connection):
    writer.update_health(1, 0, "2026-04-18 14:00:00")

    row   = db_connection.execute("SELECT * FROM sensor_health WHERE sensor_id = 1").fetchone()
    count = db_connection.execute("SELECT COUNT(*) FROM sensor_health").fetchone()[0]

    assert count == 1
    assert row["battery_ok"]   == 0
    assert row["last_updated"] == _iso_to_epoch("2026-04-18 14:00:00")
