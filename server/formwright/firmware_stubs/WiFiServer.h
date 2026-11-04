#pragma once
#include "Arduino.h"
#include "WiFiClient.h"

class WiFiServer : public Server {
public:
  WiFiServer(uint16_t port = 80, uint8_t max_clients = 4);
  WiFiServer(const IPAddress &addr, uint16_t port = 80, uint8_t max_clients = 4);
  ~WiFiServer();
  WiFiClient available();
  WiFiClient accept();
  void begin(uint16_t port = 0);
  void begin(uint16_t port, int reuse_enable);
  void setNoDelay(bool nodelay);
  bool getNoDelay();
  bool hasClient();
  size_t write(const uint8_t *data, size_t len);
  size_t write(uint8_t data);
  using Print::write;
  void end();
  void close();
  void stop();
  operator bool();
};
typedef WiFiServer NetworkServer;
