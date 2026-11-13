#pragma once
#include "Arduino.h"

class WiFiUDP : public UDP {
public:
  WiFiUDP();
  ~WiFiUDP();
  uint8_t begin(IPAddress a, uint16_t p);
  uint8_t begin(uint16_t p);
  uint8_t beginMulticast(IPAddress a, uint16_t p);
  void stop();
  int beginMulticastPacket();
  int beginPacket();
  int beginPacket(IPAddress ip, uint16_t port);
  int beginPacket(const char *host, uint16_t port);
  int endPacket();
  size_t write(uint8_t);
  size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  int parsePacket();
  int available();
  int read();
  int read(unsigned char *buffer, size_t len);
  int read(char *buffer, size_t len);
  int peek();
  void flush();
  IPAddress remoteIP();
  uint16_t remotePort();
};
typedef WiFiUDP NetworkUDP;
