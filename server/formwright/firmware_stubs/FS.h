// Files: a card or flash the simulator keeps in memory for the run. What a board wrote can be read back; the content is what was written.
#pragma once
#include "Arduino.h"
#include "Stream.h"
#define FILE_READ "r"
#define FILE_WRITE "w"
#define FILE_APPEND "a"
namespace fs {
class File : public Stream {
public:
  File(int handle = -1) : h(handle) {}
  size_t write(uint8_t c) override;
  size_t write(const uint8_t *buf, size_t n) override;
  using Print::write;
  int available() override;
  int read() override;
  int peek() override;
  size_t read(uint8_t *buf, size_t n);
  void flush() override {}
  bool seek(uint32_t pos);
  size_t position();
  size_t size();
  void close();
  const char *name();
  const char *path();
  bool isDirectory() { return false; }
  File openNextFile(const char *mode = FILE_READ) { return File(); }
  void rewindDirectory() {}
  operator bool() const { return h >= 0; }
private:
  int h;
};
class FS {
public:
  File open(const char *path, const char *mode = FILE_READ, bool create = false);
  File open(const String &path, const char *mode = FILE_READ, bool create = false) { return open(path.c_str(), mode, create); }
  bool exists(const char *path);
  bool exists(const String &path) { return exists(path.c_str()); }
  bool remove(const char *path);
  bool remove(const String &path) { return remove(path.c_str()); }
  bool rename(const char *from, const char *to);
  bool mkdir(const char *path) { return true; }
  bool rmdir(const char *path) { return true; }
  uint64_t totalBytes() { return 1ull << 30; }
  uint64_t usedBytes();
};
}
using fs::File;
using fs::FS;
