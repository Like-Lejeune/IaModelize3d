#pragma once
#include "Adafruit_ST77xx.h"
class Adafruit_ST7789 : public Adafruit_ST77xx {
public:
  Adafruit_ST7789(int8_t cs, int8_t dc, int8_t rst) : Adafruit_ST77xx(240, 320) {}
  Adafruit_ST7789(int8_t cs, int8_t dc, int8_t mosi, int8_t sclk, int8_t rst = -1) : Adafruit_ST77xx(240, 320) {}
  Adafruit_ST7789(SPIClass *spi, int8_t cs, int8_t dc, int8_t rst) : Adafruit_ST77xx(240, 320) {}
  void init(uint16_t width, uint16_t height, uint8_t mode = 0) { started(); }
};
