import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from math import radians, cos, sin, sqrt, atan2


app = FastAPI()
templates = Jinja2Templates(directory="templates")

OPENWEATHER_API_KEY = "f33a92d1f423e75d96185317f09987f7"  # Replace with your key


class LocationInput(BaseModel):
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

async def geocode_location(location: str):
    if not location or not location.strip():
        print("[DEBUG] Empty location string")
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location.strip(), "format": "json", "limit": 1}
    headers = {"User-Agent": "YourAppName/1.0 (your-email@example.com)"}  # Required by Nominatim usage policy

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = await resp.json()
            print(f"[DEBUG] Nominatim geocode response for {location}: {data}")
        except Exception as e:
            print(f"[Geocoding Error] {e}")
            return None

        if not data:
            print(f"[DEBUG] No Nominatim results for '{location}'")
            return None

        first = data[0]
        try:
            lat = float(first["lat"])
            lon = float(first["lon"])
        except (KeyError, ValueError) as e:
            print(f"[DEBUG] Error parsing lat/lon from Nominatim result: {e}")
            return None

        print(f"[DEBUG] Found coordinates for '{location}': {lat}, {lon}")
        return lat, lon





async def fetch_weather(lat, lon):
    weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
    forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
    async with httpx.AsyncClient() as client:
        weather_res = await client.get(weather_url)
        forecast_res = await client.get(forecast_url)
        return weather_res.json(), forecast_res.json()


def haversine(lat1, lon1, lat2, lon2):
    # Calculate distance in kilometers between two lat/lon points
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


@app.post("/weather")
async def get_weather(loc: LocationInput):
    # Resolve coordinates
    if loc.latitude is not None and loc.longitude is not None:
        lat, lon = loc.latitude, loc.longitude
    elif loc.location:
        coords = await geocode_location(loc.location)
        if coords is None:
            return JSONResponse({"error": "Location not found"}, status_code=404)
        lat, lon = coords
    else:
        return JSONResponse({"error": "No location provided"}, status_code=400)

    weather, forecast = await fetch_weather(lat, lon)

    # Validate API response
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
        # Convert latitude and longitude strings to floats if possible
        try:
            lat_input = float(latitude) if latitude and latitude.strip() != "" else None
            lon_input = float(longitude) if longitude and longitude.strip() != "" else None
        except ValueError:
            return templates.TemplateResponse(
                "result.html",
                {"request": request, "error": "Invalid latitude or longitude format"},
            )

        # Case 1: both location and coordinates given
        if location and (lat_input is not None and lon_input is not None):
            coords = await geocode_location(location)
            if not coords:
                return templates.TemplateResponse(
                    "result.html", {"request": request, "error": "Location not found"}
                )
            lat_loc, lon_loc = coords

            # Distance check between geocoded and provided coords
            dist_km = haversine(lat_loc, lon_loc, lat_input, lon_input)
            if dist_km > 50:
                return templates.TemplateResponse(
                    "result.html",
                    {
                        "request": request,
                        "error": "Location name and coordinates do not match",
                    },
                )
            lat, lon = lat_loc, lon_loc

        # Case 2: only coordinates
        elif lat_input is not None and lon_input is not None:
            lat, lon = lat_input, lon_input

        # Case 3: only location
        elif location:
            coords = await geocode_location(location)
            if not coords:
                return templates.TemplateResponse(
                    "result.html", {"request": request, "error": "Location not found"}
                )
            lat, lon = coords

        # Case 4: nothing provided
        else:
            return templates.TemplateResponse(
                "result.html",
                {"request": request, "error": "No location or coordinates provided"},
            )

        # Fetch weather
        weather, forecast = await fetch_weather(lat, lon)

        if weather.get("cod") != 200 or forecast.get("cod") != "200":
            error_msg = weather.get("message", "Weather API error")
            return templates.TemplateResponse(
                "result.html", {"request": request, "error": error_msg}
            )

        location_display = location if location else f"{lat}, {lon}"

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

    except Exception as e:
        # Catch-all for debugging in Render
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "error": f"Unexpected error: {str(e)}"},
        )










