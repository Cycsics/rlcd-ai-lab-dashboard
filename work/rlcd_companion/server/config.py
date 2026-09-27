from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import yaml


@dataclass(frozen=True)
class WeatherConfig:
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass(frozen=True)
class FeishuConfig:
    cli_path: str = "/opt/homebrew/bin/lark-cli"
    enabled: bool = False
    message_window_minutes: int = 15


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "Asia/Shanghai"
    weather: WeatherConfig = WeatherConfig()
    feishu: FeishuConfig = FeishuConfig()
    coding_stale_minutes: int = 8


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return _apply_env_overrides(AppConfig())
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    weather = data.get("weather") or {}
    feishu = data.get("feishu") or {}
    ai = data.get("ai") or {}
    return _apply_env_overrides(AppConfig(
        timezone=data.get("timezone", "Asia/Shanghai"),
        weather=WeatherConfig(
            latitude=float(weather.get("latitude", 0.0)),
            longitude=float(weather.get("longitude", 0.0)),
        ),
        feishu=FeishuConfig(
            cli_path=feishu.get("cli_path", "/opt/homebrew/bin/lark-cli"),
            enabled=bool(feishu.get("enabled", False)),
            message_window_minutes=int(feishu.get("message_window_minutes", 15)),
        ),
        coding_stale_minutes=int(ai.get("coding_stale_minutes", 8)),
    ))


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    if os.getenv("RLCD_FEISHU_ENABLED") == "1":
        return AppConfig(
            timezone=config.timezone,
            weather=config.weather,
            feishu=FeishuConfig(
                cli_path=config.feishu.cli_path,
                enabled=True,
                message_window_minutes=config.feishu.message_window_minutes,
            ),
            coding_stale_minutes=config.coding_stale_minutes,
        )
    return config
