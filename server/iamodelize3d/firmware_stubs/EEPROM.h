// EEPROM (arduino-esp32 libraries/EEPROM): emulated in flash, so begin(size) and commit() are needed.
#pragma once
#include "Arduino.h"

class EEPROMClass {
public:
  EEPROMClass(uint32_t sector);
  EEPROMClass(const char *name);
  EEPROMClass(void);
  ~EEPROMClass(void);
  bool begin(size_t size);
  uint8_t read(int address);
  void write(int address, uint8_t val);
  uint16_t length();
  bool commit();
  void end();
  uint8_t *getDataPtr();
  const uint8_t *getConstDataPtr() const;
  uint8_t &operator[](int address);
  uint8_t readByte(int address);
  int8_t readChar(int address);
  int16_t readShort(int address);
  int32_t readInt(int address);
  int32_t readLong(int address);
  float readFloat(int address);
  double readDouble(int address);
  bool readBool(int address);
  size_t readString(int address, char *value, size_t maxLen);
  String readString(int address);
  size_t writeByte(int address, uint8_t value);
  size_t writeChar(int address, int8_t value);
  size_t writeShort(int address, int16_t value);
  size_t writeInt(int address, int32_t value);
  size_t writeLong(int address, int32_t value);
  size_t writeFloat(int address, float value);
  size_t writeDouble(int address, double value);
  size_t writeBool(int address, bool value);
  size_t writeString(int address, const char *value);
  size_t writeString(int address, String value);
  template <typename T> T &get(int address, T &t);
  template <typename T> const T &put(int address, const T &t);
};
#ifdef FW_SIM
// firmware_sim: the templates need bodies to link
template <typename T> T &EEPROMClass::get(int address, T &t) {
  memcpy(&t, getDataPtr() + address, sizeof(T));
  return t;
}
template <typename T> const T &EEPROMClass::put(int address, const T &t) {
  memcpy(getDataPtr() + address, &t, sizeof(T));
  return t;
}
#endif
extern EEPROMClass EEPROM;
