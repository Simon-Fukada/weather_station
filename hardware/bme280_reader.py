import smbus2
import bme280
import sqlite3
import os
from datetime import datetime

def read_sensor_and_store():
    # Set the I2C port to 1 and the address to 0x76
    port = 1
    address = 0x76
    bus = smbus2.SMBus(port)
    
    # Initialize the bus and load the calibration parameters
    calibration_params = bme280.load_calibration_params(bus, address)
    
    # Take a sample reading
    data = bme280.sample(bus, address, calibration_params)
    
    # Connect to ../data/weather_data.db
    db_path = os.path.join(os.path.dirname(__file__), '../data/weather_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enforce PRAGMA foreign_keys = ON;
    cursor.execute('PRAGMA foreign_keys = ON;')
    
    # Check the sensors table for machine_name = 'bme280_local'
    machine_name = 'bme280_local'
    cursor.execute('SELECT id FROM sensors WHERE machine_name = ?', (machine_name,))
    result = cursor.fetchone()
    
    if result is None:
        # If it does not exist, insert it
        cursor.execute('''
            INSERT INTO sensors (machine_name, friendly_name, location)
            VALUES (?, ?, ?)
        ''', (machine_name, 'Living Room Sensor', 'Living Room'))
        sensor_id = cursor.lastrowid
    else:
        # If it does exist, fetch its id
        sensor_id = result[0]
    
    # Insert three distinct rows into the readings table
    readings = [
        (sensor_id, 'temperature_c', data.temperature),
        (sensor_id, 'humidity_pct', data.humidity),
        (sensor_id, 'pressure_hpa', data.pressure)
    ]
    
    cursor.executemany('''
        INSERT INTO readings (sensor_id, metric_type, value)
        VALUES (?, ?, ?)
    ''', readings)
    
    conn.commit()
    conn.close()
    
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} Success! Data recorded from {machine_name}:")
    print(f"  Temperature: {data.temperature:.2f} C")
    print(f"  Humidity:    {data.humidity:.2f} %")
    print(f"  Pressure:    {data.pressure:.2f} hPa")

if __name__ == "__main__":
    try:
        read_sensor_and_store()
    except Exception as e:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} Error reading BME280 sensor: {e}")
