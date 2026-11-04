// arduino-esp32 3.x esp32-hal.h: what every sketch gets with Arduino.h on the ESP32 family (the real one includes
// esp_system.h, esp_sleep.h, FreeRTOS, the log macros and the esp32-hal-*.h drivers). Per chip as the SoC has it
// (soc_caps.h): touch only on the S3 (and the original ESP32), DAC on neither the C3 nor the S3. Calls removed in 3.0
// (ledcSetup/ledcAttachPin, timerAlarmWrite ...) are declared too: the check warns about them (core_api) rather than
// failing a sketch written for 2.x.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <time.h>

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_INVALID_SIZE 0x104
#define ESP_ERR_NOT_FOUND 0x105
#define ESP_ERR_NOT_SUPPORTED 0x106
#define ESP_ERR_TIMEOUT 0x107
#define ESP_ERROR_CHECK(x) ((void)(x))
#define ESP_ERROR_CHECK_WITHOUT_ABORT(x) (x)
#define ESP_ARDUINO_VERSION_MAJOR 3
#define ESP_ARDUINO_VERSION_MINOR 0
#define ESP_ARDUINO_VERSION_PATCH 7
#define ESP_ARDUINO_VERSION_VAL(major, minor, patch) ((major << 16) | (minor << 8) | (patch))
#define ESP_ARDUINO_VERSION ESP_ARDUINO_VERSION_VAL(ESP_ARDUINO_VERSION_MAJOR, ESP_ARDUINO_VERSION_MINOR, ESP_ARDUINO_VERSION_PATCH)
#include "soc/soc_caps.h"

#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_sleep.h"
#include "esp_log.h"

#ifdef __cplusplus
extern "C" {
#endif
typedef enum { NOTE_C, NOTE_Cs, NOTE_D, NOTE_Eb, NOTE_E, NOTE_F, NOTE_Fs, NOTE_G, NOTE_Gs, NOTE_A, NOTE_Bb, NOTE_B, NOTE_MAX } note_t;
// LEDC, 3.x: by pin
bool ledcAttach(uint8_t pin, uint32_t freq, uint8_t resolution);
bool ledcAttachChannel(uint8_t pin, uint32_t freq, uint8_t resolution, uint8_t channel);
bool ledcWrite(uint8_t pin, uint32_t duty);
bool ledcWriteChannel(uint8_t channel, uint32_t duty);
uint32_t ledcWriteTone(uint8_t pin, uint32_t freq);
uint32_t ledcWriteNote(uint8_t pin, note_t note, uint8_t octave);
uint32_t ledcRead(uint8_t pin);
uint32_t ledcReadFreq(uint8_t pin);
bool ledcDetach(uint8_t pin);
uint32_t ledcChangeFrequency(uint8_t pin, uint32_t freq, uint8_t resolution);
bool ledcOutputInvert(uint8_t pin, bool out_invert);
bool ledcFade(uint8_t pin, uint32_t start_duty, uint32_t target_duty, int max_fade_time_ms);
bool ledcFadeWithInterrupt(uint8_t pin, uint32_t start_duty, uint32_t target_duty, int max_fade_time_ms, void (*userFunc)(void));
bool ledcFadeWithInterruptArg(uint8_t pin, uint32_t start_duty, uint32_t target_duty, int max_fade_time_ms, void (*userFunc)(void *), void *arg);
// LEDC, 2.x: by channel (removed in 3.0)
uint32_t ledcSetup(uint8_t channel, uint32_t freq, uint8_t resolution_bits);
void ledcAttachPin(uint8_t pin, uint8_t chan);
void ledcDetachPin(uint8_t pin);

// capacitive touch (the S3's GPIO1-14; the C3 has none)
#if defined(SOC_TOUCH_SENSOR_SUPPORTED)
typedef uint32_t touch_value_t;
touch_value_t touchRead(uint8_t pin);
void touchAttachInterrupt(uint8_t pin, void (*userFunc)(void), touch_value_t threshold);
void touchAttachInterruptArg(uint8_t pin, void (*userFunc)(void *), void *arg, touch_value_t threshold);
void touchDetachInterrupt(uint8_t pin);
bool touchInterruptGetLastStatus(uint8_t pin);
void touchSleepWakeUpEnable(uint8_t pin, touch_value_t threshold);
void touchSetCycles(uint16_t measure, uint16_t sleep);
#endif

// the addressable RGB LED helper (rgbLedWrite in 3.x, neopixelWrite before)
void rgbLedWrite(uint8_t pin, uint8_t red_val, uint8_t green_val, uint8_t blue_val);
void neopixelWrite(uint8_t pin, uint8_t red_val, uint8_t green_val, uint8_t blue_val);

float temperatureRead(void);
bool psramInit(void);
bool psramFound(void);
void *ps_malloc(size_t size);
void *ps_calloc(size_t n, size_t size);
void *ps_realloc(void *ptr, size_t size);
bool btStart(void);
bool btStop(void);
bool btStarted(void);
uint32_t getXtalFrequencyMhz(void);
uint32_t getApbFrequency(void);
#ifdef __cplusplus
}
// hardware timers, 3.x (frequency in Hz) and 2.x (number, divider, count up; removed in 3.0)
typedef struct hw_timer_s hw_timer_t;
hw_timer_t *timerBegin(uint32_t frequency);
hw_timer_t *timerBegin(uint8_t num, uint16_t divider, bool countUp);
void timerEnd(hw_timer_t *timer);
void timerStart(hw_timer_t *timer);
void timerStop(hw_timer_t *timer);
void timerRestart(hw_timer_t *timer);
void timerWrite(hw_timer_t *timer, uint64_t val);
uint64_t timerRead(hw_timer_t *timer);
uint64_t timerReadMicros(hw_timer_t *timer);
uint64_t timerReadMillis(hw_timer_t *timer);
uint64_t timerReadMilis(hw_timer_t *timer);
double timerReadSeconds(hw_timer_t *timer);
uint32_t timerGetFrequency(hw_timer_t *timer);
void timerAttachInterrupt(hw_timer_t *timer, void (*userFunc)(void));
void timerAttachInterrupt(hw_timer_t *timer, void (*userFunc)(void), bool edge);
void timerAttachInterruptArg(hw_timer_t *timer, void (*userFunc)(void *), void *arg);
void timerDetachInterrupt(hw_timer_t *timer);
void timerAlarm(hw_timer_t *timer, uint64_t alarm_value, bool autoreload, uint64_t reload_count);
void timerAlarmWrite(hw_timer_t *timer, uint64_t alarm_value, bool autoreload);
void timerAlarmEnable(hw_timer_t *timer);
void timerAlarmDisable(hw_timer_t *timer);
bool timerAlarmEnabled(hw_timer_t *timer);

bool getLocalTime(struct tm *info, uint32_t ms = 5000);
void configTime(long gmtOffset_sec, int daylightOffset_sec, const char *server1, const char *server2 = nullptr, const char *server3 = nullptr);
void configTzTime(const char *tz, const char *server1, const char *server2 = nullptr, const char *server3 = nullptr);
bool setCpuFrequencyMhz(uint32_t cpu_freq_mhz);
uint32_t getCpuFrequencyMhz(void);
#include "Esp.h"
#endif
