/**
 * @jest-environment jsdom
 */

const fs = require('fs');
const path = require('path');

// --- Mocks (must be set up before eval'ing app.js) ---

global.fetch = jest.fn().mockImplementation(() => Promise.resolve({
    json: () => Promise.resolve([])
}));

// Chart mock includes data/options shapes that the update path writes into.
// Without these, drawZoneChart's "update existing instance" branch throws on
// every test and the error is silently swallowed by the try/catch in the async
// functions, producing confusing console.error noise.
global.Chart = jest.fn().mockImplementation(() => ({
    destroy: jest.fn(),
    update: jest.fn(),
    chart: { ctx: {} },
    controller: {
        getDatasetMeta: jest.fn().mockReturnValue({
            data: [{ _model: { y: 50 } }]
        })
    },
    data: {
        labels: [],
        // 5 entries: normal, gradual-alert, slow-alert, fast-alert, average line
        datasets: [{ data: [] }, { data: [] }, { data: [] }, { data: [] }, { data: [] }]
    },
    options: {
        scales: {
            yAxes: [{ ticks: { suggestedMin: 0, suggestedMax: 100 } }]
        },
        animation: { onComplete: null }
    },
    scales: { 'yTemp': { top: 0, bottom: 100 } },
    rainTrend: [],
    width: 100,
    height: 100,
}));
global.Chart.helpers = {
    fontString: jest.fn().mockReturnValue('12px sans-serif')
};

HTMLCanvasElement.prototype.getContext = jest.fn().mockReturnValue({
    fillText: jest.fn(),
    measureText: jest.fn().mockReturnValue({ width: 0 }),
    save: jest.fn(),
    restore: jest.fn(),
    rotate: jest.fn(),
    translate: jest.fn(),
    beginPath: jest.fn(),
    moveTo: jest.fn(),
    lineTo: jest.fn(),
    stroke: jest.fn(),
    fillRect: jest.fn(),
});

const localStorageMock = (function() {
    let store = {};
    return {
        getItem: (key) => store[key] || null,
        setItem: (key, value) => { store[key] = value.toString(); },
        clear: () => { store = {}; }
    };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// --- DOM shell ---

document.body.innerHTML = `
    <div id="ui-pressure"></div>
    <div id="ui-wind"></div>
    <div id="ui-gust"></div>
    <div id="ui-rain"></div>
    <div id="ui-pressure-time"></div>
    <div id="ui-time"></div>
    <canvas id="pressure-sparkline"></canvas>

    <div id="ui-zone-name"></div>
    <div id="ui-temp"></div>
    <div id="ui-high"></div>
    <div id="ui-low"></div>
    <div id="ui-humidity"></div>
    <div id="ui-dewpoint"></div>
    <div id="sensor-read-time" style="display: none;"></div>
    <div id="ui-battery-warning" style="display: none;"></div>
    <canvas id="zone-chart"></canvas>

    <div id="ui-rssi"></div><div id="ui-rssi-trend"></div>
    <div id="ui-noise"></div><div id="ui-noise-trend"></div>
    <div id="ui-snr"></div><div id="ui-snr-trend"></div>

    <select id="sensor-dropdown"></select>

    <!-- Download modal stubs — required so the IIFE in app.js can attach its
         event listeners without crashing. These elements are not exercised by
         any test; they merely keep the module from throwing at eval time. -->
    <div id="download-modal-overlay"></div>
    <button id="unit-toggle-btn"></button>
    <button id="download-btn"></button>
    <button id="modal-close-btn"></button>
    <button id="download-csv-btn"></button>
    <button class="preset-chip active" data-preset="7d"></button>
    <div id="custom-date-inputs"></div>
    <input type="date" id="date-from">
    <input type="date" id="date-to">
`;

eval(fs.readFileSync(path.resolve(__dirname, 'app.js'), 'utf8'));

// --- Tests ---

describe('Weather Station Frontend (app.js)', () => {

    beforeEach(() => {
        jest.clearAllMocks();
    });

    // -------------------------------------------------------------------------
    describe('Pure Helper Functions', () => {

        describe('safeFallback', () => {
            test('returns value with unit when value is present', () => {
                expect(safeFallback(25.5, '°C')).toBe('25.5°C');
                expect(safeFallback(1013, ' hPa')).toBe('1013 hPa');
            });

            test('returns "--" for null or undefined', () => {
                expect(safeFallback(null, '°C')).toBe('--');
                expect(safeFallback(undefined, '°C')).toBe('--');
            });

            test('returns raw value when no unit is provided', () => {
                expect(safeFallback(42)).toBe(42);
                expect(safeFallback('text')).toBe('text');
            });

            test('treats zero as a valid value, not a fallback', () => {
                // 0 is falsy — this guards against accidental `if (val)` style checks
                expect(safeFallback(0, ' hPa')).toBe('0 hPa');
            });
        });

        describe('parseUtcTimestamp', () => {
            test('parses API timestamp string as UTC', () => {
                const date = parseUtcTimestamp('2026-03-20 14:00:00');
                expect(date).toBeInstanceOf(Date);
                expect(date.getUTCFullYear()).toBe(2026);
                expect(date.getUTCMonth()).toBe(2); // 0-indexed
                expect(date.getUTCDate()).toBe(20);
                expect(date.getUTCHours()).toBe(14);
                expect(date.getUTCMinutes()).toBe(0);
            });

            test('midnight parses correctly without rolling back a day', () => {
                const date = parseUtcTimestamp('2026-01-01 00:00:00');
                expect(date.getUTCDate()).toBe(1);
                expect(date.getUTCHours()).toBe(0);
            });
        });

        describe('formatChartLabelTime', () => {
            test('returns 24-hour HH:MM string', () => {
                const label = formatChartLabelTime('2026-03-20 14:30:00');
                // Only test the format — toLocaleTimeString produces local-timezone
                // output, so the exact value is environment-dependent.
                expect(label).toMatch(/^\d{2}:\d{2}$/);
            });
        });

        describe('formatDateTime', () => {
            test('handles API timestamp strings', () => {
                const formatted = formatDateTime('2026-03-20 14:00:00');
                expect(formatted).not.toBe('--:--');
                expect(formatted.length).toBeGreaterThan(5);
            });

            test('handles live Date objects', () => {
                expect(formatDateTime(new Date())).not.toBe('--:--');
            });

            test('returns "--:--" for null, undefined, and empty string', () => {
                expect(formatDateTime(null)).toBe('--:--');
                expect(formatDateTime(undefined)).toBe('--:--');
                expect(formatDateTime('')).toBe('--:--');
            });
        });

        describe('windAngularDiff', () => {
            test('returns absolute difference for simple cases', () => {
                expect(windAngularDiff(0, 90)).toBe(90);
                expect(windAngularDiff(180, 90)).toBe(90);
            });

            test('takes the short path across the 0/360 boundary', () => {
                // 350° and 10° are only 20° apart via the wrap, not 340°
                expect(windAngularDiff(350, 10)).toBe(20);
                expect(windAngularDiff(10, 350)).toBe(20);
            });

            test('returns 0 for identical directions', () => {
                expect(windAngularDiff(45, 45)).toBe(0);
            });

            test('returns 180 for opposite directions', () => {
                expect(windAngularDiff(0, 180)).toBe(180);
            });
        });

        describe('calculateChartBounds', () => {
            test('calculates correct min/max with padding', () => {
                const bounds = calculateChartBounds([10, 20, 30], 5);
                expect(bounds.suggestedMin).toBe(8.5);
                expect(bounds.suggestedMax).toBe(31.5);
            });

            test('enforces minSpan for tight data', () => {
                const bounds = calculateChartBounds([20, 20.1], 10);
                expect(bounds.suggestedMax - bounds.suggestedMin).toBe(10);
            });

            test('returns a safe default for empty input', () => {
                const bounds = calculateChartBounds([], 5);
                expect(bounds.suggestedMin).toBe(-10);
                expect(bounds.suggestedMax).toBe(10);
            });

            test('returns a safe default for null input', () => {
                const bounds = calculateChartBounds(null, 5);
                expect(bounds.suggestedMin).toBe(-10);
                expect(bounds.suggestedMax).toBe(10);
            });
        });

        describe('splitPressureData', () => {
            test('all normal when no alerts', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([
                    { value: 1013, alert: 'none' },
                    { value: 1012, alert: 'none' }
                ]);
                expect(normalData).toEqual([1013, 1012]);
                expect(slowAlertData).toEqual([null, null]);
                expect(fastAlertData).toEqual([null, null]);
            });

            test('returns three empty arrays for empty input', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([]);
                expect(normalData).toEqual([]);
                expect(slowAlertData).toEqual([]);
                expect(fastAlertData).toEqual([]);
            });

            test('slow alert populates slowAlertData', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([
                    { value: 1010, alert: 'slow' },
                    { value: 1009, alert: 'slow' }
                ]);
                expect(normalData).toEqual([1010, null]);
                expect(slowAlertData).toEqual([1010, 1009]);
                expect(fastAlertData).toEqual([null, null]);
            });

            test('fast alert populates fastAlertData', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([
                    { value: 1010, alert: 'fast' },
                    { value: 1009, alert: 'fast' }
                ]);
                expect(normalData).toEqual([1010, null]);
                expect(slowAlertData).toEqual([null, null]);
                expect(fastAlertData).toEqual([1010, 1009]);
            });

            test('bridge point appears in both datasets at none-to-slow transition', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([
                    { value: 1013, alert: 'none' },
                    { value: 1010, alert: 'slow' },
                    { value: 1009, alert: 'slow' }
                ]);
                expect(normalData).toEqual([1013, 1010, null]);   // 1010 is the bridge
                expect(slowAlertData).toEqual([null, 1010, 1009]); // 1010 is the bridge
                expect(fastAlertData).toEqual([null, null, null]);
            });

            test('bridge point appears in both datasets at slow-to-fast transition', () => {
                const { normalData, slowAlertData, fastAlertData } = splitPressureData([
                    { value: 1011, alert: 'slow' },
                    { value: 1009, alert: 'fast' },
                    { value: 1008, alert: 'fast' }
                ]);
                // NOTE: normalData[0] = 1011 because prev defaults to 'none' at i=0 —
                // a series starting in an alert state leaks a solitary point into normalData.
                // Harmless with pointRadius: 0 but arguably a bug. Flagged for follow-up.
                expect(normalData).toEqual([1011, null, null]);
                expect(slowAlertData).toEqual([1011, 1009, null]); // 1009 is the bridge out
                expect(fastAlertData).toEqual([null, 1009, 1008]); // 1009 is the bridge in
            });

            test('treats missing or falsy alert field as none', () => {
                const { normalData } = splitPressureData([
                    { value: 1013 },
                    { value: 1012, alert: false }
                ]);
                expect(normalData).toEqual([1013, 1012]);
            });
        });

        describe('fmtVal', () => {
            test('converts and formats a valid value', () => {
                expect(fmtVal(10, function(x) { return x * 2; }, 1, ' x')).toBe('20.0 x');
            });

            test('applies the decimal precision argument', () => {
                expect(fmtVal(3.14159, function(x) { return x; }, 2, ' x')).toBe('3.14 x');
            });

            test('returns "--" for null', () => {
                expect(fmtVal(null, function(x) { return x; }, 1, ' x')).toBe('--');
            });

            test('returns "--" for undefined', () => {
                expect(fmtVal(undefined, function(x) { return x; }, 1, ' x')).toBe('--');
            });

            test('treats 0 as a valid value, not a fallback', () => {
                expect(fmtVal(0, function(x) { return x; }, 1, ' x')).toBe('0.0 x');
            });
        });

        describe('fmtTemp (metric)', () => {
            test('shows one decimal when fractional part is non-zero', () => {
                expect(fmtTemp(21.3)).toBe('21.3°');
            });

            test('drops decimal when fractional part is zero', () => {
                expect(fmtTemp(24.0)).toBe('24°');
            });

            test('handles negative temperatures', () => {
                expect(fmtTemp(-5.0)).toBe('-5°');
                expect(fmtTemp(-5.5)).toBe('-5.5°');
            });

            test('returns "--" for null', () => {
                expect(fmtTemp(null)).toBe('--');
            });

            test('returns "--" for undefined', () => {
                expect(fmtTemp(undefined)).toBe('--');
            });
        });
    });

    // -------------------------------------------------------------------------
    describe('DOM Render Functions', () => {

        describe('renderWind', () => {
            test('shows speed when wind data is present', () => {
                renderWind({ wind_sustained_kmh: 15.3 });
                expect(document.getElementById('ui-wind').textContent).toBe('15.3 km/h');
            });

            test('shows dead-calm placeholder when wind data is null', () => {
                renderWind({ wind_sustained_kmh: null });
                expect(document.getElementById('ui-wind').textContent).toBe('-- km/h');
            });

            test('shows dead-calm placeholder when wind data is missing', () => {
                renderWind({});
                expect(document.getElementById('ui-wind').textContent).toBe('-- km/h');
            });
        });

        describe('updateFixedSensorData', () => {
            test('updates pressure, wind, and gust UI from API response', async () => {
                fetch.mockResolvedValueOnce({
                    json: jest.fn().mockResolvedValue({
                        mslp_hpa: 1012.5,
                        wind_sustained_kmh: 12.0,
                        wind_gust_kmh: 18.5,
                        rain_24h_mm: 3.2,
                        pressure_timestamp: '2026-03-20 12:00:00',
                        pressure_trend_72h: [{ timestamp: '2026-03-20 11:00:00', value: 1012, alert: 'none' }],
                        pressure_average_72h: 1011.0
                    })
                });

                await updateFixedSensorData();

                expect(document.getElementById('ui-pressure').textContent).toBe('1012.5 hPa');
                expect(document.getElementById('ui-wind').textContent).toBe('12.0 km/h');
                expect(document.getElementById('ui-gust').textContent).toBe('18.5 km/h');
                expect(document.getElementById('ui-rain').textContent).toBe('3.2 mm');
            });

            test('shows fallback placeholders when data is missing', async () => {
                fetch.mockResolvedValueOnce({
                    json: jest.fn().mockResolvedValue({})
                });

                await updateFixedSensorData();

                expect(document.getElementById('ui-pressure').textContent).toBe('--');
                expect(document.getElementById('ui-wind').textContent).toBe('-- km/h');
            });
        });

        describe('updateSelectedSensorData', () => {
            test('updates zone hero panel with sensor readings', async () => {
                fetch
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({
                        temperature_c: 21.3,
                        temp_high_24h: 24.0,
                        temp_low_24h: 19.5,
                        relative_humidity_pct: 55,
                        dew_point_c: 12.1,
                        timestamp: '2026-03-20 13:45:00',
                        battery_ok: 1
                    })})
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

                await updateSelectedSensorData(1, 'Patio');

                expect(document.getElementById('ui-zone-name').textContent).toBe('Patio');
                expect(document.getElementById('ui-temp').textContent).toBe('21.3°');
                expect(document.getElementById('ui-high').textContent).toBe('24°');
                expect(document.getElementById('ui-low').textContent).toBe('19.5°');
                expect(document.getElementById('ui-humidity').textContent).toBe('55%');
                expect(document.getElementById('ui-dewpoint').textContent).toBe('12.1°');
            });

            test('shows battery warning when battery_ok === 0', async () => {
                fetch
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({ temperature_c: 21.3, battery_ok: 0 }) })
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

                await updateSelectedSensorData(1, 'Patio');

                expect(document.getElementById('ui-battery-warning').style.display).toBe('block');
            });

            test('hides battery warning when battery_ok === 1', async () => {
                fetch
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({ temperature_c: 20.0, battery_ok: 1 }) })
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

                await updateSelectedSensorData(1, 'Patio');

                expect(document.getElementById('ui-battery-warning').style.display).toBe('none');
            });

            test('applies 3-tier SNR colour coding', async () => {
                const run = async (snr_db) => {
                    fetch
                        .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({ snr_db, rssi_dbm: -50, noise_dbm: -80 }) })
                        .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });
                    await updateSelectedSensorData(1, 'Radio');
                    return document.getElementById('ui-snr').style.color;
                };

                expect(await run(5)).toBe('rgb(255, 68, 68)');    // danger  < 10
                expect(await run(15)).toBe('rgb(255, 187, 51)');   // warning < 20
                expect(await run(25)).toBe('rgb(0, 200, 81)');     // good   >= 20
            });

            test('clears RF fields for a wired sensor with no radio data', async () => {
                fetch
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({ temperature_c: 20.0 }) })
                    .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

                await updateSelectedSensorData(1, 'Pi Sensor');

                expect(document.getElementById('ui-rssi').textContent).toBe('--');
                expect(document.getElementById('ui-rssi-trend').textContent).toBe('');
                const snrEl = document.getElementById('ui-snr');
                expect(snrEl.textContent).toBe('--');
                expect(snrEl.style.color).toBe('inherit');
            });
        });

        describe('Imperial unit mode', () => {
            // Click the toggle once before these tests to switch to imperial,
            // then restore metric afterwards so later tests are unaffected.
            beforeAll(async () => {
                document.getElementById('unit-toggle-btn').click();
                await new Promise(function(resolve) { setTimeout(resolve, 0); });
            });

            afterAll(async () => {
                document.getElementById('unit-toggle-btn').click();
                await new Promise(function(resolve) { setTimeout(resolve, 0); });
            });

            describe('fmtTemp (imperial)', () => {
                test('converts °C to °F and drops decimal when zero', () => {
                    expect(fmtTemp(20.0)).toBe('68°');
                });

                test('converts °C to °F and keeps one decimal when non-zero', () => {
                    expect(fmtTemp(20.5)).toBe('68.9°');
                });
            });

            describe('renderWind (imperial)', () => {
                test('shows speed in mph', () => {
                    renderWind({ wind_sustained_kmh: 15.3 });
                    expect(document.getElementById('ui-wind').textContent).toBe('9.5 mph');
                });

                test('shows placeholder in mph when data is null', () => {
                    renderWind({ wind_sustained_kmh: null });
                    expect(document.getElementById('ui-wind').textContent).toBe('-- mph');
                });
            });

            describe('updateFixedSensorData (imperial)', () => {
                test('converts pressure, gust, and rain to imperial units', async () => {
                    fetch.mockResolvedValueOnce({
                        json: jest.fn().mockResolvedValue({
                            mslp_hpa: 1012.5,
                            wind_sustained_kmh: 12.0,
                            wind_gust_kmh: 18.5,
                            rain_24h_mm: 3.2,
                            pressure_timestamp: '2026-03-20 12:00:00',
                            pressure_trend_72h: [],
                            pressure_average_72h: 1011.0
                        })
                    });

                    await updateFixedSensorData();

                    expect(document.getElementById('ui-pressure').textContent).toBe('29.90 inHg');
                    expect(document.getElementById('ui-gust').textContent).toBe('11.5 mph');
                    expect(document.getElementById('ui-rain').textContent).toBe('0.1 in');
                });
            });

            describe('updateSelectedSensorData (imperial)', () => {
                test('converts and displays temperature values in °F', async () => {
                    fetch
                        .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue({
                            temperature_c: 21.3,
                            temp_high_24h: 24.0,
                            temp_low_24h: 19.5,
                            relative_humidity_pct: 55,
                            dew_point_c: 12.1,
                            timestamp: '2026-03-20 13:45:00',
                            battery_ok: 1
                        })})
                        .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

                    await updateSelectedSensorData(1, 'Patio');

                    expect(document.getElementById('ui-temp').textContent).toBe('70.3°');
                    expect(document.getElementById('ui-high').textContent).toBe('75.2°');
                    expect(document.getElementById('ui-low').textContent).toBe('67.1°');
                    expect(document.getElementById('ui-humidity').textContent).toBe('55%');
                    expect(document.getElementById('ui-dewpoint').textContent).toBe('53.8°');
                });
            });
        });

        describe('initializeSensorDropdown', () => {
            test('populates dropdown with sensors from API', async () => {
                fetch.mockResolvedValueOnce({
                    json: jest.fn().mockResolvedValue([
                        { id: 1, location: 'Garden', friendly_name: 'Garden' },
                        { id: 2, location: 'Bedroom', friendly_name: 'Bedroom' }
                    ])
                });

                await initializeSensorDropdown();

                const dropdown = document.getElementById('sensor-dropdown');
                expect(dropdown.options.length).toBe(2);
                expect(dropdown.options[0].text).toBe('Garden');
                expect(dropdown.options[1].text).toBe('Bedroom');
            });

            test('pre-selects the sensor matching state.currentSensorId', async () => {
                // state is a const in eval'd code — it does not leak into test scope,
                // so we cannot mutate it here. State is initialized from localStorage
                // once at eval time (localStorage was empty then), so currentSensorId
                // defaults to DEFAULT_SENSOR_ID = 1. Verify that the dropdown reflects
                // whichever sensor matches that initial state.
                fetch.mockResolvedValueOnce({
                    json: jest.fn().mockResolvedValue([
                        { id: 1, location: 'Garden', friendly_name: 'Garden' },
                        { id: 2, location: 'Bedroom', friendly_name: 'Bedroom' }
                    ])
                });

                await initializeSensorDropdown();

                // Should have selected sensor 1 (the default)
                expect(document.getElementById('sensor-dropdown').value).toBe('1');
            });
        });
    });
});
