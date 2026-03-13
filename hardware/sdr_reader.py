import subprocess
import json
import sqlite3
import os
import time
from datetime import datetime
from dotenv import load_dotenv

# Explicitly load the .env file into memory BEFORE we try to read from it
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Resolve the absolute path to your database
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'weather_data.db'))

# Dynamically load the hardware mapping from the .env file.
# If the variable is missing or corrupted, we fallback to an empty dictionary to prevent fatal crashes.
try:
    raw_map = json.loads(os.getenv("SDR_SENSOR_MAP", "{}"))
    # JSON keys are always strings. We convert them to integers to match the rtl_433 output.
    SENSOR_MAP = {int(k): v for k, v in raw_map.items()}
except json.JSONDecodeError:
    print("CRITICAL ERROR: SDR_SENSOR_MAP in .env is not valid JSON. Defaulting to empty map.")
    SENSOR_MAP = {}

# Global dictionary to track the last save time per metric to prevent bloat
last_saved = {}

def should_save_reading(sensor_id: int, metric_type: str) -> bool:
    """Checks if 5 minutes (300 seconds) have passed since the last save for this metric."""
    key = (sensor_id, metric_type)
    current_time = time.time()
    
    if key in last_saved and current_time - last_saved[key] < 300:
        return False
    
    last_saved[key] = current_time
    return True

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def insert_reading(sensor_id: int, metric_type: str, value: float, timestamp: str):
    """Inserts a single metric into the EAV database schema."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO readings (sensor_id, metric_type, value, timestamp)
        VALUES (?, ?, ?, ?)
    """, (sensor_id, metric_type, value, timestamp))
    conn.commit()
    conn.close()

def run_sdr_listener():
    """Spawns the rtl_433 C-program and reads its output continuously."""
    
    # -F json: Output as JSON dictionary
    # -M utc: Standardize time to UTC
    # -M metric: Force unit conversion to Celsius and km/h regardless of the hardware's native broadcast
    command = ['rtl_433', '-F', 'json', '-M', 'utc', '-M', 'metric']

    print("Starting RTL-SDR Listener...")
    
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)

    try:
        for line in iter(process.stdout.readline, ''):
            if not line:
                continue
                
            try:
                data = json.loads(line)
                
                sensor_hardware_id = data.get("id")
                if sensor_hardware_id in SENSOR_MAP:
                    db_sensor_id = SENSOR_MAP[sensor_hardware_id]
                    timestamp = data.get("time")
                    
                    # 1. Extract Temperature
                    if "temperature_C" in data:
                        if should_save_reading(db_sensor_id, "temperature_c"):
                            insert_reading(db_sensor_id, "temperature_c", data["temperature_C"], timestamp)
                            print(f"[{timestamp}] Saved Temp: {data['temperature_C']}°C from Sensor {db_sensor_id}")
                    elif "temperature_F" in data:
                        if should_save_reading(db_sensor_id, "temperature_c"):
                            # (F - 32) * 5/9, rounded to 1 decimal place
                            converted_temp = round((data["temperature_F"] - 32) * 5/9, 1)
                            insert_reading(db_sensor_id, "temperature_c", converted_temp, timestamp)
                            print(f"[{timestamp}] Saved Temp: {converted_temp}°C (converted from {data['temperature_F']}°F) from Sensor {db_sensor_id}")
                        
                    # 2. Extract Humidity
                    if "humidity" in data:
                        if should_save_reading(db_sensor_id, "humidity_pct"):
                            insert_reading(db_sensor_id, "humidity_pct", data["humidity"], timestamp)
                            print(f"[{timestamp}] Saved Hum: {data['humidity']}% from Sensor {db_sensor_id}")
                        
                    # 3. Extract Sustained Wind Speed
                    if "wind_avg_km_h" in data:
                        if should_save_reading(db_sensor_id, "wind_kmh"):
                            insert_reading(db_sensor_id, "wind_kmh", data["wind_avg_km_h"], timestamp)
                            print(f"[{timestamp}] Saved Wind: {data['wind_avg_km_h']} km/h from Sensor {db_sensor_id}")
                    elif "wind_avg_mi_h" in data:
                        if should_save_reading(db_sensor_id, "wind_kmh"):
                            # mph * 1.60934, rounded to 1 decimal place
                            converted_wind = round(data["wind_avg_mi_h"] * 1.60934, 1)
                            insert_reading(db_sensor_id, "wind_kmh", converted_wind, timestamp)
                            print(f"[{timestamp}] Saved Wind: {converted_wind} km/h (converted from {data['wind_avg_mi_h']} mph) from Sensor {db_sensor_id}")
                        
                    # 4. Extract Wind Gusts (If the hardware supports it)
                    if "wind_max_km_h" in data:
                        if should_save_reading(db_sensor_id, "wind_gust_kmh"):
                            insert_reading(db_sensor_id, "wind_gust_kmh", data["wind_max_km_h"], timestamp)
                            print(f"[{timestamp}] Saved Gust: {data['wind_max_km_h']} km/h from Sensor {db_sensor_id}")
                    elif "wind_max_mi_h" in data:
                        if should_save_reading(db_sensor_id, "wind_gust_kmh"):
                            # mph * 1.60934, rounded to 1 decimal place
                            converted_gust = round(data["wind_max_mi_h"] * 1.60934, 1)
                            insert_reading(db_sensor_id, "wind_gust_kmh", converted_gust, timestamp)
                            print(f"[{timestamp}] Saved Gust: {converted_gust} km/h (converted from {data['wind_max_mi_h']} mph) from Sensor {db_sensor_id}")
                        
            except json.JSONDecodeError:
                continue
                
    except KeyboardInterrupt:
        print("\nShutting down SDR listener...")
    finally:
        process.terminate()

if __name__ == "__main__":
    run_sdr_listener()