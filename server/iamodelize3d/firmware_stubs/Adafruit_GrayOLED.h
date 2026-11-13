#pragma once
#include "Adafruit_GFX.h"
#include "Wire.h"
#include "SPI.h"

#define MONOOLED_BLACK 0
#define MONOOLED_WHITE 1
#define MONOOLED_INVERSE 2
#define GRAYOLED_SETCONTRAST 0x81
#define GRAYOLED_NORMALDISPLAY 0xA6
#define GRAYOLED_INVERTDISPLAY 0xA7

class Adafruit_GrayOLED : public Adafruit_GFX {
public:
  Adafruit_GrayOLED(uint8_t bpp, uint16_t w, uint16_t h, TwoWire *twi = &Wire, int8_t rst_pin = -1, uint32_t preclk = 400000,
                    uint32_t postclk = 100000);
  Adafruit_GrayOLED(uint8_t bpp, uint16_t w, uint16_t h, int8_t mosi_pin, int8_t sclk_pin, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin);
  Adafruit_GrayOLED(uint8_t bpp, uint16_t w, uint16_t h, SPIClass *spi, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin,
                    uint32_t bitrate = 8000000UL);
  ~Adafruit_GrayOLED(void);
  virtual void display(void) = 0;
  void clearDisplay(void);
  void invertDisplay(bool i);
  void setContrast(uint8_t contrastlevel);
  void drawPixel(int16_t x, int16_t y, uint16_t color);
  bool getPixel(int16_t x, int16_t y);
  uint8_t *getBuffer(void);
  void oled_command(uint8_t cmd);
  bool oled_commandList(const uint8_t *c, uint8_t n);
};
