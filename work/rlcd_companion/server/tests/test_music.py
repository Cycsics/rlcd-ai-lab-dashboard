from __future__ import annotations

from integrations.music import parse_music_output


def test_parse_music_output_builds_display_text():
    status = parse_music_output("Apple Music\t1\t周杰伦\t晴天")
    assert status.is_playing is True
    assert status.player == "Apple Music"
    assert status.artist == "周杰伦"
    assert status.title == "晴天"
    assert status.display == "周杰伦 - 晴天"


def test_parse_music_output_handles_not_playing():
    status = parse_music_output("Apple Music\t0\t\t")
    assert status.is_playing is False
    assert status.display == "未播放"
