#pragma once
#include "Adafruit_ST77xx.h"
#define INITR_BLACKTAB 0
#define INITR_GREENTAB 1
#define INITR_REDTAB 2
#define INITR_144GREENTAB 3
#define INITR_MINI160x80 4
class Adafruit_ST7735 : public Adafruit_ST77xx {
public:
  Adafruit_ST7735(int8_t cs, int8_t dc, int8_t rst) : Adafruit_ST77xx(128, 160) {}
  Adafruit_ST7735(int8_t cs, int8_t dc, int8_t mosi, int8_t sclk, int8_t rst) : Adafruit_ST77xx(128, 160) {}
  Adafruit_ST7735(SPIClass *spi, int8_t cs, int8_t dc, int8_t rst) : Adafruit_ST77xx(128, 160) {}
  void initR(uint8_t options = INITR_BLACKTAB) { started(); }
};
