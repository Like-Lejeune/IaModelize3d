// Adafruit NeoPixel (WS2812/SK6812): Adafruit_NeoPixel strip(count, pin, NEO_GRB + NEO_KHZ800).
#pragma once
#include "Arduino.h"

#define NEO_RGB ((0 << 6) | (0 << 4) | (1 << 2) | (2))
#define NEO_RBG ((0 << 6) | (0 << 4) | (2 << 2) | (1))
#define NEO_GRB ((1 << 6) | (1 << 4) | (0 << 2) | (2))
#define NEO_GBR ((2 << 6) | (2 << 4) | (0 << 2) | (1))
#define NEO_BRG ((1 << 6) | (1 << 4) | (2 << 2) | (0))
#define NEO_BGR ((2 << 6) | (2 << 4) | (1 << 2) | (0))
#define NEO_WRGB ((0 << 6) | (1 << 4) | (2 << 2) | (3))
#define NEO_RGBW ((3 << 6) | (0 << 4) | (1 << 2) | (2))
#define NEO_GRBW ((3 << 6) | (1 << 4) | (0 << 2) | (2))
#define NEO_KHZ800 0x0000
#define NEO_KHZ400 0x0100
typedef uint16_t neoPixelType;

class Adafruit_NeoPixel {
public:
  Adafruit_NeoPixel(uint16_t n, int16_t pin = 6, neoPixelType type = NEO_GRB + NEO_KHZ800);
  Adafruit_NeoPixel(void);
  ~Adafruit_NeoPixel();
  bool begin(void);
  void show(void);
  void setPin(int16_t p);
  void setPixelColor(uint16_t n, uint8_t r, uint8_t g, uint8_t b);
  void setPixelColor(uint16_t n, uint8_t r, uint8_t g, uint8_t b, uint8_t w);
  void setPixelColor(uint16_t n, uint32_t c);
  void fill(uint32_t c = 0, uint16_t first = 0, uint16_t count = 0);
  void setBrightness(uint8_t);
  void clear(void);
  void updateLength(uint16_t n);
  void updateType(neoPixelType t);
  bool canShow(void);
  uint8_t *getPixels(void) const;
  uint8_t getBrightness(void) const;
  int16_t getPin(void) const;
  uint16_t numPixels(void) const;
  uint32_t getPixelColor(uint16_t n) const;
  static uint8_t sine8(uint8_t x);
  static uint8_t gamma8(uint8_t x);
  static uint32_t Color(uint8_t r, uint8_t g, uint8_t b);
  static uint32_t Color(uint8_t r, uint8_t g, uint8_t b, uint8_t w);
  static uint32_t ColorHSV(uint16_t hue, uint8_t sat = 255, uint8_t val = 255);
  static uint32_t gamma32(uint32_t x);
  void rainbow(uint16_t first_hue = 0, int8_t reps = 1, uint8_t saturation = 255, uint8_t brightness = 255, bool gammify = true);
  static neoPixelType str2order(const char *v);
};
