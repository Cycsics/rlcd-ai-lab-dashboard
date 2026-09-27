from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from models import AiStatus, BITMAP_BYTES, SCREEN_H, SCREEN_W, Alert, DashboardState, Meeting
from pet import choose_pet_state, draw_pixel_pet
from reminders import select_alert


TZ = ZoneInfo("Asia/Shanghai")
FONT_CANDIDATES = [
    str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"),
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


FONT_11 = _font(11)
FONT_12 = _font(12)
FONT_13 = _font(13)
FONT_14 = _font(14)
FONT_16 = _font(16)
FONT_20 = _font(20)
ALERT_PANEL_BOX = (144, 62, 390, 200)
NORMAL_TOP_Y = 28
NORMAL_LEFT_W = 122
NORMAL_DOCK_Y = 258
NORMAL_LEFT_PET_BOTTOM_Y = 138
NORMAL_LEFT_SUMMARY_BOTTOM_Y = 207
NORMAL_RIGHT_TIMELINE_BOTTOM_Y = 92
NORMAL_RIGHT_FOCUS_BOTTOM_Y = 122
LUNCH_START = (12, 30)
LUNCH_END = (14, 0)


@dataclass(frozen=True)
class FocusSlot:
    title: str
    suggestion: str
    minutes: int
    in_meeting: bool = False


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    trimmed = text
    while trimmed and _text_width(draw, trimmed + suffix, font) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + suffix if trimmed else suffix


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    max_width: int | None = None,
    fill: int = 0,
) -> None:
    if max_width is not None:
        text = _fit_text(draw, text, font, max_width)
    draw.text(xy, text, font=font, fill=fill)


def _normal_grid_lines() -> list[tuple[int, int, int, int]]:
    return [
        (0, NORMAL_TOP_Y, SCREEN_W - 1, NORMAL_TOP_Y),
        (NORMAL_LEFT_W, NORMAL_TOP_Y, NORMAL_LEFT_W, NORMAL_DOCK_Y),
        (0, NORMAL_DOCK_Y, SCREEN_W - 1, NORMAL_DOCK_Y),
        (0, NORMAL_LEFT_PET_BOTTOM_Y, NORMAL_LEFT_W, NORMAL_LEFT_PET_BOTTOM_Y),
        (0, NORMAL_LEFT_SUMMARY_BOTTOM_Y, NORMAL_LEFT_W, NORMAL_LEFT_SUMMARY_BOTTOM_Y),
        (NORMAL_LEFT_W, NORMAL_RIGHT_TIMELINE_BOTTOM_Y, SCREEN_W - 1, NORMAL_RIGHT_TIMELINE_BOTTOM_Y),
        (NORMAL_LEFT_W, NORMAL_RIGHT_FOCUS_BOTTOM_Y, SCREEN_W - 1, NORMAL_RIGHT_FOCUS_BOTTOM_Y),
    ]


def _draw_grid_lines(draw: ImageDraw.ImageDraw, lines: list[tuple[int, int, int, int]]) -> None:
    for x0, y0, x1, y1 in lines:
        draw.line((x0, y0, x1, y1), fill=0)


def _mono(image: Image.Image) -> Image.Image:
    return image.point(lambda p: 0 if p < 180 else 255, mode="1")


def _dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, TZ)


def _format_top_bar(state: DashboardState) -> str:
    now = _dt(state.now_ts)
    weather = state.weather_text
    if state.temperature_c is not None:
        weather = f"{weather}{state.temperature_c}C"
    indoor = ""
    if state.indoor_temperature_c is not None and state.indoor_humidity_percent is not None:
        temp = round(state.indoor_temperature_c)
        humidity = round(state.indoor_humidity_percent)
        indoor = f" 室{temp}C {humidity}%"
    battery = f"电{state.battery_percent}%" if state.battery_percent is not None else "电--"
    weekdays = "一二三四五六日"
    return f"{now:%H:%M}  周{weekdays[now.weekday()]}  {now.month}/{now.day}      {weather}{indoor}  {battery}"


def _format_time(ts: int) -> str:
    return _dt(ts).strftime("%H:%M")


def _format_delta(now_ts: int, start_ts: int) -> str:
    delta = max(0, start_ts - now_ts)
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 180:
        return f"{minutes // 60}h"
    hour = _dt(start_ts).hour
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚上"


def _day_range(now_ts: int) -> tuple[int, int]:
    now = _dt(now_ts)
    start = now.replace(hour=8, minute=0, second=0, microsecond=0)
    end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), int(end.timestamp())


def _lunch_range(ts: int) -> tuple[int, int]:
    day = _dt(ts)
    start = day.replace(hour=LUNCH_START[0], minute=LUNCH_START[1], second=0, microsecond=0)
    end = day.replace(hour=LUNCH_END[0], minute=LUNCH_END[1], second=0, microsecond=0)
    return int(start.timestamp()), int(end.timestamp())


def _same_local_day(left_ts: int, right_ts: int) -> bool:
    return _dt(left_ts).date() == _dt(right_ts).date()


def _format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    rest = minutes % 60
    if rest == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {rest} 分钟"


def format_focus_line(slot: FocusSlot) -> str:
    title = slot.title
    if title.startswith("下段空档 "):
        title = "空档 " + title.removeprefix("下段空档 ")
    elif title.startswith("下个会前 "):
        title = "会前 " + title.removeprefix("下个会前 ")
    suggestion = slot.suggestion.removeprefix("适合：")
    return f"{title}｜{suggestion}"


def _is_weekend_rest_context(state: DashboardState) -> bool:
    if _dt(state.now_ts).weekday() < 5:
        return False
    if state.agenda_is_fallback or not state.meetings:
        return True
    return all(not _same_local_day(state.now_ts, meeting.start_ts) for meeting in state.meetings)


def classify_focus_slot(now_ts: int, meetings: list[Meeting]) -> FocusSlot:
    current = [
        meeting for meeting in meetings
        if meeting.start_ts <= now_ts < meeting.end_ts
    ]
    if current:
        meeting = sorted(current, key=lambda item: item.end_ts)[0]
        minutes = max(1, (meeting.end_ts - now_ts + 59) // 60)
        return FocusSlot(f"会议中 {_format_minutes(minutes)}", "先专注开会", minutes, True)

    lunch_start, lunch_end = _lunch_range(now_ts)
    if lunch_start <= now_ts < lunch_end:
        minutes = max(1, (lunch_end - now_ts + 59) // 60)
        return FocusSlot(f"午休中 {_format_minutes(minutes)}", "好好休息", minutes)

    future = [meeting for meeting in meetings if meeting.start_ts > now_ts]
    lunch_blocks_next_slot = now_ts < lunch_start
    if future:
        next_meeting = sorted(future, key=lambda item: item.start_ts)[0]
        slot_end = next_meeting.start_ts
        if lunch_blocks_next_slot and lunch_start < slot_end:
            slot_end = lunch_start
        minutes = max(0, (slot_end - now_ts) // 60)
        if lunch_blocks_next_slot and slot_end == lunch_start:
            if minutes >= 30:
                return FocusSlot(f"午休前 {_format_minutes(minutes)}", "适合：收尾/回消息", minutes)
            return FocusSlot(f"午休前 {_format_minutes(minutes)}", "适合：准备休息", minutes)
        if minutes >= 90:
            suggestion = "适合：深度工作"
            title = f"下段空档 {_format_minutes(minutes)}"
        elif minutes >= 30:
            suggestion = "适合：推进任务"
            title = f"下段空档 {_format_minutes(minutes)}"
        elif minutes >= 10:
            suggestion = "适合：收尾/回消息"
            title = f"下个会前 {_format_minutes(minutes)}"
        else:
            suggestion = "适合：准备开会"
            title = f"下个会前 {_format_minutes(minutes)}"
        return FocusSlot(title, suggestion, minutes)

    day_start, day_end = _day_range(now_ts)
    slot_end = day_end
    if lunch_blocks_next_slot:
        slot_end = lunch_start
    minutes = max(0, (slot_end - max(now_ts, day_start)) // 60)
    if lunch_blocks_next_slot:
        if minutes >= 30:
            return FocusSlot(f"午休前 {_format_minutes(minutes)}", "适合：收尾推进", minutes)
        return FocusSlot(f"午休前 {_format_minutes(minutes)}", "适合：准备休息", minutes)
    if minutes >= 90:
        return FocusSlot(f"今天余下 {_format_minutes(minutes)}", "适合：深度工作", minutes)
    if minutes >= 30:
        return FocusSlot(f"今天余下 {_format_minutes(minutes)}", "适合：收尾推进", minutes)
    return FocusSlot("今天快收尾", "适合：整理现场", minutes)


def classify_focus_slot_for_state(state: DashboardState) -> FocusSlot:
    if _is_weekend_rest_context(state):
        return FocusSlot("今天休息", "别安排工作", 0)
    return classify_focus_slot(state.now_ts, state.meetings)


def companion_copy(state: DashboardState, alert_kind: str | None) -> tuple[str, str]:
    if alert_kind and alert_kind.startswith("meeting"):
        return "该看日程了", "我帮你盯着"
    if state.ai_status == AiStatus.needs_confirm:
        return "Codex 卡住了", "回来看一眼"
    if state.ai_status == AiStatus.interrupted:
        return "任务中断了", "需要处理"
    if state.ai_status == AiStatus.done:
        return "我搞定啦", "等你验收"
    if state.feishu_messages.total_count > 0:
        return "飞书有点吵", "我先标出来"
    if _is_weekend_rest_context(state):
        return "今天休息", "别安排工作"
    slot = classify_focus_slot_for_state(state)
    if slot.in_meeting:
        return "先专注开会", "别分心"
    if slot.minutes >= 90:
        return "这段很干净", "适合开工"
    if slot.minutes < 10:
        return "别开新坑", "准备开会"
    if len(state.meetings) >= 4:
        return "会议迷宫", "我帮你盯着"
    return "节奏还不错", "稳稳推进"


def _alert_content_lines(alert: Alert) -> tuple[str, str, str]:
    if alert.kind.startswith("ai_"):
        parts = [part.strip() for part in alert.message.split("｜") if part.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], "｜".join(parts[2:])
        if len(parts) == 2:
            return parts[0], parts[1], alert.detail
    return "通知内容", alert.message or alert.title, alert.detail


def _alert_meeting_location_line(alert: Alert) -> str:
    if not alert.meeting or not alert.meeting.location:
        return ""
    return f"室 {alert.meeting.location}"


def _draw_message_summary(draw: ImageDraw.ImageDraw, state: DashboardState, x: int, y: int, max_width: int) -> None:
    summary = state.feishu_messages
    if not summary.is_available:
        _draw_text(draw, (x, y), "飞书 未连接", FONT_13, max_width=max_width)
        return
    if summary.total_count <= 0:
        _draw_text(draw, (x, y), f"飞书 {summary.window_minutes}m无新", FONT_13, max_width=max_width)
        return
    text = f"飞书 {summary.chat_count}群 {summary.total_count}条"
    if summary.sources:
        text = f"{text} {'+'.join(summary.sources[:2])}"
    _draw_text(draw, (x, y), text, FONT_13, max_width=max_width)


def _timeline_x(ts: int, start_ts: int, end_ts: int, x0: int, x1: int) -> int:
    if end_ts <= start_ts:
        return x0
    ratio = (ts - start_ts) / (end_ts - start_ts)
    ratio = max(0.0, min(1.0, ratio))
    return round(x0 + ratio * (x1 - x0))


def _timeline_bounds(x: int, width: int) -> tuple[int, int]:
    return x + 12, x + width - 6


def _timeline_tick_positions(state: DashboardState, x: int, width: int) -> list[int]:
    timeline_ts = state.agenda_date_ts or state.now_ts
    day_start, day_end = _day_range(timeline_ts)
    x0, x1 = _timeline_bounds(x, width)
    return [
        _timeline_x(
            int(_dt(timeline_ts).replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()),
            day_start,
            day_end,
            x0,
            x1,
        )
        for hour in (8, 12, 18, 22)
    ]


def _draw_rhythm_timeline(draw: ImageDraw.ImageDraw, state: DashboardState, x: int, y: int, width: int) -> None:
    timeline_ts = state.agenda_date_ts or state.now_ts
    day_start, day_end = _day_range(timeline_ts)
    lunch_start, lunch_end = _lunch_range(timeline_ts)
    line_y = y + 35
    x0, x1 = _timeline_bounds(x, width)
    timeline_title = "今日时间尺" if state.agenda_day_label == "今天" else f"{state.agenda_day_label}时间尺"
    _draw_text(draw, (x, y), timeline_title, FONT_13, max_width=82)
    _draw_text(draw, (x + 88, y + 1), "■会 □午 |现", FONT_11, max_width=width - 88)
    for hour, tick_x in zip((8, 12, 18, 22), _timeline_tick_positions(state, x, width)):
        _draw_text(draw, (max(x0, min(x1 - 16, tick_x - 8)), y + 18), f"{hour:02d}", FONT_11, max_width=18)
        draw.line((tick_x, line_y - 3, tick_x, line_y + 3), fill=0)
    draw.line((x0, line_y, x1, line_y), fill=0, width=1)

    lunch_x0 = _timeline_x(lunch_start, day_start, day_end, x0, x1)
    lunch_x1 = _timeline_x(lunch_end, day_start, day_end, x0, x1)
    draw.rectangle((lunch_x0, line_y - 5, lunch_x1, line_y + 5), outline=0, fill=255)
    for stripe_x in range(lunch_x0 + 3, lunch_x1, 7):
        draw.line((stripe_x, line_y + 5, min(stripe_x + 7, lunch_x1), line_y - 5), fill=0)

    for meeting in state.meetings:
        seg_start = max(meeting.start_ts, day_start)
        seg_end = min(meeting.end_ts, day_end)
        if seg_end <= day_start or seg_start >= day_end:
            continue
        sx = _timeline_x(seg_start, day_start, day_end, x0, x1)
        ex = _timeline_x(seg_end, day_start, day_end, x0, x1)
        if ex <= sx:
            ex = sx + 2
        draw.rectangle((sx, line_y - 5, ex, line_y + 5), fill=0)

    if _same_local_day(state.now_ts, timeline_ts):
        now_x = _timeline_x(state.now_ts, day_start, day_end, x0, x1)
        draw.line((now_x, line_y - 12, now_x, line_y + 14), fill=0, width=2)
        _draw_text(draw, (max(x0, min(x1 - 22, now_x - 10)), line_y + 13), "现在", FONT_11, max_width=30)


def _draw_ai_dock(draw: ImageDraw.ImageDraw, state: DashboardState, y0: int, expanded: bool = False) -> None:
    y1 = SCREEN_H - 1
    draw.rectangle((0, y0, SCREEN_W - 1, y1), outline=0, fill=255)
    if state.ai_status in {AiStatus.done, AiStatus.needs_confirm}:
        draw.rectangle((0, y0, SCREEN_W - 1, y1), outline=0, fill=0 if expanded else 255)
        fill = 255 if expanded else 0
    else:
        fill = 0

    text = _dock_status_text(state)
    if state.ai_status == AiStatus.idle:
        music_text = _fit_text(draw, text, FONT_14, 250)
        x = max(10, SCREEN_W - 10 - _text_width(draw, music_text, FONT_14))
        _draw_text(draw, (x, y0 + 9), music_text, FONT_14, max_width=250, fill=fill)
        return

    _draw_text(draw, (10, y0 + 9), text, FONT_14, max_width=380, fill=fill)

    if state.ai_status == AiStatus.coding:
        bar_x = 306
        for idx in range(6):
            if (idx + state.frame_index) % 3 == 0:
                draw.rectangle((bar_x + idx * 10, y0 + 30, bar_x + idx * 10 + 5, y0 + 34), fill=0)


def _dock_status_text(state: DashboardState) -> str:
    if state.ai_status == AiStatus.idle:
        return state.music.display
    icon = {
        AiStatus.idle: "o",
        AiStatus.coding: ">",
        AiStatus.done: "*",
        AiStatus.needs_confirm: "!",
        AiStatus.interrupted: "x",
    }[state.ai_status]
    label = {
        AiStatus.idle: "空闲",
        AiStatus.coding: "编程中",
        AiStatus.done: "完成",
        AiStatus.needs_confirm: "需确认",
        AiStatus.interrupted: "中断",
    }[state.ai_status]
    return f"AI Coding  {icon} {label}  {state.ai_title}"


def _draw_normal_dashboard(draw: ImageDraw.ImageDraw, state: DashboardState, alert: Alert | None) -> None:
    draw.rectangle((0, 0, SCREEN_W - 1, SCREEN_H - 1), outline=0, fill=255)
    _draw_text(draw, (8, 7), _format_top_bar(state), FONT_13, max_width=384)
    _draw_grid_lines(draw, _normal_grid_lines())

    left_w = NORMAL_LEFT_W
    dock_y = NORMAL_DOCK_Y

    pet_state = choose_pet_state(state, alert.kind if alert else None)
    draw_pixel_pet(draw, (10, 42, left_w - 10, 130), pet_state, state.frame_index)

    meetings_count = len(state.meetings)
    if meetings_count == 0:
        headline = f"{state.agenda_day_label}没会"
    elif meetings_count >= 4:
        headline = f"{state.agenda_day_label}有{meetings_count}场会"
    else:
        headline = f"{state.agenda_day_label}有{meetings_count}场会"
    _draw_text(draw, (16, 148), headline, FONT_14, max_width=96)
    copy_line1, copy_line2 = companion_copy(state, alert.kind if alert else None)
    _draw_text(draw, (16, 171), copy_line1, FONT_13, max_width=96)
    _draw_text(draw, (16, 190), copy_line2, FONT_13, max_width=96)
    _draw_message_summary(draw, state, 16, 217, 96)
    _draw_text(draw, (16, 242), f"待办 {state.todo_count} 个", FONT_12, max_width=96)

    right_x = left_w + 12
    right_w = SCREEN_W - right_x - 10
    _draw_rhythm_timeline(draw, state, right_x, 37, right_w)

    slot = classify_focus_slot_for_state(state)
    _draw_text(draw, (right_x, 101), format_focus_line(slot), FONT_16, max_width=right_w)

    _draw_text(draw, (right_x, 130), state.agenda_title, FONT_13, max_width=right_w)
    y = 153
    visible = state.meetings[:3]
    for meeting in visible:
        time_text = _format_time(meeting.start_ts)
        delta_text = _format_delta(state.now_ts, meeting.start_ts)
        _draw_text(draw, (right_x, y), time_text, FONT_13, max_width=42)
        _draw_text(draw, (right_x + 48, y), meeting.title, FONT_13, max_width=right_w - 100)
        _draw_text(draw, (SCREEN_W - 50, y), delta_text, FONT_12, max_width=42)
        y += 26
    if len(state.meetings) > 3:
        _draw_text(draw, (right_x + 48, y), f"还有 {len(state.meetings) - 3} 场", FONT_12, max_width=right_w - 80)
    if not state.meetings:
        _draw_text(draw, (right_x + 48, y), f"{state.agenda_day_label}没有会议", FONT_13, max_width=right_w - 60)

    _draw_ai_dock(draw, state, dock_y)


def _draw_alert(draw: ImageDraw.ImageDraw, state: DashboardState, alert: Alert) -> None:
    dock_y = 258
    draw.rectangle((0, 0, SCREEN_W - 1, SCREEN_H - 1), outline=0, fill=255)
    if state.frame_index % 2 == 0 and alert.kind in {
        "meeting_now",
        "meeting_5",
        "ai_needs_confirm",
        "ai_interrupted",
    }:
        draw.rectangle((0, 0, SCREEN_W - 1, 42), outline=0, fill=0)
        _draw_text(draw, (102, 11), alert.title, FONT_20, max_width=230, fill=255)
    else:
        _draw_text(draw, (102, 11), alert.title, FONT_20, max_width=230)
    draw.line((0, 44, SCREEN_W, 44), fill=0)
    draw.line((138, 44, 138, dock_y), fill=0)
    draw.line((0, dock_y, SCREEN_W, dock_y), fill=0)

    pet_state = choose_pet_state(state, alert.kind)
    draw_pixel_pet(draw, (20, 72, 122, 172), pet_state, state.frame_index)
    _draw_text(draw, (20, 190), "我来提醒你", FONT_14, max_width=105)

    flash_panel = state.frame_index % 2 == 0
    panel_fill = 0 if flash_panel else 255
    text_fill = 255 if flash_panel else 0
    draw.rectangle(ALERT_PANEL_BOX, outline=0, fill=panel_fill)
    heading, message, detail = _alert_content_lines(alert)
    _draw_text(draw, (154, 72), heading, FONT_13, max_width=220, fill=text_fill)
    _draw_text(draw, (154, 100), message, FONT_20, max_width=220, fill=text_fill)
    if detail:
        _draw_text(draw, (154, 137), detail, FONT_16, max_width=220, fill=text_fill)
    if alert.meeting:
        time_range = f"{_format_time(alert.meeting.start_ts)} - {_format_time(alert.meeting.end_ts)}"
        _draw_text(draw, (154, 158), time_range, FONT_16, max_width=220, fill=text_fill)
        location_line = _alert_meeting_location_line(alert)
        if location_line:
            _draw_text(draw, (154, 180), location_line, FONT_13, max_width=220, fill=text_fill)
    _draw_text(draw, (154, 215), "按 KEY/BOOT 确认", FONT_12, max_width=220)
    _draw_text(draw, (154, 232), "RESET 只会重启", FONT_11, max_width=220)

    _draw_ai_dock(draw, state, dock_y)


def render_image(state: DashboardState, acknowledged: set[str] | None = None) -> Image.Image:
    base = Image.new("L", (SCREEN_W, SCREEN_H), 255)
    draw = ImageDraw.Draw(base)
    alert = select_alert(state, acknowledged or set())
    if alert:
        _draw_alert(draw, state, alert)
    else:
        _draw_normal_dashboard(draw, state, alert)
    return _mono(base)


def render_png_bytes(state: DashboardState, acknowledged: set[str] | None = None) -> bytes:
    image = render_image(state, acknowledged)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_u8g2_xbmp_bytes(state: DashboardState, acknowledged: set[str] | None = None) -> bytes:
    image = render_image(state, acknowledged)
    pixels = image.load()
    packed = bytearray()
    for y in range(SCREEN_H):
        for byte_x in range(SCREEN_W // 8):
            value = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if pixels[x, y] == 0:
                    value |= 1 << bit
            packed.append(value)
    if len(packed) != BITMAP_BYTES:
        raise ValueError(f"位图长度错误：{len(packed)}，期望 {BITMAP_BYTES}")
    return bytes(packed)


def render_test_pattern_bytes(pattern: str = "checker") -> bytes:
    image = Image.new("1", (SCREEN_W, SCREEN_H), 255)
    draw = ImageDraw.Draw(image)
    if pattern == "diagonal":
        for offset in range(-SCREEN_H, SCREEN_W, 10):
            draw.line((offset, 0, offset + SCREEN_H, SCREEN_H), fill=0)
    else:
        cell = 10
        for y in range(0, SCREEN_H, cell):
            for x in range(0, SCREEN_W, cell):
                if (x // cell + y // cell) % 2 == 0:
                    draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=0)
    dummy = DashboardState(now_ts=0)
    return _pack_image(image, dummy)


def _pack_image(image: Image.Image, _state: DashboardState) -> bytes:
    pixels = image.load()
    packed = bytearray()
    for y in range(SCREEN_H):
        for byte_x in range(SCREEN_W // 8):
            value = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if pixels[x, y] == 0:
                    value |= 1 << bit
            packed.append(value)
    return bytes(packed)


def sample_state(now_ts: int | None = None) -> DashboardState:
    now = int(datetime.now(TZ).timestamp()) if now_ts is None else now_ts
    return DashboardState(
        now_ts=now,
        weather_text="多云",
        temperature_c=26,
        battery_percent=82,
        todo_count=5,
        meetings=[
            Meeting("产品评审", now + 48 * 60, now + 78 * 60),
            Meeting("周会", now + 2 * 3600, now + 2 * 3600 + 1800),
            Meeting("Codex Demo", now + 4 * 3600, now + 4 * 3600 + 3600),
            Meeting("面试复盘", now + 6 * 3600, now + 6 * 3600 + 1800),
        ],
        ai_status=AiStatus.coding,
        ai_title="正在生成固件草稿",
    )


if __name__ == "__main__":
    Path("preview.png").write_bytes(render_png_bytes(sample_state()))
    Path("frame.bin").write_bytes(render_u8g2_xbmp_bytes(sample_state()))
    print("已生成 preview.png 和 frame.bin")
