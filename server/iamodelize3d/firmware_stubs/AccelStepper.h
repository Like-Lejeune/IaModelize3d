// AccelStepper: real pulses on the STEP pin, at the speed the firmware sets; no acceleration ramp.
#pragma once
#include "Arduino.h"
class AccelStepper {
public:
  typedef enum { FUNCTION = 0, DRIVER = 1, FULL2WIRE = 2, FULL3WIRE = 3, FULL4WIRE = 4, HALF3WIRE = 6, HALF4WIRE = 8 } MotorInterfaceType;
  AccelStepper(uint8_t interface = AccelStepper::FULL4WIRE, uint8_t pin1 = 2, uint8_t pin2 = 3, uint8_t pin3 = 4, uint8_t pin4 = 5, bool enable = true);
  void moveTo(long a) { target = a; }
  void move(long r) { target = pos + r; }
  bool run();
  bool runSpeed();
  void runToPosition();
  void setMaxSpeed(float s) { maxs = s; }
  float maxSpeed() { return maxs; }
  void setAcceleration(float a) {}
  void setSpeed(float s) { spd = s; }
  float speed() { return spd; }
  long distanceToGo() { return target - pos; }
  long targetPosition() { return target; }
  long currentPosition() { return pos; }
  void setCurrentPosition(long p) { pos = target = p; }
  void stop() { target = pos; }
  bool isRunning() { return target != pos; }
  void setEnablePin(uint8_t p = 0xFF) {}
  void enableOutputs() {}
  void disableOutputs() {}
  void setMinPulseWidth(unsigned int) {}
  void setPinsInverted(bool = false, bool = false, bool = false) {}
private:
  bool step(float s);
  uint8_t stepPin, dirPin;
  long pos = 0, target = 0;
  float maxs = 1.0f, spd = 0.0f;
  unsigned long last = 0;
};
