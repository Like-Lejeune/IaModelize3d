// Adafruit SH110X (SH1106G 128x64, SH1107): begin(addr, reset), GFX text as Adafruit_GFX (ASCII font).
#pragma once
#include "Adafruit_GrayOLED.h"

#define SH110X_BLACK 0
#define SH110X_WHITE 1
#define SH110X_INVERSE 2
#define SH110X_MEMORYMODE 0x20
#define SH110X_SETCONTRAST 0x81
#define SH110X_DISPLAYOFF 0xAE
#define SH110X_DISPLAYON 0xAF

class Adafruit_SH110X : public Adafruit_GrayOLED {
public:
  Adafruit_SH110X(uint16_t w, uint16_t h, TwoWire *twi = &Wire, int8_t rst_pin = -1, uint32_t preclk = 400000, uint32_t postclk = 100000);
  Adafruit_SH110X(uint16_t w, uint16_t h, int8_t mosi_pin, int8_t sclk_pin, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin);
  Adafruit_SH110X(uint16_t w, uint16_t h, SPIClass *spi, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin, uint32_t bitrate = 8000000UL);
  ~Adafruit_SH110X(void);
  bool begin(uint8_t i2caddr = 0x3C, bool reset = true);
  void display(void);
};

class Adafruit_SH1106G : public Adafruit_SH110X {
public:
  Adafruit_SH1106G(uint16_t w, uint16_t h, TwoWire *twi = &Wire, int8_t rst_pin = -1, uint32_t preclk = 400000, uint32_t postclk = 100000);
  Adafruit_SH1106G(uint16_t w, uint16_t h, int8_t mosi_pin, int8_t sclk_pin, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin);
  Adafruit_SH1106G(uint16_t w, uint16_t h, SPIClass *spi, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin, uint32_t bitrate = 8000000UL);
  ~Adafruit_SH1106G(void);
  bool begin(uint8_t i2caddr = 0x3C, bool reset = true);
};

class Adafruit_SH1107 : public Adafruit_SH110X {
public:
  Adafruit_SH1107(uint16_t w, uint16_t h, TwoWire *twi = &Wire, int8_t rst_pin = -1, uint32_t preclk = 400000, uint32_t postclk = 100000);
  Adafruit_SH1107(uint16_t w, uint16_t h, int8_t mosi_pin, int8_t sclk_pin, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin);
  Adafruit_SH1107(uint16_t w, uint16_t h, SPIClass *spi, int8_t dc_pin, int8_t rst_pin, int8_t cs_pin, uint32_t bitrate = 8000000UL);
  ~Adafruit_SH1107(void);
  bool begin(uint8_t i2caddr = 0x3C, bool reset = true);
};
