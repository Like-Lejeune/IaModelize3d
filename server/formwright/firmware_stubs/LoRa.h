// LoRa (sandeepmistry): what is sent shows in the run's log; a packet arrives when the run says so.
#pragma once
#include "Arduino.h"
#include "SPI.h"
#include "Stream.h"
class LoRaClass : public Stream {
public:
  int begin(long frequency);
  void end() {}
  int beginPacket(int implicitHeader = 0);
  int endPacket(bool async = false);
  int parsePacket(int size = 0);
  int packetRssi() { return -70; }
  float packetSnr() { return 8.0f; }
  size_t write(uint8_t c) override;
  size_t write(const uint8_t *b, size_t n) override;
  using Print::write;
  int available() override;
  int read() override;
  int peek() override;
  void flush() override {}
  void onReceive(void (*cb)(int)) {}
  void onTxDone(void (*cb)()) {}
  void receive(int size = 0) {}
  void idle() {}
  void sleep();
  void setTxPower(int level, int outputPin = 0) {}
  void setFrequency(long f) {}
  void setSpreadingFactor(int sf) {}
  void setSignalBandwidth(long sbw) {}
  void setCodingRate4(int d) {}
  void setPreambleLength(long l) {}
  void setSyncWord(int sw) {}
  void enableCrc() {}
  void disableCrc() {}
  void setPins(int ss = 10, int reset = 9, int dio0 = 2) {}
  void setSPI(SPIClass &spi) {}
  void setSPIFrequency(uint32_t f) {}
};
extern LoRaClass LoRa;
