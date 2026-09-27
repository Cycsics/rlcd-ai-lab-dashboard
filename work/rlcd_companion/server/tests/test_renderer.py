from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from models import BITMAP_BYTES
from models import AiStatus, Meeting, MusicStatus
from renderer import (
    _alert_content_lines,
    _alert_meeting_location_line,
    _dock_status_text,
    _format_top_bar,
    _normal_grid_lines,
    _timeline_bounds,
    _timeline_tick_positions,
    classify_focus_slot_for_state,
    classify_focus_slot,
    companion_copy,
    format_focus_line,
    render_image,
    render_png_bytes,
    render_u8g2_xbmp_bytes,
    sample_state,
)
from reminders import Alert
from renderer import _draw_alert
from PIL import Image, ImageDraw


def test_render_image_size_and_mode():
    image = render_image(sample_state(now_ts=1_800_000_000))
    assert image.size == (400, 300)
    assert image.mode == "1"


def test_render_png_has_content():
    data = render_png_bytes(sample_state(now_ts=1_800_000_000))
    assert data.startswith(b"\x89PNG")
    assert len(data) > 1000


def test_top_bar_places_music_after_battery():
    state = sample_state(now_ts=1_800_000_000)
    state.music = MusicStatus(
        is_playing=True,
        player="Apple Music",
        artist="周杰伦",
        title="晴天",
    )
    top_bar = _format_top_bar(state)
    assert "电82%" in top_bar
    assert "音乐" not in top_bar
    assert "晴天" not in top_bar


def test_top_bar_places_indoor_temperature_and_humidity_after_weather():
    state = sample_state(now_ts=1_800_000_000)
    state.indoor_temperature_c = 24.4
    state.indoor_humidity_percent = 57.2
    top_bar = _format_top_bar(state)
    assert "多云26C 室24C 57%" in top_bar
    assert top_bar.index("多云26C") < top_bar.index("室24C 57%") < top_bar.index("电82%")


def test_idle_dock_uses_music_instead_of_ai_status():
    state = sample_state(now_ts=1_800_000_000)
    state.ai_status = AiStatus.idle
    state.ai_title = "没有任务"
    state.music = MusicStatus(
        is_playing=True,
        player="Apple Music",
        artist="周杰伦",
        title="晴天",
    )
    assert _dock_status_text(state) == "周杰伦 - 晴天"


def test_busy_ai_dock_hides_music():
    state = sample_state(now_ts=1_800_000_000)
    state.ai_status = AiStatus.coding
    state.ai_title = "正在跑测试"
    state.music = MusicStatus(
        is_playing=True,
        player="Apple Music",
        artist="周杰伦",
        title="晴天",
    )
    dock_text = _dock_status_text(state)
    assert dock_text == "AI Coding  > 编程中  正在跑测试"
    assert "晴天" not in dock_text


def test_weekend_fallback_focus_line_encourages_rest():
    sunday = int(datetime(2026, 6, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    state = sample_state(now_ts=sunday)
    state.agenda_is_fallback = True
    state.meetings = [Meeting("周一早会", sunday + 23 * 3600, sunday + 24 * 3600)]
    slot = classify_focus_slot_for_state(state)
    assert format_focus_line(slot) == "今天休息｜别安排工作"
    assert companion_copy(state, None) == ("今天休息", "别安排工作")


def test_timeline_bounds_leave_room_for_left_label():
    left, right = _timeline_bounds(134, 256)
    assert left >= 146
    assert right <= 384


def test_fallback_timeline_ticks_use_agenda_date():
    sunday = int(datetime(2026, 6, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    monday = int(datetime(2026, 6, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    state = sample_state(now_ts=sunday)
    state.agenda_date_ts = monday
    state.agenda_is_fallback = True
    positions = _timeline_tick_positions(state, 134, 256)
    assert positions == sorted(positions)
    assert len(set(positions)) == 4
    assert positions[-1] - positions[0] > 200


def test_sample_state_can_label_monday_agenda():
    state = sample_state(now_ts=1_781_360_000)
    state.agenda_day_label = "周一"
    state.agenda_title = "周一日程"
    assert state.agenda_day_label == "周一"
    assert state.agenda_title == "周一日程"


def test_normal_dashboard_has_newspaper_grid_lines():
    assert _normal_grid_lines() == [
        (0, 28, 399, 28),
        (122, 28, 122, 258),
        (0, 258, 399, 258),
        (0, 138, 122, 138),
        (0, 207, 122, 207),
        (122, 92, 399, 92),
        (122, 122, 399, 122),
    ]


def test_normal_dashboard_draws_section_dividers():
    state = sample_state(now_ts=1_800_000_000)
    state.ai_status = AiStatus.idle
    image = render_image(state)
    pixels = image.load()

    for x in range(4, 118):
        assert pixels[x, 138] == 0
        assert pixels[x, 207] == 0
    for x in range(126, 396):
        assert pixels[x, 92] == 0
        assert pixels[x, 122] == 0


def test_bitmap_byte_length():
    data = render_u8g2_xbmp_bytes(sample_state(now_ts=1_800_000_000))
    assert len(data) == BITMAP_BYTES


def test_bitmap_is_not_blank():
    data = render_u8g2_xbmp_bytes(sample_state(now_ts=1_800_000_000))
    assert any(byte != 0 for byte in data)


def test_alert_copy_names_key_button():
    image = Image.new("L", (400, 300), 255)
    draw = ImageDraw.Draw(image)
    state = sample_state(now_ts=1_800_000_000)
    alert = Alert(
        kind="ai_done",
        key="ai:done:test",
        title="完成",
        message="任务完成",
    )
    _draw_alert(draw, state, alert)
    # Smoke test: rendering the longer confirmation copy should fit without errors.
    assert image.size == (400, 300)


def test_alert_content_lines_prioritize_specific_notification():
    alert = Alert(
        kind="ai_done",
        key="ai:done:test",
        title="我搞定啦",
        message="Codex 已完成固件烧录验证",
        detail="请回到电脑验收",
    )
    heading, message, detail = _alert_content_lines(alert)
    assert heading == "通知内容"
    assert message == "Codex 已完成固件烧录验证"
    assert detail == "请回到电脑验收"


def test_meeting_alert_location_line_uses_specific_room_name():
    alert = Alert(
        kind="meeting_5",
        key="meeting:1:meeting_5",
        title="5 分钟后开会",
        message="需求评审",
        detail="准备一下",
        meeting=Meeting("需求评审", 1_800_000_300, 1_800_002_100, "T3-18F-星云"),
    )

    assert _alert_meeting_location_line(alert) == "室 T3-18F-星云"


def test_ai_alert_content_splits_project_conversation_and_task():
    alert = Alert(
        kind="ai_done",
        key="ai:done:test",
        title="我搞定啦",
        message="rlcd｜公网联调｜烧录完成",
        detail="请回到电脑验收",
    )
    heading, message, detail = _alert_content_lines(alert)
    assert heading == "rlcd"
    assert message == "公网联调"
    assert detail == "烧录完成"


def test_ai_alert_content_without_project_uses_conversation_and_task():
    alert = Alert(
        kind="ai_done",
        key="ai:done:test",
        title="我搞定啦",
        message="桌面小伙伴｜飞书日程接入",
        detail="请回到电脑验收",
    )
    heading, message, detail = _alert_content_lines(alert)
    assert heading == "桌面小伙伴"
    assert message == "飞书日程接入"
    assert detail == "请回到电脑验收"


def test_strong_alert_flashes_main_content_panel():
    even_state = sample_state(now_ts=1_800_000_000)
    even_state.ai_status = AiStatus.done
    even_state.ai_title = "Codex 已完成固件烧录验证"
    even_state.frame_index = 2

    odd_state = sample_state(now_ts=1_800_000_000)
    odd_state.ai_status = AiStatus.done
    odd_state.ai_title = "Codex 已完成固件烧录验证"
    odd_state.frame_index = 3

    even = render_image(even_state)
    odd = render_image(odd_state)
    box = (144, 62, 390, 188)
    even_pixels = list(even.crop(box).getdata())
    odd_pixels = list(odd.crop(box).getdata())
    changed = sum(1 for left, right in zip(even_pixels, odd_pixels) if left != right)
    assert changed > 20_000


def test_focus_slot_deep_work_when_next_meeting_is_far():
    now = 1_800_000_000
    meetings = [Meeting("下午会", now + 2 * 3600, now + 3 * 3600)]
    slot = classify_focus_slot(now, meetings)
    assert slot.title == "下段空档 2 小时"
    assert slot.suggestion == "适合：深度工作"


def test_focus_slot_stops_at_lunch_break():
    now = int(datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    meetings = [
        Meeting(
            "下午评审",
            int(datetime(2026, 6, 15, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
            int(datetime(2026, 6, 15, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
        )
    ]

    slot = classify_focus_slot(now, meetings)

    assert format_focus_line(slot) == "午休前 30 分钟｜收尾/回消息"


def test_focus_slot_detects_lunch_break():
    now = int(datetime(2026, 6, 15, 12, 45, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    slot = classify_focus_slot(now, [])

    assert format_focus_line(slot) == "午休中 1 小时 15 分钟｜好好休息"


def test_focus_slot_formats_compact_line():
    now = 1_800_000_000
    meetings = [Meeting("评审", now + 48 * 60, now + 78 * 60)]
    slot = classify_focus_slot(now, meetings)
    assert format_focus_line(slot) == "空档 48 分钟｜推进任务"


def test_focus_slot_prepare_when_next_meeting_is_close():
    now = 1_800_000_000
    meetings = [Meeting("站会", now + 8 * 60, now + 38 * 60)]
    slot = classify_focus_slot(now, meetings)
    assert slot.title == "下个会前 8 分钟"
    assert slot.suggestion == "适合：准备开会"


def test_focus_slot_detects_current_meeting():
    now = 1_800_000_000
    meetings = [Meeting("评审会", now - 10 * 60, now + 20 * 60)]
    slot = classify_focus_slot(now, meetings)
    assert slot.title == "会议中 20 分钟"
    assert slot.suggestion == "先专注开会"


def test_companion_copy_mentions_feishu_noise():
    state = sample_state(now_ts=1_800_000_000)
    state.feishu_messages.chat_count = 3
    state.feishu_messages.total_count = 7
    assert companion_copy(state, None)[0] == "飞书有点吵"
