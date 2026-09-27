from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import app, memory, sound_cue_for_alert
from models import AiStatus, Alert, BITMAP_BYTES, FeishuMessageSummary


def setup_function():
    memory.ai_status = AiStatus.idle
    memory.ai_title = "没有任务"
    memory.ai_updated_ts = 0
    memory.codex_sessions.clear()
    memory.codex_update_counter = 0
    memory.feishu_messages = FeishuMessageSummary()
    memory.feishu_messages_updated_ts = 0
    memory.acknowledged.clear()
    memory.last_ack = None


def test_frame_bin_returns_exact_length():
    client = TestClient(app)
    response = client.get("/frame.bin?battery=82&temp=24.4&humidity=57.2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-rlcd-pet-state"] == "busy_day"
    assert response.headers["x-rlcd-pet-mode"] == "normal"
    assert response.headers["x-rlcd-alert-level"] == "normal"
    assert response.headers["x-rlcd-sound-cue"] == "none"
    assert len(response.content) == BITMAP_BYTES


def test_state_includes_board_environment_from_query():
    client = TestClient(app)
    response = client.get("/frame.bin?battery=82&temp=24.4&humidity=57.2")
    assert response.status_code == 200

    state = client.get("/state").json()
    assert state["environment"] == {
        "indoor_temperature_c": 24.4,
        "indoor_humidity_percent": 57.2,
    }


def test_preview_png_returns_png():
    client = TestClient(app)
    response = client.get("/preview.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_ai_update_changes_state():
    client = TestClient(app)
    response = client.post("/ai", json={"status": "done", "title": "文档草稿已生成"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"

    state = client.get("/state").json()
    assert state["ai_status"] == "done"
    assert state["alert"] == "ai_done"

    frame = client.get("/frame.bin?battery=82")
    assert frame.headers["x-rlcd-pet-mode"] == "alert"
    assert frame.headers["x-rlcd-alert-level"] == "strong"
    assert frame.headers["x-rlcd-sound-cue"] == "ai_done"
    assert frame.headers["x-rlcd-alert-key"].startswith("ai:done:")


def test_sound_cue_for_meeting_and_ai_done_alerts():
    assert sound_cue_for_alert(Alert(kind="meeting_15", key="m15", title="", message="")) == "meeting"
    assert sound_cue_for_alert(Alert(kind="meeting_5", key="m5", title="", message="")) == "meeting"
    assert sound_cue_for_alert(Alert(kind="meeting_now", key="now", title="", message="")) == "meeting_now"
    assert sound_cue_for_alert(Alert(kind="ai_done", key="done", title="", message="")) == "ai_done"
    assert sound_cue_for_alert(Alert(kind="ai_needs_confirm", key="confirm", title="", message="")) == "none"


def test_ack_dismisses_ai_done():
    client = TestClient(app)
    client.post("/ai", json={"status": "done", "title": "文档草稿已生成"})
    response = client.post("/ack")
    assert response.status_code == 200
    assert response.json()["ack"].startswith("ai:done:")
    assert client.get("/state").json()["ai_status"] == "idle"


def test_codex_status_keeps_parallel_sessions():
    client = TestClient(app)
    now_ts = int(time.time())
    response = client.post(
        "/codex/status",
        json={
            "session_id": "s1",
            "status": "coding",
            "title": "跑测试",
            "project": "demo",
            "conversation_title": "后端联调",
            "updated_ts": now_ts,
        },
    )
    assert response.status_code == 200

    response = client.post(
        "/codex/status",
        json={
            "session_id": "s2",
            "status": "done",
            "title": "修复完成",
            "project": "api",
            "conversation_title": "RLCD 公网同步",
            "updated_ts": now_ts + 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["active_sessions"] == 2

    state = client.get("/state").json()
    assert state["ai_status"] == "done"
    assert state["ai_title"] == "api｜RLCD 公网同步｜修复完成"
    assert state["alert"] == "ai_done"


def test_latest_codex_update_preserves_other_waiting_session():
    client = TestClient(app)
    now_ts = int(time.time())
    client.post(
        "/codex/status",
        json={
            "session_id": "old-confirm",
            "status": "needs_confirm",
            "title": "旧任务需要确认",
            "project": "ticketing-system",
            "conversation_title": "旧会话",
            "updated_ts": now_ts,
        },
    )
    response = client.post(
        "/codex/status",
        json={
            "session_id": "new-done",
            "status": "done",
            "title": "新任务完成",
            "project": "rlcd",
            "conversation_title": "提醒逻辑",
            "updated_ts": now_ts + 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["active_sessions"] == 2
    state = client.get("/state").json()
    assert state["ai_status"] == "needs_confirm"
    assert state["ai_title"] == "ticketing-system｜旧会话｜旧任务需要确认"
    assert state["alert"] == "ai_needs_confirm"


def test_ack_dismisses_current_needs_confirm_codex_session():
    client = TestClient(app)
    client.post(
        "/codex/status",
        json={
            "session_id": "confirm-session",
            "status": "needs_confirm",
            "title": "需要你确认",
            "project": "rlcd",
        },
    )
    assert client.get("/state").json()["alert"] == "ai_needs_confirm"

    response = client.post("/ack")

    assert response.status_code == 200
    assert response.json()["ack"].startswith("ai:needs_confirm:")
    state = client.get("/state").json()
    assert state["ai_status"] == "idle"
    assert state["alert"] is None
    assert state["active_codex_sessions"] == 0


def test_codex_session_without_project_uses_conversation_and_task_only():
    client = TestClient(app)
    response = client.post(
        "/codex/status",
        json={
            "session_id": "s1",
            "status": "done",
            "title": "飞书日程已接入",
            "conversation_title": "桌面小伙伴",
        },
    )
    assert response.status_code == 200

    state = client.get("/state").json()
    assert state["ai_status"] == "done"
    assert state["ai_title"] == "桌面小伙伴｜飞书日程已接入"
    assert state["alert"] == "ai_done"


def test_codex_sessions_with_same_timestamp_use_latest_update():
    client = TestClient(app)
    now_ts = int(time.time())
    client.post(
        "/codex/status",
        json={
            "session_id": "s1",
            "status": "done",
            "title": "旧任务完成",
            "conversation_title": "通知排版",
            "updated_ts": now_ts,
        },
    )
    client.post(
        "/codex/status",
        json={
            "session_id": "s2",
            "status": "done",
            "title": "新任务完成",
            "conversation_title": "屏幕联调",
            "updated_ts": now_ts,
        },
    )

    state = client.get("/state").json()
    assert state["ai_title"] == "屏幕联调｜新任务完成"


def test_codex_hook_done_is_not_overridden_by_legacy_notify():
    client = TestClient(app)
    now_ts = int(time.time())
    client.post(
        "/codex/status",
        json={
            "session_id": "019ec948-351f-7022-8cc8-29bc9441a35e",
            "status": "done",
            "title": "经验索引已更新",
            "project": "ticketing-system",
            "conversation_title": "完善经验沉淀闭环",
            "source": "codex-hook:Stop",
            "cwd": "/example/projects/ticketing-system",
            "updated_ts": now_ts,
        },
    )
    client.post(
        "/codex/status",
        json={
            "session_id": "codex-notify:f93d8154b561",
            "status": "done",
            "title": "Codex 回合完成",
            "project": "Codex",
            "source": "codex-notify",
            "cwd": "/",
            "updated_ts": now_ts + 5,
        },
    )

    state = client.get("/state").json()
    assert state["ai_title"] == "ticketing-system｜完善经验沉淀闭环｜经验索引已更新"


def test_internal_codex_title_generation_session_is_ignored():
    client = TestClient(app)
    client.post(
        "/codex/status",
        json={
            "session_id": "internal-title",
            "status": "coding",
            "title": "正在处理：# Overview Generate 0 to 3 hyperp…",
            "project": "ticketing-system",
            "source": "codex-hook:UserPromptSubmit",
        },
    )

    state = client.get("/state").json()
    assert state["ai_status"] == "idle"
    assert state["active_codex_sessions"] == 0


def test_stale_coding_session_expires_after_configured_window():
    client = TestClient(app)
    stale_ts = int(time.time()) - 9 * 60
    client.post(
        "/codex/status",
        json={
            "session_id": "stale-coding",
            "status": "coding",
            "title": "正在处理：跑测试",
            "project": "rlcd",
            "source": "codex-hook:UserPromptSubmit",
            "updated_ts": stale_ts,
        },
    )

    state = client.get("/state").json()
    assert state["ai_status"] == "idle"
    assert state["active_codex_sessions"] == 0


def test_codex_idle_removes_session():
    client = TestClient(app)
    client.post(
        "/codex/status",
        json={"session_id": "s1", "status": "coding", "title": "跑测试"},
    )
    assert client.get("/state").json()["active_codex_sessions"] == 1

    response = client.post(
        "/codex/status",
        json={"session_id": "s1", "status": "idle", "title": ""},
    )
    assert response.status_code == 200
    state = client.get("/state").json()
    assert state["ai_status"] == "idle"
    assert state["active_codex_sessions"] == 0


def test_feishu_message_summary_can_be_pushed():
    client = TestClient(app)
    response = client.post(
        "/feishu/messages",
        json={"chat_count": 3, "total_count": 7, "sources": ["产品群", "项目群"]},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["chat_count"] == 3

    state = client.get("/state").json()
    assert state["feishu_messages"]["total_count"] == 7
    assert state["feishu_messages"]["sources"] == ["产品群", "项目群"]
    assert state["feishu_messages"]["is_available"] is True


def test_state_includes_music_status():
    client = TestClient(app)
    state = client.get("/state").json()
    assert state["music"]["display"] in {"未播放", state["music"]["display"]}
    assert "is_playing" in state["music"]


def test_state_includes_agenda_metadata():
    client = TestClient(app)
    state = client.get("/state").json()
    assert state["agenda"]["title"] == "今日日程"
    assert state["agenda"]["day_label"] == "今天"
    assert isinstance(state["agenda"]["meetings"], list)
