from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


SCREEN_W = 400
SCREEN_H = 300
BITMAP_BYTES = (SCREEN_W // 8) * SCREEN_H


class AiStatus(str, Enum):
    idle = "idle"
    coding = "coding"
    done = "done"
    needs_confirm = "needs_confirm"
    interrupted = "interrupted"


@dataclass(frozen=True)
class Meeting:
    title: str
    start_ts: int
    end_ts: int
    location: str = ""
    calendar_id: str = ""
    event_id: str = ""


@dataclass
class DashboardState:
    now_ts: int
    weather_text: str = "天气--"
    temperature_c: int | None = None
    indoor_temperature_c: float | None = None
    indoor_humidity_percent: float | None = None
    battery_percent: int | None = None
    todo_count: int = 0
    meetings: list[Meeting] = field(default_factory=list)
    agenda_day_label: str = "今天"
    agenda_title: str = "今日日程"
    agenda_date_ts: int | None = None
    agenda_is_fallback: bool = False
    ai_status: AiStatus = AiStatus.idle
    ai_title: str = "没有任务"
    frame_index: int = 0
    feishu_messages: "FeishuMessageSummary" = field(default_factory=lambda: FeishuMessageSummary())
    music: "MusicStatus" = field(default_factory=lambda: MusicStatus())


@dataclass
class CodexSession:
    session_id: str
    status: AiStatus
    title: str
    project: str = ""
    conversation_title: str = ""
    source: str = ""
    cwd: str = ""
    updated_ts: int = 0
    update_order: int = 0


@dataclass
class FeishuMessageSummary:
    chat_count: int = 0
    total_count: int = 0
    sources: list[str] = field(default_factory=list)
    is_available: bool = False
    window_minutes: int = 15


@dataclass
class MusicStatus:
    is_playing: bool = False
    player: str = ""
    title: str = ""
    artist: str = ""

    @property
    def display(self) -> str:
        if not self.is_playing:
            return "未播放"
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        if self.title:
            return self.title
        if self.player:
            return f"{self.player}播放中"
        return "播放中"


@dataclass(frozen=True)
class Alert:
    kind: str
    key: str
    title: str
    message: str
    detail: str = ""
    meeting: Meeting | None = None
