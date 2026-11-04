#pragma once
#include "FS.h"
class SPIFFSFS : public fs::FS {
public:
  bool begin(bool formatOnFail = false, const char *basePath = "/spiffs", uint8_t maxOpenFiles = 10, const char *partitionLabel = nullptr) { return true; }
  void end() {}
  bool format() { return true; }
};
static SPIFFSFS SPIFFS;
