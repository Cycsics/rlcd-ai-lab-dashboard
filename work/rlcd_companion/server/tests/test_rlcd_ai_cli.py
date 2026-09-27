from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rlcd_ai.py"


def load_cli_module():
    spec = importlib.util.spec_from_file_location("rlcd_ai", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_ai_payload_maps_aliases():
    cli = load_cli_module()
    assert cli.build_ai_payload("coding", ["正在", "写代码"]) == {
        "status": "coding",
        "title": "正在 写代码",
    }
    assert cli.build_ai_payload("confirm", ["需要确认"]) == {
        "status": "needs_confirm",
        "title": "需要确认",
    }
    assert cli.build_ai_payload("fail", []) == {
        "status": "interrupted",
        "title": "任务已中断",
    }


def test_normalize_server_url_strips_trailing_slash():
    cli = load_cli_module()
    assert cli.normalize_server_url("http://127.0.0.1:8787/") == "http://127.0.0.1:8787"


def test_parse_args_uses_env_server(monkeypatch):
    cli = load_cli_module()
    monkeypatch.setenv("RLCD_SERVER_URL", "http://desk.local:8787")
    args = cli.parse_args(["done", "完成"])
    assert args.server == "http://desk.local:8787"
    assert args.command == "done"
    assert args.title == ["完成"]
