// TinyGPSPlus (mikalhart): a fix when the run gives one, at a fixed place; the module's serial bytes are not played.
#pragma once
#include "Arduino.h"
class FwGpsLocation {
public:
  bool isValid() const;
  bool isUpdated() const { return isValid(); }
  uint32_t age() const { return isValid() ? 100 : 0xFFFFFFFF; }
  double lat() { return 43.238949; }
  double lng() { return 76.889709; }
};
class FwGpsDecimal {
public:
  FwGpsDecimal(uint32_t v = 0) : val(v) {}
  bool isValid() const;
  bool isUpdated() const { return isValid(); }
  uint32_t age() const { return 100; }
  uint32_t value() { return isValid() ? val : 0; }
  double hdop() { return 1.2; }
  double meters() { return 800.0; }
  double kmph() { return 0.0; }
  double deg() { return 0.0; }
private:
  uint32_t val;
};
class FwGpsDate {
public:
  bool isValid() const;
  uint16_t year() { return 2026; }
  uint8_t month() { return 11; }
  uint8_t day() { return 4; }
};
class FwGpsTime {
public:
  bool isValid() const;
  uint8_t hour();
  uint8_t minute();
  uint8_t second();
};
class TinyGPSPlus {
public:
  FwGpsLocation location;
  FwGpsDate date;
  FwGpsTime time;
  FwGpsDecimal altitude, speed, course, hdop{120}, satellites{7};
  bool encode(char c) { return false; }
  uint32_t charsProcessed() const { return 100; }
  uint32_t sentencesWithFix() const;
  uint32_t failedChecksum() const { return 0; }
  uint32_t passedChecksum() const { return 100; }
  static double distanceBetween(double a, double b, double c, double d);
};
