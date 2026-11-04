// Adafruit Unified Sensor (Adafruit_Sensor.h): sensors_event_t and the Adafruit_Sensor interface.
#pragma once
#include "Arduino.h"

#define SENSORS_GRAVITY_EARTH (9.80665F)
#define SENSORS_GRAVITY_STANDARD (SENSORS_GRAVITY_EARTH)
#define SENSORS_PRESSURE_SEALEVELHPA (1013.25F)
#define SENSORS_DPS_TO_RADS (0.017453293F)
#define SENSORS_RADS_TO_DPS (57.29577793F)

typedef enum {
  SENSOR_TYPE_ACCELEROMETER = (1), SENSOR_TYPE_MAGNETIC_FIELD = (2), SENSOR_TYPE_ORIENTATION = (3), SENSOR_TYPE_GYROSCOPE = (4),
  SENSOR_TYPE_LIGHT = (5), SENSOR_TYPE_PRESSURE = (6), SENSOR_TYPE_PROXIMITY = (8), SENSOR_TYPE_GRAVITY = (9),
  SENSOR_TYPE_LINEAR_ACCELERATION = (10), SENSOR_TYPE_ROTATION_VECTOR = (11), SENSOR_TYPE_RELATIVE_HUMIDITY = (12),
  SENSOR_TYPE_AMBIENT_TEMPERATURE = (13), SENSOR_TYPE_OBJECT_TEMPERATURE = (14), SENSOR_TYPE_VOLTAGE = (15),
  SENSOR_TYPE_CURRENT = (16), SENSOR_TYPE_COLOR = (17), SENSOR_TYPE_TVOC = (18), SENSOR_TYPE_VOC_INDEX = (19),
  SENSOR_TYPE_NOX_INDEX = (20), SENSOR_TYPE_CO2 = (21), SENSOR_TYPE_ECO2 = (22), SENSOR_TYPE_PM10_STD = (23),
  SENSOR_TYPE_PM25_STD = (24), SENSOR_TYPE_PM100_STD = (25), SENSOR_TYPE_GAS_RESISTANCE = (31), SENSOR_TYPE_UNITLESS_PERCENT = (32),
  SENSOR_TYPE_ALTITUDE = (33)
} sensors_type_t;

typedef struct {
  union { float v[3]; struct { float x; float y; float z; }; struct { float roll; float pitch; float heading; }; };
  int8_t status;
  uint8_t reserved[3];
} sensors_vec_t;
typedef struct {
  union { float c[3]; struct { float r; float g; float b; }; };
  uint32_t rgba;
} sensors_color_t;
typedef struct {
  int32_t version;
  int32_t sensor_id;
  int32_t type;
  int32_t reserved0;
  int32_t timestamp;
  union {
    float data[4];
    sensors_vec_t acceleration;
    sensors_vec_t magnetic;
    sensors_vec_t orientation;
    sensors_vec_t gyro;
    float temperature;
    float distance;
    float light;
    float pressure;
    float relative_humidity;
    float current;
    float voltage;
    float tvoc;
    float voc_index;
    float nox_index;
    float CO2;
    float eCO2;
    float pm10_std;
    float pm25_std;
    float pm100_std;
    float gas_resistance;
    float unitless_percent;
    float altitude;
    sensors_color_t color;
  };
} sensors_event_t;
typedef struct {
  char name[12];
  int32_t version;
  int32_t sensor_id;
  int32_t type;
  float max_value;
  float min_value;
  float resolution;
  int32_t min_delay;
} sensor_t;

class Adafruit_Sensor {
public:
  Adafruit_Sensor() {}
  virtual ~Adafruit_Sensor() {}
  virtual void enableAutoRange(bool enabled) { (void)enabled; }
  virtual bool getEvent(sensors_event_t *) = 0;
  virtual void getSensor(sensor_t *) = 0;
  void printSensorDetails(void);
};
