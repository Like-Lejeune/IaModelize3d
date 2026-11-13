// ESP32Servo (madhephaestus): Servo s; s.setPeriodHertz(50); s.attach(pin, 500, 2400); s.write(90).
#pragma once
#include "Arduino.h"

#define MIN_PULSE_WIDTH 500
#define MAX_PULSE_WIDTH 2500
#define DEFAULT_PULSE_WIDTH 1500
#define DEFAULT_TIMER_WIDTH 16

class ESP32PWM {
public:
  ESP32PWM();
  virtual ~ESP32PWM();
  static void allocateTimer(int timerNumber);
  void detachPin(int pin);
  void attachPin(uint8_t pin, double freq, uint8_t resolution_bits = 10);
  void write(uint32_t duty);
  void writeScaled(double duty);
  double writeTone(double freq);
  double setup(double freq, uint8_t resolution_bits = 10);
  bool attached();
  static bool hasPwm(int pin);
};

class Servo {
public:
  Servo();
  ~Servo();
  int attach(int pin);
  int attach(int pin, int min, int max);
  void detach();
  void write(int value);
  void writeMicroseconds(int value);
  void release();
  int read();
  int readMicroseconds();
  bool attached();
  void setTimerWidth(int value);
  int readTimerWidth();
  void setPeriodHertz(int hertz);
};
