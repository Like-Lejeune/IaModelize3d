// Wire (arduino-esp32 libraries/Wire): begin(sda, scl[, freq]) as a master, the overload set of requestFrom as is.
#pragma once
#include <functional>
#include "Arduino.h"

class TwoWire : public Stream {
public:
  TwoWire(uint8_t bus_num);
  ~TwoWire();
  bool setPins(int sda, int scl);
#if defined(ARDUINO_ARCH_RP2040)
  bool setSDA(int sda);
  bool setSCL(int scl);
#endif
  bool begin();
#if defined(ESP32)
  bool begin(uint8_t slaveAddr, int sda = -1, int scl = -1, uint32_t frequency = 0);
  bool begin(int sda, int scl, uint32_t frequency = 0);
#else
  bool begin(uint8_t slaveAddr);
#endif
  bool end();
  size_t setBufferSize(size_t bSize);
  void setTimeOut(uint16_t timeOutMillis);
  uint16_t getTimeOut();
  bool setClock(uint32_t);
  uint32_t getClock();
  void beginTransmission(uint16_t address);
  void beginTransmission(uint8_t address);
  void beginTransmission(int address);
  uint8_t endTransmission(bool sendStop);
  uint8_t endTransmission(void);
  size_t requestFrom(uint16_t address, size_t size, bool sendStop = true);
  uint8_t requestFrom(uint16_t address, uint8_t size, bool sendStop);
  uint8_t requestFrom(uint16_t address, uint8_t size, uint8_t sendStop);
  size_t requestFrom(uint8_t address, size_t len, bool stopBit);
  uint8_t requestFrom(uint16_t address, uint8_t size);
  uint8_t requestFrom(uint8_t address, uint8_t size, uint8_t sendStop);
  uint8_t requestFrom(uint8_t address, uint8_t size);
  uint8_t requestFrom(int address, int size, int sendStop);
  uint8_t requestFrom(int address, int size);
  size_t write(uint8_t);
  size_t write(const uint8_t *, size_t);
  int available(void);
  int read(void);
  int peek(void);
  void flush(void);
  size_t write(const char *s);
  size_t write(unsigned long n);
  size_t write(long n);
  size_t write(unsigned int n);
  size_t write(int n);
  void onReceive(void (*)(int));
  void onRequest(void (*)(void));
};

extern TwoWire Wire;
extern TwoWire Wire1;
