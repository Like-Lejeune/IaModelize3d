#pragma once
#include "Arduino.h"
#include "Client.h"

class WiFiClient : public Client {
public:
  WiFiClient();
  WiFiClient(int fd);
  ~WiFiClient();
  int connect(IPAddress ip, uint16_t port);
  int connect(IPAddress ip, uint16_t port, int32_t timeout_ms);
  int connect(const char *host, uint16_t port);
  int connect(const char *host, uint16_t port, int32_t timeout_ms);
  size_t write(uint8_t data);
  size_t write(const uint8_t *buf, size_t size);
  size_t write_P(PGM_P buf, size_t size);
  size_t write(Stream &stream);
  using Print::write;
  int available();
  int read();
  int read(uint8_t *buf, size_t size);
  int peek();
  void flush();
  void stop();
  uint8_t connected();
  void setNoDelay(bool nodelay);
  operator bool();
  bool operator==(const WiFiClient &);
  IPAddress remoteIP() const;
  uint16_t remotePort() const;
  IPAddress localIP() const;
  uint16_t localPort() const;
  int setTimeout(uint32_t seconds);
};
typedef WiFiClient NetworkClient;
