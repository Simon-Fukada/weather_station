from pathlib import Path

# 1. Dynamically find the absolute path to the root folder containing this config.py file
ROOT_DIR = Path(__file__).resolve().parent

# 2. Build the database path using clean division operators
DB_PATH = str(ROOT_DIR / 'data' / 'weather_data.db')
FRONTEND_PATH = str(ROOT_DIR / 'frontend')
# (Optional: You can move I2C_PORT and MAX_RETRIES from bme280_reader.py here in the future!)