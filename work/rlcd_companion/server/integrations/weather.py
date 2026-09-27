from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import urlopen


WEATHER_CODE_TEXT = {
    0: "晴",
    1: "少云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾",
    51: "小雨",
    53: "小雨",
    55: "小雨",
    61: "雨",
    63: "雨",
    65: "大雨",
    71: "雪",
    73: "雪",
    75: "大雪",
    80: "阵雨",
    81: "阵雨",
    82: "暴雨",
    95: "雷雨",
}


@dataclass
class WeatherSnapshot:
    text: str
    temperature_c: int
    fetched_at: float


_cache: WeatherSnapshot | None = None


def weather_code_to_text(code: int) -> str:
    return WEATHER_CODE_TEXT.get(code, "天气")


def precipitation_to_text(precipitation_mm: float) -> str:
    if precipitation_mm >= 8:
        return "暴雨"
    if precipitation_mm >= 4:
        return "大雨"
    if precipitation_mm >= 1:
        return "雨"
    if precipitation_mm > 0:
        return "小雨"
    return ""


def weather_text_from_current(code: int, precipitation_mm: float) -> str:
    return precipitation_to_text(precipitation_mm) or weather_code_to_text(code)


def fetch_weather(
    latitude: float,
    longitude: float,
    cache_seconds: int = 600,
    stale_cache_seconds: int = 3600,
    timeout: float = 2.0,
) -> WeatherSnapshot:
    global _cache
    now = time.time()
    if _cache and now - _cache.fetched_at < cache_seconds:
        return _cache

    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,precipitation,rain,showers",
            "timezone": "Asia/Shanghai",
        }
    )
    try:
        with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, URLError):
        if _cache and now - _cache.fetched_at < stale_cache_seconds:
            return _cache
        raise
    current = payload.get("current") or {}
    precipitation = max(
        float(current.get("precipitation") or 0),
        float(current.get("rain") or 0),
        float(current.get("showers") or 0),
    )
    snapshot = WeatherSnapshot(
        text=weather_text_from_current(int(current.get("weather_code", -1)), precipitation),
        temperature_c=round(float(current.get("temperature_2m", 0))),
        fetched_at=now,
    )
    _cache = snapshot
    return snapshot
