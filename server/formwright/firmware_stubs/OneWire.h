// OneWire (PaulStoffregen): OneWire bus(pin).
#pragma once
#include "Arduino.h"

class OneWire {
public:
  OneWire();
  OneWire(uint8_t pin);
  void begin(uint8_t pin);
  uint8_t reset(void);
  void select(const uint8_t rom[8]);
  void skip(void);
  void write(uint8_t v, uint8_t power = 0);
  void write_bytes(const uint8_t *buf, uint16_t count, bool power = 0);
  uint8_t read(void);
  void read_bytes(uint8_t *buf, uint16_t count);
  void write_bit(uint8_t v);
  uint8_t read_bit(void);
  void depower(void);
  void reset_search();
  void target_search(uint8_t family_code);
  bool search(uint8_t *newAddr, bool search_mode = true);
  static uint8_t crc8(const uint8_t *addr, uint8_t len);
  static bool check_crc16(const uint8_t *input, uint16_t len, const uint8_t *inverted_crc, uint16_t crc = 0);
  static uint16_t crc16(const uint8_t *input, uint16_t len, uint16_t crc = 0);
};
