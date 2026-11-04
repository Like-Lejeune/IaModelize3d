// SPI (arduino-esp32 libraries/SPI): begin(sck, miso, mosi, ss) picks the pins, -1 the board's defaults.
#pragma once
#include "Arduino.h"

#define SPI_MODE0 0
#define SPI_MODE1 1
#define SPI_MODE2 2
#define SPI_MODE3 3
#define FSPI 0
#define HSPI 1
#define VSPI 2
#define SPI_CLOCK_DIV2 0x00101001
#define SPI_CLOCK_DIV4 0x00241001
#define SPI_CLOCK_DIV8 0x004c1001
#define SPI_CLOCK_DIV16 0x009c1001

class SPISettings {
public:
  SPISettings();
  SPISettings(uint32_t clock, uint8_t bitOrder, uint8_t dataMode);
};

class SPIClass {
public:
  SPIClass(uint8_t spi_bus = HSPI);
  ~SPIClass();
  bool begin(int8_t sck = -1, int8_t miso = -1, int8_t mosi = -1, int8_t ss = -1);
  void end();
  void setHwCs(bool use);
  void setSSInvert(bool invert);
  void setBitOrder(uint8_t bitOrder);
  void setDataMode(uint8_t dataMode);
  void setFrequency(uint32_t freq);
  void setClockDivider(uint32_t clockDiv);
  uint32_t getClockDivider();
  void beginTransaction(SPISettings settings);
  void endTransaction(void);
  void transfer(void *data, uint32_t size);
  uint8_t transfer(uint8_t data);
  uint16_t transfer16(uint16_t data);
  uint32_t transfer32(uint32_t data);
  void transferBytes(const uint8_t *data, uint8_t *out, uint32_t size);
  void transferBits(uint32_t data, uint32_t *out, uint8_t bits);
  void write(uint8_t data);
  void write16(uint16_t data);
  void write32(uint32_t data);
  void writeBytes(const uint8_t *data, uint32_t size);
  void writePixels(const void *data, uint32_t size);
  void writePattern(const uint8_t *data, uint8_t size, uint32_t repeat);
  int8_t pinSS();
};

extern SPIClass SPI;
