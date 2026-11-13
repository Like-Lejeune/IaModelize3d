// DHT sensor library (Adafruit): DHT dht(pin, DHT22).
#pragma once
#include "Arduino.h"

#define DHT11 11
#define DHT12 12
#define DHT21 21
#define DHT22 22
#define AM2301 21
#define AM2302 22

class DHT {
public:
  DHT(uint8_t pin, uint8_t type, uint8_t count = 6);
  void begin(uint8_t usec = 55);
  float readTemperature(bool S = false, bool force = false);
  float convertCtoF(float);
  float convertFtoC(float);
  float computeHeatIndex(bool isFahrenheit = true);
  float computeHeatIndex(float temperature, float percentHumidity, bool isFahrenheit = true);
  float readHumidity(bool force = false);
  bool read(bool force = false);
};
