// BH1750 (claws/BH1750): ambient light in lux over I2C, 0x23 (ADDR low) or 0x5C.
#pragma once
#include "Arduino.h"
#include "Wire.h"

class BH1750 {
public:
  enum Mode {
    UNCONFIGURED = 0, CONTINUOUS_HIGH_RES_MODE = 0x10, CONTINUOUS_HIGH_RES_MODE_2 = 0x11, CONTINUOUS_LOW_RES_MODE = 0x13,
    ONE_TIME_HIGH_RES_MODE = 0x20, ONE_TIME_HIGH_RES_MODE_2 = 0x21, ONE_TIME_LOW_RES_MODE = 0x23
  };
  BH1750(byte addr = 0x23);
  bool begin(Mode mode = CONTINUOUS_HIGH_RES_MODE, byte addr = 0x23, TwoWire *i2c = nullptr);
  bool configure(Mode mode);
  bool setMTreg(byte MTreg);
  bool measurementReady(bool maxWait = false);
  float readLightLevel();
};
