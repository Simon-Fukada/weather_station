from setuptools import setup, find_packages

setup(
    name="weather_station",
    version="1.0.0",
    packages=find_packages(),
    py_modules=["weather_math", "config"],  # Explicitly include standalone root modules
)
