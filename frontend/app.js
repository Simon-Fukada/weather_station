// --- 1. Configuration & State ---
const API_BASE = '/api'; 
let currentSensorId = parseInt(localStorage.getItem('preferredSensorId')) || 1;
let pressureChartInstance = null;
let zoneChartInstance = null;


// --- 2. Formatting Helpers ---
function formatDateTime(input) {
    let date;
    
    // Check if the input is a raw text string from SQLite
    if (typeof input === 'string') {
        // Safari Fix: Replace space with 'T' and append 'Z' to force UTC timezone math
        const safeString = input.replace(' ', 'T') + 'Z';
        date = new Date(safeString);
    } else {
        // If it's already a Date object (like the global timestamp), just use it directly
        date = input; 
    }
    
    return date.toLocaleString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        hour: 'numeric', 
        minute: '2-digit' 
    });
}

// --- 3. Global State (Macro Banner) ---
async function fetchMacroData() {
    try {
        const response = await fetch(`${API_BASE}/macro?sensor_id=${currentSensorId}`);
        const data = await response.json();

        document.getElementById('ui-pressure').innerText = `${data.mslp_hpa} hPa`;
        
        // Update Wind Data (targeting new DOM IDs)
        var uiWind = document.getElementById('ui-wind');
        var uiGust = document.getElementById('ui-gust');
        
        // Task 1: Graceful Wind Fallbacks (ES5 / iOS 12 Safe)
        var windValue = (data.wind_sustained_kmh !== undefined && data.wind_sustained_kmh !== null) ? data.wind_sustained_kmh : '--';
        var gustValue = (data.wind_gust_kmh !== undefined && data.wind_gust_kmh !== null) ? data.wind_gust_kmh : '--';

        if (uiWind) uiWind.innerText = windValue + " km/h";
        if (uiGust) uiGust.innerText = gustValue + " km/h";

        // Pressure specific timestamp
        var pressureTime = data.pressure_timestamp ? formatDateTime(data.pressure_timestamp) : '--:--';
        var uiPressureTime = document.getElementById('ui-pressure-time');
        if (uiPressureTime) {
            uiPressureTime.innerText = pressureTime;
        }
        
        // Global Timestamp (When the iPad last successfully talked to the Pi)
        document.getElementById('ui-time').innerText = formatDateTime(new Date());

        drawPressureChart(data.pressure_trend_72h, data.pressure_average_72h);
    } catch (error) {
        console.error("Failed to fetch macro data:", error);
    }
}

// --- 4. Local State (Zone Hero) ---
async function fetchZoneData(sensorId, friendlyName) {
    try {
        document.getElementById('ui-zone-name').innerText = friendlyName;

        const currentRes = await fetch(`${API_BASE}/readings/current/${sensorId}`);
        const currentData = await currentRes.json();

        document.getElementById('ui-temp').innerHTML = `${currentData.temperature_c || "--"}&deg;`;
        document.getElementById('ui-high').innerHTML = `${currentData.temp_high_24h || "--"}&deg;`;
        document.getElementById('ui-low').innerHTML = `${currentData.temp_low_24h || "--"}&deg;`;
        document.getElementById('ui-humidity').innerText = `${currentData.humidity_pct || "--"}%`;
        document.getElementById('ui-dewpoint').innerHTML = `${currentData.dew_point_c || "--"}&deg;`;

        // Local Timestamp (When the specific sensor actually last reported)
        const staleWarning = document.getElementById('ui-stale-warning');
        staleWarning.style.display = 'block';
        staleWarning.style.color = 'var(--text-secondary)'; // Make it subtle gray instead of orange
        staleWarning.innerText = `Sensor read at: ${formatDateTime(currentData.timestamp)}`;

        const historyRes = await fetch(`${API_BASE}/readings/history/${sensorId}?hours=72`);
        const historyData = await historyRes.json();

        drawZoneChart(historyData);

    } catch (error) {
        console.error("Failed to fetch zone data:", error);
    }
}

// --- 5. Dynamic Dropdown ---
async function buildToggles() {
    try {
        const response = await fetch(`${API_BASE}/sensors`);
        const sensors = await response.json();
        
        const dropdown = document.getElementById('sensor-dropdown');
        dropdown.innerHTML = ''; 

        sensors.forEach(function(sensor) {
            const opt = document.createElement('option');
            opt.value = sensor.id;
            opt.text = sensor.location;
            if (sensor.id === currentSensorId) {
                opt.selected = true;
            }
            dropdown.appendChild(opt);
        });

        dropdown.addEventListener('change', function() {
            currentSensorId = parseInt(this.value);
            localStorage.setItem('preferredSensorId', currentSensorId);
            
            var selectedSensor = sensors.find(function(s) { return s.id === currentSensorId; });
            if (selectedSensor) {
                fetchZoneData(selectedSensor.id, selectedSensor.friendly_name);
                fetchMacroData();
            }
        });

        if (sensors.length > 0) {
            const defaultSensor = sensors.find(function(s) { return s.id === currentSensorId; }) || sensors[0];
            currentSensorId = defaultSensor.id; 
            dropdown.value = currentSensorId;
            fetchZoneData(defaultSensor.id, defaultSensor.friendly_name);
        }
    } catch (error) {
        console.error("Failed to build sensor dropdown:", error);
    }
}

// --- 6. Chart.js Drawing Engines (v2.9.4 Compatible) ---

// Task 3: Helper function for dynamic Y-axis scaling
function calculateChartBounds(data, minSpan) {
    if (!data || data.length === 0) {
        return { suggestedMin: null, suggestedMax: null };
    }
    
    var min = data[0];
    var max = data[0];
    
    for (var i = 1; i < data.length; i++) {
        if (data[i] < min) min = data[i];
        if (data[i] > max) max = data[i];
    }
    
    var range = max - min;
    var center = (max + min) / 2;
    
    // 15% buffer added to the data's range
    var bufferedRange = range * 1.15;
    
    // Ensure the span is at least the minimum allowed
    var finalSpan = bufferedRange < minSpan ? minSpan : bufferedRange;
    var halfSpan = finalSpan / 2;
    
    return {
        suggestedMin: center - halfSpan,
        suggestedMax: center + halfSpan
    };
}

function drawPressureChart(trendArray, averageValue) {
    var ctx = document.getElementById('pressure-sparkline').getContext('2d');
    var labels = trendArray.map(function(_, index) { return index; });
    var averageLineData = trendArray.map(function() { return averageValue; });

    if (pressureChartInstance) pressureChartInstance.destroy();

    pressureChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Trend',
                    data: trendArray,
                    borderColor: '#A0A0A0',
                    borderWidth: 2,
                    fill: false,
                    lineTension: 0.4,
                    pointRadius: 0
                },
                {
                    label: 'Average',
                    data: averageLineData,
                    borderColor: '#4DA8DA',
                    borderWidth: 1,
                    borderDash: [5, 5],
                    fill: false,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Task 3: Ensure Margins Match
            layout: { padding: { left: 0, right: 0, top: 0, bottom: 0 } },
            legend: { display: false },
            tooltips: { enabled: false },
            scales: {
                xAxes: [{
                    display: true,
                    position: 'top',
                    gridLines: {
                        display: true,
                        color: '#333333', // Subtle gray vertical lines
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
                            return null; // Hides the label and gridline for all other points
                        }
                    }
                }],
                yAxes: [{
                    display: true,
                    position: 'left',
                    scaleLabel: {
                        display: true,
                        labelString: 'Pressure (hPa)',
                        fontColor: '#A0A0A0'
                    },
                    ticks: {
                        fontColor: '#A0A0A0'
                    },
                    gridLines: {
                        color: '#333333'
                    },
                    // Task 2: Update the Bottom Chart
                    afterFit: function(scaleInstance) {
                        scaleInstance.width = 75;
                    }
                }]  
            },
            // Task 4: Annotate the 72-Hour Pressure Graph
            animation: {
                onComplete: function() {
                    var chartInstance = this.chart,
                        ctx = chartInstance.ctx;
                    ctx.font = Chart.helpers.fontString(10, 'normal', 'sans-serif');
                    ctx.textBaseline = 'bottom';

                    var meta = chartInstance.controller.getDatasetMeta(1);
                    
                    // Task 2: Reset styles for the mean label (Right Side)
                    var lastPoint = meta.data[meta.data.length - 1];
                    if (lastPoint) {
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

    var temperatureEntries = historyData.filter(function(d) { return d.metric_type === 'temperature_c'; });
    var timestamps = temperatureEntries.map(function(d) {
        var safeString = d.timestamp.replace(' ', 'T') + 'Z';
        var date = new Date(safeString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false});
    });
    
    var tempData = temperatureEntries.map(function(d) { return d.value; });
    var dewData = historyData.filter(function(d) { return d.metric_type === 'dew_point_c'; }).map(function(d) { return d.value; });

    // Combine Temp and Dew Point data for axis scaling
    var combinedTempData = tempData.concat(dewData);
    var tempBounds = calculateChartBounds(combinedTempData, 10);

    if (zoneChartInstance) zoneChartInstance.destroy();

    zoneChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: timestamps,
            datasets: [
                {
                    label: 'Temperature',
                    data: tempData,
                    borderColor: '#FFFFFF',
                    yAxisID: 'yTemp',
                    borderWidth: 2,
                    fill: false,
                    lineTension: 0.4,
                    pointRadius: 0,
                    pointStyle: 'line'
                },
                {
                    label: 'Dew Point',
                    data: dewData,
                    borderColor: '#00ced1',
                    yAxisID: 'yTemp',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    lineTension: 0.4,
                    pointRadius: 0,
                    pointStyle: 'line'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Task 3: Ensure Margins Match
            layout: { padding: { left: 0, right: 0, top: 0, bottom: 0 } },
            legend: { 
                display: true, 
                position: 'bottom',
                labels: {
                    fontColor: '#A0A0A0',
                    fontSize: 12,
                    padding: 15,
                    usePointStyle: true
                }
            },
            tooltips: {
                mode: 'index',
                intersect: false,
                callbacks: {
                    label: function(tooltipItem, data) {
                        var label = data.datasets[tooltipItem.datasetIndex].label || '';
                        if (label) {
                            label += ': ';
                        }
                        label += parseFloat(tooltipItem.yLabel).toFixed(1);
                        return label;
                    }
                }
            },
            scales: {
                xAxes: [{
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
                }],
                yAxes: [
                    {
                        id: 'yTemp',
                        type: 'linear',
                        position: 'left',
                        scaleLabel: { display: true, labelString: 'Temperature / Dew Point (°C)', fontColor: '#FFFFFF' },
                        ticks: { 
                            fontColor: '#FFFFFF',
                            suggestedMin: tempBounds.suggestedMin,
                            suggestedMax: tempBounds.suggestedMax
                        },
                        gridLines: { color: '#333' },
                        // Task 1: Update the Top Chart
                        afterFit: function(scaleInstance) {
                            scaleInstance.width = 75;
                        }
                    }
                ]
            }
        }
    });
}

// --- 7. The Boot Sequence & Heartbeat ---
fetchMacroData();
buildToggles();

// Poll the API
setInterval(function() {
    fetchMacroData();
    fetchZoneData(currentSensorId, document.getElementById('ui-zone-name').innerText);
}, 300000);

// Anti-Memory Leak: Force a hard page reload every 24 hours to flush iOS 12 RAM
setTimeout(() => {
    window.location.reload();
}, 86400000); // 24 hours in milliseconds