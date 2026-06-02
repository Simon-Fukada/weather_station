import json
import pytest
from unittest.mock import MagicMock, patch, call

from db_access.metrics import build_metric_dispatch, build_metric_enum
from hardware.sdr_reader import SensorBuffer, run_sdr_listener


# --- FIXTURES ---

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def Metric(db_connection):
    return build_metric_enum(db_connection)

@pytest.fixture
def metric_dispatch(db_connection):
    """Builds the dispatch table from the in-memory test DB (rtl_field_map seeded in conftest)."""
    return build_metric_dispatch(db_connection)

@pytest.fixture
def sensor_buffer(mock_db, Metric):
    return SensorBuffer(mock_db, Metric)


# --- BUFFER UNIT TESTS ---

def test_buffer_deduplication(sensor_buffer, mock_db, metric_dispatch, Metric):
    """EDGE CASE: Ensures exact duplicate radio packets are ignored."""
    sensor_id = 1
    timestamp = "2026-04-18 14:05:00"

    payload = {"temperature_C": 20.0}
    sensor_buffer.add_reading(sensor_id, timestamp, payload, metric_dispatch)
    sensor_buffer.add_reading(sensor_id, timestamp, payload, metric_dispatch)

    sensor_buffer.flush_to_db("2026-04-18 14:05:00")

    mock_db.insert_readings_bulk.assert_called_once_with(
        [(1, Metric.TEMPERATURE_C, 20.0, '2026-04-18 14:05:00')]
    )


def test_rain_odometer_rollover(sensor_buffer, mock_db, metric_dispatch, Metric):
    """
    COMPLEX LOGIC: Tests the rain delta math.
    Scenario:
    - Hour 1: Odometer at 100mm. (Delta should be 0 on first boot).
    - Hour 2: Odometer at 105mm. (Delta should be 5).
    - Hour 3: Odometer at 2mm. (Sensor battery died and reset. Delta should be 2).
    """
    sensor_id = 1

    sensor_buffer.add_reading(sensor_id, "T1", {"rain_mm": 100.0}, metric_dispatch)
    sensor_buffer.flush_to_db("Bucket1")
    mock_db.insert_readings_bulk.assert_any_call([(sensor_id, Metric.RAIN_MM, 0.0, "Bucket1")])

    sensor_buffer.add_reading(sensor_id, "T2", {"rain_mm": 105.0}, metric_dispatch)
    sensor_buffer.flush_to_db("Bucket2")
    mock_db.insert_readings_bulk.assert_any_call([(sensor_id, Metric.RAIN_MM, 5.0, "Bucket2")])

    sensor_buffer.add_reading(sensor_id, "T3", {"rain_mm": 2.0}, metric_dispatch)
    sensor_buffer.flush_to_db("Bucket3")
    mock_db.insert_readings_bulk.assert_any_call([(sensor_id, Metric.RAIN_MM, 2.0, "Bucket3")])


def test_missing_data_handling(sensor_buffer, mock_db, metric_dispatch, Metric):
    """EDGE CASE: Ensures packets missing standard keys don't crash the loop."""
    sensor_id = 1

    payload = {"humidity": 45.0}
    sensor_buffer.add_reading(sensor_id, "T1", payload, metric_dispatch)
    sensor_buffer.flush_to_db("Bucket1")

    mock_db.insert_readings_bulk.assert_called_once_with(
        [(sensor_id, Metric.HUMIDITY_PCT, 45.0, 'Bucket1')]
    )


# --- SUBPROCESS / LISTENER INTEGRATION TESTS ---

@patch('hardware.sdr_reader.build_metric_dispatch')
@patch('hardware.sdr_reader.build_metric_enum')
@patch('hardware.sdr_reader.WeatherWriter')
@patch('subprocess.Popen')
def test_listener_bucket_rotation(mock_popen, MockWriter, mock_build_enum, mock_build_dispatch, db_connection):
    """
    HAPPY PATH: Tests the actual SDR listener loop.
    We mock subprocess.Popen to feed fake console output into the script.
    build_metric_enum and build_metric_dispatch are patched to avoid needing a real DB file.
    """
    from db_access.metrics import build_metric_enum as real_build
    mock_db_instance = MockWriter.return_value
    mock_db_instance.get_sensor_map.return_value = {"12345": 1}
    mock_build_enum.return_value = real_build(db_connection)
    mock_build_dispatch.return_value = {"temperature_C": ("temperature_c", None)}

    fake_stdout = [
        json.dumps({"time": "2026-04-18 14:01:00", "id": 12345, "temperature_C": 10.0}) + "\n",
        json.dumps({"time": "2026-04-18 14:04:59", "id": 12345, "temperature_C": 12.0}) + "\n",
        json.dumps({"time": "2026-04-18 14:06:00", "id": 12345, "temperature_C": 15.0}) + "\n",
    ]

    mock_process = MagicMock()
    mock_process.stdout = fake_stdout
    mock_process.__enter__.return_value = mock_process
    mock_popen.return_value = mock_process

    run_sdr_listener()

    Metric = mock_build_enum.return_value
    mock_db_instance.insert_readings_bulk.assert_has_calls([
        call([(1, Metric.TEMPERATURE_C, 11.0, '2026-04-18 14:05:00')]),
        call([(1, Metric.TEMPERATURE_C, 15.0, '2026-04-18 14:10:00')]),
    ])

    mock_db_instance.close.assert_called_once()
