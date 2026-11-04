// ESP: the chip object (restart, deep sleep, heap, chip id).
#pragma once
#include <stdint.h>
#include "WString.h"

class EspClass {
public:
  uint16_t getCpuFreqMHz();
  uint32_t getCycleCount();
  void restart();
  uint32_t getHeapSize();
  uint32_t getFreeHeap();
  uint32_t getMinFreeHeap();
  uint32_t getMaxAllocHeap();
  uint32_t getPsramSize();
  uint32_t getFreePsram();
  uint32_t getMinFreePsram();
  uint32_t getMaxAllocPsram();
  const char *getChipModel();
  uint8_t getChipRevision();
  uint8_t getChipCores();
  const char *getSdkVersion();
  const char *getCoreVersion();
  void deepSleep(uint64_t time_us);
  uint32_t getFlashChipSize();
  uint32_t getFlashChipSpeed();
  uint32_t getSketchSize();
  String getSketchMD5();
  uint32_t getFreeSketchSpace();
  uint64_t getEfuseMac();
};
extern EspClass ESP;
