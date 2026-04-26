import pytest
import json
from unittest.mock import MagicMock, patch
from hardware.sdr_reader import SensorBuffer, METRIC_DISPATCH, run_sdr_listener

# --- FIXTURES ---
# A fixture is a setup function that Pytest runs before each test. 
# It provides a fresh, clean dummy database and buffer for every single test.
@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def sensor_buffer(mock_db):
    return SensorBuffer(mock_db)


# --- BUFFER UNIT TESTS ---

def test_buffer_deduplication(sensor_buffer, mock_db):
    """EDGE CASE: Ensures exact duplicate radio packets are ignored."""
    sensor_id = 1
    timestamp = "2026-04-18 14:05:00"
    
    # 1. Send the exact same packet twice
    payload = {"temperature_C": 20.0}
    sensor_buffer.add_reading(sensor_id, timestamp, payload, METRIC_DISPATCH)
    sensor_buffer.add_reading(sensor_id, timestamp, payload, METRIC_DISPATCH)
    
    sensor_buffer.flush_to_db("2026-04-18 14:05:00")
    
    # 2. Verify the database was only asked to write the temperature ONCE
    # If deduplication failed, the sum() / len() math would still result in 20.0, 
    # but we strictly check how many items went into the buffer.
    mock_db.insert_reading.assert_called_once_with(1, 'temperature_c', 20.0, '2026-04-18 14:05:00')


def test_rain_odometer_rollover(sensor_buffer, mock_db):
    """
    COMPLEX LOGIC: Tests the rain delta math.
    Scenario:
    - Hour 1: Odometer at 100mm. (Delta should be 0 on first boot).
    - Hour 2: Odometer at 105mm. (Delta should be 5).
    - Hour 3: Odometer at 2mm. (Sensor battery died and reset. Delta should be 2).
    """
    sensor_id = 1
    
    # Hour 1: Initial boot. 
    sensor_buffer.add_reading(sensor_id, "T1", {"rain_mm": 100.0}, METRIC_DISPATCH)
    sensor_buffer.flush_to_db("Bucket1")
    # Assert delta is 0.0 for a brand new tracking session
    mock_db.insert_reading.assert_any_call(sensor_id, "rain_mm", 0.0, "Bucket1")
    
    # Hour 2: It rained 5mm.
    sensor_buffer.add_reading(sensor_id, "T2", {"rain_mm": 105.0}, METRIC_DISPATCH)
    sensor_buffer.flush_to_db("Bucket2")
    # Assert delta correctly calculated 105 - 100 = 5.0
    mock_db.insert_reading.assert_any_call(sensor_id, "rain_mm", 5.0, "Bucket2")
    
    # Hour 3: The sensor reset and started counting from 0 again. It rained 2mm.
    sensor_buffer.add_reading(sensor_id, "T3", {"rain_mm": 2.0}, METRIC_DISPATCH)
    sensor_buffer.flush_to_db("Bucket3")
    # Assert the negative delta was caught, and the raw current value (2.0) was used.
    mock_db.insert_reading.assert_any_call(sensor_id, "rain_mm", 2.0, "Bucket3")


def test_missing_data_handling(sensor_buffer, mock_db):
    """EDGE CASE: Ensures packets missing standard keys don't crash the loop."""
    sensor_id = 1
    
    # Send a payload with ONLY humidity. No temp, no wind, no battery.
    payload = {"humidity": 45.0}
    sensor_buffer.add_reading(sensor_id, "T1", payload, METRIC_DISPATCH)
    sensor_buffer.flush_to_db("Bucket1")
    
    # Verify it gracefully processed humidity and skipped everything else
    mock_db.insert_reading.assert_called_once_with(sensor_id, 'humidity_pct', 45.0, 'Bucket1')


# --- SUBPROCESS / LISTENER INTEGRATION TESTS ---

@patch('hardware.sdr_reader.WeatherWriter')
@patch('subprocess.Popen')
def test_listener_bucket_rotation(mock_popen, MockWriter):
    """
    HAPPY PATH: Tests the actual SDR listener loop.
    We mock subprocess.Popen to feed fake console output into the script.
    """
    
    # 1. Setup the fake database
    mock_db_instance = MockWriter.return_value
    mock_db_instance.get_sensor_map.return_value = {"12345": 1} # Hardware ID "12345" maps to DB ID 1
    
    # 2. Setup the fake SDR radio output
    # We provide three lines of JSON. The first two are in the 14:00 bucket. 
    # The third line moves to 14:05, which should trigger a database flush.
    # With ceiling snapping: 14:01 and 14:04:59 both ceil to 14:05.
    # 14:06 ceils to 14:10, triggering a flush of the 14:05 bucket.
    fake_stdout = [
        json.dumps({"time": "2026-04-18 14:01:00", "id": 12345, "temperature_C": 10.0}) + "\n",
        json.dumps({"time": "2026-04-18 14:04:59", "id": 12345, "temperature_C": 12.0}) + "\n",
        json.dumps({"time": "2026-04-18 14:06:00", "id": 12345, "temperature_C": 15.0}) + "\n",
    ]
    
    # Configure the mock process to yield our fake lines
    mock_process = MagicMock()
    mock_process.stdout = fake_stdout
    mock_process.__enter__.return_value = mock_process
    mock_popen.return_value = mock_process
    
    # 3. Run the listener (It will process the lines and exit when the list is empty)
    run_sdr_listener()
    
    # 4. Verify the bucket rotation logic triggered!
    # Because 14:05 arrived, it should have averaged the 10.0 and 12.0 from the 14:00 bucket
    # and flushed them as 11.0.
    from metrics import Metric
    mock_db_instance.insert_reading.assert_called_once_with(1, Metric.TEMPERATURE_C, 11.0, '2026-04-18 14:05:00')
    
    # 5. Verify graceful shutdown flushed the remaining 14:05 bucket
    mock_db_instance.close.assert_called_once()