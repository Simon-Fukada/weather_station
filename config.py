from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

DB_PATH = str(ROOT_DIR / 'data' / 'weather_data.db')
FRONTEND_PATH = str(ROOT_DIR / 'frontend')

# Data collection interval in minutes. Must match the cron schedule for
# bme280_reader.py and the bucket size used by sdr_reader.py.
BUCKET_INTERVAL_MINUTES = 5

# Enable the kernel-level I2C driver reset as a last-resort recovery step.
# Requires hardware/i2c_reset.sh to be configured with the correct device address
# and a passwordless sudo rule (see README). Disabled by default because the reset
# affects all devices on the I2C-1 bus, not just the BME280.
ENABLE_I2C_DRIVER_RESET = True