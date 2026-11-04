// IPAddress (arduino-esp32 cores/esp32/IPAddress.h), Printable so print(WiFi.localIP()) works.
#pragma once
#include <stdint.h>
#include "Printable.h"
#include "WString.h"

class IPAddress : public Printable {
public:
  IPAddress();
  IPAddress(uint8_t first_octet, uint8_t second_octet, uint8_t third_octet, uint8_t fourth_octet);
  IPAddress(uint32_t address);
  IPAddress(const uint8_t *address);
  IPAddress(const char *address);
  IPAddress(const IPAddress &address);
  bool fromString(const char *address);
  bool fromString(const String &address);
  operator uint32_t() const;
  bool operator==(const IPAddress &addr) const;
  bool operator!=(const IPAddress &addr) const;
  bool operator==(const uint8_t *addr) const;
  uint8_t operator[](int index) const;
  uint8_t &operator[](int index);
  IPAddress &operator=(const uint8_t *address);
  IPAddress &operator=(uint32_t address);
  IPAddress &operator=(const IPAddress &address);
  virtual size_t printTo(Print &p) const;
  String toString() const;
};
extern IPAddress INADDR_NONE;
