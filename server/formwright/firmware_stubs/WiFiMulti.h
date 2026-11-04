#pragma once
#include "WiFi.h"

class WiFiMulti {
public:
  WiFiMulti();
  ~WiFiMulti();
  bool addAP(const char *ssid, const char *passphrase = NULL);
  uint8_t run(uint32_t connectTimeout = 5000, bool scanHidden = false);
};
