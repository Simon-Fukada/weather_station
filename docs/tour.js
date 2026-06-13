import { driver } from 'https://cdn.jsdelivr.net/npm/driver.js@1/dist/driver.js.mjs';

var driverObj = driver({
    animate:        true,
    smoothScroll:   true,
    overlayOpacity: 0.65,
    allowClose:     true,

    onDestroyStarted: function () {
        driverObj.destroy();
    },

    steps: [
        {
            element: '#download-btn',
            popover: {
                title: 'Your data, your way',
                description: 'Every reading logged on the Pi is exportable as an unpivoted CSV — one row per observation across every sensor, ready for Python, R, or Excel. This demo downloads 72 hours of real data from a live installation. In the full app you can export any date range, including everything collected since day one.',
                side: 'bottom',
                align: 'end'
            }
        },
        {
            element: '.zone-dropdown-container',
            popover: {
                title: 'Multiple sensors, one dashboard',
                description: 'Add multiple sensors and switch between them here. The EAV database schema means a new sensor never requires a change to table structure. The demo shows three different sensors.',
                side: 'bottom',
                align: 'center'
            }
        },
        {
            element: '.hero-section',
            popover: {
                title: 'Current conditions',
                description: 'Current temperature for the selected sensor, with its 24-hour low and high, humidity, and dew point. If the sensor transmits via 433 MHz radio, signal health metrics appear below — RSSI measures signal strength, Noise is background radio interference, and SNR is the ratio between them.',
                side: 'bottom',
                align: 'center'
            }
        },
        {
            element: '.global-telemetry',
            popover: {
                title: 'Station-wide metrics',
                description: 'Pressure, wind, and rain come from whichever sensor provides them — independent of the zone selected above. Barometric pressure is corrected to sea level using the station\'s elevation and current temperature, so the reading is directly comparable to weather forecasts.',
                side: 'top',
                align: 'center'
            }
        },
        {
            element: '.chart-container',
            popover: {
                title: '72-hour temperature history',
                description: 'Temperature and dew point over the last 72 hours. When the two lines converge you\'re approaching 100% relative humidity. Blue vertical bands mark periods of detected rainfall; darker bands indicate higher accumulation rates.',
                side: 'top',
                align: 'center'
            }
        },
        {
            element: '.sparkline-container',
            popover: {
                title: 'Pressure trend and storm alerts',
                description: 'A continuous 72-hour raw pressure trace. This shows your sensors raw readings, focusing on the pressure trend over time. Coloured segments indicate drops. Blue vertical bands mark periods of detected rainfall; darker bands indicate higher accumulation rates.',
                side: 'top',
                align: 'center',
                onNextClick: function () {
                    driverObj.destroy();
                }
            }
        }
    ]
});

var tourBtn = document.getElementById('tour-btn');
if (tourBtn) {
    tourBtn.addEventListener('click', function () {
        if (driverObj.isActive()) { return; }
        driverObj.drive();
    });
}
