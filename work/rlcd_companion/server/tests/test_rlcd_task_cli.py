from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "rlcd_task.py"


def load_task_module():
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location("rlcd_task", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["rlcd_task"] = module
    spec.loader.exec_module(module)
    return module


def test_strip_separator_removes_leading_double_dash():
    task = load_task_module()
    assert task.strip_separator(["--", "pytest", "-q"]) == ["pytest", "-q"]
    assert task.strip_separator(["pytest", "-q"]) == ["pytest", "-q"]


def test_command_title_uses_explicit_title():
    task = load_task_module()
    assert task.command_title("跑测试", ["pytest"]) == "跑测试"


def test_command_title_falls_back_to_command_name():
    task = load_task_module()
    assert task.command_title("", ["/usr/bin/python3", "-V"]) == "运行 python3"


def test_parse_run_command():
    task = load_task_module()
    args = task.parse_args(["run", "跑测试", "--", "pytest", "-q"])
    assert args.action == "run"
    assert args.title == "跑测试"
    assert task.strip_separator(args.command) == ["pytest", "-q"]


def test_global_options_work_after_subcommand():
    task = load_task_module()
    args = task.parse_args(["state", "--json"])
    assert args.action == "state"
    assert args.json is True


def test_global_options_do_not_rewrite_wrapped_command_flags():
    task = load_task_module()
    args = task.parse_args(["run", "跑测试", "--", "python", "-c", "print('--json')"])
    assert args.command == ["python", "-c", "print('--json')"]
    assert args.json is False


def test_lifecycle_action_mapping():
    task = load_task_module()
    assert task.ACTION_TO_AI["start"] == "coding"
    assert task.ACTION_TO_AI["confirm"] == "needs_confirm"
    assert task.ACTION_TO_AI["fail"] == "needs_confirm"


def test_codex_status_payload_includes_conversation_title():
    task = load_task_module()
    args = task.parse_args([
        "--session-id",
        "s1",
        "--project",
        "rlcd",
        "--conversation-title",
        "公网联调",
        "done",
        "烧录完成",
    ])
    payload = task.codex_status_payload(args, "done", "烧录完成")
    assert payload["project"] == "rlcd"
    assert payload["conversation_title"] == "公网联调"
    assert payload["title"] == "烧录完成"


def test_codex_status_payload_uses_conversation_title_env(monkeypatch):
    task = load_task_module()
    monkeypatch.setenv("RLCD_CONVERSATION_TITLE", "桌面小伙伴")
    args = task.parse_args(["done", "飞书日程接入"])
    payload = task.codex_status_payload(args, "done", "飞书日程接入")
    assert payload["conversation_title"] == "桌面小伙伴"
