#pragma once
#include "WiFi.h"

class WiFiClientSecure : public WiFiClient {
public:
  WiFiClientSecure();
  ~WiFiClientSecure();
  void setInsecure();
  void setCACert(const char *rootCA);
  void setCertificate(const char *client_ca);
  void setPrivateKey(const char *private_key);
  void setPreSharedKey(const char *pskIdent, const char *psKey);
  bool verify(const char *fingerprint, const char *domain_name);
  void setHandshakeTimeout(unsigned long handshake_timeout);
  int lastError(char *buf, const size_t size);
};
typedef WiFiClientSecure NetworkClientSecure;
