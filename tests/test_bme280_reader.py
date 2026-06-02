import pytest
from unittest.mock import patch, MagicMock
import os
from datetime import datetime


from hardware import bme280_reader

# --- Helper Classes ---

class MockBMEData:
    """A fake data object that mimics the C-struct returned by the bme280 library."""
    def __init__(self, temp, hum, pres):
        self.temperature = temp
        self.humidity = hum
        self.pressure = pres

def create_errno_121():
    """Generates a perfectly simulated Errno 121 Remote I/O Error."""
    err = IOError("Remote I/O error")
    err.errno = 121
    return err

# --- The Test Matrix ---

@patch('hardware.bme280_reader.time.sleep')
@patch('hardware.bme280_reader.bme280.sample')
@patch('hardware.bme280_reader.bme280.load_calibration_params')
@patch('hardware.bme280_reader.smbus2.SMBus')
def test_transient_hardware_failure(mock_smbus, mock_calibrate, mock_sample, mock_sleep):
    """TEST 1: Verifies the self-healing retry logic works on a single hardware lockup."""
    
    # We tell the fake sensor: "Crash on the first try, succeed on the second try"
    mock_sample.side_effect = [
        create_errno_121(), 
        MockBMEData(22.5, 45.1, 1012.3)
    ]
    
    # Execute the function
    result = bme280_reader.read_sensor_with_retry()
    
    # Assertions
    assert result.temperature == 22.5
    assert mock_sample.call_count == 2
    mock_sleep.assert_called_once_with(2) # Proves the exponential backoff triggered exactly once


@patch('hardware.bme280_reader.subprocess.run', return_value=MagicMock(returncode=1))
@patch('hardware.bme280_reader._attempt_i2c_bus_recovery', return_value=False)
@patch('hardware.bme280_reader.time.sleep')
@patch('hardware.bme280_reader.bme280.sample')
@patch('hardware.bme280_reader.bme280.load_calibration_params')
@patch('hardware.bme280_reader.smbus2.SMBus')
def test_fatal_hardware_failure(mock_smbus, mock_calibrate, mock_sample, mock_sleep, mock_recovery, mock_subprocess):
    """TEST 2: Verifies the script safely terminates if the hardware is completely dead.
    Both hardware recovery paths are short-circuited so we test only the retry loop itself."""

    # We tell the fake sensor: "Always crash"
    mock_sample.side_effect = create_errno_121()

    # We assert that the script eventually gives up and raises our custom Exception
    with pytest.raises(Exception, match="BME280 not found on I2C bus after all recovery attempts"):
        bme280_reader.read_sensor_with_retry()

    # Proves it tried exactly 3 times (the MAX_RETRIES constant)
    assert mock_sample.call_count == 3
    # Proves the backoff increased exponentially (sleep 2, then sleep 4)
    assert mock_sleep.call_count == 2


def test_time_quantization():
    """TEST 3: Verifies ceiling snap — timestamps round UP to the end of their 5-min window."""
    from hardware.utils import snap_to_interval_ceiling

    # Scenario A: 14:04:59 → ceil to 14:05:00
    assert snap_to_interval_ceiling(datetime(2026, 4, 15, 14, 4, 59), 5) == datetime(2026, 4, 15, 14, 5, 0)

    # Scenario B: 14:06:01 → ceil to 14:10:00
    assert snap_to_interval_ceiling(datetime(2026, 4, 15, 14, 6, 1), 5) == datetime(2026, 4, 15, 14, 10, 0)

    # Scenario C: exact boundary stays put
    assert snap_to_interval_ceiling(datetime(2026, 4, 15, 14, 5, 0), 5) == datetime(2026, 4, 15, 14, 5, 0)


@patch('hardware.bme280_reader.build_metric_enum')
@patch('hardware.bme280_reader.snap_to_interval_ceiling')
@patch('hardware.bme280_reader.read_sensor_with_retry')
@patch('hardware.bme280_reader.WeatherWriter')
def test_database_integration(MockWeatherWriter, mock_read, mock_snap, mock_build_enum, db_connection):
    """
    TEST 4: Verifies the DAL is called with correctly rounded values.
    Because the SQL is abstracted, we only need to test what is handed to the writer.
    """
    from db_access.metrics import build_metric_enum as real_build
    Metric = real_build(db_connection)
    mock_build_enum.return_value = Metric

    mock_read.return_value = MockBMEData(14.486, 42.539, 852.418)
    mock_snap.return_value = datetime(2026, 4, 16, 14, 5, 0)

    mock_writer_instance = MockWeatherWriter.return_value
    mock_writer_instance.get_sensor_map.return_value = {bme280_reader.SENSOR_MACHINE_NAME: 1}

    bme280_reader.read_sensor_and_store()

    MockWeatherWriter.assert_called_once_with(bme280_reader.DB_PATH)

    expected_readings = [
        (1, Metric.TEMPERATURE_C, 14.49,  "2026-04-16 14:05:00"),
        (1, Metric.HUMIDITY_PCT,  42.54,  "2026-04-16 14:05:00"),
        (1, Metric.PRESSURE_HPA,  852.42, "2026-04-16 14:05:00"),
    ]
    mock_writer_instance.insert_readings_bulk.assert_called_once_with(expected_readings)
    mock_writer_instance.close.assert_called_once()


@patch('hardware.bme280_reader.build_metric_enum')
@patch('hardware.bme280_reader.read_sensor_with_retry')
@patch('hardware.bme280_reader.WeatherWriter')
def test_null_data_safely_aborts(MockWeatherWriter, mock_read, mock_build_enum, db_connection):
    """TEST 5: Verifies that corrupted/null data aborts before writing."""
    from db_access.metrics import build_metric_enum as real_build
    mock_build_enum.return_value = real_build(db_connection)

    mock_read.return_value = MockBMEData(None, None, None)
    mock_writer_instance = MockWeatherWriter.return_value
    mock_writer_instance.get_sensor_map.return_value = {bme280_reader.SENSOR_MACHINE_NAME: 1}

    # The built-in round() function throws a TypeError if given None.
    with pytest.raises(TypeError):
        bme280_reader.read_sensor_and_store()

    # Crucial Assertion: Prove that because it crashed, the DAL was never asked to write data
    mock_writer_instance.insert_readings_bulk.assert_not_called()