from __future__ import annotations

from integrations.weather import precipitation_to_text, weather_code_to_text, weather_text_from_current


def test_weather_code_to_text():
    assert weather_code_to_text(0) == "晴"
    assert weather_code_to_text(2) == "多云"
    assert weather_code_to_text(999) == "天气"


def test_precipitation_overrides_cloudy_weather_code():
    assert precipitation_to_text(0.2) == "小雨"
    assert precipitation_to_text(1.5) == "雨"
    assert precipitation_to_text(4.5) == "大雨"
    assert precipitation_to_text(8.0) == "暴雨"
    assert weather_text_from_current(3, 8.0) == "暴雨"
    assert weather_text_from_current(3, 0.0) == "阴"
