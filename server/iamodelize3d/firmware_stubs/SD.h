#pragma once
#include "FS.h"
#include "SPI.h"
#define CARD_NONE 0
#define CARD_MMC 1
#define CARD_SD 2
#define CARD_SDHC 3
class SDFS : public fs::FS {
public:
  bool begin(uint8_t ssPin = 5, SPIClass &spi = SPI, uint32_t frequency = 4000000, const char *mountpoint = "/sd", uint8_t max_files = 5, bool format_if_empty = false) { return true; }
  void end() {}
  uint8_t cardType() { return CARD_SDHC; }
  uint64_t cardSize() { return 1ull << 32; }
};
static SDFS SD;
