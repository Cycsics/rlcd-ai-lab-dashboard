from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from config import load_config
from data_sources import build_dashboard_state
from models import AiStatus, Alert, CodexSession, DashboardState, FeishuMessageSummary
from pet import choose_pet_state
from reminders import select_alert
from renderer import render_png_bytes, render_test_pattern_bytes, render_u8g2_xbmp_bytes


class AiUpdate(BaseModel):
    status: AiStatus
    title: str = ""


class CodexStatusUpdate(BaseModel):
    status: AiStatus
    title: str = ""
    session_id: str = ""
    project: str = ""
    conversation_title: str = ""
    source: str = ""
    cwd: str = ""
    updated_ts: Optional[int] = None


class FeishuMessagesUpdate(BaseModel):
    chat_count: int = 0
    total_count: int = 0
    sources: list[str] = Field(default_factory=list)


@dataclass
class MemoryState:
    ai_status: AiStatus = AiStatus.idle
    ai_title: str = "没有任务"
    ai_updated_ts: int = 0
    codex_sessions: dict[str, CodexSession] = field(default_factory=dict)
    feishu_messages: FeishuMessageSummary = field(default_factory=FeishuMessageSummary)
    acknowledged: set[str] = field(default_factory=set)
    frame_index: int = 0
    last_ack: str | None = None
    indoor_temperature_c: float | None = None
    indoor_humidity_percent: float | None = None
    codex_update_counter: int = 0
    feishu_messages_updated_ts: int = 0


memory = MemoryState()
config = load_config()
app = FastAPI(title="RLCD 桌面小伙伴")
monitor = None
if os.getenv('RLCD_MONITOR_ENABLED', '1') == '1':
    from monitor_service import Monitor
    monitor = Monitor()
    app.include_router(monitor.router())

CODEX_STATUS_PRIORITY = {
    AiStatus.needs_confirm: 50,
    AiStatus.interrupted: 45,
    AiStatus.done: 35,
    AiStatus.coding: 25,
    AiStatus.idle: 0,
}
CODEX_VISIBLE_SECONDS = {
    AiStatus.needs_confirm: 6 * 60 * 60,
    AiStatus.interrupted: 6 * 60 * 60,
    AiStatus.done: 5 * 60,
    AiStatus.idle: 0,
}
DEFAULT_AI_TITLES = {
    AiStatus.idle: "没有任务",
    AiStatus.coding: "正在执行",
    AiStatus.done: "工作已完成",
    AiStatus.needs_confirm: "等待确认",
    AiStatus.interrupted: "任务已中断",
}
CODEX_SOURCE_PRIORITY = {
    "manual": 90,
    "codex-hook": 80,
    "rlcd-task": 70,
    "codex-notify": 10,
}


def title_for_status(status: AiStatus, title: str = "") -> str:
    return title.strip() or DEFAULT_AI_TITLES[status]


def codex_visible_seconds(status: AiStatus) -> int:
    if status == AiStatus.coding:
        return max(1, config.coding_stale_minutes) * 60
    return CODEX_VISIBLE_SECONDS[status]


def is_internal_codex_session(session: CodexSession) -> bool:
    title = session.title.strip().removeprefix("正在处理：")
    internal_markers = (
        "# Overview Generate 0 to 3 hyperp",
        "Generate a concise UI title",
        "The tasks typically have to do with coding-related tasks",
    )
    return any(marker in title for marker in internal_markers)


def purge_expired_codex_sessions(now_ts: int) -> None:
    expired: list[str] = []
    for session_id, session in memory.codex_sessions.items():
        visible_seconds = codex_visible_seconds(session.status)
        if (
            visible_seconds <= 0
            or now_ts - session.updated_ts > visible_seconds
            or is_internal_codex_session(session)
        ):
            expired.append(session_id)
    for session_id in expired:
        memory.codex_sessions.pop(session_id, None)


def active_codex_sessions(now_ts: int) -> list[CodexSession]:
    purge_expired_codex_sessions(now_ts)
    return [
        session
        for session in memory.codex_sessions.values()
        if session.status != AiStatus.idle
    ]


def session_source_priority(session: CodexSession) -> int:
    source = session.source.strip()
    if source.startswith("codex-hook:"):
        return CODEX_SOURCE_PRIORITY["codex-hook"]
    return CODEX_SOURCE_PRIORITY.get(source, 50)


def session_sort_key(session: CodexSession) -> tuple[int, int, int, int]:
    return (
        CODEX_STATUS_PRIORITY[session.status],
        session_source_priority(session),
        session.updated_ts,
        session.update_order,
    )


def codex_display_title(session: CodexSession) -> str:
    title = title_for_status(session.status, session.title)
    parts = [
        session.project.strip(),
        session.conversation_title.strip(),
        title,
    ]
    return "｜".join(part for part in parts if part)


def should_ignore_codex_update(payload: CodexStatusUpdate, status_title: str, now_ts: int) -> bool:
    source = payload.source.strip()
    if payload.status == AiStatus.idle:
        return False
    if source != "codex-notify":
        return False
    sessions = active_codex_sessions(now_ts)
    return any(session_source_priority(session) > CODEX_SOURCE_PRIORITY["codex-notify"] for session in sessions)


def aggregate_ai_state(now_ts: int) -> tuple[AiStatus, str]:
    sessions = active_codex_sessions(now_ts)
    candidates = sessions.copy()
    if memory.ai_status != AiStatus.idle:
        candidates.append(
            CodexSession(
                session_id="manual",
                status=memory.ai_status,
                title=memory.ai_title,
                source="manual",
                updated_ts=memory.ai_updated_ts or now_ts,
            )
        )
    if not candidates:
        return AiStatus.idle, DEFAULT_AI_TITLES[AiStatus.idle]

    top = max(candidates, key=session_sort_key)
    return top.status, codex_display_title(top)


def build_state(
    battery: int | None = None,
    indoor_temperature_c: float | None = None,
    indoor_humidity_percent: float | None = None,
) -> DashboardState:
    memory.frame_index += 1
    now_ts = int(time.time())
    ai_status, ai_title = aggregate_ai_state(now_ts)
    if indoor_temperature_c is not None:
        memory.indoor_temperature_c = indoor_temperature_c
    if indoor_humidity_percent is not None:
        memory.indoor_humidity_percent = indoor_humidity_percent
    state = build_dashboard_state(
        config=config,
        battery=battery,
        ai_status=ai_status,
        ai_title=ai_title,
        frame_index=memory.frame_index,
        now_ts=now_ts,
        indoor_temperature_c=memory.indoor_temperature_c,
        indoor_humidity_percent=memory.indoor_humidity_percent,
    )
    if memory.feishu_messages.is_available and now_ts - memory.feishu_messages_updated_ts < 120:
        state.feishu_messages = memory.feishu_messages
    return state


def current_alert(state: DashboardState) -> Alert | None:
    return select_alert(state, memory.acknowledged)


def sound_cue_for_alert(alert: Alert | None) -> str:
    if alert is None:
        return "none"
    if alert.kind in {"meeting_15", "meeting_5"}:
        return "meeting"
    if alert.kind == "meeting_now":
        return "meeting_now"
    if alert.kind == "ai_done":
        return "ai_done"
    return "none"


def alert_header_key(alert: Alert | None) -> str:
    if alert is None:
        return "none"
    return quote(alert.key, safe=":")


@app.get("/preview.png")
def preview_png(battery: Optional[int] = Query(default=82, ge=0, le=100)) -> Response:
    if monitor:
        return Response(content=monitor.image('png'), media_type='image/png', headers={'Cache-Control':'no-store'})
    state = build_state(battery)
    return Response(content=render_png_bytes(state, memory.acknowledged), media_type="image/png")


@app.get("/frame.bin")
def frame_bin(
    battery: Optional[int] = Query(default=None, ge=0, le=100),
    temp: Optional[float] = Query(default=None, ge=-40, le=85),
    humidity: Optional[float] = Query(default=None, ge=0, le=100),
    usb: Optional[bool] = Query(default=None),
    power_version: Optional[int] = Query(default=None,ge=1,le=10),
) -> Response:
    if monitor:
        if power_version is not None:
            monitor.environment.update({'usb_connected':usb,'power_firmware_version':power_version,'screen_seen_at':time.time()})
        return Response(content=monitor.image('bin',battery,temp,humidity),media_type='application/octet-stream',headers={
            **monitor.power_headers(),
            'X-RLCD-Layout':'monitor-v1','X-RLCD-Sound-Cue':'none',
            'X-RLCD-Alert-Level':'normal','X-RLCD-Alert-Key':'none',
            'X-RLCD-Pet-State':'idle','X-RLCD-Pet-Mode':'normal'})
    state = build_state(battery, temp, humidity)
    alert = current_alert(state)
    pet_state = choose_pet_state(state, alert.kind if alert else None)
    pet_mode = "alert" if alert else "normal"
    alert_level = "strong" if alert else "normal"
    return Response(
        content=render_u8g2_xbmp_bytes(state, memory.acknowledged),
        media_type="application/octet-stream",
        headers={
            "X-RLCD-Pet-State": pet_state,
            "X-RLCD-Pet-Mode": pet_mode,
            "X-RLCD-Alert-Level": alert_level,
            "X-RLCD-Alert-Key": alert_header_key(alert),
            "X-RLCD-Sound-Cue": sound_cue_for_alert(alert),
        },
    )


@app.get("/test-pattern.bin")
def test_pattern(pattern: str = "checker") -> Response:
    return Response(
        content=render_test_pattern_bytes(pattern),
        media_type="application/octet-stream",
    )


@app.post("/ai")
def update_ai(payload: AiUpdate) -> dict:
    memory.ai_status = payload.status
    memory.ai_title = title_for_status(payload.status, payload.title)
    memory.ai_updated_ts = int(time.time())
    memory.acknowledged = {
        key for key in memory.acknowledged if not key.startswith("ai:")
    }
    return {"ok": "true", "status": memory.ai_status.value, "title": memory.ai_title}


@app.post("/codex/status")
def update_codex_status(payload: CodexStatusUpdate) -> dict:
    now_ts = payload.updated_ts or int(time.time())
    session_id = payload.session_id.strip() or "codex:default"
    status_title = title_for_status(payload.status, payload.title)
    if should_ignore_codex_update(payload, status_title, now_ts):
        display_status, display_title = aggregate_ai_state(now_ts)
        return {
            "ok": "true",
            "ignored": "true",
            "session_id": session_id,
            "status": payload.status.value,
            "title": status_title,
            "display_status": display_status.value,
            "display_title": display_title,
            "active_sessions": len(active_codex_sessions(now_ts)),
        }
    if payload.status == AiStatus.idle:
        memory.codex_sessions.pop(session_id, None)
    else:
        memory.codex_update_counter += 1
        memory.codex_sessions[session_id] = CodexSession(
            session_id=session_id,
            status=payload.status,
            title=status_title,
            project=payload.project.strip(),
            conversation_title=payload.conversation_title.strip(),
            source=payload.source.strip() or "codex",
            cwd=payload.cwd.strip(),
            updated_ts=now_ts,
            update_order=memory.codex_update_counter,
        )
    memory.acknowledged = {
        key for key in memory.acknowledged if not key.startswith("ai:")
    }
    display_status, display_title = aggregate_ai_state(now_ts)
    return {
        "ok": "true",
        "session_id": session_id,
        "status": payload.status.value,
        "title": status_title,
        "display_status": display_status.value,
        "display_title": display_title,
        "active_sessions": len(active_codex_sessions(now_ts)),
    }


@app.post("/feishu/messages")
def update_feishu_messages(payload: FeishuMessagesUpdate) -> dict:
    sources = [source.strip() for source in payload.sources if source.strip()]
    memory.feishu_messages = FeishuMessageSummary(
        chat_count=max(0, payload.chat_count),
        total_count=max(0, payload.total_count),
        sources=sources[:4],
        is_available=True,
    )
    memory.feishu_messages_updated_ts = int(time.time())
    return {
        "ok": "true",
        "summary": {
            "chat_count": memory.feishu_messages.chat_count,
            "total_count": memory.feishu_messages.total_count,
            "sources": memory.feishu_messages.sources,
            "is_available": memory.feishu_messages.is_available,
        },
    }


@app.post("/ack")
def ack() -> dict:
    state = build_state()
    alert = current_alert(state)
    if alert:
        memory.acknowledged.add(alert.key)
        memory.last_ack = alert.key
        if alert.kind.startswith("ai_"):
            memory.ai_status = AiStatus.idle
            memory.ai_title = "没有任务"
            for session_id, session in list(memory.codex_sessions.items()):
                if session.status in {AiStatus.done, AiStatus.needs_confirm, AiStatus.interrupted}:
                    memory.codex_sessions.pop(session_id, None)
    return {"ok": "true", "ack": memory.last_ack}


@app.get("/state")
def state() -> dict:
    dashboard = build_state()
    alert = current_alert(dashboard)
    return {
        "ai_status": dashboard.ai_status.value,
        "ai_title": dashboard.ai_title,
        "alert": alert.kind if alert else None,
        "alert_key": alert.key if alert else None,
        "acknowledged": sorted(memory.acknowledged),
        "active_codex_sessions": len(active_codex_sessions(dashboard.now_ts)),
        "agenda": {
            "day_label": dashboard.agenda_day_label,
            "title": dashboard.agenda_title,
            "date_ts": dashboard.agenda_date_ts,
            "is_fallback": dashboard.agenda_is_fallback,
            "meetings": [
                {
                    "title": meeting.title,
                    "start_ts": meeting.start_ts,
                    "end_ts": meeting.end_ts,
                    "location": meeting.location,
                }
                for meeting in dashboard.meetings
            ],
        },
        "feishu_messages": {
            "chat_count": dashboard.feishu_messages.chat_count,
            "total_count": dashboard.feishu_messages.total_count,
            "sources": dashboard.feishu_messages.sources,
            "is_available": dashboard.feishu_messages.is_available,
            "window_minutes": dashboard.feishu_messages.window_minutes,
        },
        "music": {
            "is_playing": dashboard.music.is_playing,
            "player": dashboard.music.player,
            "artist": dashboard.music.artist,
            "title": dashboard.music.title,
            "display": dashboard.music.display,
        },
        "environment": {
            "indoor_temperature_c": dashboard.indoor_temperature_c,
            "indoor_humidity_percent": dashboard.indoor_humidity_percent,
        },
    }


@app.get("/codex/sessions")
def codex_sessions() -> dict:
    now_ts = int(time.time())
    sessions = sorted(active_codex_sessions(now_ts), key=session_sort_key, reverse=True)
    return {
        "sessions": [
            {
                "session_id": session.session_id,
                "status": session.status.value,
                "title": session.title,
                "project": session.project,
                "conversation_title": session.conversation_title,
                "source": session.source,
                "cwd": session.cwd,
                "updated_ts": session.updated_ts,
                "age_seconds": max(0, now_ts - session.updated_ts),
            }
            for session in sessions
        ]
    }
