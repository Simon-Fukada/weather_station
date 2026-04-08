import subprocess
import json
import sqlite3
import os
import time
from typing import Callable, Optional, Dict, Tuple
from dotenv import load_dotenv

# Explicitly load the .env file (Now only used for STATION_ELEVATION, 
# but good practice to keep the loader intact for future system variables)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'weather_data.db'))

class WeatherDatabase:
    """Manages a persistent connection to the SQLite database."""
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        # Enable Write-Ahead Logging for better concurrency and write performance
        self.conn.execute("PRAGMA journal_mode=WAL;")
        
    def get_sensor_map(self) -> Dict[str, int]:
        """
        Dynamically builds the sensor map from the database.
        Returns a dictionary mapping the Physical ID (machine_name) to the Database ID.
        Example: {'12345': 2, 'bme280_local': 1}
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, machine_name FROM sensors")
        # We enforce str() on the machine_name to ensure safe matching later
        return {str(row["machine_name"]): row["id"] for row in cursor.fetchall()}

    def insert(self, sensor_id: int, metric_type: str, value: float, timestamp: str):
        """Inserts a single time-series metric into the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO readings (sensor_id, metric_type, value, timestamp)
            VALUES (?, ?, ?, ?)
        """, (sensor_id, metric_type, value, timestamp))
        self.conn.commit()

    def update_health(self, sensor_id: int, battery_ok: int, timestamp: str):
        """
        Upserts the battery status into the state table.
        Ensures only 1 row exists per sensor to prevent database bloat.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO sensor_health (sensor_id, battery_ok, last_updated)
            VALUES (?, ?, ?)
            ON CONFLICT(sensor_id) DO UPDATE SET 
                battery_ok = excluded.battery_ok,
                last_updated = excluded.last_updated
        """, (sensor_id, battery_ok, timestamp))
        self.conn.commit()

    def close(self):
        self.conn.close()

class RateLimiter:
    """Tracks save times to prevent database bloat and excessive SD card writes."""
    def __init__(self, interval_seconds: int = 300):
        self.last_saved: Dict[Tuple[int, str], float] = {}
        self.interval = interval_seconds
        
    def should_save(self, sensor_id: int, metric_type: str) -> bool:
        """Checks if the interval has passed since the last save for this metric."""
        key = (sensor_id, metric_type)
        current_time = time.time()
        
        if key in self.last_saved and current_time - self.last_saved[key] < self.interval:
            return False
        
        self.last_saved[key] = current_time
        return True

# Map incoming JSON keys to (Database Metric Name, Optional Conversion Function, Unit for Printing)
METRIC_DISPATCH = {
    "temperature_C": ("temperature_c", None, "°C"),
    "temperature_F": ("temperature_c", lambda f: round((f - 32) * 5/9, 1), "°C (converted)"),
    "humidity":      ("humidity_pct", None, "%"),
    "wind_avg_km_h": ("wind_kmh", None, "km/h"),
    "wind_avg_mi_h": ("wind_kmh", lambda mph: round(mph * 1.60934, 1), "km/h (converted)"),
    "wind_max_km_h": ("wind_gust_kmh", None, "km/h"),
    "wind_max_mi_h": ("wind_gust_kmh", lambda mph: round(mph * 1.60934, 1), "km/h (converted)"),

    # --- New Signal Quality Metrics ---
    "rssi":          ("rssi_dbm", None, " dBm"),
    "snr":           ("snr_db", None, " dB"),
    "noise":         ("noise_dbm", None, " dBm"),
}

def run_sdr_listener():
    """Spawns the rtl_433 C-program and processes its JSON output."""
    
    command = ['rtl_433', '-F', 'json', '-M', 'utc', '-M', 'metric', '-M', 'level']


    print("Starting RTL-SDR Listener...")
    
    db = WeatherDatabase(DB_PATH)
    # We must explicitly set row_factory to sqlite3.Row so get_sensor_map can use string keys
    db.conn.row_factory = sqlite3.Row 
    
    # 1. Load the map ONCE into RAM at boot
    sensor_map = db.get_sensor_map()
    print(f"Loaded Sensor Map from Database: {sensor_map}")
    
    limiter = RateLimiter(interval_seconds=300)
    
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True) as process:
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    data = json.loads(line)
                    
                    # 2. Safely extract the physical ID and cast it to a string
                    raw_id = data.get("id")
                    if raw_id is None:
                        continue
                        
                    sensor_hardware_id = str(raw_id)
                    
                    # 3. Check our RAM cache to see if we care about this sensor
                    if sensor_hardware_id not in sensor_map:
                        continue
                        
                    db_sensor_id = sensor_map[sensor_hardware_id]
                    timestamp = data.get("time")
                    
                    # --- Battery Upsert Logic ---
                    if "battery_ok" in data:
                        battery_status = int(data["battery_ok"])
                        if limiter.should_save(db_sensor_id, "battery_state"):
                            db.update_health(db_sensor_id, battery_status, timestamp)
                            status_text = "OK" if battery_status == 1 else "LOW"
                            print(f"[{timestamp}] Updated Battery Health: {status_text} for Sensor {db_sensor_id}")
                    # ---------------------------------
                    
                    # Iterate through our known dispatch map dynamically
                    for json_key, (db_metric, conversion_func, unit_label) in METRIC_DISPATCH.items():
                        if json_key in data:
                            raw_value = data[json_key]
                            final_value = conversion_func(raw_value) if conversion_func else raw_value
                            
                            if limiter.should_save(db_sensor_id, db_metric):
                                db.insert(db_sensor_id, db_metric, final_value, timestamp)
                                print(f"[{timestamp}] Saved {db_metric}: {final_value}{unit_label} from Sensor {db_sensor_id}")
                                
                except json.JSONDecodeError:
                    continue 
                    
        except KeyboardInterrupt:
            print("\nShutting down SDR listener gracefully...")
        finally:
            db.close()
            process.terminate()

if __name__ == "__main__":
    run_sdr_listener()