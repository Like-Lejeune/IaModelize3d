// Adafruit MCP4725: a 12-bit DAC over I2C; what it is set to shows in the run's log.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "fw_sim_api.h"
class Adafruit_MCP4725 {
public:
  bool begin(uint8_t addr = 0x62, TwoWire *wire = &Wire) { return fw_has_i2c(addr); }
  bool setVoltage(uint16_t output, bool writeEEPROM, uint32_t dac_frequency = 400000) {
    char b[24];
    snprintf(b, sizeof b, "DAC %u", (unsigned)output);
    fw_said(b);
    fw_wait(100);
    return true;
  }
};
