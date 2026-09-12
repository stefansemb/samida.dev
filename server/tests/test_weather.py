import httpx
import pytest

from samida import weather as weather_module
from samida.weather import WeatherClient, WeatherError


def _mock_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(weather_module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_forecast_geocodes_then_fetches_daily_forecast(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.params["name"] == "Göteborg"
            return httpx.Response(
                200,
                json={"results": [{"name": "Göteborg", "admin1": "Västra Götaland", "country": "Sweden", "latitude": 57.7, "longitude": 11.97}]},
            )
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["latitude"] == "57.7"
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-09-13", "2026-09-14"],
                    "weather_code": [0, 61],
                    "temperature_2m_max": [18.0, 16.5],
                    "temperature_2m_min": [8.0, 9.0],
                    "precipitation_probability_max": [5, 60],
                }
            },
        )

    _mock_client(monkeypatch, handler)
    client = WeatherClient(timeout=5.0)

    result = await client.forecast("Göteborg")

    assert result.location_name == "Göteborg, Västra Götaland, Sweden"
    assert len(result.days) == 2
    assert result.days[0].condition == "clear sky"
    assert result.days[1].condition == "slight rain"
    assert result.days[0].temperature_max == 18.0


@pytest.mark.asyncio
async def test_forecast_raises_when_location_not_found(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    _mock_client(monkeypatch, handler)
    client = WeatherClient(timeout=5.0)

    with pytest.raises(WeatherError):
        await client.forecast("Nonexistentplacexyz")


@pytest.mark.asyncio
async def test_forecast_raises_when_unreachable(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _mock_client(monkeypatch, handler)
    client = WeatherClient(timeout=5.0)

    with pytest.raises(WeatherError):
        await client.forecast("Göteborg")
