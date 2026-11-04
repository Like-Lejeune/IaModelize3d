#pragma once
#include "Adafruit_SPITFT.h"
#define TFT_BLACK 0x0000
#define TFT_WHITE 0xFFFF
#define TFT_RED 0xF800
#define TFT_GREEN 0x07E0
#define TFT_BLUE 0x001F
#define TFT_CYAN 0x07FF
#define TFT_MAGENTA 0xF81F
#define TFT_YELLOW 0xFFE0
#define TFT_ORANGE 0xFC00

#define TL_DATUM 0
#define TC_DATUM 1
#define TR_DATUM 2
#define ML_DATUM 3
#define MC_DATUM 4
#define MR_DATUM 5
#define BL_DATUM 6
#define BC_DATUM 7
#define BR_DATUM 8
class TFT_eSPI : public FwTft {
public:
  TFT_eSPI(int16_t w = 240, int16_t h = 320) : FwTft(w, h) {}
  void init(uint8_t tc = 0) { started(); }
  void begin(uint8_t tc = 0) { started(); }
  void setTextFont(uint8_t f) {}
  void setFreeFont(const GFXfont *f = nullptr) {}
  void setTextDatum(uint8_t d) {}
  void setTextPadding(uint16_t p) {}
  using Adafruit_GFX::setTextColor;
  int16_t drawString(const char *s, int32_t x, int32_t y, uint8_t font = 2) { setCursor(x, y); return print(s); }
  int16_t drawString(const String &s, int32_t x, int32_t y, uint8_t font = 2) { setCursor(x, y); return print(s); }
  int16_t drawCentreString(const char *s, int32_t x, int32_t y, uint8_t font = 2) { return drawString(s, x, y, font); }
  int16_t drawCentreString(const String &s, int32_t x, int32_t y, uint8_t font = 2) { return drawString(s, x, y, font); }
  int16_t drawRightString(const char *s, int32_t x, int32_t y, uint8_t font = 2) { return drawString(s, x, y, font); }
  int16_t drawNumber(long n, int32_t x, int32_t y, uint8_t font = 2) { setCursor(x, y); return print(n); }
  int16_t drawFloat(float v, uint8_t dp, int32_t x, int32_t y, uint8_t font = 2) { setCursor(x, y); return print(v, dp); }
  void pushImage(int32_t, int32_t, int32_t, int32_t, const uint16_t *) { fillRect(0, 0, 1, 1, 1); }
};
