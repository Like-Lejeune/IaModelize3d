// RTClib (Adafruit): the clock runs with the virtual time from a fixed date, and keeps it through a sleep.
#pragma once
#include "Arduino.h"
#include "Wire.h"
class TimeSpan {
public:
  TimeSpan(int32_t s = 0) : t(s) {}
  TimeSpan(int16_t d, int8_t h, int8_t m, int8_t s) : t(d * 86400L + h * 3600L + m * 60 + s) {}
  int32_t totalseconds() const { return t; }
  int16_t days() const { return t / 86400L; }
  int8_t hours() const { return t / 3600 % 24; }
  int8_t minutes() const { return t / 60 % 60; }
  int8_t seconds() const { return t % 60; }
  int32_t t;
};
class DateTime {
public:
  DateTime(uint32_t t = 0);
  DateTime(uint16_t year, uint8_t month, uint8_t day, uint8_t hour = 0, uint8_t min = 0, uint8_t sec = 0);
  DateTime(const char *date, const char *time);
  DateTime(const __FlashStringHelper *date, const __FlashStringHelper *time);
  uint16_t year() const { return y; }
  uint8_t month() const { return m; }
  uint8_t day() const { return d; }
  uint8_t hour() const { return hh; }
  uint8_t minute() const { return mm; }
  uint8_t second() const { return ss; }
  uint8_t dayOfTheWeek() const;
  uint32_t unixtime() const;
  uint32_t secondstime() const { return unixtime() - 946684800UL; }
  bool isValid() const { return true; }
  DateTime operator+(const TimeSpan &s) const { return DateTime(unixtime() + s.totalseconds()); }
  DateTime operator-(const TimeSpan &s) const { return DateTime(unixtime() - s.totalseconds()); }
  TimeSpan operator-(const DateTime &o) const { return TimeSpan((int32_t)(unixtime() - o.unixtime())); }
  bool operator<(const DateTime &o) const { return unixtime() < o.unixtime(); }
  bool operator>(const DateTime &o) const { return unixtime() > o.unixtime(); }
  bool operator==(const DateTime &o) const { return unixtime() == o.unixtime(); }
private:
  uint16_t y; uint8_t m, d, hh, mm, ss;
};
class FwRtc {
public:
  bool begin(TwoWire *wire = &Wire) { return true; }
  void adjust(const DateTime &dt);
  DateTime now();
  bool lostPower() { return false; }
  bool isrunning() { return true; }
  bool initialized() { return true; }
  void start() {}
  float getTemperature() { return 25.0f; }
  void disable32K() {}
  bool setAlarm1(const DateTime &, int) { return true; }
  bool alarmFired(uint8_t) { return false; }
  void clearAlarm(uint8_t) {}
  void disableAlarm(uint8_t) {}
  void writeSqwPinMode(int) {}
};
#define DS3231_A1_Date 0
#define DS3231_A1_Hour 1
#define DS3231_OFF 0
class RTC_DS3231 : public FwRtc {};
class RTC_DS1307 : public FwRtc {};
class RTC_PCF8523 : public FwRtc {};
class RTC_PCF8563 : public FwRtc {};
