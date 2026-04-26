import pytest
from datetime import datetime, timezone

from api.main import _epoch_to_iso, _rf_trend_arrow
from weather_math import calculate_mslp, calculate_dew_point


# --- _epoch_to_iso ---

def test_epoch_to_iso_known_value():
    epoch = int(datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    assert _epoch_to_iso(epoch) == "2026-04-18 12:00:00"


def test_epoch_to_iso_unix_origin():
    assert _epoch_to_iso(0) == "1970-01-01 00:00:00"


# --- _rf_trend_arrow ---

def test_rf_trend_arrow_up():
    trends = {"rssi_dbm": {"current": -60.0, "past": -65.0}}
    assert _rf_trend_arrow(trends, "rssi_dbm") == "⬆️"


def test_rf_trend_arrow_down():
    trends = {"noise_dbm": {"current": -90.0, "past": -88.0}}
    assert _rf_trend_arrow(trends, "noise_dbm") == "⬇️"


def test_rf_trend_arrow_flat():
    trends = {"snr_db": {"current": 30.0, "past": 30.0}}
    assert _rf_trend_arrow(trends, "snr_db") == "➖"


def test_rf_trend_arrow_missing_key():
    assert _rf_trend_arrow({}, "rssi_dbm") == "➖"


def test_rf_trend_arrow_none_value():
    trends = {"rssi_dbm": {"current": None, "past": -65.0}}
    assert _rf_trend_arrow(trends, "rssi_dbm") == "➖"


# --- calculate_mslp (weather_math) ---

def test_calculate_mslp_boundaries():
    assert calculate_mslp(1060.0,   35.0,  -430.5) == 1010.4
    assert calculate_mslp(1020.0,   45.0,   -86.0) == 1010.6
    assert calculate_mslp(1013.25,  15.0,     0.0) == 1013.2
    assert calculate_mslp( 850.0,  -10.0,  1400.0) == 1016.3
    assert calculate_mslp( 650.0,   10.0,  3640.0) ==  991.1


# --- calculate_dew_point (weather_math) ---

def test_calculate_dew_point_boundaries():
    assert calculate_dew_point(20,   50) ==   9.3
    assert calculate_dew_point(25,  100) ==  25.0
    assert calculate_dew_point(20,    0) is None   # 0% humidity → log(0) undefined
    assert calculate_dew_point(-40,  50) == -46.4
