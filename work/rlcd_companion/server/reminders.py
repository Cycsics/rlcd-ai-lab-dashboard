from __future__ import annotations

from models import AiStatus, Alert, DashboardState, Meeting


def _first_unacked_meeting_alert(
    meetings: list[Meeting],
    now_ts: int,
    acknowledged: set[str],
    kind: str,
    max_delta_seconds: int,
    min_delta_seconds: int = 0,
) -> Alert | None:
    for meeting in sorted(meetings, key=lambda item: item.start_ts):
        delta = meeting.start_ts - now_ts
        if min_delta_seconds <= delta <= max_delta_seconds:
            key = f"meeting:{meeting.start_ts}:{kind}"
            if key in acknowledged:
                continue
            if kind == "now":
                return Alert(
                    kind="meeting_now",
                    key=key,
                    title="该进会议了",
                    message=meeting.title,
                    detail="会议已经开始",
                    meeting=meeting,
                )
            if kind == "5":
                return Alert(
                    kind="meeting_5",
                    key=key,
                    title="还有 5 分钟开会",
                    message=meeting.title,
                    detail="建议现在收尾",
                    meeting=meeting,
                )
            return Alert(
                kind="meeting_15",
                key=key,
                title="还有 15 分钟开会",
                message=meeting.title,
                detail="我先提醒你一下",
                meeting=meeting,
            )
    return None


def select_alert(state: DashboardState, acknowledged: set[str] | None = None) -> Alert | None:
    acknowledged = acknowledged or set()

    meeting_now = _first_unacked_meeting_alert(
        state.meetings,
        state.now_ts,
        acknowledged,
        kind="now",
        min_delta_seconds=-180,
        max_delta_seconds=0,
    )
    if meeting_now:
        return meeting_now

    meeting_5 = _first_unacked_meeting_alert(
        state.meetings,
        state.now_ts,
        acknowledged,
        kind="5",
        min_delta_seconds=1,
        max_delta_seconds=5 * 60,
    )
    if meeting_5:
        return meeting_5

    if state.ai_status == AiStatus.needs_confirm:
        key = f"ai:needs_confirm:{state.ai_title}"
        if key not in acknowledged:
            return Alert(
                kind="ai_needs_confirm",
                key=key,
                title="AI 需要你确认",
                message=state.ai_title or "任务暂停",
                detail="请回到电脑看一眼",
            )

    if state.ai_status == AiStatus.interrupted:
        key = f"ai:interrupted:{state.ai_title}"
        if key not in acknowledged:
            return Alert(
                kind="ai_interrupted",
                key=key,
                title="AI 中断了",
                message=state.ai_title or "任务中断",
                detail="请回到电脑看一眼",
            )

    if state.ai_status == AiStatus.done:
        key = f"ai:done:{state.ai_title}"
        if key not in acknowledged:
            return Alert(
                kind="ai_done",
                key=key,
                title="我搞定啦",
                message=state.ai_title or "AI 工作已完成",
                detail="请回到电脑验收",
            )

    meeting_15 = _first_unacked_meeting_alert(
        state.meetings,
        state.now_ts,
        acknowledged,
        kind="15",
        min_delta_seconds=5 * 60 + 1,
        max_delta_seconds=15 * 60,
    )
    if meeting_15:
        return meeting_15

    return None
