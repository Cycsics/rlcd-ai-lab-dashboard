from __future__ import annotations

import time
from dataclasses import dataclass

from config import AppConfig
from integrations.feishu import (
    fetch_agenda_view,
    fetch_current_user_open_id,
    fetch_recent_message_summary,
    fetch_todo_count,
)
from integrations.music import fetch_music_status
from integrations.weather import fetch_weather
from models import AiStatus, DashboardState, FeishuMessageSummary
from renderer import sample_state


@dataclass
class Cache:
    agenda_value: object | None = None
    meetings_at: float = 0
    todo_value: int | None = None
    todo_at: float = 0
    messages_value: object | None = None
    messages_at: float = 0
    self_open_id: str = ""
    weather_text: str | None = None
    weather_temp: int | None = None
    weather_at: float = 0
    music_value: object | None = None
    music_at: float = 0
    last_error: str = ""


cache = Cache()


def _fresh(timestamp: float, ttl: int) -> bool:
    return timestamp > 0 and time.time() - timestamp < ttl


def build_dashboard_state(
    config: AppConfig,
    battery: int | None,
    ai_status: AiStatus,
    ai_title: str,
    frame_index: int,
    now_ts: int | None = None,
    indoor_temperature_c: float | None = None,
    indoor_humidity_percent: float | None = None,
) -> DashboardState:
    now = int(time.time()) if now_ts is None else now_ts
    state = sample_state(now)
    state.battery_percent = battery
    state.indoor_temperature_c = indoor_temperature_c
    state.indoor_humidity_percent = indoor_humidity_percent
    state.ai_status = ai_status
    state.ai_title = ai_title
    state.frame_index = frame_index

    if config.feishu.enabled:
        try:
            if not _fresh(cache.meetings_at, 60):
                cache.agenda_value = fetch_agenda_view(config.feishu.cli_path, now)
                cache.meetings_at = time.time()
            if cache.agenda_value is not None:
                agenda = cache.agenda_value
                state.meetings = list(agenda.meetings)
                state.agenda_day_label = agenda.day_label
                state.agenda_title = agenda.title
                state.agenda_date_ts = agenda.date_ts
                state.agenda_is_fallback = agenda.is_fallback
        except Exception as exc:  # noqa: BLE001
            cache.last_error = f"飞书日程失败：{exc}"
            state.meetings = []

        try:
            if not _fresh(cache.todo_at, 300):
                cache.todo_value = fetch_todo_count(config.feishu.cli_path)
                cache.todo_at = time.time()
            state.todo_count = int(cache.todo_value or 0)
        except Exception as exc:  # noqa: BLE001
            cache.last_error = f"飞书待办失败：{exc}"

        try:
            if not cache.self_open_id:
                cache.self_open_id = fetch_current_user_open_id(config.feishu.cli_path)
            if not _fresh(cache.messages_at, 60):
                cache.messages_value = fetch_recent_message_summary(
                    config.feishu.cli_path,
                    now,
                    config.feishu.message_window_minutes,
                    cache.self_open_id,
                )
                cache.messages_at = time.time()
            if cache.messages_value is not None:
                state.feishu_messages = cache.messages_value
        except Exception as exc:  # noqa: BLE001
            cache.messages_value = FeishuMessageSummary(
                is_available=False,
                window_minutes=config.feishu.message_window_minutes,
            )
            cache.messages_at = time.time()
            state.feishu_messages = cache.messages_value
            cache.last_error = f"飞书消息失败：{exc}"

    try:
        if not _fresh(cache.music_at, 10):
            cache.music_value = fetch_music_status()
            cache.music_at = time.time()
        if cache.music_value is not None:
            state.music = cache.music_value
    except Exception as exc:  # noqa: BLE001
        cache.last_error = f"音乐失败：{exc}"

    try:
        if not _fresh(cache.weather_at, 600):
            weather = fetch_weather(config.weather.latitude, config.weather.longitude)
            cache.weather_text = weather.text
            cache.weather_temp = weather.temperature_c
            cache.weather_at = time.time()
        if cache.weather_text is not None:
            state.weather_text = cache.weather_text
            state.temperature_c = cache.weather_temp
    except Exception as exc:  # noqa: BLE001
        cache.last_error = f"天气失败：{exc}"

    return state
