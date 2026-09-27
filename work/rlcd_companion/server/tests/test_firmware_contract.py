from __future__ import annotations

from pathlib import Path


FIRMWARE = (
    Path(__file__).resolve().parents[2]
    / "firmware"
    / "rlcd_client"
    / "rlcd_client.ino"
)
CONFIG_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "write_firmware_config.sh"
)
RUN_TUNNEL_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "run_tunnel.sh"
)
RESTART_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "restart_services.sh"
)


def firmware_source() -> str:
    return FIRMWARE.read_text(encoding="utf-8")


def config_script_source() -> str:
    return CONFIG_SCRIPT.read_text(encoding="utf-8")


def tunnel_script_source() -> str:
    return RUN_TUNNEL_SCRIPT.read_text(encoding="utf-8")


def restart_script_source() -> str:
    return RESTART_SCRIPT.read_text(encoding="utf-8")


def test_firmware_uses_interrupt_latched_buttons_for_ack():
    source = firmware_source()
    assert "#define KEY_PIN 18" in source
    assert "#define BOOT_PIN 0" in source
    assert "ack_requested" in source
    assert "attachInterrupt(digitalPinToInterrupt(KEY_PIN)" in source
    assert "attachInterrupt(digitalPinToInterrupt(BOOT_PIN)" in source
    assert "onAckButtonPressed" in source


def test_firmware_strong_alert_uses_xor_flash_overlay():
    source = firmware_source()
    assert "drawStrongAlertOverlay" in source
    assert "setDrawColor(2)" in source
    assert "alertLevelIs(\"strong\")" in source


def test_firmware_publishes_board_environment_with_frame_request():
    source = firmware_source()
    assert "#include <Wire.h>" in source
    assert "SHTC3_ADDR" in source
    assert "readEnvironmentSafe" in source
    assert "temp=" in source
    assert "humidity=" in source


def test_firmware_plays_sound_cues_once_per_alert_key():
    source = firmware_source()
    assert "cute_audio.h" in source
    assert "X-RLCD-Alert-Key" in source
    assert "X-RLCD-Sound-Cue" in source
    assert "playPendingSoundCue" in source
    assert "last_sound_alert_key" in source


def test_firmware_audio_uses_board_tdm_output():
    audio = (FIRMWARE.parent / "cute_audio.cpp").read_text(encoding="utf-8")
    assert "I2S_MODE_TDM" in audio
    assert "I2S_DATA_BIT_WIDTH_32BIT" in audio
    assert "I2S_TDM_SLOT0" in audio
    assert "Playing sound cue" in audio


def test_firmware_audio_is_reduced_for_office_volume():
    audio = (FIRMWARE.parent / "cute_audio.cpp").read_text(encoding="utf-8")
    assert "#define ES8311_VOLUME_REG 0xB8" in audio
    assert "#define AUDIO_CUE_GAIN_PERCENT 70" in audio
    assert "scaledAmplitude(amplitude)" in audio


def test_firmware_selects_from_multiple_wifi_profiles():
    source = firmware_source()
    assert "struct WifiNetworkConfig" in source
    assert "WIFI_NETWORKS" in source
    assert "WIFI_NETWORK_COUNT" in source
    assert "match_contains" in source
    assert "normalizedWiFiName" in source
    assert "selectWiFiNetwork" in source
    assert "WiFi.SSID" in source
    assert "WiFi.begin(WIFI_SSID, WIFI_PASSWORD)" not in source


def test_firmware_keeps_wifi_connected_for_http_frame_failures():
    source = firmware_source()
    assert "HTTP_CONNECT_TIMEOUT_MS" in source
    assert "HTTP_READ_TIMEOUT_MS" in source
    assert "Frame fetch failure" in source
    assert "Wi-Fi=" in source
    assert "if (status != WL_CONNECTED)" in source
    assert "resetWiFiConnection(reason)" in source
    assert "consecutive_frame_failures" in source
    assert "noteFrameFetchFailure" in source
    assert "http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS)" in source
    assert "http.setTimeout(HTTP_READ_TIMEOUT_MS)" in source
    assert "http.setReuse(false)" in source
    assert "consecutive_frame_failures >= MAX_CONSECUTIVE_FRAME_FAILURES" not in source


def test_firmware_draws_visible_frame_fetch_marker():
    source = firmware_source()
    assert "frame_fetch_counter" in source
    assert "drawFrameFetchMarker" in source
    assert "frame_fetch_counter = (frame_fetch_counter + 1) % 100" in source
    assert 'snprintf(label, sizeof(label), "F%02u", frame_fetch_counter)' in source


def test_firmware_config_script_supports_hotspot_and_public_base_url():
    source = config_script_source()
    assert "FRAME_BASE_URL" in source
    assert "HOTSPOT_SSID_CONTAINS" in source
    assert "HOTSPOT_PASSWORD" in source
    assert "match_contains" in source
    assert "WIFI_NETWORKS[]" in source


def test_tunnel_script_restarts_ssh_when_remote_closes_connection():
    source = tunnel_script_source()
    assert "while true" in source
    assert "ssh_exit=$?" in source
    assert "cleanup_remote_port" in source
    assert "清理远端残留隧道端口" in source
    assert 'awk -v bind_host="$bind_host" -v port="$port"' in source
    assert "RLCD_TUNNEL_RETRY_DELAY" in source
    assert "ServerAliveInterval=30" in source
    assert "sleep \"$RETRY_DELAY\"" in source


def test_restart_script_cleans_stale_server_and_tunnel_before_starting():
    source = restart_script_source()
    assert "rlcd_server" in source
    assert "rlcd_tunnel" in source
    assert "pkill -f" in source
    assert 'pkill -f "scripts/run_tunnel.sh"' in source
    assert "uvicorn app:app --host 0.0.0.0" in source
    assert "--port ${LOCAL_PORT}" in source
    assert "scripts/run_tunnel.sh" in source
    assert "RLCD_TUNNEL_HOST='${TUNNEL_HOST}'" in source
    assert "RLCD_TUNNEL_USER='${TUNNEL_USER}'" in source
    assert "<<'REMOTE' || true" in source
    assert "REMOTE_BIND_PORT=\"${RLCD_REMOTE_BIND_PORT:-18787}\"" in source
    assert 'awk -v bind_host="$bind_host" -v port="$port"' in source
    assert "ss -ltnp" in source
    assert "kill remote pids" in source
    assert "kill $pids 2>/dev/null || true" in source
    assert "curl --max-time" in source
    assert "seq 1 12" in source
    assert "remote 200 15000" in source
