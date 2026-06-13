// --- 1. Configuration & Constants ---
const BASE_URL = 'static/api';
const DEFAULT_SENSOR_ID = 5;

const WIND_HISTORY_MINUTES = 180;
const MIN_MARKER_ALPHA = 0.08;
const WIND_REVERSAL_THRESHOLD_DEG = 90;

const SNR_DANGER_DB = 10;
const SNR_WARN_DB = 20;
const SNR_COLOR_DANGER = '#ff4444';
const SNR_COLOR_WARN = '#ffbb33';
const SNR_COLOR_GOOD = '#00c851';

const CHART_BOUNDS_PADDING = 1.15;


// --- 2. Module State ---
const state = {
    currentSensorId:   parseInt(localStorage.getItem('preferredSensorId'), 10) || DEFAULT_SENSOR_ID,
    currentSensorName: 'Loading...',
    pressureChart:     null,
    zoneChart:         null,
    rainTrend:         [],
};


// --- 2b. Element Cache ---
// Resolved once at script load (script tag is end-of-body, so the DOM is ready).
// Missing optional elements stay null; call sites already guard with `if (els.xxx)`.
const els = {
    // Macro banner
    pressure:           document.getElementById('ui-pressure'),
    pressureLabel:      document.getElementById('ui-pressure-label'),
    pressureTime:       document.getElementById('ui-pressure-time'),
    wind:               document.getElementById('ui-wind'),
    windCompass:        document.getElementById('ui-wind-compass'),
    windTrailContainer: document.getElementById('ui-wind-trail-container'),
    windHistory:        document.getElementById('ui-wind-history'),
    gust:               document.getElementById('ui-gust'),
    rain:               document.getElementById('ui-rain'),
    time:               document.getElementById('ui-time'),

    // Zone hero
    zoneName:           document.getElementById('ui-zone-name'),
    temp:               document.getElementById('ui-temp'),
    high:               document.getElementById('ui-high'),
    low:                document.getElementById('ui-low'),
    humidity:           document.getElementById('ui-humidity'),
    dewpoint:           document.getElementById('ui-dewpoint'),

    // RF health
    rssi:               document.getElementById('ui-rssi'),
    rssiTrend:          document.getElementById('ui-rssi-trend'),
    noise:              document.getElementById('ui-noise'),
    noiseTrend:         document.getElementById('ui-noise-trend'),
    snr:                document.getElementById('ui-snr'),
    snrTrend:           document.getElementById('ui-snr-trend'),

    // Chrome + warnings
    dropdown:           document.getElementById('sensor-dropdown'),
    pressureCanvas:     document.getElementById('pressure-sparkline'),
    zoneCanvas:         document.getElementById('zone-chart'),
    sensorReadTime:     document.getElementById('sensor-read-time'),
    batteryWarning:     document.getElementById('ui-battery-warning'),
};


// --- 3. Formatting & Chart Helpers ---

/**
 * Returns val (with optional unit suffix) or '--' when val is null/undefined.
 * @param {*} val - The value to display; null/undefined triggers the fallback
 * @param {string} [unit] - Optional suffix, e.g. ' hPa' or '°'
 * @returns {string|*}
 */
function safeFallback(val, unit) {
    if (val !== undefined && val !== null) {
        return unit ? val + unit : val;
    }
    return '--';
}

/**
 * Parses an API timestamp string as UTC. The Python readers emit "YYYY-MM-DD HH:MM:SS"
 * with no T separator and no timezone — this normalises it before constructing a Date.
 * @param {string} s
 * @returns {Date}
 */
function parseUtcTimestamp(s) {
    return new Date(s.replace(' ', 'T') + 'Z');
}

/**
 * Formats an API timestamp string as a 24-hour HH:MM label for chart x-axes.
 * @param {string} s - API timestamp in "YYYY-MM-DD HH:MM:SS" format
 * @returns {string} e.g. "14:30"
 */
function formatChartLabelTime(s) {
    return parseUtcTimestamp(s).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
}

/**
 * Formats a timestamp for display in UI banners. Accepts either an API timestamp
 * string or a live Date object; returns '--:--' when input is falsy.
 * @param {string|Date} input
 * @returns {string} e.g. "Mar 20, 2:30 PM"
 */
function formatDateTime(input) {
    if (!input) return '--:--';
    const date = typeof input === 'string' ? parseUtcTimestamp(input) : input;
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

// DRY abstraction for the shared chronological X-Axis
function getSharedXAxis() {
    return [{
        display: true,
        position: 'top',
        gridLines: {
            display: true,
            color: '#333333',
            drawBorder: false,
            zeroLineColor: '#333333'
        },
        ticks: {
            fontColor: '#A0A0A0',
            fontSize: 10,
            autoSkip: false,
            maxRotation: 0,
            callback: function(value, index, values) {
                const len = values.length;
                if (len === 0) return null;
                if (index === 0) return '-72h';
                if (index === Math.floor(len / 3)) return '-48h';
                if (index === Math.floor((len * 2) / 3)) return '-24h';
                if (index === len - 1) return 'Now';
                return null;
            }
        }
    }];
}

/**
 * Splits a flat pressure trend into three parallel arrays for Chart.js multi-colour
 * line rendering (normal / slow-alert / fast-alert). Each state-transition boundary
 * is included in both adjacent arrays to draw a seamless visual bridge between colours.
 * @param {{ value: number, alert: 'none'|'slow'|'fast', timestamp: string }[]} trendArray
 * @returns {{ normalData: (number|null)[], slowAlertData: (number|null)[], fastAlertData: (number|null)[] }}
 */
function splitPressureData(trendArray) {
    const normalData = [];
    const gradualAlertData = [];
    const slowAlertData = [];
    const fastAlertData = [];

    for (let i = 0; i < trendArray.length; i++) {
        const point = trendArray[i];
        const cur = point.alert || 'none';
        const prev = i > 0 ? (trendArray[i - 1].alert || 'none') : 'none';

        // A point is included in a state's dataset if it IS that state, or if it is the
        // first point after leaving that state — creating a visual bridge at each transition.
        normalData.push(cur === 'none' || prev === 'none' ? point.value : null);
        gradualAlertData.push(cur === 'gradual' || prev === 'gradual' ? point.value : null);
        slowAlertData.push(cur === 'slow' || prev === 'slow' ? point.value : null);
        fastAlertData.push(cur === 'fast' || prev === 'fast' ? point.value : null);
    }

    return { normalData, gradualAlertData, slowAlertData, fastAlertData };
}

/**
 * Calculates padded y-axis bounds centred on the dataset's range, enforcing a
 * minimum visible span so a flat line doesn't fill the entire chart height.
 * @param {number[]} data - Flat array of numeric readings
 * @param {number} minSpan - Minimum axis range to enforce
 * @returns {{ suggestedMin: number, suggestedMax: number }}
 */
function calculateChartBounds(data, minSpan) {
    if (!data || data.length === 0) return { suggestedMin: -10, suggestedMax: 10 };

    let min = data[0];
    let max = data[0];

    for (let i = 1; i < data.length; i++) {
        if (data[i] < min) min = data[i];
        if (data[i] > max) max = data[i];
    }

    const range = max - min;
    const center = (max + min) / 2;
    const bufferedRange = range * CHART_BOUNDS_PADDING;
    const finalSpan = bufferedRange < minSpan ? minSpan : bufferedRange;

    return {
        suggestedMin: center - (finalSpan / 2),
        suggestedMax: center + (finalSpan / 2)
    };
}


// --- 4. Global State (Macro Banner) ---

async function fetchFixedSensors() {
    const response = await fetch(`${BASE_URL}/fixed_sensors.json`);
    return response.json();
}

function renderMacroBanner(data) {
    els.pressure.textContent = safeFallback(data.mslp_hpa, ' hPa');
    if (els.pressureLabel) {
        els.pressureLabel.textContent = data.mslp_corrected ? 'Relative Pressure' : 'Station Pressure';
    }
    if (els.gust) els.gust.textContent = safeFallback(data.wind_gust_kmh, ' km/h');
    if (els.rain) els.rain.textContent = safeFallback(data.rain_24h_mm, ' mm');
    if (els.pressureTime) els.pressureTime.textContent = formatDateTime(data.pressure_timestamp);
    els.time.textContent = formatDateTime(new Date());
}

function renderWindTrail(history) {
    els.windCompass.style.display = 'block';
    els.windTrailContainer.innerHTML = '';

    // Reverse so oldest data is drawn first (controls Z-order)
    const reversedHistory = history.slice().reverse();

    reversedHistory.forEach((point) => {
        // Alpha decay: 1 - (age / window). Clamp so oldest markers stay faintly visible.
        let alpha = 1.0 - (point.age_minutes / WIND_HISTORY_MINUTES);
        alpha = Math.max(MIN_MARKER_ALPHA, alpha);

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.style.transformOrigin = '12px 12px';
        g.style.transform = `rotate(${point.direction}deg)`;
        g.style.opacity = alpha;

        if (point.age_minutes === 0) {
            // Head: full arrow for current wind
            g.innerHTML = `
                <line x1="12" y1="9" x2="12" y2="17" stroke="var(--accent-blue)" stroke-width="2" stroke-linecap="round" />
                <polygon points="9,14 15,14 12,19.5" fill="var(--accent-blue)" />
            `;
        } else {
            // Tail: small dot at the perimeter for history
            g.innerHTML = `
                <circle cx="12" cy="19.5" r="1.0" fill="var(--accent-blue)" />
            `;
        }

        els.windTrailContainer.appendChild(g);
    });
}

function renderWind(data) {
    if (!els.wind) return;

    if (data.wind_sustained_kmh === null || data.wind_sustained_kmh === undefined) {
        els.wind.textContent = '-- km/h';
        if (els.windCompass) els.windCompass.style.display = 'none';
        return;
    }

    els.wind.textContent = `${data.wind_sustained_kmh.toFixed(1)} km/h`;
    if (els.windCompass && els.windTrailContainer && data.wind_history) {
        renderWindTrail(data.wind_history);
    }
}

function updateCharts(data) {
    const rainTrend = data.rain_trend_72h || [];
    state.rainTrend = rainTrend;
    drawPressureChart(data.pressure_trend_72h, data.pressure_average_72h, rainTrend);
    drawWindDirectionHistory(data.wind_direction_history_72h);
    if (state.zoneChart) {
        state.zoneChart.rainTrend = rainTrend;
        state.zoneChart.update();
    }
}

async function updateFixedSensorData() {
    try {
        const data = await fetchFixedSensors();
        renderMacroBanner(data);
        renderWind(data);
        updateCharts(data);
    } catch (error) {
        console.error('Failed to fetch fixed sensor data:', error);
    }
}


// --- 5. Local State (Zone Hero) ---
/**
 * Fetches current readings and 72-hour history for a sensor, then updates the
 * zone hero panel: temperature, humidity, dew point, RF signal health, and
 * battery warning. Also redraws the zone temperature/dew-point chart.
 * @param {number} sensorId
 * @param {string} friendlyName - Display name shown in the zone hero heading
 */
async function updateSelectedSensorData(sensorId, friendlyName) {
    try {
        state.currentSensorName = friendlyName;
        els.zoneName.textContent = state.currentSensorName;

        const [currentRes, historyRes] = await Promise.all([
            fetch(`${BASE_URL}/readings_current_${sensorId}.json`),
            fetch(`${BASE_URL}/readings_history_${sensorId}.json`)
        ]);
        const [currentData, historyData] = await Promise.all([
            currentRes.json(),
            historyRes.json()
        ]);

        els.temp.textContent     = safeFallback(currentData.temperature_c,  '°');
        els.high.textContent     = safeFallback(currentData.temp_high_24h,  '°');
        els.low.textContent      = safeFallback(currentData.temp_low_24h,   '°');
        els.humidity.textContent = safeFallback(currentData.relative_humidity_pct, '%');
        els.dewpoint.textContent = safeFallback(currentData.dew_point_c,    '°');

        // Stateless RF UI update with 3-tier color coding
        if (currentData.snr_db !== undefined && currentData.snr_db !== null) {
            els.rssi.textContent      = currentData.rssi_dbm.toFixed(1);
            els.rssiTrend.textContent = currentData.rssi_trend;
            els.noise.textContent     = currentData.noise_dbm.toFixed(1);
            els.noiseTrend.textContent = currentData.noise_trend;

            els.snr.textContent = currentData.snr_db.toFixed(1);
            if (currentData.snr_db < SNR_DANGER_DB) {
                els.snr.style.color = SNR_COLOR_DANGER;     // High risk of data loss
            } else if (currentData.snr_db < SNR_WARN_DB) {
                els.snr.style.color = SNR_COLOR_WARN;       // Working, but low fade margin
            } else {
                els.snr.style.color = SNR_COLOR_GOOD;       // Rock solid
            }
            els.snrTrend.textContent = currentData.snr_trend;

        } else {
            // Clear the UI if a hardwired sensor (like the BME280) is selected
            els.rssi.textContent       = '--';
            els.rssiTrend.textContent  = '';
            els.noise.textContent      = '--';
            els.noiseTrend.textContent = '';
            els.snr.textContent        = '--';
            els.snr.style.color        = 'inherit';
            els.snrTrend.textContent   = '';
        }

        els.sensorReadTime.style.display = 'block';
        els.sensorReadTime.style.color = 'var(--text-secondary)';
        els.sensorReadTime.textContent = `Sensor read at: ${formatDateTime(currentData.timestamp)}`;

        // Strict equality: only warn when DB explicitly says battery is dead (0).
        // If 1 (good) or null/undefined (no battery data), stay hidden.
        if (els.batteryWarning) {
            els.batteryWarning.style.display = currentData.battery_ok === 0 ? 'block' : 'none';
        }

        drawZoneChart(historyData);

    } catch (error) {
        console.error('Failed to fetch selected sensor data:', error);
    }
}


// --- 6. Dynamic Dropdown ---
async function initializeSensorDropdown() {
    try {
        const response = await fetch(`${BASE_URL}/sensors.json`);
        const sensors = await response.json();

        els.dropdown.innerHTML = '';

        sensors.forEach((sensor) => {
            const opt = document.createElement('option');
            opt.value = sensor.id;
            opt.text = sensor.location;
            if (sensor.id === state.currentSensorId) opt.selected = true;
            els.dropdown.appendChild(opt);
        });

        els.dropdown.addEventListener('change', (event) => {
            state.currentSensorId = parseInt(event.target.value, 10);
            localStorage.setItem('preferredSensorId', state.currentSensorId);

            const selectedSensor = sensors.find((s) => s.id === state.currentSensorId);
            if (selectedSensor) {
                updateSelectedSensorData(selectedSensor.id, selectedSensor.friendly_name);
                updateFixedSensorData();
            }
        });

        if (sensors.length > 0) {
            const defaultSensor = sensors.find((s) => s.id === state.currentSensorId) || sensors[0];
            state.currentSensorId = defaultSensor.id;
            els.dropdown.value = state.currentSensorId;
            updateSelectedSensorData(defaultSensor.id, defaultSensor.friendly_name);
        }
    } catch (error) {
        console.error('Failed to initialize sensor dropdown:', error);
    }
}


// --- 7. Wind Direction History ---

function windAngularDiff(a, b) {
    const diff = Math.abs(a - b) % 360;
    return diff > 180 ? 360 - diff : diff;
}

function drawWindDirectionHistory(historyData) {
    if (!els.windHistory) return;
    els.windHistory.innerHTML = '';

    const data = historyData || [];
    const count = data.length;
    if (count === 0) return;

    for (let i = 0; i < count; i++) {
        const point = data[i];
        const pct = ((i + 0.5) / count * 100).toFixed(1);

        // Outer container: horizontally centred, stacks arrow + speed label
        const el = document.createElement('div');
        el.style.position = 'absolute';
        el.style.left = pct + '%';
        el.style.top = '3px';
        el.style.transform = 'translateX(-50%)';
        el.style.display = 'flex';
        el.style.flexDirection = 'column';
        el.style.alignItems = 'center';
        el.style.gap = '2px';

        // Arrow wrapper — rotation applied here so the speed label stays upright
        const arrowEl = document.createElement('div');

        if (point.direction !== null && point.direction !== undefined) {
            const prevDir = i > 0 ? data[i - 1].direction : null;
            const isReversal = prevDir !== null &&
                windAngularDiff(prevDir, point.direction) >= WIND_REVERSAL_THRESHOLD_DEG;
            const color = isReversal ? '#FF4444' : '#A0A0A0';

            arrowEl.style.transform = 'rotate(' + point.direction + 'deg)';
            arrowEl.innerHTML =
                '<svg width="20" height="20" viewBox="0 0 24 24">' +
                    '<line x1="12" y1="6" x2="12" y2="17" stroke="' + color + '" stroke-width="2.5" stroke-linecap="round"/>' +
                    '<polygon points="8.5,14 15.5,14 12,20" fill="' + color + '"/>' +
                '</svg>';
        } else {
            arrowEl.innerHTML =
                '<svg width="20" height="20" viewBox="0 0 24 24">' +
                    '<circle cx="12" cy="12" r="2" fill="#444"/>' +
                '</svg>';
        }

        el.appendChild(arrowEl);

        // Speed label — always upright, shows rounded km/h average for the bucket
        const speedEl = document.createElement('div');
        speedEl.style.fontSize = '9px';
        speedEl.style.color = '#888';
        speedEl.style.lineHeight = '1';
        speedEl.style.whiteSpace = 'nowrap';
        speedEl.textContent = (point.speed !== null && point.speed !== undefined)
            ? Math.round(point.speed)
            : '--';
        el.appendChild(speedEl);

        els.windHistory.appendChild(el);
    }
}


// --- 8. Rain Shading Plugin ---

// Singleton plugin shared by every time-series chart. The rain trend is read
// from the chart instance itself (chartInstance.rainTrend) — callers are
// responsible for setting it before calling .update(). This keeps the plugin
// stateless and makes the dependency visible in each draw function.
const rainPlugin = {
    beforeDatasetsDraw: function(chartInstance) {
        const rain = chartInstance.rainTrend;
        if (!rain || rain.length === 0) return;
        const ca = chartInstance.chartArea;
        if (!ca) return;

        const ctx = chartInstance.chart.ctx;
        const n = rain.length;
        const step = (ca.right - ca.left) / Math.max(n - 1, 1);

        let maxRain = 0;
        for (let j = 0; j < n; j++) {
            if (rain[j] !== null && rain[j] !== undefined && rain[j] > maxRain) {
                maxRain = rain[j];
            }
        }

        ctx.save();
        for (let i = 0; i < n; i++) {
            const rv = rain[i];
            if (rv !== null && rv !== undefined && rv > 0) {
                const alpha = maxRain > 0 ? 0.40 + (rv / maxRain) * 0.30 : 0.55;
                const x = ca.left + i * step;
                const bandLeft = i === 0 ? ca.left : x - step / 2;
                const bandRight = i === n - 1 ? ca.right : x + step / 2;
                ctx.fillStyle = `rgba(77, 168, 218, ${alpha})`;
                ctx.fillRect(bandLeft, ca.top, bandRight - bandLeft, ca.bottom - ca.top);
            }
        }
        ctx.restore();
    }
};


// --- 9. Chart.js Drawing Engines ---

/**
 * Returns a Chart.js animation.onComplete callback that paints a 'mean: X hPa'
 * label anchored to the final point of the average-line dataset. The callback
 * uses `this.chart`, so it must remain a regular function — not an arrow function.
 * @param {number} averageValue - The 72-hour mean pressure to annotate
 * @returns {function} Chart.js animation callback
 */
function makePressureAnnotation(averageValue) {
    return function() {
        const chartInstance = this.chart;
        const ctx = chartInstance.ctx;
        ctx.font = Chart.helpers.fontString(10, 'normal', 'sans-serif');
        ctx.textBaseline = 'bottom';
        const meta = chartInstance.controller.getDatasetMeta(3);
        const lastPoint = meta.data[meta.data.length - 1];
        if (lastPoint && averageValue !== undefined && averageValue !== null) {
            ctx.textAlign = 'right';
            ctx.fillStyle = '#4DA8DA';
            ctx.fillText(`mean: ${averageValue} hPa`, chartInstance.width, lastPoint._model.y - 5);
        }
    };
}

/**
 * Creates or updates the 72-hour pressure sparkline. Constructs the Chart.js
 * instance on first call; updates data in-place on subsequent calls.
 * @param {{ value: number, alert: string, timestamp: string }[]|null} trendArray
 * @param {number} averageValue - 72-hour mean pressure for the reference line
 * @param {(number|null)[]} rainTrend - Rain delta per bucket, stored on the chart for rainPlugin
 */
function drawPressureChart(trendArray, averageValue, rainTrend) {
    const ctx = els.pressureCanvas.getContext('2d');
    const safeTrendArray = trendArray || [];

    const labels = [];
    const averageLineData = [];
    const split = splitPressureData(safeTrendArray);

    for (let i = 0; i < safeTrendArray.length; i++) {
        labels.push(formatChartLabelTime(safeTrendArray[i].timestamp));
        averageLineData.push(averageValue);
    }

    if (state.pressureChart) {
        state.pressureChart.rainTrend = rainTrend || [];
        state.pressureChart.data.labels = labels;
        state.pressureChart.data.datasets[0].data = split.normalData;
        state.pressureChart.data.datasets[1].data = split.gradualAlertData;
        state.pressureChart.data.datasets[2].data = split.slowAlertData;
        state.pressureChart.data.datasets[3].data = split.fastAlertData;
        state.pressureChart.data.datasets[4].data = averageLineData;
        state.pressureChart.options.animation.onComplete = makePressureAnnotation(averageValue);
        state.pressureChart.update();
        return;
    }

    state.pressureChart = new Chart(ctx, {
        type: 'line',
        plugins: [rainPlugin],
        data: {
            labels: labels,
            datasets: [
                { label: 'Pressure (hPa)', data: split.normalData,        borderColor: '#A0A0A0', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, spanGaps: false },
                { label: 'Pressure (hPa)', data: split.gradualAlertData,  borderColor: '#FFD700', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, spanGaps: false },
                { label: 'Pressure (hPa)', data: split.slowAlertData,     borderColor: '#FF8800', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, spanGaps: false },
                { label: 'Pressure (hPa)', data: split.fastAlertData,     borderColor: '#FF4444', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, spanGaps: false },
                { label: 'Average (hPa)', data: averageLineData,           borderColor: '#4DA8DA', borderWidth: 1, borderDash: [5, 5], fill: false, pointRadius: 0 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            layout: { padding: { left: 0, right: 0, top: 0, bottom: 0 } },
            legend: { display: false },
            tooltips: {
                mode: 'index', intersect: false,
                callbacks: {
                    label: function(tooltipItem, data) {
                        const val = tooltipItem.yLabel;
                        if (val === null || val === undefined) return null;
                        return `${data.datasets[tooltipItem.datasetIndex].label || ''}: ${parseFloat(val).toFixed(1)}`;
                    }
                }
            },
            scales: {
                xAxes: getSharedXAxis(),
                yAxes: [{
                    display: true, position: 'left',
                    scaleLabel: { display: true, labelString: 'Station Press. (hPa)', fontColor: '#A0A0A0' },
                    ticks: { fontColor: '#A0A0A0' },
                    gridLines: { color: '#333333' },
                    afterFit: function(scaleInstance) { scaleInstance.width = 75; }
                }]
            },
            animation: {
                onComplete: makePressureAnnotation(averageValue)
            }
        }
    });
    state.pressureChart.rainTrend = rainTrend || [];
}

function drawZoneChart(historyData) {
    const ctx = els.zoneCanvas.getContext('2d');
    const safeHistoryData = historyData || [];

    const timestamps = [];
    const tempData = [];
    const dewData = [];

    // Single-pass O(N) loop: extract timestamp + temp + dew simultaneously
    for (let i = 0; i < safeHistoryData.length; i++) {
        const d = safeHistoryData[i];
        timestamps.push(formatChartLabelTime(d.timestamp));
        tempData.push(d.temperature_c);
        dewData.push(d.dew_point_c);
    }

    const tempBounds = calculateChartBounds(tempData.concat(dewData), 10);

    if (state.zoneChart) {
        state.zoneChart.data.labels = timestamps;
        state.zoneChart.data.datasets[0].data = tempData;
        state.zoneChart.data.datasets[1].data = dewData;
        state.zoneChart.options.scales.yAxes[0].ticks.suggestedMin = tempBounds.suggestedMin;
        state.zoneChart.options.scales.yAxes[0].ticks.suggestedMax = tempBounds.suggestedMax;
        state.zoneChart.update();
        return;
    }

    const multiColorLabelPlugin = {
        afterDraw: function(chartInstance) {
            const ctx = chartInstance.chart.ctx;
            const yAxis = chartInstance.scales['yTemp'];
            if (!yAxis) return;

            const yCenter = (yAxis.top + yAxis.bottom) / 2;
            const paddingLeft = 10;

            ctx.font = Chart.helpers.fontString(12, 'normal', '-apple-system, BlinkMacSystemFont, sans-serif');
            ctx.textBaseline = 'middle';
            ctx.textAlign = 'left';

            const w1 = ctx.measureText('Dew P. (°C)').width;
            const w2 = ctx.measureText(' / ').width;
            const w3 = ctx.measureText('Temp. (°C)').width;

            ctx.save();
            ctx.translate(paddingLeft, yCenter + ((w1 + w2 + w3) / 2));
            ctx.rotate(-Math.PI / 2);

            ctx.fillStyle = '#00ced1'; ctx.fillText('Dew P. (°C)', 0, 0);
            ctx.fillStyle = '#A0A0A0'; ctx.fillText(' / ', w1, 0);
            ctx.fillStyle = '#FFFFFF'; ctx.fillText('Temp. (°C)', w1 + w2, 0);
            ctx.restore();
        }
    };

    state.zoneChart = new Chart(ctx, {
        type: 'line',
        plugins: [rainPlugin, multiColorLabelPlugin],
        data: {
            labels: timestamps,
            datasets: [
                { label: 'Temperature', data: tempData, borderColor: '#FFFFFF', yAxisID: 'yTemp', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, pointStyle: 'line' },
                { label: 'Dew Point', data: dewData, borderColor: '#00ced1', yAxisID: 'yTemp', borderWidth: 2, fill: false, lineTension: 0, pointRadius: 0, pointStyle: 'line' }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            layout: { padding: { left: 0, right: 0, top: 0, bottom: 0 } },
            legend: { display: false },
            tooltips: {
                mode: 'index', intersect: false,
                callbacks: {
                    label: function(tooltipItem, data) {
                        return `${data.datasets[tooltipItem.datasetIndex].label || ''}: ${parseFloat(tooltipItem.yLabel).toFixed(1)}`;
                    }
                }
            },
            scales: {
                xAxes: getSharedXAxis(),
                yAxes: [{
                    id: 'yTemp', type: 'linear', position: 'left',
                    scaleLabel: { display: false },
                    ticks: { fontColor: '#FFFFFF', suggestedMin: tempBounds.suggestedMin, suggestedMax: tempBounds.suggestedMax },
                    gridLines: { color: '#333333', zeroLineColor: '#333333' },
                    afterFit: function(scaleInstance) { scaleInstance.width = 75; }
                }]
            }
        }
    });
    state.zoneChart.rainTrend = state.rainTrend;
}


// --- 10. Boot Sequence & Heartbeat ---

function init() {
    updateFixedSensorData();
    initializeSensorDropdown();
}

// If the script ever moves from end-of-body to <head>, this guard ensures the DOM
// is ready before init() touches any elements. In normal operation (and in the test
// harness, where jsdom readyState is 'complete'), init() fires immediately.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}


// --- 11. Download Modal ---

(function() {
    var overlay     = document.getElementById('download-modal-overlay');
    var openBtn     = document.getElementById('download-btn');
    var closeBtn    = document.getElementById('modal-close-btn');
    var downloadBtn = document.getElementById('download-csv-btn');

    function openModal() {
        overlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        overlay.style.display = 'none';
        document.body.style.overflow = '';
    }

    // Metrics that are computed/derived — exclude from the raw CSV export.
    var COMPUTED_METRICS = { dew_point_c: true };

    function isoUtcToEpoch(isoStr) {
        // Timestamps in history JSON are UTC strings like "2026-05-11 06:00:00".
        // Append 'Z' after replacing the space separator so Date parses them as UTC.
        return Math.round(new Date(isoStr.replace(' ', 'T') + 'Z').getTime() / 1000);
    }

    function collectRows(sensor, historyData) {
        var out  = [];
        var rows = Array.isArray(historyData) ? historyData : [];
        for (var r = 0; r < rows.length; r++) {
            var row   = rows[r];
            var ts    = row.timestamp;
            var epoch = isoUtcToEpoch(ts);
            var keys  = Object.keys(row);
            for (var k = 0; k < keys.length; k++) {
                var key = keys[k];
                if (key === 'timestamp' || COMPUTED_METRICS[key]) { continue; }
                var val = row[key];
                if (val === null || val === undefined) { continue; }
                out.push({
                    ts: ts,
                    line: [ts, epoch, sensor.timezone, sensor.id, sensor.machine_name,
                           sensor.location, sensor.latitude, sensor.longitude,
                           sensor.elevation_m, key, val].join(',')
                });
            }
        }
        return out;
    }

    function downloadCsv(csv) {
        var blob = new Blob([csv], { type: 'text/csv' });
        var url  = URL.createObjectURL(blob);
        var a    = document.createElement('a');
        a.href     = url;
        a.download = 'weather_demo_all_sensors_72h.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    openBtn.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) { closeModal(); }
    });

    downloadBtn.addEventListener('click', function() {
        fetch(BASE_URL + '/sensors.json')
            .then(function(r) { return r.json(); })
            .then(function(sensors) {
                var fetches = sensors.map(function(sensor) {
                    return fetch(BASE_URL + '/readings_history_' + sensor.id + '.json')
                        .then(function(r) { return r.json(); })
                        .then(function(history) { return collectRows(sensor, history); });
                });
                return Promise.all(fetches);
            })
            .then(function(results) {
                // Merge all sensor rows and sort by timestamp so readings
                // interleave chronologically across sensors.
                var all = [];
                for (var i = 0; i < results.length; i++) {
                    all = all.concat(results[i]);
                }
                all.sort(function(a, b) { return a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0; });

                var header = 'timestamp_utc,timestamp_epoch,timezone,sensor_id,sensor_name,location,latitude,longitude,elevation_m,metric,value';
                var lines  = [header];
                for (var j = 0; j < all.length; j++) {
                    lines.push(all[j].line);
                }
                downloadCsv(lines.join('\n'));
                closeModal();
            });
    });
})();
