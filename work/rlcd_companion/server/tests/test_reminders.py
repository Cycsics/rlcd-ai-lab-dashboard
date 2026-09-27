from __future__ import annotations

from models import AiStatus, DashboardState, Meeting
from reminders import select_alert


def state_for(delta_seconds: int) -> DashboardState:
    now = 1_800_000_000
    return DashboardState(
        now_ts=now,
        meetings=[Meeting("产品评审", now + delta_seconds, now + delta_seconds + 1800)],
    )


def test_no_meeting_alert_at_16_minutes():
    assert select_alert(state_for(16 * 60), set()) is None


def test_meeting_15_minute_alert():
    assert select_alert(state_for(15 * 60), set()).kind == "meeting_15"


def test_meeting_5_minute_alert():
    assert select_alert(state_for(5 * 60), set()).kind == "meeting_5"


def test_meeting_now_alert():
    assert select_alert(state_for(0), set()).kind == "meeting_now"


def test_ai_needs_confirm_beats_15_minute_meeting():
    state = state_for(15 * 60)
    state.ai_status = AiStatus.needs_confirm
    state.ai_title = "等待确认"
    assert select_alert(state, set()).kind == "ai_needs_confirm"


def test_ai_interrupted_alert():
    state = state_for(16 * 60)
    state.ai_status = AiStatus.interrupted
    state.ai_title = "测试失败"
    alert = select_alert(state, set())
    assert alert.kind == "ai_interrupted"
    assert alert.title == "AI 中断了"


def test_ai_done_alert_copy_does_not_hide_key_location():
    state = state_for(16 * 60)
    state.ai_status = AiStatus.done
    state.ai_title = "任务完成"
    alert = select_alert(state, set())
    assert alert.kind == "ai_done"
    assert alert.detail == "请回到电脑验收"


def test_ack_skips_current_alert():
    state = state_for(5 * 60)
    alert = select_alert(state, set())
    assert select_alert(state, {alert.key}) is None
