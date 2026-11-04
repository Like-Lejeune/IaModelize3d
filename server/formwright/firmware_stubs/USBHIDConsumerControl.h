// arduino-esp32 USBHIDConsumerControl.h: media keys
#pragma once
#if defined(CONFIG_IDF_TARGET_ESP32C3)
#error "the ESP32-C3 has no native USB device, so it cannot be a USB keyboard or mouse: use the XIAO ESP32-S3 (113991114), or BLE HID on the C3"
#endif
#include "Arduino.h"
#define CONSUMER_CONTROL_VOLUME_INCREMENT 0xE9
#define CONSUMER_CONTROL_VOLUME_DECREMENT 0xEA
#define CONSUMER_CONTROL_MUTE 0xE2
#define CONSUMER_CONTROL_PLAY_PAUSE 0xCD
#define CONSUMER_CONTROL_SCAN_NEXT 0xB5
#define CONSUMER_CONTROL_SCAN_PREVIOUS 0xB6
#define CONSUMER_CONTROL_STOP 0xB7
#define CONSUMER_CONTROL_BRIGHTNESS_INCREMENT 0x6F
#define CONSUMER_CONTROL_BRIGHTNESS_DECREMENT 0x70
class USBHIDConsumerControl {
 public:
  void begin() {}
  void end() {}
  size_t press(uint16_t k);
  size_t release() { return 1; }
};
