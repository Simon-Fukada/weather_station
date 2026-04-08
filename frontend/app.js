// --- 1. Configuration & State ---
const API_BASE = '/api'; 
let currentSensorId = parseInt(localStorage.getItem('preferredSensorId')) || 1;
let currentSensorName = "Loading..."; // Storing name in memory, not the DOM
let pressureChartInstance = null;
let zoneChartInstance = null;


// --- 2. Formatting & Configuration Helpers ---

function safeFallback(val, unit) {
    if (val !== undefined && val !== null) {
        return unit ? val + unit : val;
    }
    return "--";
}

function formatDateTime(input) {
    // Defensive check: instantly abort if data is missing
    if (!input) return '--:--';

    let date;
    if (typeof input === 'string') {
        const safeString = input.replace(' ', 'T') + 'Z';
        date = new Date(safeString);
    } else {
        date = input; 
    }
    
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
                var len = values.length;
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

function calculateChartBounds(data, minSpan) {
    if (!data || data.length === 0) return { suggestedMin: -10, suggestedMax: 10 };
    
    var min = data[0];
    var max = data[0];
    
    for (var i = 1; i < data.length; i++) {
        if (data[i] < min) min = data[i];
        if (data[i] > max) max = data[i];
    }
    
    var range = max - min;
    var center = (max + min) / 2;
    var bufferedRange = range * 1.15;
    var finalSpan = bufferedRange < minSpan ? minSpan : bufferedRange;
    
    return {
        suggestedMin: center - (finalSpan / 2),
        suggestedMax: center + (finalSpan / 2)
    };
}


// --- 3. Global State (Macro Banner) ---
async function updateFixedSensorData() {
    try {
        const response = await fetch(`${API_BASE}/fixed_sensors?sensor_id=${currentSensorId}`);
        const data = await response.json();

        document.getElementById('ui-pressure').innerText = safeFallback(data.mslp_hpa, ' hPa');
        
        var uiWind = document.getElementById('ui-wind');
        var uiGust = document.getElementById('ui-gust');
        if (uiWind) uiWind.innerText = safeFallback(data.wind_sustained_kmh, ' km/h');
        if (uiGust) uiGust.innerText = safeFallback(data.wind_gust_kmh, ' km/h');

        var uiPressureTime = document.getElementById('ui-pressure-time');
        if (uiPressureTime) uiPressureTime.innerText = formatDateTime(data.pressure_timestamp);
        
        document.getElementById('ui-time').innerText = formatDateTime(new Date());

        drawPressureChart(data.pressure_trend_72h, data.pressure_average_72h);
    } catch (error) {
        console.error("Failed to fetch fixed sensor data:", error);
    }
}


// --- 4. Local State (Zone Hero) ---
async function updateSelectedSensorData(sensorId, friendlyName) {
    try {
        // Update state in memory
        currentSensorName = friendlyName;
        document.getElementById('ui-zone-name').innerText = currentSensorName;

        const currentRes = await fetch(`${API_BASE}/readings/current/${sensorId}`);
        const currentData = await currentRes.json();

        document.getElementById('ui-temp').innerHTML = safeFallback(currentData.temperature_c, '&deg;');
        document.getElementById('ui-high').innerHTML = safeFallback(currentData.temp_high_24h, '&deg;');
        document.getElementById('ui-low').innerHTML = safeFallback(currentData.temp_low_24h, '&deg;');
        document.getElementById('ui-humidity').innerHTML = safeFallback(currentData.humidity_pct, '%');
        document.getElementById('ui-dewpoint').innerHTML = safeFallback(currentData.dew_point_c, '&deg;');

// NEW: Stateless RF UI Update with Color Coding
        if (currentData.snr_db !== undefined && currentData.snr_db !== null) {
            document.getElementById('ui-rssi').innerText = currentData.rssi_dbm.toFixed(1);
            document.getElementById('ui-rssi-trend').innerText = currentData.rssi_trend;

            document.getElementById('ui-noise').innerText = currentData.noise_dbm.toFixed(1);
            document.getElementById('ui-noise-trend').innerText = currentData.noise_trend;

            const snrEl = document.getElementById('ui-snr');
            snrEl.innerText = currentData.snr_db.toFixed(1);
            
            // The 3-Tier SNR Logic
            if (currentData.snr_db < 10) {
                snrEl.style.color = '#ff4444'; // Red (Danger: High risk of data loss)
            } else if (currentData.snr_db < 20) {
                snrEl.style.color = '#ffbb33'; // Yellow (Warning: Working, but low fade margin)
            } else {
                snrEl.style.color = '#00C851'; // Green (Excellent: Rock solid)
            }

            document.getElementById('ui-snr-trend').innerText = currentData.snr_trend;
            
        } else {
            // Clear the UI if a hardwired sensor (like the BME280) is selected
            document.getElementById('ui-rssi').innerText = '--';
            document.getElementById('ui-rssi-trend').innerText = '';
            document.getElementById('ui-noise').innerText = '--';
            document.getElementById('ui-noise-trend').innerText = '';
            
            const snrEl = document.getElementById('ui-snr');
            snrEl.innerText = '--';
            snrEl.style.color = 'inherit'; // RESET the color back to gray!
            document.getElementById('ui-snr-trend').innerText = '';
        }


        const sensorReadTime = document.getElementById('sensor-read-time');
        sensorReadTime.style.display = 'block';
        sensorReadTime.style.color = 'var(--text-secondary)'; 
        sensorReadTime.innerText = `Sensor read at: ${formatDateTime(currentData.timestamp)}`;

        // Battery Warning Toggle
        const batteryWarning = document.getElementById('ui-battery-warning');
        if (batteryWarning) {
            // Strict equality (===) ensures we only show the warning if the database explicitly says the battery is dead (0). 
            // If it is 1 (Good) or null/undefined (No battery data), the warning stays hidden.
            if (currentData.battery_ok === 0) {
                batteryWarning.style.display = 'block';
            } else {
                batteryWarning.style.display = 'none';
            }
        }

        const historyRes = await fetch(`${API_BASE}/readings/history/${sensorId}?hours=72`);
        const historyData = await historyRes.json();

        drawZoneChart(historyData);

    } catch (error) {
        console.error("Failed to fetch selected sensor data:", error);
    }
}


// --- 5. Dynamic Dropdown ---
async function initializeSensorDropdown() {
    try {
        const response = await fetch(`${API_BASE}/sensors`);
        const sensors = await response.json();
        
        const dropdown = document.getElementById('sensor-dropdown');
        dropdown.innerHTML = ''; 

        sensors.forEach(function(sensor) {
            const opt = document.createElement('option');
            opt.value = sensor.id;
            opt.text = sensor.location;
            if (sensor.id === currentSensorId) opt.selected = true;
            dropdown.appendChild(opt);
        });

        dropdown.addEventListener('change', function() {
            currentSensorId = parseInt(this.value);
            localStorage.setItem('preferredSensorId', currentSensorId);
            
            var selectedSensor = sensors.find(function(s) { return s.id === currentSensorId; });
            if (selectedSensor) {
                updateSelectedSensorData(selectedSensor.id, selectedSensor.friendly_name);
                updateFixedSensorData();
            }
        });

        if (sensors.length > 0) {
            const defaultSensor = sensors.find(function(s) { return s.id === currentSensorId; }) || sensors[0];
            currentSensorId = defaultSensor.id; 
            dropdown.value = currentSensorId;
            updateSelectedSensorData(defaultSensor.id, defaultSensor.friendly_name);
        }
    } catch (error) {
        console.error("Failed to initialize sensor dropdown:", error);
    }
}


// --- 6. Chart.js Drawing Engines ---

function drawPressureChart(trendArray, averageValue) {
    var ctx = document.getElementById('pressure-sparkline').getContext('2d');
    var safeTrendArray = trendArray || [];
    
    var labels = safeTrendArray.map(function(d) {
        return new Date(d.timestamp.replace(' ', 'T') + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false});
    });
    var trendValues = safeTrendArray.map(function(d) { return d.value; });
    var averageLineData = safeTrendArray.map(function() { return averageValue; });

    if (pressureChartInstance) pressureChartInstance.destroy();

    pressureChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'Pressure (hPa)', data: trendValues, borderColor: '#A0A0A0', borderWidth: 2, fill: false, lineTension: 0.4, pointRadius: 0 },
                { label: 'Average (hPa)', data: averageLineData, borderColor: '#4DA8DA', borderWidth: 1, borderDash: [5, 5], fill: false, pointRadius: 0 }
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
                        return (data.datasets[tooltipItem.datasetIndex].label || '') + ': ' + parseFloat(tooltipItem.yLabel).toFixed(1);
                    }
                }
            },
            scales: {
                xAxes: getSharedXAxis(), 
                yAxes: [{
                    display: true, position: 'left',
                    scaleLabel: { display: true, labelString: 'Pressure (hPa)', fontColor: '#A0A0A0' },
                    ticks: { fontColor: '#A0A0A0' },
                    gridLines: { color: '#333333' },
                    afterFit: function(scaleInstance) { scaleInstance.width = 75; }
                }]  
            },
            animation: {
                onComplete: function() {
                    var chartInstance = this.chart, ctx = chartInstance.ctx;
                    ctx.font = Chart.helpers.fontString(10, 'normal', 'sans-serif');
                    ctx.textBaseline = 'bottom';

                    var meta = chartInstance.controller.getDatasetMeta(1);
                    var lastPoint = meta.data[meta.data.length - 1];
                    
                    if (lastPoint && averageValue !== undefined && averageValue !== null) {
                        ctx.textAlign = 'right';
                        ctx.fillStyle = '#4DA8DA';
                        ctx.fillText('mean: ' + averageValue + ' hPa', chartInstance.width, lastPoint._model.y - 5);
                    }
                }
            }
        }
    });
}

function drawZoneChart(historyData) {
    var ctx = document.getElementById('zone-chart').getContext('2d');
    var safeHistoryData = historyData || [];

    var temperatureEntries = safeHistoryData.filter(function(d) { return d.metric_type === 'temperature_c'; });
    var timestamps = temperatureEntries.map(function(d) {
        return new Date(d.timestamp.replace(' ', 'T') + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false});
    });
    
    var tempData = temperatureEntries.map(function(d) { return d.value; });
    var dewData = safeHistoryData.filter(function(d) { return d.metric_type === 'dew_point_c'; }).map(function(d) { return d.value; });

    var tempBounds = calculateChartBounds(tempData.concat(dewData), 10);

    if (zoneChartInstance) zoneChartInstance.destroy();

    var multiColorLabelPlugin = {
        afterDraw: function(chartInstance) {
            var ctx = chartInstance.chart.ctx;
            var yAxis = chartInstance.scales['yTemp'];
            if (!yAxis) return; 

            var yCenter = (yAxis.top + yAxis.bottom) / 2;
            var paddingLeft = 10; 

            ctx.font = Chart.helpers.fontString(12, 'normal', '-apple-system, BlinkMacSystemFont, sans-serif');
            ctx.textBaseline = 'middle';
            ctx.textAlign = 'left';

            var w1 = ctx.measureText('Dew Point (°C)').width;
            var w2 = ctx.measureText(' / ').width;
            var w3 = ctx.measureText('Temperature (°C)').width;

            ctx.save();
            ctx.translate(paddingLeft, yCenter + ((w1 + w2 + w3) / 2));
            ctx.rotate(-Math.PI / 2);

            ctx.fillStyle = '#00ced1'; ctx.fillText('Dew Point (°C)', 0, 0);
            ctx.fillStyle = '#A0A0A0'; ctx.fillText(' / ', w1, 0);
            ctx.fillStyle = '#FFFFFF'; ctx.fillText('Temperature (°C)', w1 + w2, 0);
            ctx.restore();
        }
    };

    zoneChartInstance = new Chart(ctx, {
        type: 'line',
        plugins: [multiColorLabelPlugin],
        data: {
            labels: timestamps,
            datasets: [
                { label: 'Temperature', data: tempData, borderColor: '#FFFFFF', yAxisID: 'yTemp', borderWidth: 2, fill: false, lineTension: 0.4, pointRadius: 0, pointStyle: 'line' },
                { label: 'Dew Point', data: dewData, borderColor: '#00ced1', yAxisID: 'yTemp', borderWidth: 2, fill: false, lineTension: 0.4, pointRadius: 0, pointStyle: 'line' }
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
                        return (data.datasets[tooltipItem.datasetIndex].label || '') + ': ' + parseFloat(tooltipItem.yLabel).toFixed(1);
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
}


// --- 7. The Boot Sequence & Heartbeat ---

// 1. Load the fixed barometer and anemometer data
updateFixedSensorData(); 

// 2. Build the dropdown and load the first available sensor
initializeSensorDropdown(); 

// 3. Keep everything alive every 5 minutes
setInterval(function() {
    updateFixedSensorData();
    // Passing the pure state variable directly
    updateSelectedSensorData(currentSensorId, currentSensorName); 
}, 300000);

// 4. Flush iPad memory daily
setTimeout(() => { window.location.reload(); }, 86400000);