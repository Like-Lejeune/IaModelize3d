#pragma once
#include <functional>
#include "Arduino.h"

class Ticker {
public:
  Ticker();
  ~Ticker();
  typedef void (*callback_with_arg_t)(void *);
  typedef std::function<void(void)> callback_function_t;
  void attach(float seconds, callback_function_t callback);
  void attach_ms(uint64_t milliseconds, callback_function_t callback);
  void attach_us(uint64_t micros, callback_function_t callback);
  template <typename TArg> void attach(float seconds, void (*callback)(TArg), TArg arg);
  template <typename TArg> void attach_ms(uint64_t milliseconds, void (*callback)(TArg), TArg arg);
  void once(float seconds, callback_function_t callback);
  void once_ms(uint64_t milliseconds, callback_function_t callback);
  void once_us(uint64_t micros, callback_function_t callback);
  template <typename TArg> void once(float seconds, void (*callback)(TArg), TArg arg);
  template <typename TArg> void once_ms(uint64_t milliseconds, void (*callback)(TArg), TArg arg);
  void detach();
  bool active();
};
