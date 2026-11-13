// Adafruit INA219: the run sets the power (channel 5), at a fixed bus voltage.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "fw_sim_api.h"
class Adafruit_INA219 {
public:
  Adafruit_INA219(uint8_t addr = 0x40) {}
  bool begin(TwoWire *wire = &Wire) { return true; }
  void setCalibration_32V_2A() {}
  void setCalibration_32V_1A() {}
  void setCalibration_16V_400mA() {}
  float getBusVoltage_V() { return 12.0f; }
  float getShuntVoltage_mV() { return getCurrent_mA() * 0.1f; }
  float getCurrent_mA() { return fw_env_value(5) / 12.0f * 1000.0f; }
  float getPower_mW() { return fw_env_value(5) * 1000.0f; }
  void powerSave(bool) {}
  bool success() { return true; }
};
