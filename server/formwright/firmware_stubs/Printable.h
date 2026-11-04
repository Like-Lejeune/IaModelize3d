// Printable: what Print::print(const Printable &) takes (IPAddress, JSON variants).
#pragma once
#include <stddef.h>
class Print;
class Printable {
public:
  virtual ~Printable() {}
  virtual size_t printTo(Print &p) const = 0;
};
