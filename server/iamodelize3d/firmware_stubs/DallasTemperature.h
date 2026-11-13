// DallasTemperature (DS18B20 on OneWire): sensors(&oneWire), requestTemperatures(), getTempCByIndex(0).
#pragma once
#include "OneWire.h"

#define DEVICE_DISCONNECTED_C -127
#define DEVICE_DISCONNECTED_F -196.6
#define DEVICE_DISCONNECTED_RAW -7040
typedef uint8_t DeviceAddress[8];

class DallasTemperature {
public:
  struct request_t {
    bool result;
    unsigned long timestamp;
    operator bool() { return result; }
  };
  DallasTemperature();
  DallasTemperature(OneWire *);
  DallasTemperature(OneWire *, uint8_t);
  void setOneWire(OneWire *);
  void setPullupPin(uint8_t);
  void begin(void);
  uint8_t getDeviceCount(void);
  uint8_t getDS18Count(void);
  bool validAddress(const uint8_t *);
  bool validFamily(const uint8_t *deviceAddress);
  bool getAddress(uint8_t *, uint8_t);
  bool isConnected(const uint8_t *);
  uint8_t getResolution();
  void setResolution(uint8_t);
  uint8_t getResolution(const uint8_t *);
  bool setResolution(const uint8_t *, uint8_t, bool skipGlobalBitResolutionCalculation = false);
  void setWaitForConversion(bool);
  bool getWaitForConversion(void);
  void setCheckForConversion(bool);
  bool getCheckForConversion(void);
  request_t requestTemperatures(void);
  request_t requestTemperaturesByAddress(const uint8_t *);
  request_t requestTemperaturesByIndex(uint8_t);
  int32_t getTemp(const uint8_t *);
  float getTempC(const uint8_t *);
  float getTempF(const uint8_t *);
  float getTempCByIndex(uint8_t);
  float getTempFByIndex(uint8_t);
  bool isParasitePowerMode(void);
  bool isConversionComplete(void);
  static uint16_t millisToWaitForConversion(uint8_t);
  uint16_t millisToWaitForConversion();
  static float toFahrenheit(float);
  static float toCelsius(float);
  static float rawToCelsius(int32_t);
  static float rawToFahrenheit(int32_t);
};
