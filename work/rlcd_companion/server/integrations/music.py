from __future__ import annotations

import subprocess

from models import MusicStatus


APPLE_MUSIC_SCRIPT = """
tell application "System Events"
    if exists process "Music" then
        tell application "Music"
            if player state is playing then
                set trackArtist to artist of current track
                set trackName to name of current track
                return "Apple Music" & tab & "1" & tab & trackArtist & tab & trackName
            else
                return "Apple Music" & tab & "0" & tab & "" & tab & ""
            end if
        end tell
    end if
end tell
return ""
"""


def parse_music_output(raw: str) -> MusicStatus:
    parts = raw.strip().split("\t")
    if len(parts) < 2 or not parts[0].strip():
        return MusicStatus()
    player = parts[0].strip()
    is_playing = parts[1].strip() == "1"
    artist = parts[2].strip() if len(parts) > 2 else ""
    title = parts[3].strip() if len(parts) > 3 else ""
    return MusicStatus(
        is_playing=is_playing,
        player=player,
        artist=artist,
        title=title,
    )


def _run_osascript(script: str, timeout: float) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def _detect_netease(timeout: float) -> MusicStatus:
    result = subprocess.run(
        ["pgrep", "-if", "网易云音乐|NetEase|NeteaseMusic"],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return MusicStatus(is_playing=True, player="网易云音乐")
    return MusicStatus()


def fetch_music_status(timeout: float = 0.5) -> MusicStatus:
    try:
        apple_status = parse_music_output(_run_osascript(APPLE_MUSIC_SCRIPT, timeout))
        if apple_status.is_playing:
            return apple_status
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        return _detect_netease(min(timeout, 0.2))
    except (OSError, subprocess.SubprocessError):
        return MusicStatus()
