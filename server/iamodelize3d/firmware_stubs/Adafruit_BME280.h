// Adafruit BME280: begin(addr, wire) on I2C (0x77, or 0x76 with SDO low), temperature/pressure/humidity reads.
#pragma once
#include "Adafruit_Sensor.h"
#include "Wire.h"
#include "SPI.h"

#define BME280_ADDRESS (0x77)
#define BME280_ADDRESS_ALTERNATE (0x76)

class Adafruit_BME280 {
public:
  enum sensor_sampling { SAMPLING_NONE = 0b000, SAMPLING_X1 = 0b001, SAMPLING_X2 = 0b010, SAMPLING_X4 = 0b011, SAMPLING_X8 = 0b100, SAMPLING_X16 = 0b101 };
  enum sensor_mode { MODE_SLEEP = 0b00, MODE_FORCED = 0b01, MODE_NORMAL = 0b11 };
  enum sensor_filter { FILTER_OFF = 0b000, FILTER_X2 = 0b001, FILTER_X4 = 0b010, FILTER_X8 = 0b011, FILTER_X16 = 0b100 };
  enum standby_duration { STANDBY_MS_0_5 = 0b000, STANDBY_MS_10 = 0b110, STANDBY_MS_20 = 0b111, STANDBY_MS_62_5 = 0b001,
                          STANDBY_MS_125 = 0b010, STANDBY_MS_250 = 0b011, STANDBY_MS_500 = 0b100, STANDBY_MS_1000 = 0b101 };
  Adafruit_BME280();
  Adafruit_BME280(int8_t cspin, SPIClass *theSPI = &SPI);
  Adafruit_BME280(int8_t cspin, int8_t mosipin, int8_t misopin, int8_t sckpin);
  ~Adafruit_BME280(void);
  bool begin(uint8_t addr = BME280_ADDRESS, TwoWire *theWire = &Wire);
  bool init();
  void setSampling(sensor_mode mode = MODE_NORMAL, sensor_sampling tempSampling = SAMPLING_X16, sensor_sampling pressSampling = SAMPLING_X16,
                   sensor_sampling humSampling = SAMPLING_X16, sensor_filter filter = FILTER_OFF, standby_duration duration = STANDBY_MS_0_5);
  bool takeForcedMeasurement(void);
  float readTemperature(void);
  float readPressure(void);
  float readHumidity(void);
  float readAltitude(float seaLevel);
  float seaLevelForAltitude(float altitude, float pressure);
  uint32_t sensorID(void);
  float getTemperatureCompensation(void);
  void setTemperatureCompensation(float);
  Adafruit_Sensor *getTemperatureSensor(void);
  Adafruit_Sensor *getPressureSensor(void);
  Adafruit_Sensor *getHumiditySensor(void);
};
