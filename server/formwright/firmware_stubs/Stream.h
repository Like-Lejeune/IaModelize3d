// Stream (arduino-esp32 cores/esp32/Stream.h): reading, parsing and timeouts on top of Print.
#pragma once
#include "Print.h"

enum LookaheadMode { SKIP_ALL, SKIP_NONE, SKIP_WHITESPACE };
#define NO_IGNORE_CHAR '\x01'

class Stream : public Print {
public:
  virtual int available() = 0;
  virtual int read() = 0;
  virtual int peek() = 0;
  Stream() {}
  virtual ~Stream() {}
  void setTimeout(unsigned long timeout);
  unsigned long getTimeout(void);
  bool find(const char *target);
  bool find(uint8_t *target);
  bool find(const char *target, size_t length);
  bool find(const uint8_t *target, size_t length);
  bool find(char target);
  bool findUntil(const char *target, const char *terminator);
  bool findUntil(const char *target, size_t targetLen, const char *terminate, size_t termLen);
  long parseInt(LookaheadMode lookahead = SKIP_ALL, char ignore = NO_IGNORE_CHAR);
  float parseFloat(LookaheadMode lookahead = SKIP_ALL, char ignore = NO_IGNORE_CHAR);
  virtual size_t readBytes(char *buffer, size_t length);
  virtual size_t readBytes(uint8_t *buffer, size_t length);
  size_t readBytesUntil(char terminator, char *buffer, size_t length);
  size_t readBytesUntil(char terminator, uint8_t *buffer, size_t length);
  virtual String readString();
  String readStringUntil(char terminator);
};
