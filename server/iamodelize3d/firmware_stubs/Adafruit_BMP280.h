// Adafruit BMP280: temperature and pressure as the run sets them (channels 1, 3).
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "Adafruit_Sensor.h"
#include "fw_sim_api.h"

class Adafruit_BMP280 {
public:
  Adafruit_BMP280(TwoWire *wire = &Wire) {}
  bool begin(uint8_t addr = 0x77, uint8_t chipid = 0x58) { return true; }
  float readTemperature() { return fw_env_value(1); }
  float readPressure() { return fw_env_value(3); }
  float readAltitude(float sea = 1013.25f) { return 44330.0f * (1.0f - pow(readPressure() / 100.0f / sea, 0.1903f)); }
  void setSampling(int = 0, int = 0, int = 0, int = 0, int = 0) {}
};
