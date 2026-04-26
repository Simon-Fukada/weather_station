from enum import Enum


class Metric(str, Enum):
    TEMPERATURE_C = "temperature_c"
    PRESSURE_HPA  = "pressure_hpa"
    HUMIDITY_PCT  = "humidity_pct"
    DEW_POINT_C   = "dew_point_c"   # calculated at API layer, not stored in readings
    WIND_KMH      = "wind_kmh"
    WIND_DIR_DEG  = "wind_dir_deg"
    WIND_GUST_KMH = "wind_gust_kmh"
    RAIN_MM       = "rain_mm"
    RSSI_DBM      = "rssi_dbm"
    SNR_DB        = "snr_db"
    NOISE_DBM     = "noise_dbm"
