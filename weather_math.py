import math

def calculate_vector_average(wind_data: list):
    """
    Calculates true vector average from a list of (speed, direction) tuples.
    Returns: (avg_speed, avg_dir, cardinal_direction)
    """
    if not wind_data:
        return None, None, None

    u_sum = 0.0
    v_sum = 0.0
    count = len(wind_data)

    for speed, direction in wind_data:
        # Convert polar to Cartesian U/V vectors
        u_sum += -speed * math.sin(math.radians(direction))
        v_sum += -speed * math.cos(math.radians(direction))

    # Average the forces
    u_avg = u_sum / count
    v_avg = v_sum / count

    # Reconstruct the vector
    avg_speed = math.sqrt(u_avg**2 + v_avg**2)
    avg_dir = (math.degrees(math.atan2(u_avg, v_avg)) + 360) % 360

    # Map to Cardinal Direction
    cardinal_points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", 
                       "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((avg_dir + 11.25) / 22.5) % 16
    
    return round(avg_speed, 1), int(avg_dir), cardinal_points[index]

def calculate_mslp(abs_pressure_hpa: float, temp_c: float, elevation_m: float) -> float:
    temp_component = temp_c + (0.0065 * elevation_m) + 273.15
    base = 1 - ((0.0065 * elevation_m) / temp_component)
    mslp = abs_pressure_hpa * math.pow(base, -5.257)
    return round(mslp, 1)


def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    if temp_c is None or humidity_pct is None:
        return None

    if humidity_pct <= 0:
        return None

    a = 17.27
    b = 237.3
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    return round(dew_point, 1)


def convert_f_to_c(fahrenheit: float) -> float:
    """Converts Fahrenheit to Celsius, rounded to 1 decimal place."""
    return round((fahrenheit - 32) * 5.0 / 9.0, 1)

def convert_mph_to_kmh(mph: float) -> float:
    """Converts Miles Per Hour to Kilometers Per Hour, rounded to 1 decimal place."""
    return round(mph * 1.60934, 1)

def convert_inches_to_mm(inches: float) -> float:
    """Converts Inches to Millimeters, rounded to 2 decimal places."""
    return round(inches * 25.4, 2)