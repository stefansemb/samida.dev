from dataclasses import dataclass

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes used by Open-Meteo.
# https://open-meteo.com/en/docs#weather_variable_documentation
_WEATHER_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class WeatherError(RuntimeError):
    """The location couldn't be resolved or the forecast couldn't be fetched."""


@dataclass(frozen=True)
class DailyForecast:
    date: str
    condition: str
    temperature_min: float
    temperature_max: float
    precipitation_probability_max: float | None


@dataclass(frozen=True)
class WeatherForecast:
    location_name: str
    days: list[DailyForecast]


class WeatherClient:
    """Free, keyless forecasts from Open-Meteo - works the same regardless
    of which chat model asked for the weather."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def forecast(self, location: str, days: int = 7) -> WeatherForecast:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                geo_response = await client.get(
                    GEOCODING_URL,
                    params={"name": location, "count": 1, "language": "en", "format": "json"},
                )
                geo_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise WeatherError("Could not look up that location.") from exc

            results = geo_response.json().get("results") or []
            if not results:
                raise WeatherError(f"Could not find a location called '{location}'.")
            place = results[0]

            try:
                forecast_response = await client.get(
                    FORECAST_URL,
                    params={
                        "latitude": place["latitude"],
                        "longitude": place["longitude"],
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                        "timezone": "auto",
                        "forecast_days": days,
                    },
                )
                forecast_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise WeatherError("Could not fetch the forecast.") from exc

        daily = forecast_response.json().get("daily") or {}
        dates = daily.get("time", [])
        codes = daily.get("weather_code", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        rain_chances = daily.get("precipitation_probability_max", [])

        days_out = [
            DailyForecast(
                date=dates[i],
                condition=_WEATHER_CODES.get(codes[i], f"code {codes[i]}"),
                temperature_min=lows[i],
                temperature_max=highs[i],
                precipitation_probability_max=rain_chances[i] if i < len(rain_chances) else None,
            )
            for i in range(len(dates))
        ]

        name_parts = [part for part in (place.get("name"), place.get("admin1"), place.get("country")) if part]
        return WeatherForecast(location_name=", ".join(name_parts), days=days_out)
