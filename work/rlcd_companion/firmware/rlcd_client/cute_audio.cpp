#include "cute_audio.h"

#include <Arduino.h>
#include <ESP_I2S.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

#define AUDIO_SAMPLE_RATE 24000
#define AUDIO_I2S_MCLK_PIN 16
#define AUDIO_I2S_BCLK_PIN 9
#define AUDIO_I2S_WS_PIN 45
#define AUDIO_I2S_DOUT_PIN 8
#define AUDIO_PA_PIN 46
#define ES8311_ADDR 0x18
#define ES8311_VOLUME_REG 0xB8
#define AUDIO_CUE_GAIN_PERCENT 70
#define AUDIO_TDM_SLOT_MASK (I2S_TDM_SLOT0 | I2S_TDM_SLOT1 | I2S_TDM_SLOT2 | I2S_TDM_SLOT3)

static I2SClass audio_i2s(I2S_NUM_0);
static bool audio_ready = false;
static bool audio_attempted = false;

static bool es8311WriteReg(uint8_t reg, uint8_t value)
{
  Wire.beginTransmission(ES8311_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

static bool es8311ReadReg(uint8_t reg, uint8_t *value)
{
  Wire.beginTransmission(ES8311_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom((uint8_t)ES8311_ADDR, (uint8_t)1) != 1) {
    return false;
  }
  *value = Wire.read();
  return true;
}

static bool initEs8311Codec()
{
  uint8_t regv = 0;
  bool ok = true;

  ok &= es8311WriteReg(0x44, 0x08);
  ok &= es8311WriteReg(0x44, 0x08);
  ok &= es8311WriteReg(0x01, 0x30);
  ok &= es8311WriteReg(0x02, 0x00);
  ok &= es8311WriteReg(0x03, 0x10);
  ok &= es8311WriteReg(0x16, 0x24);
  ok &= es8311WriteReg(0x04, 0x10);
  ok &= es8311WriteReg(0x05, 0x00);
  ok &= es8311WriteReg(0x0B, 0x00);
  ok &= es8311WriteReg(0x0C, 0x00);
  ok &= es8311WriteReg(0x10, 0x1F);
  ok &= es8311WriteReg(0x11, 0x7F);
  ok &= es8311WriteReg(0x00, 0x80);

  if (es8311ReadReg(0x00, &regv)) {
    ok &= es8311WriteReg(0x00, regv & 0xBF);
  }

  ok &= es8311WriteReg(0x01, 0x3F);

  if (es8311ReadReg(0x06, &regv)) {
    ok &= es8311WriteReg(0x06, regv & ~0x20);
  }

  ok &= es8311WriteReg(0x13, 0x10);
  ok &= es8311WriteReg(0x1B, 0x0A);
  ok &= es8311WriteReg(0x1C, 0x6A);
  ok &= es8311WriteReg(0x44, 0x58);

  ok &= es8311WriteReg(0x09, 0x0C);
  ok &= es8311WriteReg(0x0A, 0x0C);
  ok &= es8311WriteReg(0x02, 0x00);
  ok &= es8311WriteReg(0x05, 0x00);
  ok &= es8311WriteReg(0x03, 0x10);
  ok &= es8311WriteReg(0x04, 0x10);
  ok &= es8311WriteReg(0x07, 0x00);
  ok &= es8311WriteReg(0x08, 0xFF);
  ok &= es8311WriteReg(0x06, 0x03);

  ok &= es8311WriteReg(0x00, 0x80);
  ok &= es8311WriteReg(0x01, 0x3F);
  ok &= es8311WriteReg(0x09, 0x0C);
  ok &= es8311WriteReg(0x0A, 0x4C);
  ok &= es8311WriteReg(0x17, 0xBF);
  ok &= es8311WriteReg(0x0E, 0x02);
  ok &= es8311WriteReg(0x12, 0x00);
  ok &= es8311WriteReg(0x14, 0x1A);
  ok &= es8311WriteReg(0x0D, 0x01);
  ok &= es8311WriteReg(0x15, 0x40);
  ok &= es8311WriteReg(0x37, 0x08);
  ok &= es8311WriteReg(0x45, 0x00);
  ok &= es8311WriteReg(0x31, 0x00);
  ok &= es8311WriteReg(0x32, ES8311_VOLUME_REG);

  return ok;
}

bool setupCuteAudio()
{
  if (audio_ready) {
    return true;
  }
  if (audio_attempted) {
    return false;
  }
  audio_attempted = true;

  pinMode(AUDIO_PA_PIN, OUTPUT);
  digitalWrite(AUDIO_PA_PIN, LOW);

  audio_i2s.setPins(AUDIO_I2S_BCLK_PIN, AUDIO_I2S_WS_PIN, AUDIO_I2S_DOUT_PIN, -1, AUDIO_I2S_MCLK_PIN);
  if (!audio_i2s.begin(I2S_MODE_TDM, AUDIO_SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO, AUDIO_TDM_SLOT_MASK)) {
    Serial.printf("Audio I2S init failed: %d\n", audio_i2s.lastError());
    return false;
  }

  if (!initEs8311Codec()) {
    Serial.println("ES8311 init failed; sound cues disabled");
    return false;
  }

  digitalWrite(AUDIO_PA_PIN, HIGH);
  audio_ready = true;
  Serial.println("Cute audio ready");
  return true;
}

static void writeSilence(uint16_t ms)
{
  const int total_frames = (AUDIO_SAMPLE_RATE * ms) / 1000;
  int32_t samples[96 * 4] = {0};
  int written = 0;
  while (written < total_frames) {
    int frames = min(96, total_frames - written);
    audio_i2s.write((const uint8_t *)samples, frames * 4 * sizeof(int32_t));
    written += frames;
    yield();
  }
}

static int scaledAmplitude(int amplitude)
{
  return (amplitude * AUDIO_CUE_GAIN_PERCENT) / 100;
}

static void playTone(float freq_hz, uint16_t ms, int amplitude)
{
  const float two_pi = 6.28318530718f;
  const int total_frames = (AUDIO_SAMPLE_RATE * ms) / 1000;
  const int attack_frames = max(1, (AUDIO_SAMPLE_RATE * 10) / 1000);
  const int release_frames = max(1, (AUDIO_SAMPLE_RATE * 18) / 1000);
  int32_t samples[96 * 4];
  int frame = 0;

  while (frame < total_frames) {
    int frames = min(96, total_frames - frame);
    for (int i = 0; i < frames; ++i) {
      int pos = frame + i;
      float env = 1.0f;
      if (pos < attack_frames) {
        env = (float)pos / (float)attack_frames;
      } else if (pos > total_frames - release_frames) {
        env = (float)(total_frames - pos) / (float)release_frames;
      }
      float sample = sinf(two_pi * freq_hz * (float)pos / (float)AUDIO_SAMPLE_RATE) * env;
      int32_t value = (int32_t)(sample * scaledAmplitude(amplitude)) << 16;
      samples[i * 4] = value;
      samples[i * 4 + 1] = value;
      samples[i * 4 + 2] = 0;
      samples[i * 4 + 3] = 0;
    }
    audio_i2s.write((const uint8_t *)samples, frames * 4 * sizeof(int32_t));
    frame += frames;
    yield();
  }
}

void playCuteSoundCue(const char *cue)
{
  if (!cue || cue[0] == '\0' || strcmp(cue, "none") == 0) {
    return;
  }
  if (!audio_ready && !setupCuteAudio()) {
    return;
  }

  Serial.printf("Playing sound cue: %s\n", cue);
  if (strcmp(cue, "ai_done") == 0) {
    playTone(988.0f, 80, 6200);
    writeSilence(18);
    playTone(1318.5f, 90, 6600);
    writeSilence(18);
    playTone(1568.0f, 120, 6000);
  } else if (strcmp(cue, "meeting_now") == 0) {
    playTone(1046.5f, 85, 7600);
    writeSilence(22);
    playTone(1046.5f, 85, 7600);
    writeSilence(22);
    playTone(1396.9f, 130, 7200);
  } else if (strcmp(cue, "meeting") == 0) {
    playTone(880.0f, 85, 6000);
    writeSilence(24);
    playTone(1174.7f, 115, 6400);
  }
  writeSilence(40);
}
