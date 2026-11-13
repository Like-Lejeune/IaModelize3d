#pragma once
#include "FS.h"
class LittleFSFS : public fs::FS {
public:
  bool begin(bool formatOnFail = false, const char *basePath = "/littlefs", uint8_t maxOpenFiles = 10, const char *partitionLabel = nullptr) { return true; }
  void end() {}
  bool format() { return true; }
};
static LittleFSFS LittleFS;
