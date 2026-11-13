// HX711 (bogde): the scale reads what the run puts on it, through the offset and scale the firmware sets.
#pragma once
#include "Arduino.h"
class HX711 {
public:
  void begin(byte dout, byte sck, byte gain = 128) {}
  bool is_ready() { return true; }
  void wait_ready(unsigned long ms = 0) {}
  bool wait_ready_timeout(unsigned long timeout = 1000, unsigned long ms = 1) { return true; }
  long read();
  long read_average(byte times = 10) { return read(); }
  double get_value(byte times = 1) { return read() - offset; }
  float get_units(byte times = 1) { return get_value(times) / scale; }
  void tare(byte times = 10) { offset = read(); }
  void set_scale(float s = 1.f) { scale = s; }
  float get_scale() { return scale; }
  void set_offset(long o = 0) { offset = o; }
  long get_offset() { return offset; }
  void set_gain(byte g = 128) {}
  void power_down() {}
  void power_up() {}
private:
  float scale = 1.f;
  long offset = 0;
};
