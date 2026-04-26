import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

import weather_math
from api import transforms
from config import DB_PATH, FRONTEND_PATH
from db_access import reader
from metrics import Metric

load_dotenv()

ELEVATION_M = float(os.getenv("STATION_ELEVATION", 0))

# Populated once at startup — maps metric name string to its metric_types.id integer.
# All reader calls that filter by metric type use these IDs, not string literals.
METRIC_IDS: dict = {}


def _load_metric_ids() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        stored = [(m.value,) for m in Metric if m is not Metric.DEW_POINT_C]
        conn.executemany("INSERT OR IGNORE INTO metric_types (name) VALUES (?)", stored)
        conn.commit()
        rows = conn.execute("SELECT id, name FROM metric_types").fetchall()
        METRIC_IDS.update({row["name"]: row["id"] for row in rows})
    finally:
        conn.close()


def _epoch_to_iso(epoch: int) -> str:
    """Converts a Unix epoch integer to a UTC ISO timestamp string for API responses."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_metric_ids()
    yield


app = FastAPI(title="Weather Station API", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _rf_trend_arrow(rf_trends: dict, metric_key: str) -> str:
    metric_data = rf_trends.get(metric_key)
    if not metric_data or metric_data["current"] is None or metric_data["past"] is None:
        return "➖"

    diff = metric_data["current"] - metric_data["past"]
    if diff > 0:
        return "⬆️"
    if diff < 0:
        return "⬇️"
    return "➖"


@app.get("/api/sensors")
def get_all_sensors(conn: sqlite3.Connection = Depends(get_db)):
    rows = reader.get_all_sensors(conn)
    return [dict(row) for row in rows]


@app.get("/api/readings/current/{sensor_id}")
def get_current_reading(sensor_id: int, conn: sqlite3.Connection = Depends(get_db)):
    current_rows = reader.get_latest_sensor_readings(conn, sensor_id)

    if not current_rows:
        raise HTTPException(status_code=404, detail="No readings found.")

    data = {
        "sensor_id": sensor_id,
        "timestamp": _epoch_to_iso(current_rows[0]["timestamp"]),
    }
    for row in current_rows:
        data[row["metric_type"]] = round(row["value"], 1)

    if Metric.TEMPERATURE_C in data and Metric.HUMIDITY_PCT in data:
        data[Metric.DEW_POINT_C] = weather_math.calculate_dew_point(
            data[Metric.TEMPERATURE_C], data[Metric.HUMIDITY_PCT]
        )

    extremes = reader.get_24h_extremes(conn, sensor_id, METRIC_IDS[Metric.TEMPERATURE_C])
    data["temp_high_24h"] = round(extremes["high"], 1) if extremes and extremes["high"] is not None else data.get(Metric.TEMPERATURE_C)
    data["temp_low_24h"] = round(extremes["low"], 1) if extremes and extremes["low"] is not None else data.get(Metric.TEMPERATURE_C)

    health_row = reader.get_sensor_health(conn, sensor_id)
    data["battery_ok"] = health_row["battery_ok"] if health_row else None

    rf_trends = reader.get_rf_trend_data(
        conn, sensor_id,
        METRIC_IDS[Metric.RSSI_DBM],
        METRIC_IDS[Metric.NOISE_DBM],
        METRIC_IDS[Metric.SNR_DB],
    )
    data["rssi_trend"] = _rf_trend_arrow(rf_trends, Metric.RSSI_DBM)
    data["noise_trend"] = _rf_trend_arrow(rf_trends, Metric.NOISE_DBM)
    data["snr_trend"] = _rf_trend_arrow(rf_trends, Metric.SNR_DB)

    return data


@app.get("/api/fixed_sensors")
def get_fixed_sensor_data(sensor_id: int = 1, conn: sqlite3.Connection = Depends(get_db)):
    pressure_row = reader.get_latest_global_metric(conn, METRIC_IDS[Metric.PRESSURE_HPA])
    current_pressure = pressure_row["value"] if pressure_row else None
    pressure_timestamp = _epoch_to_iso(pressure_row["timestamp"]) if pressure_row else None

    temp_row = reader.get_latest_single_metric(conn, sensor_id, METRIC_IDS[Metric.TEMPERATURE_C])
    current_temp = temp_row["value"] if temp_row else None

    trend_rows = reader.get_pivoted_trend(
        conn,
        {Metric.PRESSURE_HPA: METRIC_IDS[Metric.PRESSURE_HPA],
         Metric.RAIN_MM:      METRIC_IDS[Metric.RAIN_MM]},
        hours_back=72,
    )
    raw_wind_72h = reader.get_recent_wind_vectors(
        conn,
        METRIC_IDS[Metric.WIND_KMH],
        METRIC_IDS[Metric.WIND_DIR_DEG],
        minutes_back=4320,
    )
    live_wind, wind_history     = transforms.process_wind_history(raw_wind_72h)
    max_gust                    = reader.get_global_max_wind_gust(conn, METRIC_IDS[Metric.WIND_GUST_KMH])
    rain_24h                    = reader.get_global_rain_total(conn, METRIC_IDS[Metric.RAIN_MM], hours_back=24)

    mslp           = weather_math.calculate_mslp(current_pressure, current_temp, ELEVATION_M)
    metric_grid    = transforms.build_metric_grid(trend_rows, hours_back=72)
    trend_data, pressure_avg = transforms.process_pressure_trend(metric_grid, current_pressure)
    wind_direction_history   = transforms.process_wind_direction_history(raw_wind_72h)
    rain_trend_72h           = [bucket.get(Metric.RAIN_MM) for bucket in metric_grid]

    for point in trend_data:
        point["timestamp"] = _epoch_to_iso(point["timestamp"])

    return {
        "mslp_hpa":                 mslp,
        "pressure_trend_72h":       trend_data,
        "pressure_average_72h":     pressure_avg,
        "pressure_timestamp":       pressure_timestamp,
        "wind_sustained_kmh":       live_wind["speed"],
        "wind_cardinal":            live_wind["cardinal"],
        "wind_direction_deg":       live_wind["direction"],
        "wind_history":             wind_history,
        "wind_gust_kmh":            max_gust,
        "rain_24h_mm":              rain_24h,
        "wind_direction_history_72h": wind_direction_history,
        "rain_trend_72h":           rain_trend_72h,
    }


@app.get("/api/readings/history/{sensor_id}")
def get_historical_readings(sensor_id: int, hours: int = 72, conn: sqlite3.Connection = Depends(get_db)):
    rows = reader.get_pivoted_trend(
        conn,
        {Metric.TEMPERATURE_C: METRIC_IDS[Metric.TEMPERATURE_C],
         Metric.HUMIDITY_PCT:  METRIC_IDS[Metric.HUMIDITY_PCT]},
        hours_back=hours,
        sensor_id=sensor_id,
    )
    history_grid = transforms.build_metric_grid(rows, hours_back=hours)
    history = transforms.process_historical_readings(history_grid)

    for point in history:
        point["timestamp"] = _epoch_to_iso(point["timestamp"])

    return history


app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
