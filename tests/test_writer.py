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

def test_get_sensor_map(writer, db_connection):
    db_connection.execute(
        "INSERT INTO sensors (machine_name, friendly_name, location) VALUES ('SDR-XYZ', 'Ambient', 'Roof')"
    )
    db_connection.commit()
    sensor_map = writer.get_sensor_map()
    assert sensor_map == {"rtl_433_outdoor": 1, "SDR-XYZ": 2}


def test_insert_readings_bulk(writer, db_connection):
    payload = [
        (1, "temperature_c", 15.0, "2026-04-18 12:00:00"),
        (1, "relative_humidity_pct", 50.0, "2026-04-18 12:00:00"),
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
