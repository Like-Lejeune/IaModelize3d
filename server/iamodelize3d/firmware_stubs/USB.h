// arduino-esp32 USB.h: the native USB device (ESP32-S3)
#pragma once
#if defined(CONFIG_IDF_TARGET_ESP32C3)
#error "the ESP32-C3 has no native USB device, so it cannot be a USB keyboard or mouse: use the XIAO ESP32-S3 (113991114), or BLE HID on the C3"
#endif
#include "Arduino.h"
class ESPUSB {
 public:
  bool begin() { return true; }
  operator bool() const { return true; }
  void VID(uint16_t) {}
  void PID(uint16_t) {}
  void productName(const char*) {}
  void manufacturerName(const char*) {}
  void serialNumber(const char*) {}
};
static ESPUSB USB;
