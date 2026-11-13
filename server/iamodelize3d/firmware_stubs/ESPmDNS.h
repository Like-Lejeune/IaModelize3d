#pragma once
#include "WiFi.h"

class MDNSResponder {
public:
  MDNSResponder();
  ~MDNSResponder();
  bool begin(const char *hostName);
  void end();
  void setInstanceName(String name);
  void setInstanceName(const char *name);
  bool addService(const char *service, const char *proto, uint16_t port);
  bool addService(String service, String proto, uint16_t port);
  bool addServiceTxt(const char *name, const char *proto, const char *key, const char *value);
  void enableArduino(uint16_t port = 3232, bool auth = false);
  void disableArduino();
  void enableWorkstation(int interface = 0);
  IPAddress queryHost(char *host, uint32_t timeout = 2000);
  int queryService(char *service, char *proto);
  int queryService(const String &service, const String &proto);
};
extern MDNSResponder MDNS;
