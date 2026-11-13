// Arduino's Servo library has no ESP32 port (it stops with #error there); arduino-pico ships its own Servo.h.
#pragma once
#if defined(ESP32)
#error "Servo.h does not support the ESP32: include <ESP32Servo.h> (library ESP32Servo), same Servo class"
#else
#include "ESP32Servo.h"
#endif
