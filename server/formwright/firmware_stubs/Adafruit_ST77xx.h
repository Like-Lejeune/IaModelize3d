#pragma once
#include "Adafruit_SPITFT.h"
#define ST77XX_BLACK 0x0000
#define ST77XX_WHITE 0xFFFF
#define ST77XX_RED 0xF800
#define ST77XX_GREEN 0x07E0
#define ST77XX_BLUE 0x001F
#define ST77XX_CYAN 0x07FF
#define ST77XX_MAGENTA 0xF81F
#define ST77XX_YELLOW 0xFFE0
#define ST77XX_ORANGE 0xFC00
#define ST7735_BLACK 0x0000
#define ST7735_WHITE 0xFFFF
#define ST7735_RED 0xF800
#define ST7735_GREEN 0x07E0
#define ST7735_BLUE 0x001F
#define ST7735_CYAN 0x07FF
#define ST7735_MAGENTA 0xF81F
#define ST7735_YELLOW 0xFFE0
#define ST7735_ORANGE 0xFC00

class Adafruit_ST77xx : public FwTft {
public:
  Adafruit_ST77xx(uint16_t w, uint16_t h) : FwTft(w, h) {}
};
