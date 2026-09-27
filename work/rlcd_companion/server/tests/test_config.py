from __future__ import annotations

from config import load_config


def test_env_can_enable_feishu_without_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RLCD_FEISHU_ENABLED", "1")
    config = load_config(tmp_path / "missing.yaml")
    assert config.feishu.enabled is True

