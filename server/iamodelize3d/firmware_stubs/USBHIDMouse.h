// arduino-esp32 USBHIDMouse.h
#pragma once
#if defined(CONFIG_IDF_TARGET_ESP32C3)
#error "the ESP32-C3 has no native USB device, so it cannot be a USB keyboard or mouse: use the XIAO ESP32-S3 (113991114), or BLE HID on the C3"
#endif
#include "Arduino.h"
#define MOUSE_LEFT 0x01
#define MOUSE_RIGHT 0x02
#define MOUSE_MIDDLE 0x04
class USBHIDMouse {
 public:
  void begin() {}
  void end() {}
  void click(uint8_t b = MOUSE_LEFT);
  void move(int8_t x, int8_t y, int8_t w = 0, int8_t p = 0);
  void press(uint8_t = MOUSE_LEFT) {}
  void release(uint8_t = MOUSE_LEFT) {}
  bool isPressed(uint8_t = MOUSE_LEFT) { return false; }
};
