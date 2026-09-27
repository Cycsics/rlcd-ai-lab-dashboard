#pragma once
#include <stdint.h>

// Pure state machine: SOF detects a PC USB host, not VBUS/charging.
// Unsigned subtraction keeps intervals valid across millis() wraparound.
class UsbStandbyPolicy {
public:
  enum Action { None, EnterStandby, LeaveStandby };
  bool sleeping = false;
  bool connected = true;
  Action update(uint32_t now, bool usb, bool pressed, bool enabled, uint32_t seconds) {
    if (!initialized) { initialized=true; started=now; changed=now; raw=usb; }
    if (usb != raw) { raw=usb; changed=now; }
    if (raw != connected && uint32_t(now-changed) >= (raw ? 250u : 3000u)) {
      connected=raw;
      if (!connected) { disconnected=now; counting=true; }
    }
    if (connected) { counting=false; manual_hold=false; }
    if (sleeping && (connected || pressed || !enabled)) {
      sleeping=false;
      if (pressed && !connected) manual_hold=true;
      return LeaveStandby;
    }
    if (!sleeping && enabled && counting && !manual_hold &&
        uint32_t(now-started)>=10000u && uint32_t(now-disconnected)>=seconds*1000u) {
      sleeping=true;
      return EnterStandby;
    }
    return None;
  }
private:
  bool initialized=false, raw=true, counting=false, manual_hold=false;
  uint32_t started=0, changed=0, disconnected=0;
};
