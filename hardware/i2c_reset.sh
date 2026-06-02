#!/bin/bash
# Resets the I2C-1 adapter by unbinding and rebinding the DesignWare driver.
# Must be run as root. Called by bme280_reader.py as a last-resort recovery step.
DEVICE="1f00074000.i2c"
DRIVER="/sys/bus/platform/drivers/i2c_designware"

echo "$DEVICE" > "$DRIVER/unbind" || exit 1
sleep 0.3
echo "$DEVICE" > "$DRIVER/bind"  || exit 1
