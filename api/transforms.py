import time

import weather_math
from config import BUCKET_INTERVAL_MINUTES

_FAST_LOOKBACK_BUCKETS = 36    # 3 h at 5-min resolution
_FAST_THRESHOLD_HPA = -3.0     # sharp front: ≤ -3 hPa / 3 h

_SLOW_LOOKBACK_BUCKETS = 144   # 12 h at 5-min resolution
_SLOW_THRESHOLD_HPA = -4.0     # deepening low: ≤ -4 hPa / 12 h

_GRADUAL_LOOKBACK_BUCKETS = 288  # 24 h at 5-min resolution
_GRADUAL_THRESHOLD_HPA = -4.0    # persistent gradual deepening: ≤ -4 hPa / 24 h


def process_wind_history(raw_wind_rows: list, total_minutes: int = 180, interval_minutes: int = 15) -> tuple:
    """
    Buckets raw wind vectors into chronological intervals in a single O(N) pass.
    Returns a tuple: (live_wind_dict, historical_wind_list)
    """
    now = int(time.time())
    buckets = {i: [] for i in range(0, total_minutes, interval_minutes)}

    for row in raw_wind_rows:
        age_minutes = (now - row['timestamp']) / 60.0
        bucket_index = int(age_minutes // interval_minutes) * interval_minutes

        if bucket_index in buckets:
            buckets[bucket_index].append((row['speed'], row['direction']))

    wind_history = []
    for step_minutes in sorted(buckets.keys()):
        bucket_tuples = buckets[step_minutes]
        if bucket_tuples:
            speed, direction, cardinal = weather_math.calculate_vector_average(bucket_tuples)
            if direction is not None:
                wind_history.append({
                    "age_minutes": step_minutes,
                    "direction": direction,
                    "speed": speed,
                    "cardinal": cardinal
                })

    live_wind = next((item for item in wind_history if item["age_minutes"] == 0), {
        "speed": None, "direction": None, "cardinal": "--"
    })

    return live_wind, wind_history


def process_wind_direction_history(raw_wind_rows: list, total_hours: int = 72, interval_hours: int = 6) -> list:
    """
    Buckets raw wind vectors into interval_hours-sized windows over total_hours.
    Returns a list ordered oldest-first (left-to-right on chart), each entry being
    {"direction": degrees_or_None, "speed": kmh_or_None}.
    Always returns exactly total_hours // interval_hours entries.
    """
    now = int(time.time())
    interval_minutes = interval_hours * 60

    buckets = {i: [] for i in range(0, total_hours * 60, interval_minutes)}

    for row in raw_wind_rows:
        age_minutes = (now - row['timestamp']) / 60.0
        bucket_key = int(age_minutes // interval_minutes) * interval_minutes
        if bucket_key in buckets:
            buckets[bucket_key].append((row['speed'], row['direction']))

    # Second loop is only over 12 bucket keys — O(1) — not re-scanning the input.
    # Sorted descending = oldest first = left-to-right chart order.
    result = []
    for age_key in sorted(buckets.keys(), reverse=True):
        tuples = buckets[age_key]
        if tuples:
            speed, direction, _ = weather_math.calculate_vector_average(tuples)
            result.append({"direction": direction, "speed": speed})
        else:
            result.append({"direction": None, "speed": None})

    return result


def build_metric_grid(sql_rows, hours_back: int = 72, interval_minutes: int = BUCKET_INTERVAL_MINUTES) -> list:
    """
    Builds a gap-filled time-series grid from pre-pivoted SQL rows (as returned by get_pivoted_trend).
    Each SQL row becomes a dict keyed by its columns; missing timestamps produce a row with only
    a 'timestamp' key so downstream .get() calls return None — preserving chart gaps.
    Works for any number of metrics: single (pressure) or multi (temperature + humidity).
    Timestamps in the grid are Unix epoch integers, matching the readings table.
    """
    lookup = {row["timestamp"]: dict(row) for row in sql_rows}

    interval_seconds = interval_minutes * 60
    now = int(time.time())
    remainder = now % interval_seconds
    end_epoch = now if remainder == 0 else now + (interval_seconds - remainder)
    start_epoch = end_epoch - hours_back * 3600

    result = []
    current = start_epoch
    while current <= end_epoch:
        entry = lookup.get(current, {"timestamp": current})
        entry["timestamp"] = current
        result.append(entry)
        current += interval_seconds
    return result


def process_pressure_trend(metric_grid: list, fallback_pressure: float) -> tuple:
    """
    Builds the 72 h station-pressure trend for charting and calculates the mean.
    Raw station pressure is used (no MSLP correction) so the diurnal temperature
    cycle does not introduce noise into the historical display. MSLP correction is
    applied only to the current reading shown in the banner.
    Each point is annotated with 'alert': 'fast' (≤ -3 hPa / 3 h, sharp front),
    'slow' (≤ -4 hPa / 12 h, deepening low), or 'none'. Fast takes priority.
    Returns a tuple: (trend_data_list, pressure_average_float)
    """
    trend_data = []
    valid_pressures = []

    for i, bucket in enumerate(metric_grid):
        abs_pressure = bucket.get("pressure_hpa")
        if abs_pressure is not None:
            valid_pressures.append(abs_pressure)

        # Raw station pressure deltas — elevation is constant so no MSLP correction needed.
        # Fast check runs first; if it fires, slow check is skipped (fast takes priority).
        alert = 'none'
        if abs_pressure is not None and i >= _FAST_LOOKBACK_BUCKETS:
            lookback_pressure = metric_grid[i - _FAST_LOOKBACK_BUCKETS].get("pressure_hpa")
            if lookback_pressure is not None and (abs_pressure - lookback_pressure) <= _FAST_THRESHOLD_HPA:
                alert = 'fast'
        if alert == 'none' and abs_pressure is not None and i >= _SLOW_LOOKBACK_BUCKETS:
            lookback_pressure = metric_grid[i - _SLOW_LOOKBACK_BUCKETS].get("pressure_hpa")
            if lookback_pressure is not None and (abs_pressure - lookback_pressure) <= _SLOW_THRESHOLD_HPA:
                alert = 'slow'
        if alert == 'none' and abs_pressure is not None and i >= _GRADUAL_LOOKBACK_BUCKETS:
            lookback_pressure = metric_grid[i - _GRADUAL_LOOKBACK_BUCKETS].get("pressure_hpa")
            if lookback_pressure is not None and (abs_pressure - lookback_pressure) <= _GRADUAL_THRESHOLD_HPA:
                alert = 'gradual'

        trend_data.append({"timestamp": bucket["timestamp"], "value": abs_pressure, "alert": alert})

    pressure_avg = sum(valid_pressures) / len(valid_pressures) if valid_pressures else fallback_pressure
    safe_avg = round(pressure_avg, 1) if pressure_avg is not None else None

    return trend_data, safe_avg


def process_historical_readings(metric_grid: list, Metric) -> list:
    """
    Extracts temperature and calculates dew point from a metric grid.
    Expects buckets with 'timestamp', 'temperature_c', and 'relative_humidity_pct' keys.
    Returns a wide-format list of dicts for frontend charting.
    """
    final_history = []

    for bucket in metric_grid:
        temp = bucket.get(Metric.TEMPERATURE_C)
        hum  = bucket.get(Metric.HUMIDITY_PCT)
        dew_point = weather_math.calculate_dew_point(temp, hum)

        final_history.append({
            "timestamp": bucket["timestamp"],
            "temperature_c": temp,
            "dew_point_c": dew_point
        })

    return final_history
