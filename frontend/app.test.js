/**
 * @jest-environment jsdom
 */

const fs = require('fs');
const path = require('path');

// Mocking global objects BEFORE loading app.js
global.fetch = jest.fn().mockImplementation(() => Promise.resolve({
    json: () => Promise.resolve([])
}));

global.Chart = jest.fn().mockImplementation(() => ({
    destroy: jest.fn(),
    update: jest.fn(),
    chart: { ctx: {} },
    controller: {
        getDatasetMeta: jest.fn().mockReturnValue({
            data: [{ _model: { y: 50 } }]
        })
    },
    width: 100,
    height: 100,
    scales: {
        'yTemp': { top: 0, bottom: 100 }
    }
}));
global.Chart.helpers = {
    fontString: jest.fn().mockReturnValue('12px sans-serif')
};

// Mock Canvas getContext (jsdom doesn't implement it)
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
});

// Mock localStorage
const localStorageMock = (function() {
    let store = {};
    return {
        getItem: (key) => store[key] || null,
        setItem: (key, value) => { store[key] = value.toString(); },
        clear: () => { store = {}; }
    };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Setup the DOM structure required by app.js
document.body.innerHTML = `
    <div id="ui-pressure"></div>
    <div id="ui-wind"></div>
    <div id="ui-gust"></div>
    <div id="ui-pressure-time"></div>
    <div id="ui-time"></div>
    <canvas id="pressure-sparkline"></canvas>
    
    <div id="ui-zone-name"></div>
    <div id="ui-temp"></div>
    <div id="ui-high"></div>
    <div id="ui-low"></div>
    <div id="ui-humidity"></div>
    <div id="ui-dewpoint"></div>
    <div id="ui-stale-warning" style="display: none;"></div>
    <div id="ui-battery-warning" style="display: none;"></div>
    <canvas id="zone-chart"></canvas>
    
    <select id="sensor-dropdown"></select>
`;

// Load the app.js code
const appJsCode = fs.readFileSync(path.resolve(__dirname, 'app.js'), 'utf8');

// Use eval in the global scope to define functions. 
// We wrap it to handle the immediate execution of boot sequence safely.
eval(appJsCode);

describe('Weather Station Frontend (app.js)', () => {
    
    beforeEach(() => {
        jest.clearAllMocks();
    });

    describe('Pure Helper Functions', () => {
        test('safeFallback returns value with unit if value exists', () => {
            expect(safeFallback(25.5, '°C')).toBe('25.5°C');
            expect(safeFallback(1013, ' hPa')).toBe('1013 hPa');
        });

        test('safeFallback returns "--" for null or undefined', () => {
            expect(safeFallback(null, '°C')).toBe('--');
            expect(safeFallback(undefined, '°C')).toBe('--');
        });

        test('formatDateTime handles ISO-like strings and Date objects', () => {
            const dateStr = '2026-03-20 14:00:00';
            const formatted = formatDateTime(dateStr);
            expect(formatted).not.toBe('--:--');
            expect(formatted.length).toBeGreaterThan(5);
            
            const dateObj = new Date();
            expect(formatDateTime(dateObj)).not.toBe('--:--');
        });

        test('formatDateTime returns fallback for missing input', () => {
            expect(formatDateTime(null)).toBe('--:--');
            expect(formatDateTime('')).toBe('--:--');
        });

        test('calculateChartBounds calculates correct min/max with buffer', () => {
            const data = [10, 20, 30]; 
            const bounds = calculateChartBounds(data, 5);
            expect(bounds.suggestedMin).toBe(8.5);
            expect(bounds.suggestedMax).toBe(31.5);
        });

        test('calculateChartBounds respects minSpan for tight data', () => {
            const data = [20, 20.1]; 
            const bounds = calculateChartBounds(data, 10);
            expect(bounds.suggestedMax - bounds.suggestedMin).toBe(10);
        });
    });

    describe('DOM Manipulation Functions', () => {
        test('updateFixedSensorData updates pressure and wind UI', async () => {
            const mockData = {
                mslp_hpa: 1012.5,
                wind_sustained_kmh: 12.0,
                wind_gust_kmh: 18.5,
                pressure_timestamp: '2026-03-20 12:00:00',
                pressure_trend_72h: [{ timestamp: '2026-03-20 11:00:00', value: 1012 }],
                pressure_average_72h: 1011.0
            };

            fetch.mockResolvedValueOnce({
                json: jest.fn().mockResolvedValue(mockData)
            });

            await updateFixedSensorData();

            expect(document.getElementById('ui-pressure').innerText).toBe('1012.5 hPa');
            expect(document.getElementById('ui-wind').innerText).toBe('12 km/h');
            expect(document.getElementById('ui-gust').innerText).toBe('18.5 km/h');
            expect(global.Chart).toHaveBeenCalled();
        });

        test('updateSelectedSensorData updates zone UI and handles battery warning', async () => {
            const currentMock = {
                temperature_c: 21.3,
                temp_high_24h: 24.0,
                temp_low_24h: 19.5,
                humidity_pct: 55,
                dew_point_c: 12.1,
                timestamp: '2026-03-20 13:45:00',
                battery_ok: 0 
            };
            const historyMock = [
                { metric_type: 'temperature_c', value: 21, timestamp: '2026-03-20 13:00:00' },
                { metric_type: 'dew_point_c', value: 12, timestamp: '2026-03-20 13:00:00' }
            ];

            fetch
                .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue(currentMock) }) 
                .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue(historyMock) }); 

            await updateSelectedSensorData(1, 'Patio');

            expect(document.getElementById('ui-zone-name').innerText).toBe('Patio');
            expect(document.getElementById('ui-temp').innerHTML).toBe('21.3°');
            expect(document.getElementById('ui-humidity').innerHTML).toBe('55%');
            
            const batteryWarning = document.getElementById('ui-battery-warning');
            expect(batteryWarning.style.display).toBe('block');
        });

        test('updateSelectedSensorData hides battery warning if battery is OK', async () => {
            const currentMock = {
                temperature_c: 20.0,
                battery_ok: 1 
            };

            fetch
                .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue(currentMock) })
                .mockResolvedValueOnce({ json: jest.fn().mockResolvedValue([]) });

            await updateSelectedSensorData(1, 'Patio');

            const batteryWarning = document.getElementById('ui-battery-warning');
            expect(batteryWarning.style.display).toBe('none');
        });
    });
});
