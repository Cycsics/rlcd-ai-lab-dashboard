from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from integrations.feishu import (
    enrich_meetings_with_event_details,
    choose_agenda_view,
    parse_meetings,
    parse_recent_message_summary,
    parse_todo_count,
)


def test_parse_meetings_filters_past_and_sorts():
    now = 1_800_000_000
    payload = {
        "items": [
            {"summary": "未来会议 B", "start_time": now + 7200, "end_time": now + 9000},
            {"summary": "已结束会议", "start_time": now - 7200, "end_time": now - 3600},
            {"summary": "未来会议 A", "start_time": now + 1800, "end_time": now + 3600},
        ]
    }
    meetings = parse_meetings(payload, now)
    assert [meeting.title for meeting in meetings] == ["未来会议 A", "未来会议 B"]


def test_parse_meetings_accepts_nested_time_dict():
    now = 1_800_000_000
    payload = {
        "data": {
            "items": [
                {
                    "title": "产品评审",
                    "start": {"timestamp": str(now + 1800)},
                    "end": {"timestamp": str(now + 3600)},
                }
            ]
        }
    }
    meetings = parse_meetings(payload, now)
    assert len(meetings) == 1
    assert meetings[0].title == "产品评审"


def test_parse_meetings_accepts_feishu_datetime_dict():
    now = 1_781_408_000
    payload = {
        "ok": True,
        "data": [
            {
                "summary": "早会",
                "start_time": {"datetime": "2026-06-15T09:20:00+08:00"},
                "end_time": {"datetime": "2026-06-15T09:30:00+08:00"},
            }
        ],
    }
    meetings = parse_meetings(payload, now)
    assert len(meetings) == 1
    assert meetings[0].title == "早会"
    assert meetings[0].start_ts == 1_781_486_400


def test_parse_meetings_extracts_meeting_room_location():
    now = 1_781_408_000
    payload = {
        "data": [
            {
                "summary": "需求评审",
                "start_time": {"datetime": "2026-06-15T10:00:00+08:00"},
                "end_time": {"datetime": "2026-06-15T10:30:00+08:00"},
                "meeting_room": {"name": "T3-18F-星云"},
            }
        ],
    }

    meetings = parse_meetings(payload, now)

    assert len(meetings) == 1
    assert meetings[0].location == "T3-18F-星云"


def test_enrich_meetings_uses_resource_attendee_from_event_detail():
    now = 1_781_408_000
    payload = {
        "data": [
            {
                "summary": "需求评审",
                "event_id": "event_1_0",
                "calendar_id": "wrong_calendar_id",
                "organizer_calendar_id": "feishu.cn_primary@group.calendar.feishu.cn",
                "start_time": {"datetime": "2026-06-15T10:00:00+08:00"},
                "end_time": {"datetime": "2026-06-15T10:30:00+08:00"},
            }
        ],
    }
    meetings = parse_meetings(payload, now)

    def fake_fetch(calendar_id: str, event_id: str) -> dict:
        assert calendar_id == "feishu.cn_primary@group.calendar.feishu.cn"
        assert event_id == "event_1_0"
        return {
            "data": {
                "event": {
                    "attendees": [
                        {
                            "type": "resource",
                            "display_name": "F20-上海-小会议室(6) 国际创新谷",
                            "room_id": "omm_room",
                        },
                        {"type": "user", "display_name": "罗文彬"},
                    ]
                }
            }
        }

    enriched = enrich_meetings_with_event_details(meetings, fake_fetch)

    assert enriched[0].location == "F20-上海-小会议室(6) 国际创新谷"


def test_choose_agenda_view_falls_back_to_monday_on_empty_weekend():
    sunday = 1_781_409_600  # 2026-06-14 12:00:00+08:00

    def fake_fetch(day: str):
        if day == "2026-06-14":
            return []
        if day == "2026-06-15":
            return [
                {
                    "summary": "周一早会",
                    "start_time": {"datetime": "2026-06-15T09:20:00+08:00"},
                    "end_time": {"datetime": "2026-06-15T09:30:00+08:00"},
                }
            ]
        raise AssertionError(day)

    view = choose_agenda_view(fake_fetch, sunday)
    assert view.day_label == "周一"
    assert view.title == "周一日程"
    assert [meeting.title for meeting in view.meetings] == ["周一早会"]
    assert view.is_fallback is True


def test_choose_agenda_view_can_enrich_today_meeting_locations():
    now = int(datetime(2026, 6, 15, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())

    def fake_fetch_day(day: str):
        assert day == "2026-06-15"
        return {
            "data": [
                {
                    "summary": "需求评审",
                    "event_id": "event_1_0",
                    "organizer_calendar_id": "feishu.cn_primary@group.calendar.feishu.cn",
                    "start_time": {"datetime": "2026-06-15T10:00:00+08:00"},
                    "end_time": {"datetime": "2026-06-15T10:30:00+08:00"},
                }
            ],
        }

    def fake_fetch_detail(calendar_id: str, event_id: str):
        return {
            "data": {
                "event": {
                    "attendees": [
                        {
                            "type": "resource",
                            "display_name": "F20-上海-小会议室(6) 国际创新谷",
                            "rsvp_status": "accept",
                        }
                    ]
                }
            }
        }

    view = choose_agenda_view(
        fake_fetch_day,
        now,
        fake_fetch_detail,
        default_calendar_id="feishu.cn_primary@group.calendar.feishu.cn",
    )

    assert view.meetings[0].location == "F20-上海-小会议室(6) 国际创新谷"


def test_parse_todo_count():
    payload = {"ok": True, "data": {"items": [{"summary": "A"}, {"summary": "B"}]}}
    assert parse_todo_count(payload) == 2


def test_parse_recent_message_summary_filters_self_and_groups_sources():
    payload = {
        "messages": [
            {
                "message_id": "om_1",
                "chat_id": "oc_a",
                "chat_name": "项目群",
                "sender": {"open_id": "ou_other", "name": "张三"},
            },
            {
                "message_id": "om_2",
                "chat_id": "oc_a",
                "chat_name": "项目群",
                "sender": {"open_id": "ou_other2", "name": "李四"},
            },
            {
                "message_id": "om_self",
                "chat_id": "oc_b",
                "chat_name": "自己发的群",
                "sender": {"open_id": "ou_me", "name": "我"},
            },
            {
                "message_id": "om_deleted",
                "chat_id": "oc_c",
                "chat_name": "已撤回",
                "sender": {"open_id": "ou_other", "name": "张三"},
                "deleted": True,
            },
        ]
    }

    summary = parse_recent_message_summary(payload, self_open_id="ou_me", window_minutes=15)

    assert summary.is_available is True
    assert summary.window_minutes == 15
    assert summary.total_count == 2
    assert summary.chat_count == 1
    assert summary.sources == ["项目群"]


def test_parse_recent_message_summary_uses_p2p_partner_name():
    payload = {
        "data": [
            {
                "message_id": "om_1",
                "chat_id": "oc_p2p",
                "chat_partner": {"name": "王五"},
                "sender": {"open_id": "ou_other"},
            }
        ]
    }

    summary = parse_recent_message_summary(payload, self_open_id="ou_me")

    assert summary.sources == ["王五"]
