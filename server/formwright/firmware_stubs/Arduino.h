// Formwright firmware check: the Arduino core's API surface for g++ -fsyntax-only, declarations only. It follows
// arduino-esp32 3.x (with the 2.x LEDC calls kept, the check warns about them) and arduino-pico; the board's pin names
// come from pins_arduino.h, selected by -DFW_BOARD_*. Signatures are the real ones, so misuse fails as it would.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdbool.h>
#include <math.h>
#include <inttypes.h>
#include <limits.h>
#include <ctype.h>
#include <time.h>
#ifdef __cplusplus
#include <algorithm>
#include <cmath>
#include <functional>
#endif

#define HIGH 0x1
#define LOW 0x0
#define INPUT 0x01
#define OUTPUT 0x03
#define PULLUP 0x04
#define INPUT_PULLUP 0x05
#define PULLDOWN 0x08
#define INPUT_PULLDOWN 0x09
#define OPEN_DRAIN 0x10
#define OUTPUT_OPEN_DRAIN 0x13
#define ANALOG 0xC0
#define DISABLED 0x00
#define RISING 0x01
#define FALLING 0x02
#define CHANGE 0x03
#define ONLOW 0x04
#define ONHIGH 0x05
#define ONLOW_WE 0x0C
#define ONHIGH_WE 0x0D
#define PI 3.1415926535897932384626433832795
#define HALF_PI 1.5707963267948966192313216916398
#define TWO_PI 6.283185307179586476925286766559
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define EULER 2.718281828459045235360287471352
#define SERIAL 0x0
#define DISPLAY 0x1
#define LSBFIRST 0
#define MSBFIRST 1
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#define NOT_A_PIN -1
#define NOT_AN_INTERRUPT -1
#define NOT_A_PORT -1
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))
#define radians(deg) ((deg) * DEG_TO_RAD)
#define degrees(rad) ((rad) * RAD_TO_DEG)
#define sq(x) ((x) * (x))
#define _min(a, b) ((a) < (b) ? (a) : (b))
#define _max(a, b) ((a) > (b) ? (a) : (b))
#define lowByte(w) ((uint8_t)((w) & 0xff))
#define highByte(w) ((uint8_t)((w) >> 8))
#define bitRead(value, bit) (((value) >> (bit)) & 0x01)
#define bitSet(value, bit) ((value) |= (1UL << (bit)))
#define bitClear(value, bit) ((value) &= ~(1UL << (bit)))
#define bitToggle(value, bit) ((value) ^= (1UL << (bit)))
#define bitWrite(value, bit, bitvalue) ((bitvalue) ? bitSet(value, bit) : bitClear(value, bit))
#define bit(b) (1UL << (b))
#define _BV(b) (1UL << (b))
#define BIT(nr) (1UL << (nr))
#define BIT64(nr) (1ULL << (nr))
#define digitalPinToInterrupt(p) (p)
#define digitalPinToGPIONumber(p) (p)
#define digitalPinIsValid(p) ((p) >= 0)
#define analogInputToDigitalPin(p) (p)
#define digitalPinHasPWM(p) ((p) >= 0)
#define clockCyclesPerMicrosecond() ((long int)240)
#define clockCyclesToMicroseconds(a) ((a) / clockCyclesPerMicrosecond())
#define microsecondsToClockCycles(a) ((a) * clockCyclesPerMicrosecond())
#define interrupts() ((void)0)
#define noInterrupts() ((void)0)
#define sei() ((void)0)
#define cli() ((void)0)

// program memory is ordinary memory on these chips
#define PROGMEM
#define PGM_P const char *
#define PGM_VOID_P const void *
#define PSTR(s) (s)
#define pgm_read_byte(addr) (*(const unsigned char *)(addr))
#define pgm_read_word(addr) (*(const unsigned short *)(addr))
#define pgm_read_dword(addr) (*(const unsigned long *)(addr))
#define pgm_read_float(addr) (*(const float *)(addr))
#define pgm_read_ptr(addr) (*(const void *const *)(addr))
#define pgm_read_byte_near(addr) pgm_read_byte(addr)
#define pgm_read_word_near(addr) pgm_read_word(addr)
#define pgm_read_dword_near(addr) pgm_read_dword(addr)
#define pgm_read_float_near(addr) pgm_read_float(addr)
#define pgm_read_byte_far(addr) pgm_read_byte(addr)
#define memcpy_P memcpy
#define memcmp_P memcmp
#define strcpy_P strcpy
#define strncpy_P strncpy
#define strcat_P strcat
#define strcmp_P strcmp
#define strncmp_P strncmp
#define strlen_P strlen
#define strstr_P strstr
#define sprintf_P sprintf
#define snprintf_P snprintf
#define vsnprintf_P vsnprintf
#define printf_P printf
#define IRAM_ATTR
#define DRAM_ATTR
#ifdef FW_SIM
// firmware_sim: the section the virtual board carries across a deep sleep
#define RTC_DATA_ATTR __attribute__((section("rtcmem")))
#define RTC_NOINIT_ATTR RTC_DATA_ATTR
#define RTC_FAST_ATTR RTC_DATA_ATTR
#define RTC_SLOW_ATTR RTC_DATA_ATTR
#else
#define RTC_DATA_ATTR
#define RTC_NOINIT_ATTR
#define RTC_FAST_ATTR
#define RTC_SLOW_ATTR
#endif
#define ARDUINO_ISR_ATTR
#define WORD_ALIGNED_ATTR
#define NOINLINE_ATTR __attribute__((noinline))

typedef bool boolean;
typedef uint8_t byte;
typedef unsigned int word;

#ifdef __cplusplus
extern "C" {
#endif
void setup(void);
void loop(void);
void yield(void);

void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t val);
int digitalRead(uint8_t pin);
void attachInterrupt(uint8_t pin, void (*)(void), int mode);
void attachInterruptArg(uint8_t pin, void (*)(void *), void *arg, int mode);
void detachInterrupt(uint8_t pin);

typedef enum { ADC_0db, ADC_2_5db, ADC_6db, ADC_11db, ADC_ATTENDB_MAX } adc_attenuation_t;
uint16_t analogRead(uint8_t pin);
uint32_t analogReadMilliVolts(uint8_t pin);
void analogReadResolution(uint8_t bits);
void analogSetAttenuation(adc_attenuation_t attenuation);
void analogSetPinAttenuation(uint8_t pin, adc_attenuation_t attenuation);
void analogSetClockDiv(uint8_t clockDiv);
void analogWrite(uint8_t pin, int value);

unsigned long micros(void);
unsigned long millis(void);
void delay(uint32_t ms);
void delayMicroseconds(uint32_t us);

uint8_t shiftIn(uint8_t dataPin, uint8_t clockPin, uint8_t bitOrder);
void shiftOut(uint8_t dataPin, uint8_t clockPin, uint8_t bitOrder, uint8_t val);

char *dtostrf(double val, signed char width, unsigned char prec, char *sout);
#ifndef _WIN32
char *itoa(int val, char *s, int radix);
char *ltoa(long val, char *s, int radix);
char *utoa(unsigned int val, char *s, int radix);
char *ultoa(unsigned long val, char *s, int radix);
#else
int setenv(const char *name, const char *value, int overwrite);
int unsetenv(const char *name);
#endif
#ifdef __cplusplus
}
#endif

#ifdef __cplusplus
// arduino-esp32 uses the standard library's, not macros
using std::abs;
using std::isinf;
using std::isnan;
using std::max;
using std::min;
using ::round;

void analogWriteFrequency(uint32_t freq);
void analogWriteFrequency(uint8_t pin, uint32_t freq);
void analogWriteResolution(uint8_t bits);
void analogWriteResolution(uint8_t pin, uint8_t bits);
void tone(uint8_t _pin, unsigned int frequency, unsigned long duration = 0);
void noTone(uint8_t _pin);
unsigned long pulseIn(uint8_t pin, uint8_t state, unsigned long timeout = 1000000L);
unsigned long pulseInLong(uint8_t pin, uint8_t state, unsigned long timeout = 1000000L);

long random(long howbig);
long random(long howsmall, long howbig);
void randomSeed(unsigned long seed);
long map(long x, long in_min, long in_max, long out_min, long out_max);
uint16_t makeWord(uint16_t w);
uint16_t makeWord(uint8_t h, uint8_t l);
#define word(...) makeWord(__VA_ARGS__)

inline bool isAlphaNumeric(int c) { return isalnum(c); }
inline bool isAlpha(int c) { return isalpha(c); }
inline bool isAscii(int c) { return (c & ~0x7f) == 0; }
inline bool isWhitespace(int c) { return c == ' ' || c == '\t'; }
inline bool isControl(int c) { return iscntrl(c); }
inline bool isDigit(int c) { return isdigit(c); }
inline bool isGraph(int c) { return isgraph(c); }
inline bool isLowerCase(int c) { return islower(c); }
inline bool isPrintable(int c) { return isprint(c); }
inline bool isPunct(int c) { return ispunct(c); }
inline bool isSpace(int c) { return isspace(c); }
inline bool isUpperCase(int c) { return isupper(c); }
inline bool isHexadecimalDigit(int c) { return isxdigit(c); }
inline int toAscii(int c) { return c & 0x7f; }
inline int toLowerCase(int c) { return tolower(c); }
inline int toUpperCase(int c) { return toupper(c); }

#include "WString.h"
#include "Printable.h"
#include "Print.h"
#include "Stream.h"
#include "IPAddress.h"
#include "Client.h"
#include "Server.h"
#include "Udp.h"
#include "HardwareSerial.h"
#endif

#if defined(ESP32)
// what esp32-hal.h brings with Arduino.h on the ESP32 family: sleep, timers, LEDC, touch, logs, FreeRTOS
#include "esp32-hal.h"
#endif

#include "pins_arduino.h"
