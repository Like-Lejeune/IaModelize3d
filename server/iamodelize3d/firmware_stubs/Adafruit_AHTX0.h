// Adafruit AHTX0: temperature and humidity as the run sets them (channels 1, 2).
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "Adafruit_Sensor.h"
#include "fw_sim_api.h"

class Adafruit_AHTX0 {
public:
  bool begin(TwoWire *wire = &Wire, int32_t sensor_id = 0, uint8_t addr = 0x38) { return true; }
  bool getEvent(sensors_event_t *humidity, sensors_event_t *temp) {
    fw_wait(80000);
    if (humidity) humidity->relative_humidity = fw_env_value(2);
    if (temp) temp->temperature = fw_env_value(1);
    return true;
  }
};
