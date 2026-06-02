import csv
import io
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

import weather_math
from api import transforms
from config import DB_PATH, FRONTEND_PATH
from db_access import reader
from db_access.metrics import build_metric_enum

# Built once at startup from the metric_types table.
# Metric.TEMPERATURE_C.id gives the integer FK used in all reader calls.
Metric = None


def _initialize_metrics() -> None:
    global Metric
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        Metric = build_metric_enum(conn)
    finally:
        conn.close()


def _epoch_to_iso(epoch: int) -> str:
    """Converts a Unix epoch integer to a UTC ISO timestamp string for API responses."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class SelectiveGZipMiddleware:
    """Applies GZip compression to all responses except the CSV export endpoint,
    where streaming must not be buffered."""
    def __init__(self, app: ASGIApp, minimum_size: int = 500) -> None:
        self.app = app
        self.gzip_app = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/api/export/csv":
            await self.app(scope, receive, send)
        else:
            await self.gzip_app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _initialize_metrics()
    yield


app = FastAPI(title="Weather Station API", lifespan=lifespan)
app.add_middleware(SelectiveGZipMiddleware, minimum_size=500)


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

    extremes = reader.get_24h_extremes(conn, sensor_id, Metric.TEMPERATURE_C.id)
    data["temp_high_24h"] = round(extremes["high"], 1) if extremes and extremes["high"] is not None else data.get(Metric.TEMPERATURE_C)
    data["temp_low_24h"] = round(extremes["low"], 1) if extremes and extremes["low"] is not None else data.get(Metric.TEMPERATURE_C)

    health_row = reader.get_sensor_health(conn, sensor_id)
    data["battery_ok"] = health_row["battery_ok"] if health_row else None

    rf_trends = reader.get_rf_trend_data(
        conn, sensor_id,
        Metric.RSSI_DBM.id,
        Metric.NOISE_DBM.id,
        Metric.SNR_DB.id,
    )
    data["rssi_trend"] = _rf_trend_arrow(rf_trends, Metric.RSSI_DBM)
    data["noise_trend"] = _rf_trend_arrow(rf_trends, Metric.NOISE_DBM)
    data["snr_trend"] = _rf_trend_arrow(rf_trends, Metric.SNR_DB)

    return data


@app.get("/api/fixed_sensors")
def get_fixed_sensor_data(sensor_id: int = 1, conn: sqlite3.Connection = Depends(get_db)):
    pressure_row = reader.get_latest_global_metric(conn, Metric.PRESSURE_HPA.id)
    current_pressure = pressure_row["value"] if pressure_row else None
    pressure_timestamp = _epoch_to_iso(pressure_row["timestamp"]) if pressure_row else None

    temp_row = reader.get_latest_single_metric(conn, sensor_id, Metric.TEMPERATURE_C.id)
    current_temp = temp_row["value"] if temp_row else None

    trend_rows = reader.get_pivoted_trend(
        conn,
        {Metric.PRESSURE_HPA: Metric.PRESSURE_HPA.id,
         Metric.RAIN_MM:      Metric.RAIN_MM.id},
        hours_back=72,
    )
    raw_wind_72h = reader.get_recent_wind_vectors(
        conn,
        Metric.WIND_KMH.id,
        Metric.WIND_DIR_DEG.id,
        minutes_back=4320,
    )
    live_wind, wind_history     = transforms.process_wind_history(raw_wind_72h)
    max_gust                    = reader.get_global_max_wind_gust(conn, Metric.WIND_GUST_KMH.id)
    rain_24h                    = reader.get_global_rain_total(conn, Metric.RAIN_MM.id, hours_back=24)

    elevation_m = reader.get_sensor_elevation(conn, pressure_row["sensor_id"]) if pressure_row else None
    if current_pressure is not None and elevation_m is not None and current_temp is not None:
        mslp = weather_math.calculate_mslp(current_pressure, current_temp, elevation_m)
        mslp_corrected = True
    elif current_pressure is not None:
        mslp = current_pressure
        mslp_corrected = False
    else:
        mslp = None
        mslp_corrected = False

    metric_grid    = transforms.build_metric_grid(trend_rows, hours_back=72)
    trend_data, pressure_avg = transforms.process_pressure_trend(metric_grid, current_pressure)
    wind_direction_history   = transforms.process_wind_direction_history(raw_wind_72h)
    rain_trend_72h           = [bucket.get(Metric.RAIN_MM) for bucket in metric_grid]

    for point in trend_data:
        point["timestamp"] = _epoch_to_iso(point["timestamp"])

    return {
        "mslp_hpa":                 mslp,
        "mslp_corrected":           mslp_corrected,
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
        {Metric.TEMPERATURE_C: Metric.TEMPERATURE_C.id,
         Metric.HUMIDITY_PCT:  Metric.HUMIDITY_PCT.id},
        hours_back=hours,
        sensor_id=sensor_id,
    )
    history_grid = transforms.build_metric_grid(rows, hours_back=hours)
    history = transforms.process_historical_readings(history_grid, Metric)

    for point in history:
        point["timestamp"] = _epoch_to_iso(point["timestamp"])

    return history


_EXPORT_PRESETS = {
    "24h": 24 * 3600,
    "7d":  7  * 24 * 3600,
    "30d": 30 * 24 * 3600,
}
_CSV_BATCH_SIZE = 300


@app.get("/api/export/csv")
def export_csv(
    date_range: Optional[str] = Query(default="7d", alias="range"),
    from_date:  Optional[str] = Query(default=None),
    to_date:    Optional[str] = Query(default=None),
):
    now = int(datetime.now(timezone.utc).timestamp())

    if from_date or to_date:
        try:
            ts_from = int(datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            ts_to   = int(datetime.strptime(to_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 86399
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Use YYYY-MM-DD for from_date and to_date.")
        filename = f"weather_data_{from_date}_to_{to_date}.csv"
    elif date_range == "all":
        ts_from, ts_to = 0, now
        filename = "weather_data_all.csv"
    elif date_range in _EXPORT_PRESETS:
        ts_from = now - _EXPORT_PRESETS[date_range]
        ts_to   = now
        filename = f"weather_data_last_{date_range}.csv"
    else:
        raise HTTPException(status_code=400, detail="range must be 24h, 7d, 30d, or all.")

    def generate():
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "timestamp_utc", "timestamp_epoch", "timezone",
                "sensor_id", "sensor_name", "location",
                "latitude", "longitude", "elevation_m",
                "metric", "value",
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            batch_count = 0
            for row in reader.get_export_readings(conn, ts_from, ts_to):
                writer.writerow([
                    _epoch_to_iso(row["timestamp"]),
                    row["timestamp"],
                    row["timezone"]    or "",
                    row["sensor_id"],
                    row["sensor_name"],
                    row["location"]    or "",
                    row["latitude"]    if row["latitude"]    is not None else "",
                    row["longitude"]   if row["longitude"]   is not None else "",
                    row["elevation_m"] if row["elevation_m"] is not None else "",
                    row["metric"],
                    row["value"],
                ])
                batch_count += 1
                if batch_count >= _CSV_BATCH_SIZE:
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)
                    batch_count = 0

            if batch_count:
                yield buf.getvalue()
        finally:
            conn.close()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
