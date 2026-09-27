#pragma once

// 复制本文件为 config.h，或运行 scripts/write_firmware_config.sh 生成。
// Mac 局域网 IP 可用命令查看：ipconfig getifaddr en0。
// 如果在公司使用手机热点，可添加一个 match_contains=true 的 profile。

#define WIFI_SSID "your_wifi_name"
#define WIFI_PASSWORD "your_wifi_password"

static const WifiNetworkConfig WIFI_NETWORKS[] = {
  {WIFI_SSID, WIFI_PASSWORD, false},
  {"PhoneHotspot", "your_hotspot_password", true},
};
#define WIFI_NETWORK_COUNT (sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]))

#define FRAME_URL "http://192.0.2.10:8787/frame.bin"
#define ACK_URL "http://192.0.2.10:8787/ack"

// 刷新间隔。第一版建议 3000ms，方便看到 AI 状态变化。
#define FRAME_REFRESH_MS 3000

// 小伙伴普通本地动画间隔。这里只重画本地缓存画面，不会额外请求 Mac。
// 强提醒时固件会自动降到 350ms，让提醒更明显。
#define PET_ANIMATION_MS 700
