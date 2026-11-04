// TMCStepper: the driver's settings have no effect on the run; STEP and DIR are GPIOs and the virtual board sees them.
#pragma once
#include "Arduino.h"
#include "HardwareSerial.h"
class TMC2209Stepper {
public:
  TMC2209Stepper(Stream *s, float rs, uint8_t addr = 0) {}
  TMC2209Stepper(uint16_t rx, uint16_t tx, float rs, uint8_t addr = 0) {}
  void begin() {}
  void toff(uint8_t) {}
  void rms_current(uint16_t, float = 0.5f) {}
  void microsteps(uint16_t) {}
  void pwm_autoscale(bool) {}
  void en_spreadCycle(bool) {}
  void TCOOLTHRS(uint32_t) {}
  void SGTHRS(uint8_t) {}
  void blank_time(uint8_t) {}
  uint8_t test_connection() { return 0; }
  uint32_t SG_RESULT() { return 0; }
  void VACTUAL(int32_t) {}
};
