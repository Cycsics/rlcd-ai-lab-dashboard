#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <math.h>
#include <Preferences.h>
#include "driver/usb_serial_jtag.h"

#include "ST7305_U8g2.h"
#include "adc_bsp.h"
#include "cute_audio.h"
#include "pet_pose.h"
#include "monitor_offline.h"
#include "monitor_power.h"

struct WifiNetworkConfig {
  const char *ssid;
  const char *password;
  bool match_contains;
};

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

#define LCD_WIDTH 400
#define LCD_HEIGHT 300
#define FRAME_BYTES ((LCD_WIDTH / 8) * LCD_HEIGHT)

#ifndef PET_ANIMATION_MS
#define PET_ANIMATION_MS 1000
#endif

#ifndef WIFI_NETWORK_COUNT
static const WifiNetworkConfig WIFI_NETWORKS[] = {
  {WIFI_SSID, WIFI_PASSWORD, false},
};
#define WIFI_NETWORK_COUNT (sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]))
#endif

#define RLCD_SCK_PIN 11
#define RLCD_MOSI_PIN 12
#define RLCD_DC_PIN 5
#define RLCD_CS_PIN 40
#define RLCD_RST_PIN 41
#define KEY_PIN 18
#define BOOT_PIN 0
#define I2C_SDA_PIN 13
#define I2C_SCL_PIN 14
#define SHTC3_ADDR 0x70
#define SHTC3_WAKEUP 0x3517
#define SHTC3_SLEEP 0xB098
#define SHTC3_MEASURE_T_RH 0x7866
#define SHTC3_TEMP_OFFSET_C 4.0f
#define ENV_REFRESH_MS 10000
#define HTTP_CONNECT_TIMEOUT_MS 5000
#define HTTP_READ_TIMEOUT_MS 5000
#define WIFI_RECONNECT_COOLDOWN_MS 3000

static ST7305_U8g2 lcd(RLCD_SCK_PIN, RLCD_MOSI_PIN, RLCD_DC_PIN, RLCD_CS_PIN, RLCD_RST_PIN);
static U8G2 *u8g2 = nullptr;
static uint8_t frame[FRAME_BYTES];
static uint8_t incoming_frame[FRAME_BYTES];
static bool monitor_layout = true;
static bool frame_ready = false;
static uint32_t last_good_frame_ms = 0;
static Preferences power_preferences;
static UsbStandbyPolicy usb_standby;
static bool usb_sleep_enabled = true;
static uint32_t usb_sleep_seconds = 300;
static uint32_t awake_cpu_mhz = 240;
static void drawFrameBuffer();

static uint32_t last_frame_ms = 0;
static uint32_t last_pet_ms = 0;
static uint8_t pet_frame = 0;
static String pet_state = "idle";
static String pet_mode = "normal";
static String alert_level = "normal";
static String alert_key = "none";
static String sound_cue = "none";
static String pending_sound_cue = "none";
static String last_sound_alert_key = "";
static bool last_key_state = HIGH;
static bool last_boot_state = HIGH;
static volatile bool ack_requested = false;
static uint32_t last_key_change_ms = 0;
static uint32_t last_ack_ms = 0;
static bool env_ready = false;
static float indoor_temp_c = NAN;
static float indoor_humidity = NAN;
static uint32_t last_env_ms = 0;
static uint8_t consecutive_frame_failures = 0;
static uint32_t last_wifi_reset_ms = 0;
static uint8_t frame_fetch_counter = 0;

static void IRAM_ATTR onAckButtonPressed()
{
  ack_requested = true;
}

static const char *wifiStatusName(wl_status_t status)
{
  switch (status) {
  case WL_IDLE_STATUS:
    return "IDLE";
  case WL_NO_SSID_AVAIL:
    return "NO_SSID";
  case WL_SCAN_COMPLETED:
    return "SCAN_DONE";
  case WL_CONNECTED:
    return "CONNECTED";
  case WL_CONNECT_FAILED:
    return "CONNECT_FAILED";
  case WL_CONNECTION_LOST:
    return "CONNECTION_LOST";
  case WL_DISCONNECTED:
    return "DISCONNECTED";
  default:
    return "UNKNOWN";
  }
}

static String normalizedWiFiName(const String &value)
{
  String normalized = "";
  normalized.reserve(value.length());
  for (size_t i = 0; i < value.length(); ++i) {
    char ch = value.charAt(i);
    if (ch == ' ' || ch == '\t' || ch == '*') {
      continue;
    }
    normalized += (char)tolower((unsigned char)ch);
  }
  return normalized;
}

static bool wifiNetworkMatches(const String &ssid, const WifiNetworkConfig &network)
{
  if (network.ssid == nullptr || network.ssid[0] == '\0') {
    return false;
  }
  if (network.match_contains) {
    return normalizedWiFiName(ssid).indexOf(normalizedWiFiName(network.ssid)) >= 0;
  }
  return ssid == network.ssid;
}

static int matchingWiFiProfileIndex(const String &ssid)
{
  for (size_t i = 0; i < WIFI_NETWORK_COUNT; ++i) {
    if (wifiNetworkMatches(ssid, WIFI_NETWORKS[i])) {
      return (int)i;
    }
  }
  return -1;
}

static bool selectWiFiNetwork(int scan_count, String *selected_ssid, const WifiNetworkConfig **selected_network)
{
  for (size_t profile = 0; profile < WIFI_NETWORK_COUNT; ++profile) {
    int best_scan = -1;
    int best_rssi = -200;
    for (int scan = 0; scan < scan_count; ++scan) {
      String ssid = WiFi.SSID(scan);
      if (!wifiNetworkMatches(ssid, WIFI_NETWORKS[profile])) {
        continue;
      }
      int rssi = WiFi.RSSI(scan);
      if (best_scan < 0 || rssi > best_rssi) {
        best_scan = scan;
        best_rssi = rssi;
      }
    }
    if (best_scan >= 0) {
      *selected_ssid = WiFi.SSID(best_scan);
      *selected_network = &WIFI_NETWORKS[profile];
      Serial.printf("Selected Wi-Fi profile %u: %s via %s match, RSSI=%d\n",
                    (unsigned)profile + 1,
                    selected_ssid->c_str(),
                    WIFI_NETWORKS[profile].match_contains ? "contains" : "exact",
                    best_rssi);
      return true;
    }
  }
  return false;
}

static int scanWiFiNetworks()
{
  Serial.println("Scanning Wi-Fi networks...");
  int count = WiFi.scanNetworks(false, true);
  if (count <= 0) {
    Serial.printf("No networks found: %d\n", count);
    return count;
  }

  Serial.printf("Found %d networks\n", count);
  for (int i = 0; i < count && i < 20; ++i) {
    int profile = matchingWiFiProfileIndex(WiFi.SSID(i));
    Serial.printf("  %2d: %s RSSI=%d CH=%d ENC=%d%s\n",
                  i + 1,
                  WiFi.SSID(i).c_str(),
                  WiFi.RSSI(i),
                  WiFi.channel(i),
                  WiFi.encryptionType(i),
                  profile >= 0 ? " <-- configured" : "");
  }
  return count;
}

static void drawMessage(const char *line1, const char *line2 = "", const char *line3 = "")
{
  u8g2->clearBuffer();
  u8g2->setDrawColor(1);
  u8g2->drawFrame(8, 8, LCD_WIDTH - 16, LCD_HEIGHT - 16);
  u8g2->setFont(u8g2_font_6x13_tf);
  u8g2->drawStr(24, 64, line1);
  if (line2 && line2[0]) {
    u8g2->drawStr(24, 92, line2);
  }
  if (line3 && line3[0]) {
    u8g2->drawStr(24, 120, line3);
  }
  u8g2->sendBuffer();
}

static void connectWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  String selected_ssid = "";
  const WifiNetworkConfig *selected_network = nullptr;

  int scan_count = scanWiFiNetworks();
  if (!selectWiFiNetwork(scan_count, &selected_ssid, &selected_network)) {
    selected_network = &WIFI_NETWORKS[0];
    selected_ssid = selected_network->ssid;
    Serial.printf("No configured Wi-Fi visible; falling back to first profile: %s\n", selected_ssid.c_str());
  }
  WiFi.begin(selected_ssid.c_str(), selected_network->password);
  Serial.printf("Connecting Wi-Fi: %s\n", selected_ssid.c_str());
  if (!frame_ready) drawMessage("Connecting Wi-Fi", selected_ssid.c_str());
  WiFi.scanDelete();

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    if (monitor_layout && frame_ready) drawFrameBuffer();
    Serial.print(".");
    if (millis() - start > 20000) {
      if (monitor_layout) return;
      wl_status_t status = WiFi.status();
      Serial.printf("\nWi-Fi timeout, status=%d (%s), retrying\n", status, wifiStatusName(status));
      drawMessage("Wi-Fi timeout", "Check config.h");
      WiFi.disconnect();
      delay(1000);
      scan_count = scanWiFiNetworks();
      if (!selectWiFiNetwork(scan_count, &selected_ssid, &selected_network)) {
        selected_network = &WIFI_NETWORKS[0];
        selected_ssid = selected_network->ssid;
        Serial.printf("No configured Wi-Fi visible; retrying first profile: %s\n", selected_ssid.c_str());
      }
      WiFi.begin(selected_ssid.c_str(), selected_network->password);
      Serial.printf("Connecting Wi-Fi: %s\n", selected_ssid.c_str());
      drawMessage("Connecting Wi-Fi", selected_ssid.c_str());
      WiFi.scanDelete();
      start = millis();
    }
  }
  Serial.println("");
  Serial.printf("Wi-Fi connected: %s\n", WiFi.localIP().toString().c_str());
  if (!frame_ready) drawMessage("Wi-Fi connected", WiFi.localIP().toString().c_str());
}

static void resetWiFiConnection(const char *reason)
{
  uint32_t now = millis();
  if (now - last_wifi_reset_ms < WIFI_RECONNECT_COOLDOWN_MS) {
    return;
  }

  last_wifi_reset_ms = now;
  wl_status_t status = WiFi.status();
  Serial.printf("Resetting Wi-Fi: %s, status=%d (%s)\n",
                reason ? reason : "frame fetch recovery",
                status,
                wifiStatusName(status));
  if (!monitor_layout) drawMessage("Wi-Fi reconnecting", reason ? reason : "Frame fetch recovery");
  WiFi.disconnect();
  delay(500);
  connectWiFi();
}

static void noteFrameFetchSuccess()
{
  if (consecutive_frame_failures > 0) {
    Serial.printf("Frame fetch recovered after %u failures\n", consecutive_frame_failures);
  }
  consecutive_frame_failures = 0;
}

static void noteFrameFetchFailure(const char *reason)
{
  if (consecutive_frame_failures < 255) {
    consecutive_frame_failures++;
  }
  wl_status_t status = WiFi.status();
  Serial.printf("Frame fetch failure %u: %s, Wi-Fi=%d (%s)\n",
                consecutive_frame_failures,
                reason ? reason : "unknown",
                status,
                wifiStatusName(status));
  if (status != WL_CONNECTED) {
    resetWiFiConnection(reason);
  }
}

static uint8_t readBatteryLevelSafe()
{
  static bool adc_ready = false;
  if (!adc_ready) {
    Adc_PortInit();
    adc_ready = true;
  }
  return Adc_GetBatteryLevel();
}

static void setupBoardI2c()
{
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000);
  Serial.printf("I2C ready: SDA=%d SCL=%d\n", I2C_SDA_PIN, I2C_SCL_PIN);
}

static bool writeI2cCommand(uint8_t address, uint16_t command)
{
  Wire.beginTransmission(address);
  Wire.write((uint8_t)(command >> 8));
  Wire.write((uint8_t)(command & 0xFF));
  return Wire.endTransmission() == 0;
}

static uint8_t shtc3Crc(const uint8_t *data, uint8_t len)
{
  uint8_t crc = 0xFF;
  for (uint8_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

static bool readShtc3Once(float *temp_c, float *humidity_percent)
{
  if (!writeI2cCommand(SHTC3_ADDR, SHTC3_WAKEUP)) {
    return false;
  }
  delay(20);
  if (!writeI2cCommand(SHTC3_ADDR, SHTC3_MEASURE_T_RH)) {
    writeI2cCommand(SHTC3_ADDR, SHTC3_SLEEP);
    return false;
  }
  delay(20);

  uint8_t bytes[6] = {0};
  int read = Wire.requestFrom((uint8_t)SHTC3_ADDR, (uint8_t)6);
  if (read != 6) {
    writeI2cCommand(SHTC3_ADDR, SHTC3_SLEEP);
    return false;
  }
  for (int i = 0; i < 6; ++i) {
    bytes[i] = Wire.read();
  }
  writeI2cCommand(SHTC3_ADDR, SHTC3_SLEEP);

  if (shtc3Crc(bytes, 2) != bytes[2] || shtc3Crc(bytes + 3, 2) != bytes[5]) {
    return false;
  }

  uint16_t raw_temp = ((uint16_t)bytes[0] << 8) | bytes[1];
  uint16_t raw_humidity = ((uint16_t)bytes[3] << 8) | bytes[4];
  *temp_c = (175.0f * (float)raw_temp / 65536.0f) - 45.0f - SHTC3_TEMP_OFFSET_C;
  *humidity_percent = 100.0f * (float)raw_humidity / 65536.0f;
  return true;
}

static void readEnvironmentSafe(bool force = false)
{
  uint32_t now = millis();
  if (!force && env_ready && now - last_env_ms < ENV_REFRESH_MS) {
    return;
  }

  float temp = NAN;
  float humidity = NAN;
  if (readShtc3Once(&temp, &humidity)) {
    indoor_temp_c = temp;
    indoor_humidity = humidity;
    env_ready = true;
    last_env_ms = now;
    Serial.printf("SHTC3 indoor: %.1fC %.1f%%\n", indoor_temp_c, indoor_humidity);
  } else {
    Serial.println("SHTC3 read failed; keeping previous environment value");
    last_env_ms = now;
  }
}

static String frameUrlWithTelemetry()
{
  uint8_t battery = readBatteryLevelSafe();
  readEnvironmentSafe();
  String url = FRAME_URL;
  url += (url.indexOf('?') >= 0) ? "&battery=" : "?battery=";
  url += String(battery);
  url += usb_serial_jtag_is_connected() ? "&usb=1&power_version=1" : "&usb=0&power_version=1";
  if (env_ready && !isnan(indoor_temp_c) && !isnan(indoor_humidity)) {
    url += "&temp=";
    url += String(indoor_temp_c, 1);
    url += "&humidity=";
    url += String(indoor_humidity, 1);
  }
  return url;
}

static void queueSoundCueIfNeeded(const String &next_alert_key, const String &next_sound_cue)
{
  if (next_sound_cue.length() == 0 || next_sound_cue == "none") {
    return;
  }
  if (next_alert_key.length() == 0 || next_alert_key == "none") {
    return;
  }
  if (next_alert_key == last_sound_alert_key) {
    return;
  }
  pending_sound_cue = next_sound_cue;
  last_sound_alert_key = next_alert_key;
  Serial.printf("Queued sound cue: %s alert=%s\n", pending_sound_cue.c_str(), next_alert_key.c_str());
}

static void playPendingSoundCue()
{
  if (pending_sound_cue.length() == 0 || pending_sound_cue == "none") {
    return;
  }
  String cue = pending_sound_cue;
  pending_sound_cue = "none";
  playCuteSoundCue(cue.c_str());
}

static bool fetchFrame()
{
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (WiFi.status() != WL_CONNECTED) return false;

  String url = frameUrlWithTelemetry();
  HTTPClient http;
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_READ_TIMEOUT_MS);
  http.setReuse(false);
  Serial.printf("GET %s\n", url.c_str());
  if (!http.begin(url)) {
    Serial.println("HTTP begin failed");
    http.end();
    noteFrameFetchFailure("HTTP begin failed");
    return false;
  }
  const char *header_keys[] = {
    "X-RLCD-Pet-State",
    "X-RLCD-Pet-Mode",
    "X-RLCD-Alert-Level",
    "X-RLCD-Alert-Key",
    "X-RLCD-Sound-Cue",
    "X-RLCD-Layout",
    "X-RLCD-Usb-Sleep-Enabled",
    "X-RLCD-Usb-Sleep-Seconds",
  };
  http.collectHeaders(header_keys, 8);

  int status = http.GET();
  if (status != HTTP_CODE_OK) {
    Serial.printf("HTTP GET failed: %d\n", status);
    http.end();
    noteFrameFetchFailure("HTTP GET failed");
    return false;
  }
  String next_pet_state = http.header("X-RLCD-Pet-State");
  if (next_pet_state.length() > 0) {
    pet_state = next_pet_state;
  }
  String next_pet_mode = http.header("X-RLCD-Pet-Mode");
  if (next_pet_mode.length() > 0) {
    pet_mode = next_pet_mode;
  }
  String next_alert_level = http.header("X-RLCD-Alert-Level");
  if (next_alert_level.length() > 0) {
    alert_level = next_alert_level;
  }
  String next_alert_key = http.header("X-RLCD-Alert-Key");
  if (next_alert_key.length() > 0) {
    alert_key = next_alert_key;
  }
  String next_sound_cue = http.header("X-RLCD-Sound-Cue");
  if (next_sound_cue.length() > 0) {
    sound_cue = next_sound_cue;
  }
  bool next_monitor_layout = http.header("X-RLCD-Layout") == "monitor-v1";
  String power_enabled_header = http.header("X-RLCD-Usb-Sleep-Enabled");
  String power_seconds_header = http.header("X-RLCD-Usb-Sleep-Seconds");
  Serial.printf("Pet state=%s mode=%s alert=%s key=%s sound=%s\n",
                pet_state.c_str(),
                pet_mode.c_str(),
                alert_level.c_str(),
                alert_key.c_str(),
                sound_cue.c_str());

  int size = http.getSize();
  if (size > 0 && size != FRAME_BYTES) {
    Serial.printf("Unexpected frame size: %d\n", size);
    http.end();
    noteFrameFetchFailure("Unexpected frame size");
    return false;
  }

  WiFiClient *stream = http.getStreamPtr();
  int total = 0;
  uint32_t start = millis();
  while (total < FRAME_BYTES && millis() - start < 10000) {
    int available = stream->available();
    if (available > 0) {
      int want = min(available, FRAME_BYTES - total);
      int read = stream->readBytes(incoming_frame + total, want);
      total += read;
    } else {
      delay(1);
    }
  }
  http.end();

  if (total != FRAME_BYTES) {
    Serial.printf("Incomplete frame: %d/%d\n", total, FRAME_BYTES);
    noteFrameFetchFailure("Incomplete frame");
    return false;
  }
  frame_fetch_counter = (frame_fetch_counter + 1) % 100;
  // Apply only validated settings from a complete successful response.
  bool valid_seconds = power_seconds_header.length() > 0 && power_seconds_header.length() <= 5;
  for (size_t i=0; i<power_seconds_header.length(); i++) {
    if (power_seconds_header[i]<'0' || power_seconds_header[i]>'9') valid_seconds=false;
  }
  if ((power_enabled_header=="0" || power_enabled_header=="1") && valid_seconds) {
    uint32_t seconds=power_seconds_header.toInt();
    bool enabled=power_enabled_header=="1";
    if (seconds<=86400 && (enabled!=usb_sleep_enabled || seconds!=usb_sleep_seconds)) {
      usb_sleep_enabled=enabled; usb_sleep_seconds=seconds;
      power_preferences.putBool("enabled",enabled);
      power_preferences.putUInt("seconds",seconds);
    }
  }
  memcpy(frame, incoming_frame, FRAME_BYTES);
  monitor_layout = next_monitor_layout;
  frame_ready = true;
  last_good_frame_ms = millis();
  if (monitor_layout) pending_sound_cue = "none";
  else queueSoundCueIfNeeded(alert_key, sound_cue);
  noteFrameFetchSuccess();
  return true;
}

static bool petStateIs(const char *name)
{
  return pet_state.equals(name);
}

static bool petModeIs(const char *name)
{
  return pet_mode.equals(name);
}

static bool alertLevelIs(const char *name)
{
  return alert_level.equals(name);
}

static uint32_t currentPetAnimationMs()
{
  if (alertLevelIs("strong") || petStateIs("needs_confirm")) {
    return 280;
  }
  if (petStateIs("ai_done") || petStateIs("meeting_soon")) {
    return 360;
  }
  if (petStateIs("ai_coding") || petStateIs("busy_day")) {
    return 480;
  }
  return PET_ANIMATION_MS;
}

static void drawStrongAlertOverlay()
{
  if (!alertLevelIs("strong") || pet_frame % 2 != 0) {
    return;
  }
  u8g2->setDrawColor(2);
  u8g2->drawBox(14, 62, 117, 123);
  u8g2->drawBox(138, 44, LCD_WIDTH - 138, 214);
  u8g2->setDrawColor(1);
  u8g2->drawFrame(14, 62, 117, 123);
  u8g2->drawFrame(138, 44, LCD_WIDTH - 138, 214);
}

static void drawBadge(int x, int y, const char *kind)
{
  u8g2->drawFrame(x, y, 17, 19);
  if (strcmp(kind, "!") == 0) {
    u8g2->drawVLine(x + 8, y + 4, 9);
    u8g2->drawPixel(x + 8, y + 15);
  } else if (strcmp(kind, "bat") == 0) {
    u8g2->drawFrame(x + 3, y + 6, 10, 7);
    u8g2->drawBox(x + 13, y + 8, 2, 3);
    u8g2->drawBox(x + 5, y + 8, 3, 3);
  } else {
    u8g2->drawPixel(x + 5, y + 6);
    u8g2->drawPixel(x + 11, y + 6);
    u8g2->drawHLine(x + 5, y + 13, 7);
  }
}

static PetPose currentPetPose()
{
  PetPose pose;
  pose.alert_mode = petModeIs("alert");
  pose.strong_alert = alertLevelIs("strong");
  pose.pet_x0 = pose.alert_mode ? 20 : 10;
  pose.pet_y0 = pose.alert_mode ? 72 : 42;
  pose.pet_x1 = pose.alert_mode ? 122 : 112;
  pose.pet_y1 = pose.alert_mode ? 172 : 130;
  pose.clear_x0 = pose.alert_mode ? 14 : pose.pet_x0;
  pose.clear_y0 = pose.alert_mode ? 62 : pose.pet_y0;
  pose.clear_x1 = pose.alert_mode ? 130 : 121;
  pose.clear_y1 = pose.alert_mode ? 184 : pose.pet_y1;
  pose.cx = (pose.pet_x0 + pose.pet_x1) / 2;
  pose.cycle4 = pet_frame % 4;
  pose.phase8 = pet_frame % 8;
  const int bob = pose.strong_alert
                    ? ((pose.cycle4 == 1) ? -5 : ((pose.cycle4 == 3) ? 4 : 0))
                    : ((pose.cycle4 == 1) ? -2 : ((pose.cycle4 == 3) ? 1 : 0));
  pose.top = pose.pet_y0 + 8 + bob;
  return pose;
}

static void clearPetRegion(const PetPose &pose)
{
  u8g2->setDrawColor(0);
  u8g2->drawBox(pose.clear_x0,
                pose.clear_y0,
                pose.clear_x1 - pose.clear_x0 + 1,
                pose.clear_y1 - pose.clear_y0 + 1);
  u8g2->setDrawColor(1);
}

static void drawStrongAlertFrame(const PetPose &pose)
{
  if (!pose.strong_alert || pet_frame % 2 == 0) {
    return;
  }

  const int clear_w = pose.clear_x1 - pose.clear_x0 + 1;
  const int clear_h = pose.clear_y1 - pose.clear_y0 + 1;
  u8g2->drawFrame(pose.clear_x0, pose.clear_y0, clear_w, clear_h);
  u8g2->drawFrame(pose.clear_x0 + 3, pose.clear_y0 + 3, clear_w - 6, clear_h - 6);
  u8g2->drawBox(pose.clear_x0 + 7, pose.clear_y0 + 7, 7, 7);
  u8g2->drawBox(pose.clear_x1 - 13, pose.clear_y0 + 7, 7, 7);
  u8g2->drawBox(pose.clear_x0 + 7, pose.clear_y1 - 13, 7, 7);
  u8g2->drawBox(pose.clear_x1 - 13, pose.clear_y1 - 13, 7, 7);
}

static void drawThickLine(int x0, int y0, int x1, int y1)
{
  u8g2->drawLine(x0, y0, x1, y1);
  u8g2->drawLine(x0 + 1, y0, x1 + 1, y1);
  u8g2->drawLine(x0, y0 + 1, x1, y1 + 1);
}

static void drawSparkle(int x, int y)
{
  u8g2->drawHLine(x - 4, y, 9);
  u8g2->drawVLine(x, y - 4, 9);
}

static void drawAntenna(int x, int y, int wobble)
{
  u8g2->drawVLine(x + 5, y - 6 - wobble, 6);
  u8g2->drawFrame(x, y - 10 - wobble, 11, 5);
}

static void drawAHead(const PetPose &pose, const char *mood, int lean = 0, int yshift = 0)
{
  const int cx = pose.cx + lean;
  const int top = pose.top + yshift;
  const bool blink = strcmp(mood, "sleepy") != 0 && pet_frame % 10 == 0 && petStateIs("idle");
  const int antenna_wobble = (pose.phase8 % 4 == 1) ? 1 : 0;

  drawAntenna(cx - 19, top + 1, antenna_wobble);
  drawAntenna(cx + 10, top + 1, pose.phase8 % 4 == 3 ? 1 : 0);
  u8g2->drawRFrame(cx - 30, top, 61, 37, 7);
  u8g2->drawRFrame(cx - 29, top + 1, 59, 35, 6);

  if (blink || strcmp(mood, "sleepy") == 0) {
    u8g2->drawHLine(cx - 18, top + 17, 11);
    u8g2->drawHLine(cx + 8, top + 17, 11);
  } else if (strcmp(mood, "worried") == 0) {
    u8g2->drawLine(cx - 19, top + 12, cx - 10, top + 21);
    u8g2->drawLine(cx + 19, top + 12, cx + 10, top + 21);
  } else if (strcmp(mood, "happy") == 0) {
    u8g2->drawBox(cx - 18, top + 13, 8, 8);
    u8g2->drawBox(cx + 10, top + 13, 8, 8);
    u8g2->drawPixel(cx - 9, top + 14);
    u8g2->drawPixel(cx + 9, top + 14);
  } else {
    u8g2->drawBox(cx - 18, top + 13, 8, 8);
    u8g2->drawBox(cx + 10, top + 13, 8, 8);
  }

  if (strcmp(mood, "worried") == 0) {
    u8g2->drawLine(cx - 8, top + 29, cx, top + 25);
    u8g2->drawLine(cx, top + 25, cx + 8, top + 29);
  } else if (strcmp(mood, "happy") == 0) {
    u8g2->drawHLine(cx - 8, top + 28, 17);
    u8g2->drawPixel(cx - 9, top + 27);
    u8g2->drawPixel(cx + 9, top + 27);
  } else if (strcmp(mood, "sleepy") == 0) {
    u8g2->drawHLine(cx - 7, top + 29, 15);
    u8g2->drawPixel(cx - 8, top + 28);
    u8g2->drawPixel(cx + 8, top + 28);
  } else {
    u8g2->drawHLine(cx - 7, top + 28, 15);
  }
}

static void drawABody(const PetPose &pose, int lean = 0, int yshift = 0)
{
  const int cx = pose.cx + lean;
  const int top = pose.top + yshift;
  u8g2->drawRFrame(cx - 22, top + 39, 45, 39, 6);
  u8g2->drawRFrame(cx - 18, top + 43, 37, 31, 3);
  u8g2->drawFrame(cx - 12, top + 51, 25, 17);
  u8g2->drawHLine(cx - 24, top + 81, 49);
}

static void drawIdleSway(const PetPose &pose)
{
  const int lean = (pose.phase8 < 4) ? -1 : 1;
  drawAHead(pose, "normal", lean);
  drawABody(pose, lean);
  drawThickLine(pose.cx - 22 + lean, pose.top + 54, pose.cx - 42, pose.top + 64 + (pose.cycle4 == 2 ? 2 : 0));
  drawThickLine(pose.cx + 22 + lean, pose.top + 54, pose.cx + 42, pose.top + 64 - (pose.cycle4 == 2 ? 2 : 0));
  if (pose.phase8 == 6) {
    drawSparkle(pose.cx + 43, pose.top + 7);
  }
}

static void drawJumpRope(const PetPose &pose)
{
  const int jump = (pose.phase8 == 1 || pose.phase8 == 2 || pose.phase8 == 5 || pose.phase8 == 6) ? -4 : 0;
  PetPose lifted = pose;
  lifted.top += jump;
  drawAHead(lifted, "happy");
  drawABody(lifted);
  const int rope_top = pose.top + ((pose.phase8 < 4) ? 7 : 73);
  u8g2->drawLine(pose.cx - 45, rope_top, pose.cx - 26, pose.top + 58 + jump);
  u8g2->drawLine(pose.cx + 45, rope_top, pose.cx + 26, pose.top + 58 + jump);
  u8g2->drawHLine(pose.cx - 35, rope_top, 71);
  drawThickLine(lifted.cx - 22, lifted.top + 54, pose.cx - 43, pose.top + 58 + jump);
  drawThickLine(lifted.cx + 22, lifted.top + 54, pose.cx + 43, pose.top + 58 + jump);
}

static void drawBikeRide(const PetPose &pose)
{
  drawIdleSway(pose);
}

static void drawTypingPet(const PetPose &pose)
{
  drawAHead(pose, "normal");
  drawABody(pose);
  const int laptop_x = pose.cx + 18;
  const int laptop_y = pose.top + 51;
  u8g2->drawFrame(laptop_x, laptop_y, 35, 22);
  u8g2->drawFrame(laptop_x + 4, laptop_y + 5, 27, 11);
  u8g2->drawBox(laptop_x - 5, laptop_y + 23, 43, 7);
  for (int i = 0; i < 4; ++i) {
    const int key_x = laptop_x + 1 + i * 8;
    if (i == pose.phase8 % 4) {
      u8g2->drawBox(key_x, laptop_y + 25, 5, 3);
    } else {
      u8g2->drawPixel(key_x + 2, laptop_y + 26);
    }
  }
  drawThickLine(pose.cx + 22, pose.top + 56, laptop_x - 2, laptop_y + 26);
  drawThickLine(pose.cx - 22, pose.top + 56, pose.cx - 39, pose.top + 64);
  for (int i = 0; i < 3; ++i) {
    const int dot_x = laptop_x + 7 + i * 7;
    if ((pet_frame + i) % 4 == 0) {
      u8g2->drawBox(dot_x, laptop_y + 8, 3, 3);
    } else {
      u8g2->drawPixel(dot_x + 1, laptop_y + 9);
    }
  }
}

static void drawCelebratePet(const PetPose &pose)
{
  const int jump = (pose.phase8 == 1 || pose.phase8 == 2) ? -5 : 0;
  PetPose lifted = pose;
  lifted.top += jump;
  drawAHead(lifted, "happy");
  drawABody(lifted);
  const int wave = (pose.phase8 % 2 == 0) ? 10 : 1;
  drawThickLine(lifted.cx - 22, lifted.top + 54, lifted.cx - 42, lifted.top + 38 - wave);
  drawThickLine(lifted.cx + 22, lifted.top + 54, lifted.cx + 42, lifted.top + 38 - wave);
  drawSparkle(pose.cx - 43, pose.top + 8);
  drawSparkle(pose.cx + 43, pose.top + 8);
}

static void drawConfirmPet(const PetPose &pose)
{
  drawAHead(pose, "worried");
  drawABody(pose);
  const int sign_y = pose.top + ((pose.phase8 % 2 == 0) ? 50 : 47);
  drawThickLine(pose.cx - 22, pose.top + 56, pose.cx - 45, sign_y + 10);
  drawThickLine(pose.cx + 22, pose.top + 56, pose.cx + 45, sign_y + 10);
  u8g2->drawRBox(pose.cx - 40, sign_y, 81, 30, 4);
  u8g2->setDrawColor(0);
  u8g2->drawStr(pose.cx - 25, sign_y + 19, "ACK?");
  u8g2->drawVLine(pose.cx + 28, sign_y + 7, 11);
  u8g2->drawBox(pose.cx + 26, sign_y + 21, 5, 3);
  u8g2->setDrawColor(1);
}

static void drawMeetingPet(const PetPose &pose)
{
  drawAHead(pose, "happy");
  drawABody(pose);
  const int bell_x = pose.cx + 41;
  const int bell_y = pose.top + 24 + ((pose.phase8 % 2 == 0) ? -4 : 2);
  drawThickLine(pose.cx - 22, pose.top + 56, pose.cx - 42, pose.top + 64);
  drawThickLine(pose.cx + 22, pose.top + 56, bell_x, bell_y + 10);
  u8g2->drawFrame(bell_x - 7, bell_y, 15, 13);
  u8g2->drawHLine(bell_x - 10, bell_y + 13, 21);
  u8g2->drawPixel(bell_x, bell_y + 16);
  if (pose.phase8 % 2 == 0) {
    u8g2->drawLine(bell_x + 13, bell_y - 3, bell_x + 19, bell_y - 8);
    u8g2->drawLine(bell_x + 13, bell_y + 3, bell_x + 21, bell_y + 1);
  }
}

static void drawBusyPet(const PetPose &pose)
{
  const int lean = (pose.phase8 < 4) ? 2 : -2;
  drawAHead(pose, "normal", lean);
  drawABody(pose, lean);
  const int step = (pose.phase8 % 2 == 0) ? 7 : -2;
  drawThickLine(pose.cx - 22 + lean, pose.top + 56, pose.cx - 42, pose.top + 66 + step);
  drawThickLine(pose.cx + 22 + lean, pose.top + 56, pose.cx + 40, pose.top + 64 - step);
  u8g2->drawFrame(pose.cx + 29, pose.top + 51, 18, 14);
  u8g2->drawHLine(pose.cx + 33, pose.top + 55, 10);
  u8g2->drawPixel(pose.cx + 35, pose.top + 60);
  u8g2->drawPixel(pose.cx + 41, pose.top + 60);
}

static void drawLowBatteryPet(const PetPose &pose)
{
  PetPose tired = pose;
  tired.top += 5;
  drawAHead(tired, "sleepy");
  drawABody(tired);
  drawThickLine(tired.cx - 22, tired.top + 56, tired.cx - 42, tired.top + 70);
  drawThickLine(tired.cx + 22, tired.top + 56, tired.cx + 42, tired.top + 70);
  drawBadge(pose.pet_x1 - 30, pose.pet_y0 + 8, "bat");
}

static void drawLocalPet()
{
  PetPose pose = currentPetPose();
  clearPetRegion(pose);
  drawStrongAlertFrame(pose);

  if (pose.strong_alert || petStateIs("needs_confirm")) {
    drawConfirmPet(pose);
  } else if (petStateIs("ai_coding")) {
    drawTypingPet(pose);
  } else if (petStateIs("ai_done")) {
    drawCelebratePet(pose);
  } else if (petStateIs("meeting_soon")) {
    drawMeetingPet(pose);
  } else if (petStateIs("busy_day")) {
    drawBusyPet(pose);
  } else if (petStateIs("low_battery")) {
    drawLowBatteryPet(pose);
  } else {
    const uint8_t idle_scene = (pet_frame / 24) % 3;
    if (idle_scene == 1) {
      drawJumpRope(pose);
    } else if (idle_scene == 2) {
      drawBikeRide(pose);
    } else {
      drawIdleSway(pose);
    }
  }

  if ((pose.strong_alert || petStateIs("needs_confirm")) && pet_frame % 2 == 0) {
    drawBadge(pose.pet_x1 - 24, pose.pet_y0 + 4, "!");
  }
}

static void drawFrameFetchMarker()
{
  char label[4];
  snprintf(label, sizeof(label), "F%02u", frame_fetch_counter);
  u8g2->setDrawColor(0);
  u8g2->drawBox(LCD_WIDTH - 26, LCD_HEIGHT - 10, 25, 9);
  u8g2->setDrawColor(1);
  u8g2->drawFrame(LCD_WIDTH - 26, LCD_HEIGHT - 10, 25, 9);
  u8g2->setFont(u8g2_font_4x6_tr);
  u8g2->drawStr(LCD_WIDTH - 22, LCD_HEIGHT - 3, label);
}

static void drawFrameBuffer()
{
  u8g2->clearBuffer();
  u8g2->setDrawColor(1);
  u8g2->drawXBMP(0, 0, LCD_WIDTH, LCD_HEIGHT, frame);
  if (monitor_layout) {
    if (millis() - last_good_frame_ms >= 30000) {
      u8g2->setDrawColor(0);
      u8g2->drawBox(0, 280, LCD_WIDTH, 20);
      u8g2->setDrawColor(1);
      u8g2->drawXBMP(6, 282, MONITOR_OFFLINE_WIDTH, MONITOR_OFFLINE_HEIGHT, monitor_offline_bits);
    }
  } else {
    drawLocalPet();
    drawStrongAlertOverlay();
    drawFrameFetchMarker();
  }
  u8g2->sendBuffer();
}

static void sendAck()
{
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  HTTPClient http;
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_READ_TIMEOUT_MS);
  http.setReuse(false);
  Serial.printf("POST %s\n", ACK_URL);
  if (!http.begin(ACK_URL)) {
    Serial.println("ACK begin failed");
    http.end();
    return;
  }
  int status = http.POST("");
  Serial.printf("ACK status: %d\n", status);
  http.end();
}

static void handleKey()
{
  bool key_state = digitalRead(KEY_PIN);
  bool boot_state = digitalRead(BOOT_PIN);
  bool pressed = (key_state == LOW) || (boot_state == LOW);
  uint32_t now = millis();
  if (key_state != last_key_state || boot_state != last_boot_state) {
    last_key_change_ms = now;
    last_key_state = key_state;
    last_boot_state = boot_state;
    if (pressed) {
      ack_requested = true;
    }
  }
  bool requested = ack_requested;
  if (!requested || now - last_key_change_ms < 35) {
    return;
  }
  if (now - last_ack_ms < 900) {
    noInterrupts();
    ack_requested = false;
    interrupts();
    return;
  }
  noInterrupts();
  ack_requested = false;
  interrupts();
  last_ack_ms = now;
  Serial.printf("ACK button event: key=%d boot=%d\n", key_state == LOW, boot_state == LOW);
  if (pressed || requested) {
    sendAck();
    delay(350);
    fetchFrame();
    pet_frame++;
    drawFrameBuffer();
    playPendingSoundCue();
  }
}

void setup()
{
  Serial.begin(115200);
  delay(300);
  power_preferences.begin("rlcd-power",false);
  usb_sleep_enabled=power_preferences.getBool("enabled",true);
  usb_sleep_seconds=power_preferences.getUInt("seconds",300);
  if (usb_sleep_seconds>86400) usb_sleep_seconds=300;
  awake_cpu_mhz=getCpuFrequencyMhz();

  pinMode(KEY_PIN, INPUT_PULLUP);
  pinMode(BOOT_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(KEY_PIN), onAckButtonPressed, FALLING);
  attachInterrupt(digitalPinToInterrupt(BOOT_PIN), onAckButtonPressed, FALLING);
  lcd.begin(0, U8G2_R1);
  u8g2 = lcd.getU8g2();

  drawMessage("RLCD companion", "Booting...");
  setupBoardI2c();
  readEnvironmentSafe(true);
  setupCuteAudio();
  connectWiFi();

  if (fetchFrame()) {
    drawFrameBuffer();
    playPendingSoundCue();
  } else {
    drawMessage("Frame fetch failed", "Check Mac service", FRAME_URL);
  }
  last_frame_ms = millis();
}

void loop()
{
  const bool wake_key=digitalRead(KEY_PIN)==LOW || digitalRead(BOOT_PIN)==LOW || ack_requested;
  UsbStandbyPolicy::Action power_action=usb_standby.update(
      millis(),usb_serial_jtag_is_connected(),wake_key,usb_sleep_enabled,usb_sleep_seconds);
  if (power_action==UsbStandbyPolicy::EnterStandby) {
    pending_sound_cue="none";
    digitalWrite(46,LOW); // amplifier off
    lcd.standby(true);
    WiFi.disconnect(false);
    WiFi.mode(WIFI_OFF);
    setCpuFrequencyMhz(80); // keep native USB clock/detection alive
  } else if (power_action==UsbStandbyPolicy::LeaveStandby) {
    ack_requested=false;
    setCpuFrequencyMhz(awake_cpu_mhz);
    lcd.standby(false);
    drawMessage("Waking up", "Connecting...");
    connectWiFi();
    if (fetchFrame()) drawFrameBuffer();
    last_frame_ms=millis();
  }
  if (usb_standby.sleeping) {
    ack_requested=false;
    delay(100);
    return; // no frames, redraws, environment reads or sounds while off
  }
  if (!monitor_layout) handleKey();
  else ack_requested = false;
  uint32_t now = millis();
  if (frame_ready && now - last_pet_ms >= (monitor_layout ? 1000 : currentPetAnimationMs())) {
    pet_frame++;
    drawFrameBuffer();
    last_pet_ms = now;
  }
  if (now - last_frame_ms >= FRAME_REFRESH_MS) {
    if (fetchFrame()) {
      pet_frame++;
      drawFrameBuffer();
      playPendingSoundCue();
    } else {
      Serial.println("Keeping last good frame");
    }
    last_frame_ms = now;
  }
  delay(10);
}
