import json
import sqlite3
import subprocess
from datetime import datetime
from typing import Dict

import weather_math
from config import BUCKET_INTERVAL_MINUTES, DB_PATH
from db_access.metrics import build_metric_dispatch, build_metric_enum
from db_access.writer import WeatherWriter
from hardware.utils import snap_to_interval_ceiling


class SensorBuffer:
    """Aggregates high-frequency sensor data and flushes aggregated values to the database."""

    def __init__(self, db: WeatherWriter, Metric):
        self.db = db
        self.Metric = Metric
        self.sensors = {}
        self.seen_packets = set()
        self.rain_odometer = {}

    def add_reading(self, db_sensor_id: int, raw_timestamp: str, data: dict, metric_dispatch: dict):
        packet_signature = (db_sensor_id, raw_timestamp)
        if packet_signature in self.seen_packets:
            return
        self.seen_packets.add(packet_signature)

        if db_sensor_id not in self.sensors:
            self.sensors[db_sensor_id] = {
                "temperature_c": [], "relative_humidity_pct": [],
                "wind_gusts": [], "wind_vectors": [],
                "rain_mm": [], "battery_ok": [],
                "rssi_dbm": [], "snr_db": [], "noise_dbm": []
            }

        buf = self.sensors[db_sensor_id]

        if "battery_ok" in data:
            buf["battery_ok"].append(int(data["battery_ok"]))

        for json_key, (metric_name, conversion_func) in metric_dispatch.items():
            if json_key in data:
                raw_val = data[json_key]
                final_val = conversion_func(raw_val) if conversion_func else raw_val

                if metric_name == self.Metric.WIND_KMH:
                    buf["wind_gusts"].append(final_val)
                elif metric_name == self.Metric.WIND_GUST_KMH:
                    buf["wind_gusts"].append(final_val)
                elif metric_name == self.Metric.RAIN_MM:
                    buf["rain_mm"].append(final_val)
                else:
                    buf[metric_name].append(final_val)

        if "wind_avg_km_h" in data and "wind_dir_deg" in data:
            buf["wind_vectors"].append((data["wind_avg_km_h"], data["wind_dir_deg"]))

    def flush_to_db(self, snapped_timestamp: str):
        for sensor_id, buf in self.sensors.items():
            readings = []

            for metric in [self.Metric.TEMPERATURE_C, self.Metric.HUMIDITY_PCT,
                           self.Metric.RSSI_DBM, self.Metric.SNR_DB, self.Metric.NOISE_DBM]:
                if buf[metric]:
                    avg_val = round(sum(buf[metric]) / len(buf[metric]), 1)
                    readings.append((sensor_id, metric, avg_val, snapped_timestamp))

            if buf["rain_mm"]:
                current_odometer = max(buf["rain_mm"])
                if sensor_id not in self.rain_odometer:
                    self.rain_odometer[sensor_id] = current_odometer
                    rain_delta = 0.0
                else:
                    rain_delta = current_odometer - self.rain_odometer[sensor_id]
                    if rain_delta < 0:
                        rain_delta = current_odometer
                    self.rain_odometer[sensor_id] = current_odometer
                readings.append((sensor_id, self.Metric.RAIN_MM, round(rain_delta, 2), snapped_timestamp))

            if buf["wind_gusts"]:
                max_gust = round(max(buf["wind_gusts"]), 1)
                readings.append((sensor_id, self.Metric.WIND_GUST_KMH, max_gust, snapped_timestamp))

            if buf["wind_vectors"]:
                avg_speed, avg_dir, _ = weather_math.calculate_vector_average(buf["wind_vectors"])
                readings.append((sensor_id, self.Metric.WIND_KMH, avg_speed, snapped_timestamp))
                readings.append((sensor_id, self.Metric.WIND_DIR_DEG, avg_dir, snapped_timestamp))

            if readings:
                self.db.insert_readings_bulk(readings)

            if buf["battery_ok"]:
                worst_battery = min(buf["battery_ok"])
                self.db.update_health(sensor_id, worst_battery, snapped_timestamp)

            print(f"[{snapped_timestamp}] Flushed buffered data for Sensor {sensor_id}", flush=True)

        self.sensors.clear()
        self.seen_packets.clear()


def run_sdr_listener():
    command = ['rtl_433', '-F', 'json', '-M', 'utc', '-M', 'metric', '-M', 'level']
    print("Starting RTL-SDR Listener with In-Memory Buffer...", flush=True)

    db = WeatherWriter(DB_PATH)

    startup_conn = sqlite3.connect(DB_PATH)
    startup_conn.row_factory = sqlite3.Row
    Metric = build_metric_enum(startup_conn)
    metric_dispatch = build_metric_dispatch(startup_conn)
    startup_conn.close()

    sensor_map = db.get_sensor_map()
    print(f"Loaded Sensor Map from Database: {sensor_map}", flush=True)

    buffer = SensorBuffer(db, Metric)
    current_bucket = None

    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    raw_id = data.get("id")
                    if raw_id is None:
                        continue

                    sensor_hardware_id = str(raw_id)
                    if sensor_hardware_id not in sensor_map:
                        continue

                    db_sensor_id = sensor_map[sensor_hardware_id]
                    raw_timestamp = data.get("time")

                    try:
                        dt = datetime.strptime(raw_timestamp, "%Y-%m-%d %H:%M:%S")
                        snapped_timestamp = snap_to_interval_ceiling(dt, BUCKET_INTERVAL_MINUTES).strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    if current_bucket is None:
                        current_bucket = snapped_timestamp
                    elif snapped_timestamp != current_bucket:
                        buffer.flush_to_db(current_bucket)
                        current_bucket = snapped_timestamp

                    buffer.add_reading(db_sensor_id, raw_timestamp, data, metric_dispatch)

                except json.JSONDecodeError:
                    continue

        except KeyboardInterrupt:
            print("\nShutting down SDR listener gracefully...", flush=True)
        finally:
            if current_bucket:
                buffer.flush_to_db(current_bucket)
            db.close()
            process.terminate()
            process.wait(timeout=2)


if __name__ == "__main__":
    run_sdr_listener()
