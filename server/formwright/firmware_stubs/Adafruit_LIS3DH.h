// Adafruit LIS3DH: at rest, flat: 1 g down. Shaking it is not played.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "Adafruit_Sensor.h"
#include "fw_sim_api.h"

#define LIS3DH_RANGE_2_G 0
#define LIS3DH_RANGE_4_G 1
#define LIS3DH_RANGE_8_G 2
#define LIS3DH_DATARATE_50_HZ 4
class Adafruit_LIS3DH {
public:
  int16_t x = 0, y = 0, z = 16384;
  float x_g = 0, y_g = 0, z_g = 1;
  Adafruit_LIS3DH(TwoWire *wire = &Wire) {}
  Adafruit_LIS3DH(int8_t cs, SPIClass *spi = nullptr) {}
  bool begin(uint8_t addr = 0x18, uint8_t id = 0x33) { return true; }
  void setRange(int) {}
  void setDataRate(int) {}
  void setClick(uint8_t, uint8_t, uint8_t = 10, uint8_t = 20, uint8_t = 255) {}
  uint8_t getClick() { return 0; }
  void read() { fw_wait(1000); }
  bool getEvent(sensors_event_t *e) {
    if (e) { e->acceleration.x = 0; e->acceleration.y = 0; e->acceleration.z = 9.81f; }
    return true;
  }
};
