// Print (arduino-esp32 cores/esp32/Print.h): every print/println overload the core has, printf with format checking.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <time.h>
#include "WString.h"
#include "Printable.h"

class Print {
public:
  Print() {}
  virtual ~Print() {}
  int getWriteError();
  void clearWriteError();
  virtual size_t write(uint8_t) = 0;
  size_t write(const char *str);
  virtual size_t write(const uint8_t *buffer, size_t size);
  size_t write(const char *buffer, size_t size);
  virtual int availableForWrite();
  size_t printf(const char *format, ...) __attribute__((format(printf, 2, 3)));
  size_t vprintf(const char *format, va_list arg);

  size_t print(const __FlashStringHelper *ifsh);
  size_t print(const String &);
  size_t print(const char[]);
  size_t print(char);
  size_t print(unsigned char, int = 10);
  size_t print(int, int = 10);
  size_t print(unsigned int, int = 10);
  size_t print(long, int = 10);
  size_t print(unsigned long, int = 10);
  size_t print(long long, int = 10);
  size_t print(unsigned long long, int = 10);
  size_t print(double, int = 2);
  size_t print(const Printable &);
  size_t print(struct tm *timeinfo, const char *format = NULL);

  size_t println(const __FlashStringHelper *ifsh);
  size_t println(const String &s);
  size_t println(const char[]);
  size_t println(char);
  size_t println(unsigned char, int = 10);
  size_t println(int, int = 10);
  size_t println(unsigned int, int = 10);
  size_t println(long, int = 10);
  size_t println(unsigned long, int = 10);
  size_t println(long long, int = 10);
  size_t println(unsigned long long, int = 10);
  size_t println(double, int = 2);
  size_t println(const Printable &);
  size_t println(struct tm *timeinfo, const char *format = NULL);
  size_t println(void);
  virtual void flush() {}
};
