import smbus2
import bme280
import sys
import time
from datetime import datetime, timezone, timedelta
from db_access.writer import WeatherWriter
from config import DB_PATH
from metrics import Metric

# Define constants
I2C_PORT = 1
BME280_ADDRESS = 0x76
MAX_RETRIES = 3

def get_snapped_timestamp() -> str:
    """Returns the current time snapped up to the next 5-minute boundary (ceiling).
    A reading taken at 8:07 is labelled 8:10 — the end of its collection window."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    remainder = now.minute % 5
    if remainder == 0:
        snapped_dt = now.replace(second=0, microsecond=0)
    else:
        snapped_dt = now.replace(second=0, microsecond=0) + timedelta(minutes=(5 - remainder))
    return snapped_dt.strftime("%Y-%m-%d %H:%M:%S")

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
            if e.errno != 121:
                raise
            print(f"[{datetime.now().strftime('%H:%M:%S')}] I2C remote I/O error — device not responding (attempt {attempt}/{MAX_RETRIES}).")
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

    raise Exception("BME280 not found on I2C bus after recovery — check wiring and power.")

def read_sensor_and_store():
    # 1. Fetch hardware data safely
    data = read_sensor_with_retry()
    snapped_timestamp = get_snapped_timestamp()
    
    # 2. Database transaction via the DAL
    writer = WeatherWriter(DB_PATH)
    try:
        # Abstracted away the SELECT / INSERT logic
        sensor_id = writer.get_or_create_sensor(
            machine_name='bme280_local',
            friendly_name='Living Room Sensor',
            location='Living Room'
        )
        
        # Format the readings for the bulk insert
        readings = [
            (sensor_id, Metric.TEMPERATURE_C, round(data.temperature, 2), snapped_timestamp),
            (sensor_id, Metric.HUMIDITY_PCT,   round(data.humidity, 2),    snapped_timestamp),
            (sensor_id, Metric.PRESSURE_HPA,   round(data.pressure, 2),    snapped_timestamp),
        ]
        
        # Abstracted away the executemany SQL logic
        writer.insert_readings_bulk(readings)
        
    finally:
        writer.close()

if __name__ == "__main__":
    try:
        read_sensor_and_store()
    except Exception as e:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} CRITICAL: {e}")