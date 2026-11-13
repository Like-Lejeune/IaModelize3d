// PZEM-004T v3 (mandulaj): the mains circuit's power as the run sets it, at a fixed 230 V.
#pragma once
#include "Arduino.h"
#include "HardwareSerial.h"
class PZEM004Tv30 {
public:
  PZEM004Tv30(HardwareSerial &port, uint8_t rx = 0, uint8_t tx = 0, uint8_t addr = 0xF8) {}
  float voltage() { return 230.0f; }
  float current() { return power() / 230.0f; }
  float power();
  float energy() { return 0.0f; }
  float frequency() { return 50.0f; }
  float pf() { return 1.0f; }
  bool resetEnergy() { return true; }
  bool setAddress(uint8_t) { return true; }
  uint8_t getAddress() { return 0xF8; }
};
