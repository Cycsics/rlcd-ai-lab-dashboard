from __future__ import annotations

from PIL import ImageDraw

from models import AiStatus, DashboardState


def choose_pet_state(state: DashboardState, alert_kind: str | None = None) -> str:
    if state.battery_percent is not None and state.battery_percent <= 15:
        return "low_battery"
    if alert_kind and alert_kind.startswith("meeting"):
        return "meeting_soon"
    if state.ai_status == AiStatus.needs_confirm:
        return "needs_confirm"
    if state.ai_status == AiStatus.done:
        return "ai_done"
    if state.ai_status == AiStatus.coding:
        return "ai_coding"
    if len(state.meetings) >= 4:
        return "busy_day"
    return "idle"


def draw_pixel_pet(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    pet_state: str,
    frame_index: int = 0,
) -> None:
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    top = y0 + 8
    blink = frame_index % 8 == 0

    # Body
    draw.rectangle((cx - 24, top + 24, cx + 24, top + 66), outline=0, fill=255)
    draw.rectangle((cx - 18, top + 30, cx + 18, top + 58), outline=0, fill=255)

    # Head
    draw.rectangle((cx - 28, top, cx + 28, top + 32), outline=0, fill=255)
    draw.rectangle((cx - 20, top - 6, cx - 8, top), outline=0, fill=255)
    draw.rectangle((cx + 8, top - 6, cx + 20, top), outline=0, fill=255)

    # Eyes
    if blink and pet_state == "idle":
        draw.line((cx - 16, top + 14, cx - 8, top + 14), fill=0, width=2)
        draw.line((cx + 8, top + 14, cx + 16, top + 14), fill=0, width=2)
    else:
        draw.rectangle((cx - 16, top + 10, cx - 10, top + 17), fill=0)
        draw.rectangle((cx + 10, top + 10, cx + 16, top + 17), fill=0)

    # Mouth and status mark
    if pet_state in {"needs_confirm", "low_battery"}:
        draw.line((cx - 8, top + 25, cx, top + 21), fill=0, width=2)
        draw.line((cx, top + 21, cx + 8, top + 25), fill=0, width=2)
    elif pet_state in {"ai_done", "meeting_soon"}:
        draw.arc((cx - 10, top + 18, cx + 10, top + 30), start=0, end=180, fill=0, width=2)
    else:
        draw.line((cx - 8, top + 24, cx + 8, top + 24), fill=0, width=2)

    # Arms
    if pet_state in {"meeting_soon", "ai_done"}:
        wave = 6 if frame_index % 2 == 0 else 0
        draw.line((cx - 24, top + 38, cx - 42, top + 28 - wave), fill=0, width=3)
        draw.line((cx + 24, top + 38, cx + 42, top + 28 + wave), fill=0, width=3)
    elif pet_state == "ai_coding":
        draw.rectangle((cx - 34, top + 54, cx + 34, top + 64), outline=0, fill=255)
        cursor_x = cx - 25 + (frame_index % 5) * 10
        draw.rectangle((cursor_x, top + 57, cursor_x + 4, top + 61), fill=0)
    else:
        draw.line((cx - 24, top + 40, cx - 38, top + 50), fill=0, width=3)
        draw.line((cx + 24, top + 40, cx + 38, top + 50), fill=0, width=3)

    # Status badge
    if pet_state == "needs_confirm":
        draw.rectangle((x1 - 24, y0 + 4, x1 - 8, y0 + 24), outline=0, fill=255)
        draw.line((x1 - 16, y0 + 8, x1 - 16, y0 + 17), fill=0, width=2)
        draw.point((x1 - 16, y0 + 21), fill=0)
    elif pet_state == "low_battery":
        draw.rectangle((x1 - 30, y0 + 8, x1 - 8, y0 + 20), outline=0, fill=255)
        draw.rectangle((x1 - 7, y0 + 11, x1 - 5, y0 + 17), fill=0)
        draw.rectangle((x1 - 27, y0 + 11, x1 - 22, y0 + 17), fill=0)

