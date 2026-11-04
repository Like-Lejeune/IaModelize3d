#pragma once
#include "Print.h"
class Server : public Print {
public:
  virtual void begin(uint16_t port = 0) = 0;
};
