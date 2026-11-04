// ESP32-BLE-Keyboard (T-vK) BleKeyboard.h
#pragma once
#include "Arduino.h"
#include "Print.h"
#ifndef KEY_LEFT_CTRL
#define KEY_LEFT_CTRL 0x80
#define KEY_LEFT_SHIFT 0x81
#define KEY_LEFT_ALT 0x82
#define KEY_LEFT_GUI 0x83
#define KEY_RIGHT_CTRL 0x84
#define KEY_RIGHT_SHIFT 0x85
#define KEY_RIGHT_ALT 0x86
#define KEY_RIGHT_GUI 0x87
#define KEY_UP_ARROW 0xDA
#define KEY_DOWN_ARROW 0xD9
#define KEY_LEFT_ARROW 0xD8
#define KEY_RIGHT_ARROW 0xD7
#define KEY_BACKSPACE 0xB2
#define KEY_TAB 0xB3
#define KEY_RETURN 0xB0
#define KEY_ESC 0xB1
#define KEY_INSERT 0xD1
#define KEY_DELETE 0xD4
#define KEY_PAGE_UP 0xD3
#define KEY_PAGE_DOWN 0xD6
#define KEY_HOME 0xD2
#define KEY_END 0xD5
#define KEY_CAPS_LOCK 0xC1
#define KEY_F1 0xC2
#define KEY_F2 0xC3
#define KEY_F3 0xC4
#define KEY_F4 0xC5
#define KEY_F5 0xC6
#define KEY_F6 0xC7
#define KEY_F7 0xC8
#define KEY_F8 0xC9
#define KEY_F9 0xCA
#define KEY_F10 0xCB
#define KEY_F11 0xCC
#define KEY_F12 0xCD
#endif
typedef uint8_t MediaKeyReport[2];
const MediaKeyReport KEY_MEDIA_NEXT_TRACK = {1, 0};
const MediaKeyReport KEY_MEDIA_PREVIOUS_TRACK = {2, 0};
const MediaKeyReport KEY_MEDIA_STOP = {4, 0};
const MediaKeyReport KEY_MEDIA_PLAY_PAUSE = {8, 0};
const MediaKeyReport KEY_MEDIA_MUTE = {16, 0};
const MediaKeyReport KEY_MEDIA_VOLUME_UP = {32, 0};
const MediaKeyReport KEY_MEDIA_VOLUME_DOWN = {64, 0};
class BleKeyboard : public Print {
 public:
  BleKeyboard(const char * = "ESP32 Keyboard", const char * = "Espressif", uint8_t = 100) {}
  void begin() {}
  void end() {}
  bool isConnected() { return true; }
  void setBatteryLevel(uint8_t) {}
  void setName(const char *) {}
  void setDelay(uint32_t) {}
  size_t press(uint8_t k);
  size_t press(const MediaKeyReport k);
  size_t release(uint8_t) { return 1; }
  size_t release(const MediaKeyReport) { return 1; }
  void releaseAll() {}
  size_t write(uint8_t k) override;
  size_t write(const MediaKeyReport k);
  size_t write(const uint8_t *b, size_t n) override;
  using Print::write;
};
