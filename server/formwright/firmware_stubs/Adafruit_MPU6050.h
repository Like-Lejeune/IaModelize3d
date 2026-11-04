// Adafruit MPU6050: at rest, flat: 1 g down, no turning. Shaking it is not played.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "Adafruit_Sensor.h"
#include "fw_sim_api.h"

#define MPU6050_RANGE_2_G 0
#define MPU6050_RANGE_8_G 2
#define MPU6050_RANGE_500_DEG 1
#define MPU6050_BAND_21_HZ 4
class Adafruit_MPU6050 {
public:
  bool begin(uint8_t addr = 0x68, TwoWire *wire = &Wire, int32_t id = 0) { return true; }
  void setAccelerometerRange(int) {}
  void setGyroRange(int) {}
  void setFilterBandwidth(int) {}
  bool getEvent(sensors_event_t *a, sensors_event_t *g, sensors_event_t *t) {
    fw_wait(1000);
    if (a) { a->acceleration.x = 0; a->acceleration.y = 0; a->acceleration.z = 9.81f; }
    if (g) { g->gyro.x = 0; g->gyro.y = 0; g->gyro.z = 0; }
    if (t) t->temperature = fw_env_value(1);
    return true;
  }
};
