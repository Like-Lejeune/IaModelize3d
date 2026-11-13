// Adafruit ADS1X15: an I2C ADC; an open input reads zero.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#define GAIN_TWOTHIRDS 0
#define GAIN_ONE 1
#define GAIN_TWO 2
#define GAIN_FOUR 3
#define GAIN_EIGHT 4
#define GAIN_SIXTEEN 5
class Adafruit_ADS1X15 {
public:
  bool begin(uint8_t addr = 0x48, TwoWire *wire = &Wire) { return true; }
  void setGain(int gain) {}
  void setDataRate(uint16_t rate) {}
  int16_t readADC_SingleEnded(uint8_t channel) { return 0; }
  int16_t readADC_Differential_0_1() { return 0; }
  float computeVolts(int16_t counts) { return counts * 0.0001875f; }
};
class Adafruit_ADS1115 : public Adafruit_ADS1X15 {};
class Adafruit_ADS1015 : public Adafruit_ADS1X15 {};
