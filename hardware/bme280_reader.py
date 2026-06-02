import smbus2
import bme280
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from config import BUCKET_INTERVAL_MINUTES, DB_PATH, ENABLE_I2C_DRIVER_RESET, ROOT_DIR
from db_access.metrics import build_metric_enum
from db_access.writer import WeatherWriter
from hardware.utils import snap_to_interval_ceiling

# Hardware constants
I2C_PORT       = 1
BME280_ADDRESS = 0x76
MAX_RETRIES    = 3

# Must match the machine_name inserted into the sensors table during setup.
SENSOR_MACHINE_NAME = 'bme280_local'

def _attempt_i2c_bus_recovery():
    """
    Sends 9 SCL clock pulses to free a slave stuck mid-transaction (I2C spec §3.1.16).
    A slave interrupted mid-byte holds SDA low; 9 pulses guarantees it finishes any
    pending bit (8 data + 1 ACK) and releases the bus regardless of where it's stuck.
    Returns True if the sequence ran, False if GPIO access was unavailable.
    """
    try:
        from gpiozero import DigitalOutputDevice

        sda = DigitalOutputDevice(2, initial_value=True)
        scl = DigitalOutputDevice(3, initial_value=True)
        try:
            for _ in range(9):
                scl.off()
                time.sleep(0.0001)
                scl.on()
                time.sleep(0.0001)
            # STOP condition: SDA transitions low → high while SCL is high
            sda.off()
            time.sleep(0.0001)
            sda.on()
        finally:
            sda.close()
            scl.close()

        time.sleep(0.5)  # allow I2C driver to reclaim pins before next read
        return True
    except Exception as exc:
        print(f"  -> GPIO bus recovery unavailable: {exc}")
        return False


def _read_sensor_once():
    """Single I2C read attempt. Raises IOError on any bus failure."""
    with smbus2.SMBus(I2C_PORT) as bus:
        calibration_params = bme280.load_calibration_params(bus, BME280_ADDRESS)
        return bme280.sample(bus, BME280_ADDRESS, calibration_params)


def read_sensor_with_retry():
    """Reads the BME280 with exponential-backoff retries, then hardware bus recovery."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _read_sensor_once()
        except IOError as e:
            if e.errno not in (110, 121):
                raise
            label = "timed out (clock stretch)" if e.errno == 110 else "not responding"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] I2C error — device {label} (attempt {attempt}/{MAX_RETRIES}).")
            if attempt < MAX_RETRIES:
                sleep_time = 2 ** attempt
                print(f"  -> Retrying in {sleep_time}s...")
                time.sleep(sleep_time)

    # All software retries exhausted — attempt the I2C spec recovery procedure
    print(f"  -> All retries failed. Attempting I2C bus recovery (9-clock pulse)...")
    if _attempt_i2c_bus_recovery():
        print(f"  -> Recovery pulse sent. Retrying sensor read...")
        try:
            data = _read_sensor_once()
            print(f"  -> Bus recovery successful.")
            return data
        except IOError:
            pass

    # GPIO pulse didn't recover the bus — escalate to kernel driver reset if enabled.
    # Disabled by default (ENABLE_I2C_DRIVER_RESET in config.py) because the reset
    # affects all devices on the I2C-1 bus, not just the BME280.
    if ENABLE_I2C_DRIVER_RESET:
        print(f"  -> GPIO recovery ineffective. Resetting I2C kernel driver...")
        try:
            result = subprocess.run(
                ['sudo', str(ROOT_DIR / 'hardware' / 'i2c_reset.sh')],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                time.sleep(1.0)
                print(f"  -> Driver reset complete. Retrying sensor read...")
                try:
                    data = _read_sensor_once()
                    print(f"  -> Driver reset recovery successful.")
                    return data
                except IOError:
                    pass
            else:
                print(f"  -> Driver reset failed: {result.stderr.decode().strip()}")
        except Exception as exc:
            print(f"  -> Driver reset unavailable: {exc}")

    raise Exception("BME280 not found on I2C bus after all recovery attempts — check wiring and power.")

def read_sensor_and_store():
    data = read_sensor_with_retry()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapped_timestamp = snap_to_interval_ceiling(now, BUCKET_INTERVAL_MINUTES).strftime("%Y-%m-%d %H:%M:%S")

    startup_conn = sqlite3.connect(DB_PATH)
    startup_conn.row_factory = sqlite3.Row
    Metric = build_metric_enum(startup_conn)
    startup_conn.close()

    writer = WeatherWriter(DB_PATH)
    try:
        sensor_map = writer.get_sensor_map()
        if SENSOR_MACHINE_NAME not in sensor_map:
            raise ValueError(
                f"BME280 sensor '{SENSOR_MACHINE_NAME}' not found in the sensors table. "
                "Add it with an INSERT statement and re-run."
            )
        sensor_id = sensor_map[SENSOR_MACHINE_NAME]
        readings = [
            (sensor_id, Metric.TEMPERATURE_C, round(data.temperature, 2), snapped_timestamp),
            (sensor_id, Metric.HUMIDITY_PCT,   round(data.humidity, 2),    snapped_timestamp),
            (sensor_id, Metric.PRESSURE_HPA,   round(data.pressure, 2),    snapped_timestamp),
        ]
        writer.insert_readings_bulk(readings)
    finally:
        writer.close()

if __name__ == "__main__":
    try:
        read_sensor_and_store()
    except Exception as e:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} CRITICAL: {e}")