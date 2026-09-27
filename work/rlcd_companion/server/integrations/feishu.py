from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from models import FeishuMessageSummary, Meeting

TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class FeishuStatus:
    ok: bool
    message: str


@dataclass(frozen=True)
class AgendaView:
    day_label: str
    title: str
    date_ts: int
    meetings: list[Meeting]
    is_fallback: bool = False


def check_cli(cli_path: str = "/opt/homebrew/bin/lark-cli") -> FeishuStatus:
    try:
        result = subprocess.run(
            [cli_path, "doctor"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return FeishuStatus(False, f"找不到飞书 CLI：{cli_path}")
    except subprocess.TimeoutExpired:
        return FeishuStatus(False, "飞书 CLI doctor 超时")

    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        return FeishuStatus(False, output or "飞书 CLI doctor 失败")
    return FeishuStatus(True, result.stdout.strip())


def fetch_current_user_open_id(cli_path: str = "/opt/homebrew/bin/lark-cli") -> str:
    result = subprocess.run(
        [cli_path, "doctor"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(result.stdout)
    for check in payload.get("checks", []):
        if not isinstance(check, dict):
            continue
        message = str(check.get("message", ""))
        match = re.search(r"\((ou_[^)]+)\)", message)
        if match:
            return match.group(1)
    return ""


def run_agenda(
    cli_path: str = "/opt/homebrew/bin/lark-cli",
    start: str | None = None,
    end: str | None = None,
) -> Any:
    command = [cli_path, "calendar", "+agenda", "--format", "json", "--as", "user"]
    if start:
        command.extend(["--start", start])
    if end:
        command.extend(["--end", end])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def run_event_detail(
    cli_path: str,
    calendar_id: str,
    event_id: str,
) -> Any:
    result = subprocess.run(
        [
            cli_path,
            "calendar",
            "events",
            "get",
            "--format",
            "json",
            "--as",
            "user",
            "--params",
            json.dumps(
                {
                    "calendar_id": calendar_id,
                    "event_id": event_id,
                    "need_attendee": True,
                    "max_attendee_num": 50,
                    "user_id_type": "open_id",
                },
                ensure_ascii=False,
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def fetch_primary_calendar_id(cli_path: str = "/opt/homebrew/bin/lark-cli") -> str:
    result = subprocess.run(
        [cli_path, "calendar", "calendars", "primary", "--format", "json", "--as", "user"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(result.stdout)
    calendars = payload.get("data", {}).get("calendars", [])
    for item in calendars:
        calendar = item.get("calendar") if isinstance(item, dict) else None
        if isinstance(calendar, dict) and calendar.get("calendar_id"):
            return str(calendar["calendar_id"])
    return ""


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "events", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_items(value)
            if nested:
                return nested
    return []


def _extract_timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number // 1000 if number > 10_000_000_000 else number
    if isinstance(value, str) and value.isdigit():
        number = int(value)
        return number // 1000 if number > 10_000_000_000 else number
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value).timestamp())
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("timestamp", "datetime", "date_time", "time"):
            ts = _extract_timestamp(value.get(key))
            if ts:
                return ts
    return None


def _extract_location(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "display_name", "summary", "location", "address"):
            location = _extract_location(value.get(key))
            if location:
                return location
    if isinstance(value, list):
        parts = [_extract_location(item) for item in value]
        return "、".join(part for part in parts if part)
    return ""


def _extract_calendar_id(item: dict[str, Any]) -> str:
    return str(item.get("organizer_calendar_id") or item.get("calendar_id") or "")


def _extract_event_id(item: dict[str, Any]) -> str:
    return str(item.get("event_id") or item.get("id") or "")


def _extract_event(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("event"), dict):
            return data["event"]
        if isinstance(payload.get("event"), dict):
            return payload["event"]
    return {}


def _extract_resource_location_from_event(payload: Any) -> str:
    event = _extract_event(payload)
    location = _extract_location(event.get("location"))
    if location:
        return location
    attendees = event.get("attendees")
    if isinstance(attendees, list):
        resource_names = [
            _extract_location(attendee.get("display_name"))
            for attendee in attendees
            if isinstance(attendee, dict)
            and attendee.get("type") == "resource"
            and attendee.get("rsvp_status") != "decline"
        ]
        return "、".join(name for name in resource_names if name)
    return ""


def parse_meetings(payload: Any, now_ts: int) -> list[Meeting]:
    meetings: list[Meeting] = []
    for item in _extract_items(payload):
        title = item.get("summary") or item.get("title") or item.get("name") or "未命名会议"
        location = (
            _extract_location(item.get("location"))
            or _extract_location(item.get("meeting_room"))
            or _extract_location(item.get("room"))
            or _extract_location(item.get("rooms"))
            or _extract_location(item.get("meeting_rooms"))
        )
        start = (
            _extract_timestamp(item.get("start_time"))
            or _extract_timestamp(item.get("start"))
            or _extract_timestamp(item.get("start_at"))
        )
        end = (
            _extract_timestamp(item.get("end_time"))
            or _extract_timestamp(item.get("end"))
            or _extract_timestamp(item.get("end_at"))
            or (start + 1800 if start else None)
        )
        if not start or not end:
            continue
        if end < now_ts:
            continue
        meetings.append(
            Meeting(
                title=str(title),
                start_ts=start,
                end_ts=end,
                location=location,
                calendar_id=_extract_calendar_id(item),
                event_id=_extract_event_id(item),
            )
        )
    return sorted(meetings, key=lambda meeting: meeting.start_ts)


def enrich_meetings_with_event_details(
    meetings: list[Meeting],
    fetch_detail: Any,
    default_calendar_id: str = "",
) -> list[Meeting]:
    enriched: list[Meeting] = []
    for meeting in meetings:
        calendar_id = default_calendar_id or meeting.calendar_id
        if meeting.location or not calendar_id or not meeting.event_id:
            enriched.append(meeting)
            continue
        try:
            detail = fetch_detail(calendar_id, meeting.event_id)
        except Exception:  # noqa: BLE001
            enriched.append(meeting)
            continue
        location = _extract_resource_location_from_event(detail)
        enriched.append(replace(meeting, location=location) if location else meeting)
    return enriched


def fetch_remaining_meetings(cli_path: str, now_ts: int) -> list[Meeting]:
    meetings = parse_meetings(run_agenda(cli_path), now_ts)
    return enrich_meetings_with_event_details(
        meetings,
        lambda calendar_id, event_id: run_event_detail(cli_path, calendar_id, event_id),
    )


def _date_text(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).date().isoformat()


def _date_start_ts(day_text: str) -> int:
    day = datetime.fromisoformat(day_text).replace(tzinfo=TZ)
    return int(day.timestamp())


def _next_monday(day: datetime) -> datetime:
    days = (7 - day.weekday()) % 7
    if days == 0:
        days = 7
    return day + timedelta(days=days)


def choose_agenda_view(
    fetch_day: Any,
    now_ts: int,
    fetch_detail: Any | None = None,
    default_calendar_id: str = "",
) -> AgendaView:
    today = datetime.fromtimestamp(now_ts, TZ)
    today_text = today.date().isoformat()
    today_meetings = parse_meetings(fetch_day(today_text), now_ts)
    if fetch_detail is not None:
        today_meetings = enrich_meetings_with_event_details(
            today_meetings,
            fetch_detail,
            default_calendar_id,
        )
    if today_meetings or today.weekday() < 5:
        return AgendaView(
            day_label="今天",
            title="今日日程",
            date_ts=_date_start_ts(today_text),
            meetings=today_meetings,
        )

    monday = _next_monday(today)
    monday_text = monday.date().isoformat()
    monday_meetings = parse_meetings(fetch_day(monday_text), now_ts)
    if fetch_detail is not None:
        monday_meetings = enrich_meetings_with_event_details(
            monday_meetings,
            fetch_detail,
            default_calendar_id,
        )
    return AgendaView(
        day_label="周一",
        title="周一日程",
        date_ts=_date_start_ts(monday_text),
        meetings=monday_meetings,
        is_fallback=True,
    )


def fetch_agenda_view(cli_path: str, now_ts: int) -> AgendaView:
    def fetch_day(day_text: str) -> Any:
        return run_agenda(cli_path, start=day_text, end=day_text)

    primary_calendar_id = fetch_primary_calendar_id(cli_path)
    return choose_agenda_view(
        fetch_day,
        now_ts,
        lambda calendar_id, event_id: run_event_detail(cli_path, calendar_id, event_id),
        primary_calendar_id,
    )


def _iso_at(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds")


def run_recent_messages(
    cli_path: str = "/opt/homebrew/bin/lark-cli",
    now_ts: int | None = None,
    window_minutes: int = 15,
) -> Any:
    now = int(datetime.now(TZ).timestamp()) if now_ts is None else now_ts
    start = now - max(1, window_minutes) * 60
    result = subprocess.run(
        [
            cli_path,
            "im",
            "+messages-search",
            "--format",
            "json",
            "--page-size",
            "50",
            "--start",
            _iso_at(start),
            "--end",
            _iso_at(now),
            "--exclude-sender-type",
            "bot",
            "--as",
            "user",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _extract_message_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if "message_id" in payload:
        return [payload]
    for key in ("messages", "items", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        nested = _extract_message_items(value)
        if nested:
            return nested
    return []


def _message_sender_open_id(item: dict[str, Any]) -> str:
    sender = item.get("sender")
    if isinstance(sender, dict):
        for key in ("open_id", "id", "sender_id", "user_id"):
            value = sender.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("sender_open_id", "sender_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _message_source_name(item: dict[str, Any]) -> str:
    for key in ("chat_name", "chat"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = value.get("name") or value.get("chat_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    partner = item.get("chat_partner")
    if isinstance(partner, dict):
        name = partner.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    sender = item.get("sender")
    if isinstance(sender, dict):
        name = sender.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    chat_id = item.get("chat_id")
    if isinstance(chat_id, str) and chat_id:
        return f"会话{chat_id[-4:]}"
    return "飞书会话"


def parse_recent_message_summary(
    payload: Any,
    self_open_id: str = "",
    window_minutes: int = 15,
) -> FeishuMessageSummary:
    items = []
    for item in _extract_message_items(payload):
        if item.get("deleted") is True:
            continue
        if self_open_id and _message_sender_open_id(item) == self_open_id:
            continue
        items.append(item)

    source_names: list[str] = []
    source_keys: set[str] = set()
    for item in items:
        source_key = str(item.get("chat_id") or _message_source_name(item))
        if source_key in source_keys:
            continue
        source_keys.add(source_key)
        source_names.append(_message_source_name(item))

    return FeishuMessageSummary(
        chat_count=len(source_keys),
        total_count=len(items),
        sources=source_names[:4],
        is_available=True,
        window_minutes=window_minutes,
    )


def fetch_recent_message_summary(
    cli_path: str,
    now_ts: int,
    window_minutes: int = 15,
    self_open_id: str = "",
) -> FeishuMessageSummary:
    return parse_recent_message_summary(
        run_recent_messages(cli_path, now_ts, window_minutes),
        self_open_id=self_open_id,
        window_minutes=window_minutes,
    )


def run_my_tasks(cli_path: str = "/opt/homebrew/bin/lark-cli") -> Any:
    result = subprocess.run(
        [
            cli_path,
            "task",
            "+get-my-tasks",
            "--complete=false",
            "--page-limit",
            "10",
            "--format",
            "json",
            "--as",
            "user",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def parse_todo_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    data = payload.get("data", payload)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return len(items)
    return 0


def fetch_todo_count(cli_path: str) -> int:
    return parse_todo_count(run_my_tasks(cli_path))
