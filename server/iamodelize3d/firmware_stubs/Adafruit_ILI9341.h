#pragma once
#include "Adafruit_SPITFT.h"
#define ILI9341_BLACK 0x0000
#define ILI9341_WHITE 0xFFFF
#define ILI9341_RED 0xF800
#define ILI9341_GREEN 0x07E0
#define ILI9341_BLUE 0x001F
#define ILI9341_CYAN 0x07FF
#define ILI9341_MAGENTA 0xF81F
#define ILI9341_YELLOW 0xFFE0
#define ILI9341_ORANGE 0xFC00

class Adafruit_ILI9341 : public FwTft {
public:
  Adafruit_ILI9341(int8_t cs, int8_t dc, int8_t mosi, int8_t sclk, int8_t rst = -1, int8_t miso = -1) : FwTft(240, 320) {}
  Adafruit_ILI9341(int8_t cs, int8_t dc, int8_t rst = -1) : FwTft(240, 320) {}
  Adafruit_ILI9341(SPIClass *spi, int8_t cs, int8_t dc, int8_t rst = -1) : FwTft(240, 320) {}
  void begin(uint32_t freq = 0) { started(); }
};
