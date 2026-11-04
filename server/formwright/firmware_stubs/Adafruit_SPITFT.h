// The Adafruit SPI colour TFTs: GFX text and where it lands, each change seen at once as on the panel.
#pragma once
#include "Adafruit_GFX.h"
#include "SPI.h"
class FwTft : public Adafruit_GFX {
public:
  FwTft(int16_t w, int16_t h);
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  size_t write(uint8_t c) override;
  using Print::write;
  void invertDisplay(bool i);
  void enableDisplay(bool enable);
  uint16_t color565(uint8_t r, uint8_t g, uint8_t b) { return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3); }
protected:
  void started();
};
