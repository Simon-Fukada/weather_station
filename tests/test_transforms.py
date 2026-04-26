import pytest
from api.transforms import process_pressure_trend


def _make_grid(pressures):
    """Minimal metric_grid from a list of pressure values (or None for gaps)."""
    return [
        {
            "timestamp": "2026-04-01 {:02d}:{:02d}:00".format((i * 5) // 60, (i * 5) % 60),
            "pressure_hpa": p,
        }
        for i, p in enumerate(pressures)
    ]


def test_no_alert_when_pressure_stable():
    grid = _make_grid([1013.0] * 40)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(point["alert"] == 'none' for point in trend)


def test_fast_alert_triggered_by_3hpa_drop_in_3h():
    # 36 buckets at 1013 then 4 at 1009 — 4 hPa drop in 3 h exceeds fast threshold
    grid = _make_grid([1013.0] * 36 + [1009.0] * 4)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(trend[i]["alert"] == 'none' for i in range(36))
    assert all(trend[i]["alert"] == 'fast' for i in range(36, 40))


def test_no_alert_for_drop_below_fast_threshold():
    # Drop of 1 hPa in 3 h — below both thresholds
    grid = _make_grid([1013.0] * 36 + [1012.0] * 4)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(point["alert"] == 'none' for point in trend)


def test_slow_alert_triggered_by_4hpa_drop_in_12h():
    # Linear 4 hPa drop spread evenly over 144 buckets (12 h).
    # Each 3-hour window only sees ~1 hPa — below the fast threshold.
    # The full 12-hour window sees exactly 4 hPa — meets the slow threshold.
    values = [1013.0 - (i * 4.0 / 144) for i in range(145)]
    grid = _make_grid(values)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(trend[i]["alert"] == 'none' for i in range(144))
    assert trend[144]["alert"] == 'slow'


def test_fast_takes_priority_over_slow():
    # A 4 hPa drop in 3 h also satisfies the 12 h window — should be 'fast', not 'slow'
    grid = _make_grid([1013.0] * 144 + [1009.0] * 4)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(trend[i]["alert"] == 'fast' for i in range(144, 148))


def test_no_alert_when_lookback_is_none():
    # Gap at the fast lookback position — cannot determine drop, so no alert
    grid = _make_grid([None] * 36 + [1009.0] * 4)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all(point["alert"] == 'none' for point in trend)


def test_alert_field_present_on_all_points():
    grid = _make_grid([1013.0] * 10)
    trend, _ = process_pressure_trend(grid, 1013.0)
    assert all("alert" in point for point in trend)
