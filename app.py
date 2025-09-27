import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from math import radians, cos, sin, sqrt, atan2
import asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

OPENWEATHER_API_KEY = "f33a92d1f423e75d96185317f09987f7"  # Replace with your key

class LocationInput(BaseModel):
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

async def geocode_location(location: str):
    """Geocode location with better error handling and timeout"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location, "format": "json", "limit": 1}
    
    # Add proper headers to respect Nominatim's usage policy
    headers = {
        "User-Agent": "WeatherApp/1.0 (your-email@example.com)",  # Replace with your email
        "Accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()  # Raises an exception for bad status codes
            data = resp.json()
            if not data:
                return None
            return float(data[0]["lat"]), float(data[0]["lon"])
    except (httpx.RequestError, httpx.HTTPStatusError, KeyError, ValueError) as e:
        print(f"Geocoding error for '{location}': {e}")
        return None

async def fetch_weather(lat, lon):
    """Fetch weather data with error handling"""
    weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
    forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            weather_res = await client.get(weather_url)
            forecast_res = await client.get(forecast_url)
            
            weather_res.raise_for_status()
            forecast_res.raise_for_status()
            
            return weather_res.json(), forecast_res.json()
    except httpx.RequestError as e:
        print(f"Weather API error: {e}")
        return None, None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

@app.post("/weather")
async def get_weather(loc: LocationInput):
    if loc.latitude is not None and loc.longitude is not None:
        lat, lon = loc.latitude, loc.longitude
    elif loc.location:
        coords = await geocode_location(loc.location)
        if coords is None:
            return JSONResponse({"error": "Location not found or geocoding service unavailable"}, status_code=404)
        lat, lon = coords
    else:
        return JSONResponse({"error": "No location provided"}, status_code=400)

    weather, forecast = await fetch_weather(lat, lon)
    
    if weather is None or forecast is None:
        return JSONResponse({"error": "Weather service unavailable"}, status_code=503)

    if weather.get("cod") != 200:
        return JSONResponse({"error": weather.get("message", "Weather API error")}, status_code=404)
    if forecast.get("cod") != "200":
        return JSONResponse({"error": forecast.get("message", "Forecast API error")}, status_code=404)

    return {
        "location": loc.location if loc.location else f"{lat},{lon}",
        "current": {
            "temperature_c": weather["main"]["temp"],
            "humidity": weather["main"]["humidity"],
            "weather": weather["weather"][0]["description"],
            "icon_url": f"http://openweathermap.org/img/wn/{weather['weather'][0]['icon']}@2x.png",
        },
        "5_day_forecast": [
            {
                "datetime": entry["dt_txt"],
                "temperature_c": entry["main"]["temp"],
                "weather": entry["weather"][0]["description"],
                "icon_url": f"http://openweathermap.org/img/wn/{entry['weather'][0]['icon']}@2x.png",
            }
            for entry in forecast.get("list", [])
        ],
    }

@app.get("/", response_class=HTMLResponse)
async def form_get(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.post("/weather-html", response_class=HTMLResponse)
async def form_post(
    request: Request,
    location: Optional[str] = Form(None),
    latitude: Optional[str] = Form(None),
    longitude: Optional[str] = Form(None),
):
    try:
        lat_input = float(latitude) if latitude and latitude.strip() != "" else None
        lon_input = float(longitude) if longitude and longitude.strip() != "" else None
    except ValueError:
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "error": "Invalid latitude or longitude format"},
        )

    # Determine which method to use for getting coordinates
    if location and (lat_input is not None and lon_input is not None):
        # Both provided - verify they match
        coords = await geocode_location(location)
        if not coords:
            return templates.TemplateResponse(
                "result.html", {"request": request, "error": "Location not found or geocoding service unavailable"}
            )
        lat_loc, lon_loc = coords
        dist_km = haversine(lat_loc, lon_loc, lat_input, lon_input)
        if dist_km > 50:
            return templates.TemplateResponse(
                "result.html",
                {"request": request, "error": "Location name and coordinates do not match"},
            )
        lat, lon = lat_loc, lon_loc
    elif lat_input is not None and lon_input is not None:
        # Only coordinates
        lat, lon = lat_input, lon_input
    elif location:
        # Only location name
        coords = await geocode_location(location)
        if not coords:
            return templates.TemplateResponse(
                "result.html", {"request": request, "error": "Location not found or geocoding service unavailable. Try using coordinates instead."}
            )
        lat, lon = coords
    else:
        return templates.TemplateResponse(
            "result.html", {"request": request, "error": "No location or coordinates provided"}
        )

    weather, forecast = await fetch_weather(lat, lon)
    
    if weather is None or forecast is None:
        return templates.TemplateResponse(
            "result.html", {"request": request, "error": "Weather service temporarily unavailable"}
        )

    if weather.get("cod") != 200 or forecast.get("cod") != "200":
        error_msg = weather.get("message", "Weather API error")
        return templates.TemplateResponse(
            "result.html", {"request": request, "error": error_msg}
        )

    location_display = location if location else f"{lat:.4f}, {lon:.4f}"

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "location": location_display,
            "current": weather,
            "forecast": forecast.get("list", []),
            "error": None,
        },
    )
