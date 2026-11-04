// The virtual board (firmware_sim.py): the bodies of the Arduino API that firmware_stubs/ only declares, compiled with the
// sketch to WebAssembly and run on a virtual clock. It knows pins, time and the chip's sleep; the circuit stays on the host:
// sim_pin() answers what an input sees (a Thevenin source from the host's solve of the graph) and the event log says what
// the outputs did, so nothing here is about a particular part. Anything the sketch calls that has no body here stays an
// import, and calling it stops the run as 'not modelled' rather than passing.
//
// Log, one event per line on stdout (<t> is microseconds since power-on):
//   O <t> <gpio> D <0|1>        driven as a digital output
//   O <t> <gpio> Z 0            released: input or high impedance
//   O <t> <gpio> P <duty 0-1000> <freq>   PWM
//   O <t> <gpio> T <freq>       a tone (50 % square); 0 ends it
//   B <t> <boot number> <cause> a boot; M <t> deep|light|wake a power state
//   S <t> <text>                a line on Serial
//   L <t> <addr> <0|1>          a display turned off/on; F <t> <addr> <text> what a display() showed
//   X <t> <gpio> <count> <rrggbb,...>  an addressable LED chain's show()
//   W <t> <code> <detail>       something the firmware did that the host should judge (once per code + detail)
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_SH110X.h>
#include <Adafruit_NeoPixel.h>
#include <BH1750.h>
#include <Adafruit_BME280.h>
#include <esp_sleep.h>
#include <esp_timer.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <EEPROM.h>
#include <string>
#include <vector>
#include <set>
#include <map>

#define IMPORT(name) __attribute__((import_module("sim"), import_name(name)))
extern "C" {
IMPORT("pin") int64_t sim_pin(int gpio, int64_t t, const void *states);   // (vth_mv << 32) | rth_ohm; rth 0xffffffff = nothing drives it
IMPORT("next_env") int64_t sim_next_env(int64_t t);                       // the next change of the environment after t
IMPORT("env") int sim_env(int channel, int64_t t);                        // a sensor reading on a bus, x100
IMPORT("boot_t") int64_t sim_boot_t(void);
IMPORT("boot_n") int sim_boot_n(void);
IMPORT("boot_cause") int sim_boot_cause(void);
IMPORT("boot_mask") int64_t sim_boot_mask(void);
IMPORT("end_t") int64_t sim_end_t(void);
IMPORT("adc_full") int sim_adc_full(void);
IMPORT("has_i2c") int sim_has_i2c(int addr);
IMPORT("rtc_load") void sim_rtc_load(void *p, int n);
IMPORT("rtc_save") void sim_rtc_save(const void *p, int n);
IMPORT("slept") void sim_slept(int64_t wake_t, int cause, int64_t mask);
IMPORT("nvs_size") int sim_nvs_size(void);
IMPORT("nvs_load") void sim_nvs_load(void *p);
IMPORT("nvs_save") void sim_nvs_save(const void *p, int n);
}
extern "C" char __start_rtcmem[] __attribute__((weak));
extern "C" char __stop_rtcmem[] __attribute__((weak));

static const int NPINS = 64;
static const int BOOT_US = 120000;     // a deep-sleep wake to the first line of setup()
static const int RPULL = 45000;        // the chip's internal pull resistors
static const int VDD_MV = 3300;
static const int EXIT_END = 0, EXIT_SLEPT = 10, EXIT_RESTART = 11;

struct Pin {
  int mode = 0;              // what pinMode set; 0 = never touched
  int out = 0;               // the output latch
  bool driving = false, pwm = false, sleep_wake = false, wake_high = false;
  int bits = 8, duty = 0, freq = 0, tone = 0;
  int64_t tone_end = 0;
  void (*isr)(void *) = nullptr;
  void *isr_arg = nullptr;
  void (*isr0)(void) = nullptr;
  int isr_mode = 0, last = -1;
  int64_t cached = 0;
  unsigned cache_epoch = 0;
};
// the state vector sim_pin hands the host: for each GPIO 0 hi-z, 1 low, 2 high, 3 PWM/tone
static Pin pins[NPINS];
static int32_t pin_state[NPINS];
static int64_t now_us = 0, boot_t = 0, end_t = 0, next_env = 0;
static unsigned epoch = 1;
static bool in_isr = false;
static int64_t timer_wake = -1;
static int adc_bits = 12;
static uint32_t rnd = 12345;
static std::set<std::string> warned;
static std::string logbuf;
static size_t logged = 0;
static bool sleep_gpio_light = false;

static void flush_log() {
  if (!logbuf.empty()) {
    fwrite(logbuf.data(), 1, logbuf.size(), stdout);
    logbuf.clear();
  }
  fflush(stdout);
}
static void emit(const std::string &line) {
  if (logged > 12000000) return;
  logged += line.size() + 1;
  logbuf += line;
  logbuf += '\n';
  if (logbuf.size() > 60000) flush_log();
}
static std::string i2s(int64_t v) { return std::to_string((long long)v); }
static void warn(const char *code, const std::string &detail) {
  std::string key = std::string(code) + " " + detail;
  if (warned.insert(key).second) emit("W " + i2s(now_us) + " " + key);
}
static void finish(int code) {
  flush_log();
  _Exit(code);
}
extern "C" __attribute__((export_name("sim_now"))) int64_t sim_now(void) { return now_us; }
extern "C" __attribute__((export_name("sim_flush"))) void sim_flush(void) { flush_log(); }

static void state_changed(int g) {
  Pin &p = pins[g];
  pin_state[g] = !p.driving ? 0 : p.tone ? 3 : p.pwm ? (p.duty ? 3 : 1) : p.out ? 2 : 1;
  epoch++;
}
static void log_pin(int g) {
  Pin &p = pins[g];
  std::string h = "O " + i2s(now_us) + " " + std::to_string(g) + " ";
  if (!p.driving) emit(h + "Z 0");
  else if (p.tone) emit(h + "T " + std::to_string(p.tone));
  else if (p.pwm) {
    int full = (1 << p.bits) - 1;
    emit(h + "P " + i2s((int64_t)p.duty * 1000 / (full ? full : 1)) + " " + std::to_string(p.freq));
  } else emit(h + "D " + std::to_string(p.out));
  state_changed(g);
}
static bool valid(int g) { return g >= 0 && g < NPINS; }

// the voltage an input sees: the host's source with the internal pull in parallel; -1 when nothing at all sets it
static int pin_mv(int g, int64_t t, int pull) {
  Pin &p = pins[g];
  if (p.cache_epoch != epoch) {
    p.cached = sim_pin(g, t, pin_state);
    p.cache_epoch = epoch;
  }
  int vth = (int)(p.cached >> 32);
  uint32_t rth = (uint32_t)p.cached;
  bool open = rth == 0xffffffffu;
  if (open && !pull) return -1;
  if (open) return pull > 0 ? VDD_MV : 0;
  if (!pull) return vth;
  double vp = pull > 0 ? VDD_MV : 0, gt = 1.0 / (rth ? rth : 1), gp = 1.0 / RPULL;
  return (int)((vth * gt + vp * gp) / (gt + gp));
}
static int pin_pull(const Pin &p) {
  return (p.mode & PULLUP) && !(p.mode & OUTPUT & ~INPUT) ? 1 : (p.mode & PULLDOWN) ? -1 : 0;
}
static int read_level(int g, bool report) {
  Pin &p = pins[g];
  int mv = pin_mv(g, now_us, pin_pull(p));
  if (mv < 0) {
    if (report) warn("float_read", std::to_string(g));
    return 0;
  }
  if (report && mv > VDD_MV / 4 && mv < VDD_MV * 3 / 4) warn("mid_level", std::to_string(g) + " " + std::to_string(mv));
  return mv > VDD_MV / 2;
}
static void fire_isrs() {
  if (in_isr) return;
  in_isr = true;
  for (int g = 0; g < NPINS; g++) {
    Pin &p = pins[g];
    if (!p.isr && !p.isr0) continue;
    int lv = read_level(g, false), was = p.last;
    p.last = lv;
    if (was < 0 || lv == was) continue;
    bool rise = lv && !was;
    if (p.isr_mode == CHANGE || (p.isr_mode == RISING && rise) || (p.isr_mode == FALLING && !rise) ||
        (p.isr_mode == ONLOW && !lv) || (p.isr_mode == ONHIGH && lv)) {
      if (p.isr0) p.isr0();
      else p.isr(p.isr_arg);
    }
  }
  in_isr = false;
}
static int timed_tones = 0;
static void advance(int64_t us) {
  int64_t target = now_us + us;
  if (!timed_tones && (next_env < 0 || next_env > target) && (!end_t || target < end_t)) {
    now_us = target;   // nearly every call: nothing to do on the way
    return;
  }
  for (;;) {
    int64_t step = target;
    if (next_env >= 0 && next_env <= step) step = next_env;
    for (int g = 0; timed_tones && g < NPINS; g++) {
      if (pins[g].tone && pins[g].tone_end && pins[g].tone_end <= step) step = pins[g].tone_end;
    }
    if (end_t && step >= end_t) {
      now_us = end_t;
      finish(EXIT_END);
    }
    now_us = step;
    bool changed = false;
    if (next_env >= 0 && next_env <= now_us) {
      next_env = sim_next_env(now_us);
      epoch++;
      changed = true;
    }
    for (int g = 0; timed_tones && g < NPINS; g++) {
      if (pins[g].tone && pins[g].tone_end && pins[g].tone_end <= now_us) {
        pins[g].tone = 0;
        pins[g].tone_end = 0;
        pins[g].driving = false;
        timed_tones--;
        log_pin(g);
      }
    }
    if (changed) fire_isrs();
    if (now_us >= target) return;
  }
}

// ------------------------------------------------------------------ pins
extern "C" {
void pinMode(uint8_t pin, uint8_t mode) {
  if (!valid(pin)) return;
  Pin &p = pins[pin];
  p.mode = mode;
  bool drive = (mode & OUTPUT & ~INPUT) != 0 || mode == OUTPUT;
  if (p.pwm && drive) return;
  if (p.pwm) p.pwm = false;
  bool was = p.driving;
  p.driving = drive;
  if (drive != was || !drive) {
    if (drive != was) log_pin(pin);
    else state_changed(pin);
  }
  advance(1);
}
void digitalWrite(uint8_t pin, uint8_t val) {
  if (!valid(pin)) return;
  Pin &p = pins[pin];
  val = val ? 1 : 0;
  if (!p.driving) {
    p.out = val;
    if (!p.mode) warn("write_no_mode", std::to_string(pin));
    advance(1);
    return;
  }
  if (p.pwm) {
    p.pwm = false;
    p.out = val;
    log_pin(pin);
  } else if (p.out != val) {
    p.out = val;
    log_pin(pin);
  }
  advance(1);
}
int digitalRead(uint8_t pin) {
  advance(5);
  if (!valid(pin)) return 0;
  Pin &p = pins[pin];
  if (p.driving) return p.out;
  if (!p.mode) warn("read_no_mode", std::to_string(pin));
  return read_level(pin, true);
}
void attachInterrupt(uint8_t pin, void (*f)(void), int mode) {
  if (!valid(pin)) return;
  pins[pin].isr0 = f;
  pins[pin].isr_mode = mode;
  pins[pin].last = read_level(pin, false);
}
void attachInterruptArg(uint8_t pin, void (*f)(void *), void *arg, int mode) {
  if (!valid(pin)) return;
  pins[pin].isr = f;
  pins[pin].isr_arg = arg;
  pins[pin].isr_mode = mode;
  pins[pin].last = read_level(pin, false);
}
void detachInterrupt(uint8_t pin) {
  if (!valid(pin)) return;
  pins[pin].isr = nullptr;
  pins[pin].isr0 = nullptr;
}
uint32_t analogReadMilliVolts(uint8_t pin) {
  advance(20);
  if (!valid(pin)) return 0;
  int mv = pin_mv(pin, now_us, pin_pull(pins[pin]));
  if (mv < 0) {
    warn("float_adc", std::to_string(pin));   // randomSeed(analogRead(A0)) is the usual reason: not a finding on its own
    return (uint32_t)(esp_random() % 400);
  }
  return mv;
}
uint16_t analogRead(uint8_t pin) {
  int mv = (int)analogReadMilliVolts(pin), full = sim_adc_full();
  if (mv > full) mv = full;
  int top = (1 << adc_bits) - 1;
  return (uint16_t)((int64_t)mv * top / full);
}
void analogReadResolution(uint8_t bits) { adc_bits = bits ? bits : 12; }
void analogSetAttenuation(adc_attenuation_t) {}
void analogSetPinAttenuation(uint8_t, adc_attenuation_t) {}
void analogSetClockDiv(uint8_t) {}

// ------------------------------------------------------------------ time
unsigned long micros(void) {
  advance(10);
  return (unsigned long)(now_us - boot_t);
}
unsigned long millis(void) {
  advance(10);
  return (unsigned long)((now_us - boot_t) / 1000);
}
void delay(uint32_t ms) { advance(ms ? (int64_t)ms * 1000 : 1); }
void delayMicroseconds(uint32_t us) { advance(us ? us : 1); }
void yield(void) { advance(1); }
int64_t esp_timer_get_time(void) {
  advance(2);
  return now_us - boot_t;
}
void vTaskDelay(const TickType_t t) { advance(t ? (int64_t)t * 1000 : 1); }
TickType_t xTaskGetTickCount(void) { return (TickType_t)((now_us - boot_t) / 1000); }

// ------------------------------------------------------------------ LEDC / PWM / tone
bool ledcAttach(uint8_t pin, uint32_t freq, uint8_t bits) {
  if (!valid(pin)) return false;
  Pin &p = pins[pin];
  p.driving = true;
  p.pwm = true;
  p.bits = bits;
  p.freq = freq;
  p.duty = 0;
  p.mode = OUTPUT;
  log_pin(pin);
  return true;
}
bool ledcWrite(uint8_t pin, uint32_t duty) {
  advance(2);
  if (!valid(pin)) return false;
  Pin &p = pins[pin];
  if (!p.pwm) {
    warn("ledc_not_attached", std::to_string(pin));
    return false;
  }
  if ((int)duty != p.duty) {
    p.duty = duty;
    log_pin(pin);
  }
  return true;
}
uint32_t ledcRead(uint8_t pin) { return valid(pin) ? pins[pin].duty : 0; }
uint32_t ledcReadFreq(uint8_t pin) { return valid(pin) ? pins[pin].freq : 0; }
bool ledcDetach(uint8_t pin) {
  if (!valid(pin)) return false;
  pins[pin].pwm = false;
  pins[pin].driving = false;
  log_pin(pin);
  return true;
}
uint32_t ledcWriteTone(uint8_t pin, uint32_t freq) {
  if (!valid(pin)) return 0;
  Pin &p = pins[pin];
  p.driving = true;
  p.mode = OUTPUT;
  if ((int)freq != p.tone) {
    if (p.tone_end) timed_tones--;
    p.tone = freq;
    p.tone_end = 0;
    log_pin(pin);
  }
  return freq;
}
uint32_t ledcChangeFrequency(uint8_t pin, uint32_t freq, uint8_t bits) {
  if (!valid(pin)) return 0;
  pins[pin].freq = freq;
  pins[pin].bits = bits;
  return freq;
}
bool ledcFade(uint8_t pin, uint32_t start, uint32_t target, int ms) {
  if (!valid(pin) || !pins[pin].pwm) return false;
  int steps = 32;
  for (int i = 0; i <= steps; i++) {
    pins[pin].duty = start + ((int64_t)target - (int64_t)start) * i / steps;
    log_pin(pin);
    if (i < steps) advance((int64_t)ms * 1000 / steps);
  }
  return true;
}
void analogWrite(uint8_t pin, int value) {
  if (!valid(pin)) return;
  if (!pins[pin].pwm) ledcAttach(pin, 1000, 8);
  ledcWrite(pin, value);
}

// ------------------------------------------------------------------ sleep
static int wake_level_hit(int64_t t, int64_t *mask_out) {
  int64_t mask = 0;
  epoch++;
  for (int g = 0; g < NPINS; g++) {
    Pin &p = pins[g];
    if (!p.sleep_wake) continue;
    p.cache_epoch = 0;
    int mv = pin_mv(g, t, p.wake_high ? -1 : 1);   // ESP-IDF sets the pull that keeps the pin idle while it sleeps
    if ((mv > VDD_MV / 2) == p.wake_high) mask |= 1LL << g;
  }
  *mask_out = mask;
  return mask != 0;
}
// when the chip would wake from now on: a wake pin already at its level wakes it at once, as a level trigger does
static int64_t find_wake(int *cause, int64_t *mask) {
  int64_t t = now_us;
  for (;;) {
    if (wake_level_hit(t, mask)) {
      *cause = ESP_SLEEP_WAKEUP_GPIO;
      return t;
    }
    int64_t nx = sim_next_env(t);
    int64_t tw = timer_wake >= 0 ? now_us + timer_wake : -1;
    if (tw >= 0 && (nx < 0 || tw <= nx)) {
      *cause = ESP_SLEEP_WAKEUP_TIMER;
      *mask = 0;
      return tw;
    }
    if (nx < 0) {
      *cause = ESP_SLEEP_WAKEUP_UNDEFINED;
      return -1;
    }
    t = nx;
  }
}
void esp_deep_sleep_start(void) {
  emit("M " + i2s(now_us) + " deep");
  for (int g = 0; g < NPINS; g++) {
    Pin &p = pins[g];
    if (p.driving || p.pwm || p.tone) {
      p.driving = false;
      p.pwm = false;
      p.tone = 0;
      log_pin(g);
    }
  }
  epoch++;
  int cause = 0;
  int64_t mask = 0, wake = find_wake(&cause, &mask);
  if (&__start_rtcmem[0] && &__stop_rtcmem[0]) sim_rtc_save(__start_rtcmem, (int)(__stop_rtcmem - __start_rtcmem));
  sim_slept(wake, cause, mask);
  finish(EXIT_SLEPT);
  __builtin_unreachable();
}
void esp_deep_sleep(uint64_t us) {
  timer_wake = (int64_t)us;
  esp_deep_sleep_start();
  __builtin_unreachable();
}
esp_err_t esp_sleep_enable_timer_wakeup(uint64_t us) {
  timer_wake = (int64_t)us;
  return ESP_OK;
}
esp_err_t esp_sleep_disable_wakeup_source(esp_sleep_source_t) {
  timer_wake = -1;
  for (int g = 0; g < NPINS; g++) pins[g].sleep_wake = false;
  return ESP_OK;
}
#if defined(SOC_GPIO_SUPPORT_DEEPSLEEP_WAKEUP)
esp_err_t esp_deep_sleep_enable_gpio_wakeup(uint64_t mask, esp_deepsleep_gpio_wake_up_mode_t mode) {
  for (int g = 0; g < NPINS; g++) {
    if (mask >> g & 1) {
      if (g > 5) warn("wake_pin_invalid", std::to_string(g));
      else {
        pins[g].sleep_wake = true;
        pins[g].wake_high = mode == ESP_GPIO_WAKEUP_GPIO_HIGH;
      }
    }
  }
  return ESP_OK;
}
uint64_t esp_sleep_get_gpio_wakeup_status(void) { return (uint64_t)sim_boot_mask(); }
#endif
#if defined(SOC_PM_SUPPORT_EXT0_WAKEUP)
esp_err_t esp_sleep_enable_ext0_wakeup(gpio_num_t g, int level) {
  pins[g].sleep_wake = true;
  pins[g].wake_high = level != 0;
  return ESP_OK;
}
#endif
#if defined(SOC_PM_SUPPORT_EXT1_WAKEUP)
esp_err_t esp_sleep_enable_ext1_wakeup(uint64_t mask, esp_sleep_ext1_wakeup_mode_t mode) {
  for (int g = 0; g < NPINS; g++) {
    if (mask >> g & 1) {
      pins[g].sleep_wake = true;
      pins[g].wake_high = mode == ESP_EXT1_WAKEUP_ANY_HIGH;
    }
  }
  return ESP_OK;
}
uint64_t esp_sleep_get_ext1_wakeup_status(void) { return (uint64_t)sim_boot_mask(); }
#endif
esp_sleep_wakeup_cause_t esp_sleep_get_wakeup_cause(void) { return (esp_sleep_wakeup_cause_t)sim_boot_cause(); }
esp_err_t esp_sleep_pd_config(esp_sleep_pd_domain_t, esp_sleep_pd_option_t) { return ESP_OK; }
esp_err_t esp_sleep_enable_gpio_wakeup(void) {
  sleep_gpio_light = true;
  return ESP_OK;
}
esp_err_t gpio_wakeup_enable(gpio_num_t g, gpio_int_type_t t) {
  if (valid(g)) {
    pins[g].sleep_wake = true;
    pins[g].wake_high = t == GPIO_INTR_HIGH_LEVEL;
  }
  return ESP_OK;
}
esp_err_t gpio_wakeup_disable(gpio_num_t g) {
  if (valid(g)) pins[g].sleep_wake = false;
  return ESP_OK;
}
esp_err_t esp_light_sleep_start(void) {
  emit("M " + i2s(now_us) + " light");
  int cause = 0;
  int64_t mask = 0, wake = find_wake(&cause, &mask);
  if (wake < 0) wake = end_t;
  advance(wake > now_us ? wake - now_us : 1);
  emit("M " + i2s(now_us) + " wake");
  return ESP_OK;
}
void esp_restart(void) {
  flush_log();
  finish(EXIT_RESTART);
  __builtin_unreachable();
}
esp_reset_reason_t esp_reset_reason(void) { return sim_boot_cause() ? ESP_RST_DEEPSLEEP : ESP_RST_POWERON; }
uint32_t esp_random(void) {
  rnd = rnd * 1664525u + 1013904223u;
  return rnd ^ (uint32_t)(now_us >> 3);
}
void esp_fill_random(void *buf, size_t len) {
  for (size_t i = 0; i < len; i++) ((uint8_t *)buf)[i] = (uint8_t)(esp_random() >> 16);
}
uint32_t esp_get_free_heap_size(void) { return 200000; }
uint32_t esp_get_minimum_free_heap_size(void) { return 180000; }
float temperatureRead(void) { return 35.0f; }
uint32_t getXtalFrequencyMhz(void) { return 40; }
uint32_t getApbFrequency(void) { return 80000000; }
esp_err_t gpio_set_level(gpio_num_t g, uint32_t v) {
  digitalWrite(g, v);
  return ESP_OK;
}
int gpio_get_level(gpio_num_t g) { return digitalRead(g); }
esp_err_t gpio_set_direction(gpio_num_t g, gpio_mode_t m) {
  pinMode(g, (m & GPIO_MODE_OUTPUT) ? OUTPUT : INPUT);
  return ESP_OK;
}
esp_err_t gpio_pullup_en(gpio_num_t g) {
  if (valid(g)) pins[g].mode |= PULLUP;
  epoch++;
  return ESP_OK;
}
esp_err_t gpio_pullup_dis(gpio_num_t g) {
  if (valid(g)) pins[g].mode &= ~PULLUP;
  epoch++;
  return ESP_OK;
}
esp_err_t gpio_pulldown_en(gpio_num_t g) {
  if (valid(g)) pins[g].mode |= PULLDOWN;
  epoch++;
  return ESP_OK;
}
esp_err_t gpio_pulldown_dis(gpio_num_t g) {
  if (valid(g)) pins[g].mode &= ~PULLDOWN;
  epoch++;
  return ESP_OK;
}
esp_err_t gpio_hold_en(gpio_num_t) { return ESP_OK; }
esp_err_t gpio_hold_dis(gpio_num_t) { return ESP_OK; }
void gpio_deep_sleep_hold_en(void) {}
void gpio_deep_sleep_hold_dis(void) {}
char *dtostrf(double val, signed char width, unsigned char prec, char *sout) {
  sprintf(sout, "%*.*f", width, prec, val);
  return sout;
}
}  // extern "C"

void analogWriteFrequency(uint32_t) {}
void analogWriteResolution(uint8_t) {}
bool setCpuFrequencyMhz(uint32_t) { return true; }
uint32_t getCpuFrequencyMhz(void) { return 160; }
void tone(uint8_t pin, unsigned int freq, unsigned long duration) {
  if (!valid(pin)) return;
  Pin &p = pins[pin];
  if (p.tone != (int)freq || !p.driving) {
    p.driving = true;
    p.tone = freq;
    log_pin(pin);
  }
  if (p.tone_end) timed_tones--;
  p.tone_end = duration ? now_us + (int64_t)duration * 1000 : 0;
  if (p.tone_end) timed_tones++;
  advance(5);
}
void noTone(uint8_t pin) {
  if (!valid(pin)) return;
  Pin &p = pins[pin];
  if (p.tone) {
    if (p.tone_end) timed_tones--;
    p.tone = 0;
    p.tone_end = 0;
    p.driving = false;   // the core detaches the pin from its timer
    log_pin(pin);
  }
  advance(5);
}
unsigned long pulseIn(uint8_t pin, uint8_t state, unsigned long timeout) {
  int64_t start = now_us;
  while (digitalRead(pin) == state) {
    if (now_us - start > (int64_t)timeout) return 0;
    advance(10);
  }
  while (digitalRead(pin) != state) {
    if (now_us - start > (int64_t)timeout) return 0;
    advance(10);
  }
  int64_t t0 = now_us;
  while (digitalRead(pin) == state) {
    if (now_us - start > (int64_t)timeout) return 0;
    advance(10);
  }
  return (unsigned long)(now_us - t0);
}
long random(long howbig) { return howbig > 0 ? (long)(esp_random() % (uint32_t)howbig) : 0; }
long random(long lo, long hi) { return hi > lo ? lo + random(hi - lo) : lo; }
void randomSeed(unsigned long seed) { rnd ^= (uint32_t)seed; }
long map(long x, long a, long b, long c, long d) {
  long dv = b - a;
  return dv ? (x - a) * (d - c) / dv + c : c;
}
uint16_t makeWord(uint16_t w) { return w; }
uint16_t makeWord(uint8_t h, uint8_t l) { return (uint16_t)((h << 8) | l); }

// ------------------------------------------------------------------ String
#define BUF(s) ((s)._b ? (s)._b : (char *)"")
static void s_set(String *s, const char *p, unsigned n);
String::String(const char *c) { s_set(this, c ? c : "", c ? (unsigned)strlen(c) : 0); }
String::String(const char *c, unsigned int n) { s_set(this, c, n); }
String::String(const uint8_t *c, unsigned int n) { s_set(this, (const char *)c, n); }
String::String(const String &o) { s_set(this, BUF(o), o._l); }
String::String(const __FlashStringHelper *c) { s_set(this, (const char *)c, c ? (unsigned)strlen((const char *)c) : 0); }
String::String(String &&o) {
  _b = o._b;
  _l = o._l;
  o._b = nullptr;
  o._l = 0;
}
String::String(char c) { s_set(this, &c, 1); }
static std::string num_str(unsigned long long v, int base) {
  if (!v) return "0";
  std::string r;
  while (v) {
    r.insert(r.begin(), "0123456789abcdefghijklmnopqrstuvwxyz"[v % (base > 1 && base <= 36 ? base : 10)]);
    v /= (base > 1 && base <= 36 ? base : 10);
  }
  return r;
}
static std::string snum_str(long long v, int base) {
  if (v < 0 && base == 10) return "-" + num_str((unsigned long long)(-v), base);
  return num_str((unsigned long long)v, base);
}
static std::string flt_str(double v, int dec) {
  char b[64];
  snprintf(b, sizeof b, "%.*f", dec, v);
  return b;
}
#define S_STD(s) do { std::string _t = (s); s_set(this, _t.data(), (unsigned)_t.size()); } while (0)
String::String(unsigned char v, unsigned char base) { S_STD(num_str(v, base)); }
String::String(int v, unsigned char base) { S_STD(snum_str(v, base)); }
String::String(unsigned int v, unsigned char base) { S_STD(num_str(v, base)); }
String::String(long v, unsigned char base) { S_STD(snum_str(v, base)); }
String::String(unsigned long v, unsigned char base) { S_STD(num_str(v, base)); }
String::String(float v, unsigned int d) { S_STD(flt_str(v, d)); }
String::String(double v, unsigned int d) { S_STD(flt_str(v, d)); }
String::String(long long v, unsigned char base) { S_STD(snum_str(v, base)); }
String::String(unsigned long long v, unsigned char base) { S_STD(num_str(v, base)); }
String::~String() { free(_b); }
static void s_set(String *s, const char *p, unsigned n) {
  char *b = (char *)malloc(n + 1);
  memcpy(b, p, n);
  b[n] = 0;
  s->_b = b;
  s->_l = n;
}
bool String::reserve(unsigned int) { return true; }
unsigned int String::length() const { return _l; }
bool String::isEmpty() const { return _l == 0; }
String &String::operator=(const String &r) {
  if (this != &r) {
    char *old = _b;
    s_set(this, BUF(r), r._l);
    free(old);
  }
  return *this;
}
String &String::operator=(const char *c) {
  char *old = _b;
  s_set(this, c ? c : "", c ? (unsigned)strlen(c) : 0);
  free(old);
  return *this;
}
String &String::operator=(const __FlashStringHelper *c) { return *this = (const char *)c; }
String &String::operator=(String &&r) {
  if (this != &r) {
    free(_b);
    _b = r._b;
    _l = r._l;
    r._b = nullptr;
    r._l = 0;
  }
  return *this;
}
bool String::concat(const char *c, unsigned int n) {
  char *b = (char *)malloc(_l + n + 1);
  if (_b) memcpy(b, _b, _l);
  memcpy(b + _l, c, n);
  b[_l + n] = 0;
  free(_b);
  _b = b;
  _l += n;
  return true;
}
bool String::concat(const String &o) { return concat(BUF(o), o._l); }
bool String::concat(const char *c) { return c ? concat(c, (unsigned)strlen(c)) : false; }
bool String::concat(const uint8_t *c, unsigned int n) { return concat((const char *)c, n); }
bool String::concat(char c) { return concat(&c, 1); }
#define S_CAT(T, E) bool String::concat(T v) { std::string _t = (E); return concat(_t.data(), (unsigned)_t.size()); }
S_CAT(unsigned char, num_str(v, 10))
S_CAT(int, snum_str(v, 10))
S_CAT(unsigned int, num_str(v, 10))
S_CAT(long, snum_str(v, 10))
S_CAT(unsigned long, num_str(v, 10))
S_CAT(float, flt_str(v, 2))
S_CAT(double, flt_str(v, 2))
S_CAT(long long, snum_str(v, 10))
S_CAT(unsigned long long, num_str(v, 10))
bool String::concat(const __FlashStringHelper *c) { return concat((const char *)c); }
#define S_ADD(T) String &String::operator+=(T v) { concat(v); return *this; }
S_ADD(const String &)
S_ADD(const char *)
S_ADD(char)
S_ADD(unsigned char)
S_ADD(int)
S_ADD(unsigned int)
S_ADD(long)
S_ADD(unsigned long)
S_ADD(float)
S_ADD(double)
S_ADD(long long)
S_ADD(unsigned long long)
S_ADD(const __FlashStringHelper *)
#define S_SUM(T) StringSumHelper &operator+(const StringSumHelper &l, T v) { auto &a = const_cast<StringSumHelper &>(l); a.concat(v); return a; }
S_SUM(const String &)
S_SUM(const char *)
S_SUM(char)
S_SUM(unsigned char)
S_SUM(int)
S_SUM(unsigned int)
S_SUM(long)
S_SUM(unsigned long)
S_SUM(float)
S_SUM(double)
S_SUM(long long)
S_SUM(unsigned long long)
S_SUM(const __FlashStringHelper *)
int String::compareTo(const String &s) const { return strcmp(c_str(), s.c_str()); }
bool String::equals(const String &s) const { return _l == s._l && !strcmp(c_str(), s.c_str()); }
bool String::equals(const char *c) const { return !strcmp(c_str(), c ? c : ""); }
bool String::operator==(const String &r) const { return equals(r); }
bool String::operator==(const char *c) const { return equals(c); }
bool String::operator!=(const String &r) const { return !equals(r); }
bool String::operator!=(const char *c) const { return !equals(c); }
bool String::operator<(const String &r) const { return compareTo(r) < 0; }
bool String::operator>(const String &r) const { return compareTo(r) > 0; }
bool String::operator<=(const String &r) const { return compareTo(r) <= 0; }
bool String::operator>=(const String &r) const { return compareTo(r) >= 0; }
bool String::equalsIgnoreCase(const String &s) const { return _l == s._l && !strcasecmp(c_str(), s.c_str()); }
bool String::equalsConstantTime(const String &s) const { return equals(s); }
bool String::startsWith(const char *p) const { return !strncmp(c_str(), p, strlen(p)); }
bool String::startsWith(const String &p) const { return startsWith(p.c_str()); }
bool String::startsWith(const String &p, unsigned int off) const { return off <= _l && !strncmp(c_str() + off, p.c_str(), p._l); }
bool String::endsWith(const char *p) const {
  size_t n = strlen(p);
  return n <= _l && !strcmp(c_str() + _l - n, p);
}
bool String::endsWith(const String &p) const { return endsWith(p.c_str()); }
char String::charAt(unsigned int i) const { return i < _l ? _b[i] : 0; }
void String::setCharAt(unsigned int i, char c) {
  if (i < _l) _b[i] = c;
}
char String::operator[](unsigned int i) const { return charAt(i); }
char &String::operator[](unsigned int i) {
  static char dummy;
  return i < _l ? _b[i] : dummy;
}
void String::getBytes(unsigned char *buf, unsigned int n, unsigned int from) const {
  if (!n) return;
  unsigned avail = from < _l ? _l - from : 0, k = avail < n - 1 ? avail : n - 1;
  if (k) memcpy(buf, c_str() + from, k);
  buf[k] = 0;
}
void String::toCharArray(char *buf, unsigned int n, unsigned int from) const { getBytes((unsigned char *)buf, n, from); }
const char *String::c_str() const { return BUF(*this); }
char *String::begin() { return _b; }
char *String::end() { return _b ? _b + _l : nullptr; }
const char *String::begin() const { return c_str(); }
const char *String::end() const { return c_str() + _l; }
int String::indexOf(char c) const { return indexOf(c, 0); }
int String::indexOf(char c, unsigned int from) const {
  if (from >= _l) return -1;
  const char *p = strchr(c_str() + from, c);
  return p ? (int)(p - c_str()) : -1;
}
int String::indexOf(const String &s) const { return indexOf(s, 0); }
int String::indexOf(const String &s, unsigned int from) const {
  if (from > _l) return -1;
  const char *p = strstr(c_str() + from, s.c_str());
  return p ? (int)(p - c_str()) : -1;
}
int String::lastIndexOf(char c) const {
  const char *p = strrchr(c_str(), c);
  return p ? (int)(p - c_str()) : -1;
}
int String::lastIndexOf(char c, unsigned int from) const {
  for (int i = (int)(from < _l ? from : _l - 1); i >= 0; i--) {
    if (_b && _b[i] == c) return i;
  }
  return -1;
}
int String::lastIndexOf(const String &s) const { return lastIndexOf(s, _l); }
int String::lastIndexOf(const String &s, unsigned int from) const {
  for (int i = (int)(from < _l ? from : _l); i >= 0; i--) {
    if (i + s._l <= _l && !strncmp(c_str() + i, s.c_str(), s._l)) return i;
  }
  return -1;
}
String String::substring(unsigned int a) const { return substring(a, _l); }
String String::substring(unsigned int a, unsigned int b) const {
  if (a > b) {
    unsigned t = a;
    a = b;
    b = t;
  }
  if (a >= _l) return String("");
  if (b > _l) b = _l;
  return String(c_str() + a, b - a);
}
void String::replace(char f, char r) {
  for (unsigned i = 0; i < _l; i++) {
    if (_b[i] == f) _b[i] = r;
  }
}
void String::replace(const String &f, const String &r) {
  std::string s = c_str(), a = f.c_str(), b = r.c_str();
  if (a.empty()) return;
  for (size_t p = s.find(a); p != std::string::npos; p = s.find(a, p + b.size())) s.replace(p, a.size(), b);
  *this = s.c_str();
}
void String::remove(unsigned int i) { remove(i, _l); }
void String::remove(unsigned int i, unsigned int n) {
  if (i >= _l) return;
  if (n > _l - i) n = _l - i;
  memmove(_b + i, _b + i + n, _l - i - n + 1);
  _l -= n;
}
void String::toLowerCase() {
  for (unsigned i = 0; i < _l; i++) _b[i] = (char)tolower(_b[i]);
}
void String::toUpperCase() {
  for (unsigned i = 0; i < _l; i++) _b[i] = (char)toupper(_b[i]);
}
void String::trim() {
  std::string s = c_str();
  size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
  *this = a == std::string::npos ? "" : s.substr(a, b - a + 1).c_str();
}
long String::toInt() const { return atol(c_str()); }
float String::toFloat() const { return (float)atof(c_str()); }
double String::toDouble() const { return atof(c_str()); }
const String emptyString;

// ------------------------------------------------------------------ Print / Stream
int Print::getWriteError() { return 0; }
void Print::clearWriteError() {}
size_t Print::write(const char *s) { return s ? write((const uint8_t *)s, strlen(s)) : 0; }
size_t Print::write(const uint8_t *b, size_t n) {
  for (size_t i = 0; i < n; i++) write(b[i]);
  return n;
}
size_t Print::write(const char *b, size_t n) { return write((const uint8_t *)b, n); }
int Print::availableForWrite() { return 0; }
size_t Print::vprintf(const char *f, va_list a) {
  char b[256];
  int n = vsnprintf(b, sizeof b, f, a);
  if (n < 0) return 0;
  return write((const uint8_t *)b, n < (int)sizeof b ? n : (int)sizeof b - 1);
}
size_t Print::printf(const char *f, ...) {
  va_list a;
  va_start(a, f);
  size_t n = vprintf(f, a);
  va_end(a);
  return n;
}
#define P_STD(s) do { std::string _t = (s); return write((const uint8_t *)_t.data(), _t.size()); } while (0)
size_t Print::print(const __FlashStringHelper *s) { return write((const char *)s); }
size_t Print::print(const String &s) { return write((const uint8_t *)s.c_str(), s.length()); }
size_t Print::print(const char s[]) { return write(s); }
size_t Print::print(char c) { return write((uint8_t)c); }
size_t Print::print(unsigned char v, int b) { P_STD(num_str(v, b)); }
size_t Print::print(int v, int b) { P_STD(snum_str(v, b)); }
size_t Print::print(unsigned int v, int b) { P_STD(num_str(v, b)); }
size_t Print::print(long v, int b) { P_STD(snum_str(v, b)); }
size_t Print::print(unsigned long v, int b) { P_STD(num_str(v, b)); }
size_t Print::print(long long v, int b) { P_STD(snum_str(v, b)); }
size_t Print::print(unsigned long long v, int b) { P_STD(num_str(v, b)); }
size_t Print::print(double v, int d) { P_STD(flt_str(v, d)); }
size_t Print::print(const Printable &p) { return p.printTo(*this); }
size_t Print::println(void) { return write((const uint8_t *)"\r\n", 2); }
#define P_LN(T) size_t Print::println(T v) { size_t n = print(v); return n + println(); }
#define P_LN2(T) size_t Print::println(T v, int b) { size_t n = print(v, b); return n + println(); }
P_LN(const __FlashStringHelper *)
P_LN(const String &)
P_LN(const char *)
P_LN(char)
P_LN2(unsigned char)
P_LN2(int)
P_LN2(unsigned int)
P_LN2(long)
P_LN2(unsigned long)
P_LN2(long long)
P_LN2(unsigned long long)
P_LN2(double)
P_LN(const Printable &)
void Stream::setTimeout(unsigned long) {}
unsigned long Stream::getTimeout() { return 1000; }
long Stream::parseInt(LookaheadMode, char) { return 0; }
float Stream::parseFloat(LookaheadMode, char) { return 0; }
size_t Stream::readBytes(char *, size_t) { return 0; }
size_t Stream::readBytes(uint8_t *, size_t) { return 0; }
size_t Stream::readBytesUntil(char, char *, size_t) { return 0; }
size_t Stream::readBytesUntil(char, uint8_t *, size_t) { return 0; }
String Stream::readString() { return String(""); }
String Stream::readStringUntil(char) { return String(""); }

// ------------------------------------------------------------------ Serial
static std::string serial_line;
static size_t serial_put(uint8_t c) {
  if (c == '\n') {
    emit("S " + i2s(now_us) + " " + serial_line);
    serial_line.clear();
  } else if (c != '\r' && serial_line.size() < 300) {
    serial_line += (char)c;
  }
  return 1;
}
void USBSerialPort::begin(unsigned long) {}
void USBSerialPort::end() {}
int USBSerialPort::available() { return 0; }
int USBSerialPort::availableForWrite() { return 256; }
int USBSerialPort::peek() { return -1; }
int USBSerialPort::read() { return -1; }
size_t USBSerialPort::read(uint8_t *, size_t) { return 0; }
size_t USBSerialPort::read(char *, size_t) { return 0; }
void USBSerialPort::flush() {}
size_t USBSerialPort::write(uint8_t c) { return serial_put(c); }
size_t USBSerialPort::write(const uint8_t *b, size_t n) {
  for (size_t i = 0; i < n; i++) serial_put(b[i]);
  return n;
}
USBSerialPort::operator bool() const { return true; }
bool USBSerialPort::isConnected() { return true; }
bool USBSerialPort::isPlugged() { return true; }
void USBSerialPort::setTxTimeoutMs(uint32_t) {}
size_t USBSerialPort::setRxBufferSize(size_t n) { return n; }
size_t USBSerialPort::setTxBufferSize(size_t n) { return n; }
void USBSerialPort::setDebugOutput(bool) {}
uint32_t USBSerialPort::baudRate() { return 115200; }
USBSerialPort Serial;
HardwareSerial::HardwareSerial(uint8_t) {}
void HardwareSerial::begin(unsigned long, uint32_t, int8_t, int8_t, bool, unsigned long, uint8_t) {}
void HardwareSerial::end() {}
void HardwareSerial::updateBaudRate(unsigned long) {}
uint32_t HardwareSerial::baudRate() { return 115200; }
int HardwareSerial::available() { return 0; }
int HardwareSerial::availableForWrite() { return 256; }
int HardwareSerial::peek() { return -1; }
int HardwareSerial::read() { return -1; }
size_t HardwareSerial::read(uint8_t *, size_t) { return 0; }
size_t HardwareSerial::read(char *, size_t) { return 0; }
void HardwareSerial::flush() {}
void HardwareSerial::flush(bool) {}
size_t HardwareSerial::write(uint8_t c) { return serial_put(c); }
size_t HardwareSerial::write(const uint8_t *b, size_t n) {
  for (size_t i = 0; i < n; i++) serial_put(b[i]);
  return n;
}
HardwareSerial::operator bool() const { return true; }
bool HardwareSerial::setPins(int8_t, int8_t, int8_t, int8_t) { return true; }
size_t HardwareSerial::setRxBufferSize(size_t n) { return n; }
size_t HardwareSerial::setTxBufferSize(size_t n) { return n; }
void HardwareSerial::setDebugOutput(bool) {}
HardwareSerial Serial0(0), Serial1(1);
#if defined(FW_BOARD_XIAO_ESP32S3) || defined(FW_BOARD_PICO) || defined(FW_BOARD_PICO_W)
HardwareSerial Serial2(2);
#endif
void EspClass::restart() { esp_restart(); }
void EspClass::deepSleep(uint64_t us) { esp_deep_sleep(us); }
uint32_t EspClass::getFreeHeap() { return 200000; }
uint32_t EspClass::getCycleCount() { return (uint32_t)(now_us * 160); }
uint16_t EspClass::getCpuFreqMHz() { return 160; }
uint64_t EspClass::getEfuseMac() { return 0x1234567890ULL; }
EspClass ESP;

// ------------------------------------------------------------------ I2C: which addresses answer; reads return nothing
static std::vector<uint8_t> rx;
static int tx_addr = -1;
TwoWire::TwoWire(uint8_t) {}
TwoWire::~TwoWire() {}
bool TwoWire::setPins(int, int) { return true; }
bool TwoWire::begin() { return true; }
#if defined(ESP32)
bool TwoWire::begin(uint8_t, int, int, uint32_t) { return true; }
bool TwoWire::begin(int, int, uint32_t) { return true; }
#else
bool TwoWire::begin(uint8_t) { return true; }
#endif
bool TwoWire::end() { return true; }
size_t TwoWire::setBufferSize(size_t n) { return n; }
void TwoWire::setTimeOut(uint16_t) {}
uint16_t TwoWire::getTimeOut() { return 50; }
bool TwoWire::setClock(uint32_t) { return true; }
uint32_t TwoWire::getClock() { return 100000; }
void TwoWire::beginTransmission(uint16_t a) { tx_addr = a; }
void TwoWire::beginTransmission(uint8_t a) { tx_addr = a; }
void TwoWire::beginTransmission(int a) { tx_addr = a; }
uint8_t TwoWire::endTransmission(bool) {
  advance(200);
  return sim_has_i2c(tx_addr) ? 0 : 2;
}
uint8_t TwoWire::endTransmission() { return endTransmission(true); }
static uint8_t wire_request(int a, int n) {
  advance(200);
  rx.clear();
  if (!sim_has_i2c(a)) return 0;
  if ((a == 0x23 || a == 0x5C) && n == 2) {
    int raw = sim_env(0, now_us) * 12 / 1000;
    if (raw > 65535) raw = 65535;
    rx.push_back((uint8_t)(raw >> 8));
    rx.push_back((uint8_t)raw);
    return 2;
  }
  warn("i2c_raw_read", std::to_string(a));
  rx.assign(n, 0);
  return (uint8_t)n;
}
size_t TwoWire::requestFrom(uint16_t a, size_t n, bool) { return wire_request(a, (int)n); }
uint8_t TwoWire::requestFrom(uint16_t a, uint8_t n, bool) { return wire_request(a, n); }
uint8_t TwoWire::requestFrom(uint16_t a, uint8_t n, uint8_t) { return wire_request(a, n); }
size_t TwoWire::requestFrom(uint8_t a, size_t n, bool) { return wire_request(a, (int)n); }
uint8_t TwoWire::requestFrom(uint16_t a, uint8_t n) { return wire_request(a, n); }
uint8_t TwoWire::requestFrom(uint8_t a, uint8_t n, uint8_t) { return wire_request(a, n); }
uint8_t TwoWire::requestFrom(uint8_t a, uint8_t n) { return wire_request(a, n); }
uint8_t TwoWire::requestFrom(int a, int n, int) { return wire_request(a, n); }
uint8_t TwoWire::requestFrom(int a, int n) { return wire_request(a, n); }
size_t TwoWire::write(uint8_t) { return 1; }
size_t TwoWire::write(const uint8_t *, size_t n) { return n; }
int TwoWire::available() { return (int)rx.size(); }
int TwoWire::read() {
  if (rx.empty()) return -1;
  int v = rx.front();
  rx.erase(rx.begin());
  return v;
}
int TwoWire::peek() { return rx.empty() ? -1 : rx.front(); }
void TwoWire::flush() {}
size_t TwoWire::write(const char *s) { return strlen(s); }
size_t TwoWire::write(unsigned long) { return 1; }
size_t TwoWire::write(long) { return 1; }
size_t TwoWire::write(unsigned int) { return 1; }
size_t TwoWire::write(int) { return 1; }
void TwoWire::onReceive(void (*)(int)) {}
void TwoWire::onRequest(void (*)(void)) {}
TwoWire Wire(0), Wire1(1);

// ------------------------------------------------------------------ GFX: text and where it lands, not pixels
struct Run { int x, y, size; std::string text; };
struct Gfx {
  int w = 128, h = 64, x = 0, y = 0, sx = 1, sy = 1, addr = 0, rot = 0;
  bool wrap = true, custom_font = false, drew = false;
  std::vector<Run> runs;
  std::string last;
};
static std::map<const void *, Gfx> gfxs;
static Gfx &G(const void *o) { return gfxs[o]; }
Adafruit_GFX::Adafruit_GFX(int16_t w, int16_t h) {
  Gfx &g = G(this);
  g.w = w;
  g.h = h;
}
void Adafruit_GFX::startWrite() {}
void Adafruit_GFX::writePixel(int16_t x, int16_t y, uint16_t c) { drawPixel(x, y, c); }
void Adafruit_GFX::writeFillRect(int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::writeFastVLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::writeFastHLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::writeLine(int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::endWrite() {}
void Adafruit_GFX::setRotation(uint8_t r) {
  Gfx &g = G(this);
  if ((r & 1) != (g.rot & 1)) {
    int t = g.w;
    g.w = g.h;
    g.h = t;
  }
  g.rot = r;
}
void Adafruit_GFX::invertDisplay(bool) {}
void Adafruit_GFX::drawFastVLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawFastHLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillRect(int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillScreen(uint16_t c) {
  Gfx &g = G(this);
  g.runs.clear();
  g.drew = c != 0;
}
void Adafruit_GFX::drawLine(int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawRect(int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawCircle(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawCircleHelper(int16_t, int16_t, int16_t, uint8_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillCircle(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillCircleHelper(int16_t, int16_t, int16_t, uint8_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawTriangle(int16_t, int16_t, int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillTriangle(int16_t, int16_t, int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawRoundRect(int16_t, int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::fillRoundRect(int16_t, int16_t, int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawBitmap(int16_t, int16_t, const uint8_t *, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawBitmap(int16_t, int16_t, const uint8_t *, int16_t, int16_t, uint16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawBitmap(int16_t, int16_t, uint8_t *, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawBitmap(int16_t, int16_t, uint8_t *, int16_t, int16_t, uint16_t, uint16_t) { G(this).drew = true; }
void Adafruit_GFX::drawChar(int16_t x, int16_t y, unsigned char c, uint16_t, uint16_t, uint8_t s) {
  Gfx &g = G(this);
  g.runs.push_back({x, y, s, std::string(1, (char)c)});
}
void Adafruit_GFX::drawChar(int16_t x, int16_t y, unsigned char c, uint16_t a, uint16_t b, uint8_t s, uint8_t) { drawChar(x, y, c, a, b, s); }
void Adafruit_GFX::getTextBounds(const char *s, int16_t x, int16_t y, int16_t *x1, int16_t *y1, uint16_t *w, uint16_t *h) {
  Gfx &g = G(this);
  *x1 = x;
  *y1 = y;
  *w = (uint16_t)(strlen(s) * 6 * g.sx);
  *h = (uint16_t)(8 * g.sy);
}
void Adafruit_GFX::getTextBounds(const __FlashStringHelper *s, int16_t x, int16_t y, int16_t *a, int16_t *b, uint16_t *w, uint16_t *h) { getTextBounds((const char *)s, x, y, a, b, w, h); }
void Adafruit_GFX::getTextBounds(const String &s, int16_t x, int16_t y, int16_t *a, int16_t *b, uint16_t *w, uint16_t *h) { getTextBounds(s.c_str(), x, y, a, b, w, h); }
void Adafruit_GFX::setTextSize(uint8_t s) { setTextSize(s, s); }
void Adafruit_GFX::setTextSize(uint8_t a, uint8_t b) {
  Gfx &g = G(this);
  g.sx = a ? a : 1;
  g.sy = b ? b : 1;
}
void Adafruit_GFX::setFont(const GFXfont *f) { G(this).custom_font = f != nullptr; }
void Adafruit_GFX::setCursor(int16_t x, int16_t y) {
  Gfx &g = G(this);
  g.x = x;
  g.y = y;
}
void Adafruit_GFX::setTextColor(uint16_t) {}
void Adafruit_GFX::setTextColor(uint16_t, uint16_t) {}
void Adafruit_GFX::setTextWrap(bool w) { G(this).wrap = w; }
void Adafruit_GFX::cp437(bool) {}
size_t Adafruit_GFX::write(uint8_t c) {
  Gfx &g = G(this);
  if (c == '\n') {
    g.x = 0;
    g.y += 8 * g.sy;
    return 1;
  }
  if (c == '\r') return 1;
  int cw = 6 * g.sx, ch = 8 * g.sy;
  if (g.wrap && g.x + cw > g.w) {
    g.x = 0;
    g.y += ch;
  }
  if (!g.custom_font && (g.x + cw - g.sx > g.w || g.y + ch > g.h)) warn("display_clipped", std::to_string(g.addr));
  if (!g.runs.empty() && g.runs.back().y == g.y && g.runs.back().size == g.sx && g.runs.back().x + (int)g.runs.back().text.size() * cw == g.x)
    g.runs.back().text += (char)c;
  else
    g.runs.push_back({g.x, g.y, g.sx, std::string(1, (char)c)});
  g.x += cw;
  return 1;
}
int16_t Adafruit_GFX::width() const { return (int16_t)gfxs[this].w; }
int16_t Adafruit_GFX::height() const { return (int16_t)gfxs[this].h; }
uint8_t Adafruit_GFX::getRotation() const { return (uint8_t)gfxs[this].rot; }
int16_t Adafruit_GFX::getCursorX() const { return (int16_t)gfxs[this].x; }
int16_t Adafruit_GFX::getCursorY() const { return (int16_t)gfxs[this].y; }

static void g_frame(Gfx &g) {
  std::vector<Run> rs = g.runs;
  std::sort(rs.begin(), rs.end(), [](const Run &a, const Run &b) { return a.y != b.y ? a.y < b.y : a.x < b.x; });
  std::string out;
  for (auto &r : rs) {
    if (!out.empty()) out += " | ";
    out += r.text;
  }
  if (g.drew) out += out.empty() ? "(graphics)" : " | (graphics)";
  if (out != g.last) {
    g.last = out;
    emit("F " + i2s(now_us) + " " + std::to_string(g.addr) + " " + out);
  }
}
static bool g_begin(Gfx &g, int addr) {
  g.addr = addr;
  advance(5000);
  if (!sim_has_i2c(addr)) {
    warn("i2c_absent", std::to_string(addr));
    return false;
  }
  emit("L " + i2s(now_us) + " " + std::to_string(addr) + " 1");
  return true;
}
Adafruit_SSD1306::Adafruit_SSD1306(uint8_t w, uint8_t h, TwoWire *, int8_t, uint32_t, uint32_t) : Adafruit_GFX(w, h) {}
Adafruit_SSD1306::~Adafruit_SSD1306() {}
bool Adafruit_SSD1306::begin(uint8_t, uint8_t addr, bool, bool) { return g_begin(G(this), addr ? addr : 0x3C); }
void Adafruit_SSD1306::display() {
  advance(25000);
  g_frame(G(this));
}
void Adafruit_SSD1306::clearDisplay() {
  Gfx &g = G(this);
  g.runs.clear();
  g.drew = false;
}
void Adafruit_SSD1306::invertDisplay(bool) {}
void Adafruit_SSD1306::dim(bool) {}
void Adafruit_SSD1306::drawPixel(int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_SSD1306::drawFastHLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_SSD1306::drawFastVLine(int16_t, int16_t, int16_t, uint16_t) { G(this).drew = true; }
void Adafruit_SSD1306::startscrollright(uint8_t, uint8_t) {}
void Adafruit_SSD1306::startscrollleft(uint8_t, uint8_t) {}
void Adafruit_SSD1306::stopscroll() {}
void Adafruit_SSD1306::ssd1306_command(uint8_t c) {
  Gfx &g = G(this);
  if (c == SSD1306_DISPLAYOFF) emit("L " + i2s(now_us) + " " + std::to_string(g.addr) + " 0");
  if (c == SSD1306_DISPLAYON) emit("L " + i2s(now_us) + " " + std::to_string(g.addr) + " 1");
  advance(100);
}
bool Adafruit_SSD1306::getPixel(int16_t, int16_t) { return false; }

Adafruit_GrayOLED::Adafruit_GrayOLED(uint8_t, uint16_t w, uint16_t h, TwoWire *, int8_t, uint32_t, uint32_t) : Adafruit_GFX(w, h) {}
Adafruit_GrayOLED::~Adafruit_GrayOLED() {}
void Adafruit_GrayOLED::clearDisplay() {
  Gfx &g = G(this);
  g.runs.clear();
  g.drew = false;
}
void Adafruit_GrayOLED::invertDisplay(bool) {}
void Adafruit_GrayOLED::setContrast(uint8_t) {}
void Adafruit_GrayOLED::drawPixel(int16_t, int16_t, uint16_t) { G(this).drew = true; }
bool Adafruit_GrayOLED::getPixel(int16_t, int16_t) { return false; }
void Adafruit_GrayOLED::oled_command(uint8_t c) {
  Gfx &g = G(this);
  if (c == SH110X_DISPLAYOFF) emit("L " + i2s(now_us) + " " + std::to_string(g.addr) + " 0");
  if (c == SH110X_DISPLAYON) emit("L " + i2s(now_us) + " " + std::to_string(g.addr) + " 1");
  advance(100);
}
Adafruit_SH110X::Adafruit_SH110X(uint16_t w, uint16_t h, TwoWire *t, int8_t r, uint32_t a, uint32_t b) : Adafruit_GrayOLED(1, w, h, t, r, a, b) {}
Adafruit_SH110X::~Adafruit_SH110X() {}
bool Adafruit_SH110X::begin(uint8_t addr, bool) { return g_begin(G(this), addr); }
void Adafruit_SH110X::display() {
  advance(25000);
  g_frame(G(this));
}
Adafruit_SH1106G::Adafruit_SH1106G(uint16_t w, uint16_t h, TwoWire *t, int8_t r, uint32_t a, uint32_t b) : Adafruit_SH110X(w, h, t, r, a, b) {}
Adafruit_SH1106G::~Adafruit_SH1106G() {}
bool Adafruit_SH1106G::begin(uint8_t addr, bool reset) { return Adafruit_SH110X::begin(addr, reset); }
Adafruit_SH1107::Adafruit_SH1107(uint16_t w, uint16_t h, TwoWire *t, int8_t r, uint32_t a, uint32_t b) : Adafruit_SH110X(w, h, t, r, a, b) {}
Adafruit_SH1107::~Adafruit_SH1107() {}
bool Adafruit_SH1107::begin(uint8_t addr, bool reset) { return Adafruit_SH110X::begin(addr, reset); }

// ------------------------------------------------------------------ addressable LEDs
struct Neo { int pin = -1, n = 0, bright = 255; std::vector<uint32_t> c; };
static std::map<const void *, Neo> neos;
Adafruit_NeoPixel::Adafruit_NeoPixel(uint16_t n, int16_t pin, neoPixelType) {
  Neo &s = neos[this];
  s.n = n;
  s.pin = pin;
  s.c.assign(n, 0);
}
Adafruit_NeoPixel::Adafruit_NeoPixel() {}
Adafruit_NeoPixel::~Adafruit_NeoPixel() {}
bool Adafruit_NeoPixel::begin() {
  Neo &s = neos[this];
  if (valid(s.pin)) {
    pins[s.pin].driving = true;
    pins[s.pin].mode = OUTPUT;
    pins[s.pin].out = 0;
    log_pin(s.pin);
  }
  return true;
}
void Adafruit_NeoPixel::show() {
  Neo &s = neos[this];
  std::string cs;
  char b[8];
  for (uint32_t c : s.c) {
    uint32_t r = (c >> 16 & 255) * s.bright / 255, g = (c >> 8 & 255) * s.bright / 255, bl = (c & 255) * s.bright / 255;
    snprintf(b, sizeof b, "%02x%02x%02x", (unsigned)r, (unsigned)g, (unsigned)bl);
    if (!cs.empty()) cs += ',';
    cs += b;
  }
  emit("X " + i2s(now_us) + " " + std::to_string(s.pin) + " " + std::to_string(s.n) + " " + cs);
  advance(30LL * s.n + 50);
}
void Adafruit_NeoPixel::setPin(int16_t p) { neos[this].pin = p; }
void Adafruit_NeoPixel::setPixelColor(uint16_t n, uint8_t r, uint8_t g, uint8_t b) {
  Neo &s = neos[this];
  if (n < s.n) s.c[n] = (uint32_t)r << 16 | (uint32_t)g << 8 | b;
}
void Adafruit_NeoPixel::setPixelColor(uint16_t n, uint8_t r, uint8_t g, uint8_t b, uint8_t) { setPixelColor(n, r, g, b); }
void Adafruit_NeoPixel::setPixelColor(uint16_t n, uint32_t c) {
  Neo &s = neos[this];
  if (n < s.n) s.c[n] = c;
}
void Adafruit_NeoPixel::fill(uint32_t c, uint16_t first, uint16_t count) {
  Neo &s = neos[this];
  int end = count ? first + count : s.n;
  for (int i = first; i < end && i < s.n; i++) s.c[i] = c;
}
void Adafruit_NeoPixel::setBrightness(uint8_t b) { neos[this].bright = b; }
void Adafruit_NeoPixel::clear() {
  Neo &s = neos[this];
  s.c.assign(s.n, 0);
}
void Adafruit_NeoPixel::updateLength(uint16_t n) {
  Neo &s = neos[this];
  s.n = n;
  s.c.assign(n, 0);
}
void Adafruit_NeoPixel::updateType(neoPixelType) {}
bool Adafruit_NeoPixel::canShow() { return true; }
uint8_t Adafruit_NeoPixel::getBrightness() const { return (uint8_t)neos[this].bright; }
int16_t Adafruit_NeoPixel::getPin() const { return (int16_t)neos[this].pin; }
uint16_t Adafruit_NeoPixel::numPixels() const { return (uint16_t)neos[this].n; }
uint32_t Adafruit_NeoPixel::getPixelColor(uint16_t n) const {
  auto &s = neos[this];
  return n < s.n ? s.c[n] : 0;
}
uint32_t Adafruit_NeoPixel::Color(uint8_t r, uint8_t g, uint8_t b) { return (uint32_t)r << 16 | (uint32_t)g << 8 | b; }
uint32_t Adafruit_NeoPixel::Color(uint8_t r, uint8_t g, uint8_t b, uint8_t w) { return (uint32_t)w << 24 | (uint32_t)r << 16 | (uint32_t)g << 8 | b; }
uint32_t Adafruit_NeoPixel::ColorHSV(uint16_t hue, uint8_t sat, uint8_t val) {
  // the six segments of the wheel, as the library has them, without its gamma
  int h = (hue * 6L) >> 8 & 0xff, seg = (hue * 6L) >> 16;
  int r = 0, g = 0, b = 0;
  switch (seg % 6) {
    case 0: r = 255; g = h; break;
    case 1: r = 255 - h; g = 255; break;
    case 2: g = 255; b = h; break;
    case 3: g = 255 - h; b = 255; break;
    case 4: r = h; b = 255; break;
    default: r = 255; b = 255 - h; break;
  }
  int s1 = sat + 1, v1 = val + 1;
  int c = 255 - sat;
  r = ((r * s1 >> 8) + c) * v1 >> 8;
  g = ((g * s1 >> 8) + c) * v1 >> 8;
  b = ((b * s1 >> 8) + c) * v1 >> 8;
  return (uint32_t)r << 16 | (uint32_t)g << 8 | b;
}
uint8_t Adafruit_NeoPixel::sine8(uint8_t x) { return (uint8_t)(127.5 + 127.5 * sin(x * 2 * 3.14159265 / 256)); }
uint8_t Adafruit_NeoPixel::gamma8(uint8_t x) { return (uint8_t)(pow(x / 255.0, 2.6) * 255 + 0.5); }
uint32_t Adafruit_NeoPixel::gamma32(uint32_t x) {
  return (uint32_t)gamma8(x >> 16 & 255) << 16 | (uint32_t)gamma8(x >> 8 & 255) << 8 | gamma8(x & 255);
}

// ------------------------------------------------------------------ I2C sensors: the environment's channels, x100
// channel 0 light lux, 1 temperature C, 2 humidity %, 3 pressure Pa/100
BH1750::BH1750(byte) {}
bool BH1750::begin(Mode, byte addr, TwoWire *) {
  advance(200);
  if (!sim_has_i2c(addr)) {
    warn("i2c_absent", std::to_string(addr));
    return false;
  }
  return true;
}
bool BH1750::configure(Mode) { return true; }
bool BH1750::setMTreg(byte) { return true; }
bool BH1750::measurementReady(bool) { return true; }
float BH1750::readLightLevel() {
  advance(200);
  return sim_env(0, now_us) / 100.0f;
}
Adafruit_BME280::Adafruit_BME280() {}
Adafruit_BME280::~Adafruit_BME280() {}
bool Adafruit_BME280::begin(uint8_t addr, TwoWire *) {
  advance(2000);
  if (!sim_has_i2c(addr)) {
    warn("i2c_absent", std::to_string(addr));
    return false;
  }
  return true;
}
void Adafruit_BME280::setSampling(sensor_mode, sensor_sampling, sensor_sampling, sensor_sampling, sensor_filter, standby_duration) {}
bool Adafruit_BME280::takeForcedMeasurement() {
  advance(10000);
  return true;
}
float Adafruit_BME280::readTemperature() {
  advance(300);
  return sim_env(1, now_us) / 100.0f;
}
float Adafruit_BME280::readHumidity() {
  advance(300);
  return sim_env(2, now_us) / 100.0f;
}
float Adafruit_BME280::readPressure() {
  advance(300);
  return (float)sim_env(3, now_us);
}
float Adafruit_BME280::readAltitude(float sea) {
  float p = readPressure() / 100.0f;
  return 44330.0f * (1.0f - powf(p / sea, 0.1903f));
}
uint32_t Adafruit_BME280::sensorID() { return 0x60; }

// ------------------------------------------------------------------ flash: Preferences and EEPROM outlive a boot
static std::map<std::string, std::string> nvs;
static bool nvs_read = false;
static void nvs_open() {
  if (nvs_read) return;
  nvs_read = true;
  int n = sim_nvs_size();
  if (n <= 0) return;
  std::string raw(n, 0);
  sim_nvs_load(&raw[0]);
  for (size_t i = 0; i + 8 <= raw.size();) {
    uint32_t a, b;
    memcpy(&a, &raw[i], 4);
    memcpy(&b, &raw[i + 4], 4);
    nvs[raw.substr(i + 8, a)] = raw.substr(i + 8 + a, b);
    i += 8 + a + b;
  }
}
static void nvs_commit() {
  std::string raw;
  for (auto &kv : nvs) {
    uint32_t a = (uint32_t)kv.first.size(), b = (uint32_t)kv.second.size();
    raw.append((const char *)&a, 4);
    raw.append((const char *)&b, 4);
    raw += kv.first;
    raw += kv.second;
  }
  sim_nvs_save(raw.data(), (int)raw.size());
}
static std::map<const void *, std::string> pref_ns;
static std::string pref_key(const void *o, const char *k) { return pref_ns[o] + "/" + (k ? k : ""); }
static size_t pref_put(const void *o, const char *k, const void *v, size_t n) {
  nvs_open();
  nvs[pref_key(o, k)] = std::string((const char *)v, n);
  nvs_commit();
  return n;
}
static bool pref_get(const void *o, const char *k, void *v, size_t n) {
  nvs_open();
  auto it = nvs.find(pref_key(o, k));
  if (it == nvs.end() || it->second.size() != n) return false;
  memcpy(v, it->second.data(), n);
  return true;
}
Preferences::Preferences() {}
Preferences::~Preferences() {}
bool Preferences::begin(const char *name, bool, const char *) {
  pref_ns[this] = name ? name : "";
  return true;
}
void Preferences::end() {}
bool Preferences::clear() {
  nvs_open();
  std::string pre = pref_ns[this] + "/";
  for (auto it = nvs.begin(); it != nvs.end();) it = it->first.rfind(pre, 0) == 0 ? nvs.erase(it) : std::next(it);
  nvs_commit();
  return true;
}
bool Preferences::remove(const char *k) {
  nvs_open();
  bool had = nvs.erase(pref_key(this, k)) > 0;
  nvs_commit();
  return had;
}
#define PREF(NAME, T) \
  size_t Preferences::put##NAME(const char *k, T v) { return pref_put(this, k, &v, sizeof v); } \
  T Preferences::get##NAME(const char *k, T d) { T v; return pref_get(this, k, &v, sizeof v) ? v : d; }
PREF(Char, int8_t)
PREF(UChar, uint8_t)
PREF(Short, int16_t)
PREF(UShort, uint16_t)
PREF(Int, int32_t)
PREF(UInt, uint32_t)
PREF(Long, int32_t)
PREF(ULong, uint32_t)
PREF(Long64, int64_t)
PREF(ULong64, uint64_t)
PREF(Float, float)
PREF(Double, double)
PREF(Bool, bool)
size_t Preferences::putString(const char *k, const char *v) { return pref_put(this, k, v ? v : "", v ? strlen(v) : 0); }
size_t Preferences::putString(const char *k, String v) { return pref_put(this, k, v.c_str(), v.length()); }
size_t Preferences::putBytes(const char *k, const void *v, size_t n) { return pref_put(this, k, v, n); }
bool Preferences::isKey(const char *k) {
  nvs_open();
  return nvs.count(pref_key(this, k)) > 0;
}
size_t Preferences::getString(const char *k, char *v, size_t n) {
  nvs_open();
  auto it = nvs.find(pref_key(this, k));
  if (it == nvs.end() || !n) return 0;
  size_t m = it->second.size() < n - 1 ? it->second.size() : n - 1;
  memcpy(v, it->second.data(), m);
  v[m] = 0;
  return m;
}
String Preferences::getString(const char *k, String d) {
  nvs_open();
  auto it = nvs.find(pref_key(this, k));
  return it == nvs.end() ? d : String(it->second.c_str());
}
size_t Preferences::getBytesLength(const char *k) {
  nvs_open();
  auto it = nvs.find(pref_key(this, k));
  return it == nvs.end() ? 0 : it->second.size();
}
size_t Preferences::getBytes(const char *k, void *buf, size_t n) {
  nvs_open();
  auto it = nvs.find(pref_key(this, k));
  if (it == nvs.end()) return 0;
  size_t m = it->second.size() < n ? it->second.size() : n;
  memcpy(buf, it->second.data(), m);
  return m;
}
size_t Preferences::freeEntries() { return 500; }
static std::string eeprom_buf;
EEPROMClass::EEPROMClass() {}
EEPROMClass::~EEPROMClass() {}
bool EEPROMClass::begin(size_t n) {
  nvs_open();
  auto it = nvs.find("eeprom");
  eeprom_buf = it != nvs.end() ? it->second : std::string(n, (char)0xff);
  eeprom_buf.resize(n, (char)0xff);
  return true;
}
uint8_t EEPROMClass::read(int a) { return a >= 0 && a < (int)eeprom_buf.size() ? (uint8_t)eeprom_buf[a] : 0; }
void EEPROMClass::write(int a, uint8_t v) {
  if (a >= 0 && a < (int)eeprom_buf.size()) eeprom_buf[a] = (char)v;
}
uint16_t EEPROMClass::length() { return (uint16_t)eeprom_buf.size(); }
bool EEPROMClass::commit() {
  nvs["eeprom"] = eeprom_buf;
  nvs_commit();
  return true;
}
void EEPROMClass::end() { commit(); }
uint8_t *EEPROMClass::getDataPtr() { return (uint8_t *)&eeprom_buf[0]; }
const uint8_t *EEPROMClass::getConstDataPtr() const { return (const uint8_t *)eeprom_buf.data(); }
uint8_t &EEPROMClass::operator[](int a) { return (uint8_t &)eeprom_buf[a]; }
#define EE(RN, WN, T) \
  T EEPROMClass::read##RN(int a) { T v; memcpy(&v, getDataPtr() + a, sizeof v); return v; } \
  size_t EEPROMClass::write##WN(int a, T v) { memcpy(getDataPtr() + a, &v, sizeof v); return sizeof v; }
EE(Byte, Byte, uint8_t)
EE(Char, Char, int8_t)
EE(Short, Short, int16_t)
EE(Int, Int, int32_t)
EE(Long, Long, int32_t)
EE(Float, Float, float)
EE(Double, Double, double)
EE(Bool, Bool, bool)
EEPROMClass EEPROM;

// ------------------------------------------------------------------ Wi-Fi: the radio draws, the network never answers
// Nothing is out there in a run: a sketch must go on without it. N <t> <0|1> says the radio is on or off.
static bool radio = false;
static void radio_set(bool on) {
  if (on != radio) emit("N " + i2s(now_us) + " " + (on ? "1" : "0"));
  radio = on;
}
wl_status_t WiFiClass::begin(const char *, const char *, int32_t, const uint8_t *, bool) {
  radio_set(true);
  return WL_DISCONNECTED;
}
wl_status_t WiFiClass::begin(const String &, const String &, int32_t, const uint8_t *, bool) {
  radio_set(true);
  return WL_DISCONNECTED;
}
wl_status_t WiFiClass::begin() {
  radio_set(true);
  return WL_DISCONNECTED;
}
wl_status_t WiFiClass::status() {
  advance(100);
  return radio ? WL_DISCONNECTED : WL_STOPPED;
}
bool WiFiClass::disconnect(bool off, bool) {
  if (off) radio_set(false);
  return true;
}
bool WiFiClass::reconnect() { return false; }
bool WiFiClass::isConnected() { return false; }
bool WiFiClass::setAutoConnect(bool) { return true; }
bool WiFiClass::setAutoReconnect(bool) { return true; }
uint8_t WiFiClass::waitForConnectResult(unsigned long t) {
  advance((int64_t)t * 1000);
  return WL_CONNECT_FAILED;
}
IPAddress WiFiClass::localIP() { return IPAddress(); }
IPAddress WiFiClass::softAPIP() { return IPAddress(); }
String WiFiClass::macAddress() { return String("00:00:00:00:00:00"); }
String WiFiClass::SSID() const { return String(""); }
int8_t WiFiClass::RSSI() { return 0; }
bool WiFiClass::setHostname(const char *) { return true; }
bool WiFiClass::mode(wifi_mode_t m) {
  radio_set(m != WIFI_MODE_NULL);
  return true;
}
wifi_mode_t WiFiClass::getMode() { return radio ? WIFI_MODE_STA : WIFI_MODE_NULL; }
bool WiFiClass::setSleep(bool) { return true; }
bool WiFiClass::setSleep(wifi_ps_type_t) { return true; }
bool WiFiClass::setTxPower(wifi_power_t) { return true; }
bool WiFiClass::softAP(const char *, const char *, int, int, int, bool) {
  radio_set(true);
  return true;
}
bool WiFiClass::softAP(const String &, const String &, int, int, int, bool) {
  radio_set(true);
  return true;
}
bool WiFiClass::softAPdisconnect(bool off) {
  if (off) radio_set(false);
  return true;
}
WiFiClass WiFi;
IPAddress::IPAddress() {}
IPAddress::IPAddress(uint8_t, uint8_t, uint8_t, uint8_t) {}
IPAddress::IPAddress(uint32_t) {}
IPAddress::IPAddress(const IPAddress &) : Printable() {}
IPAddress::operator uint32_t() const { return 0; }
size_t IPAddress::printTo(Print &p) const { return p.print("0.0.0.0"); }
String IPAddress::toString() const { return String("0.0.0.0"); }
Uri::Uri(const char *) {}
Uri::Uri(const String &) {}
Uri::~Uri() {}
WebServer::WebServer(int) {}
WebServer::~WebServer() {}
void WebServer::begin() {}
void WebServer::begin(uint16_t) {}
void WebServer::handleClient() { advance(50); }
void WebServer::close() {}
void WebServer::on(const Uri &, THandlerFunction) {}
void WebServer::on(const Uri &, HTTPMethod, THandlerFunction) {}
void WebServer::onNotFound(THandlerFunction) {}
void WebServer::send(int, const char *, const String &) {}
void WebServer::send(int, const String &, const String &) {}
void WebServer::send(int, const char *, const char *) {}
void WebServer::sendHeader(const String &, const String &, bool) {}
String WebServer::arg(String) { return String(""); }
bool WebServer::hasArg(String) { return false; }

// ------------------------------------------------------------------ entry
int main() {
  now_us = boot_t = sim_boot_t();
  end_t = sim_end_t();
  next_env = sim_next_env(now_us - 1);
  rnd ^= (uint32_t)(sim_boot_n() * 2654435761u);
  if (&__start_rtcmem[0] && &__stop_rtcmem[0]) sim_rtc_load(__start_rtcmem, (int)(__stop_rtcmem - __start_rtcmem));
  emit("B " + i2s(now_us) + " " + std::to_string(sim_boot_n()) + " " + std::to_string(sim_boot_cause()));
  setup();
  for (;;) {
    loop();
    advance(1);
  }
}

#include "libs.inc"
