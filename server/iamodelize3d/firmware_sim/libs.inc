// The libraries behind the accessory library's modules (included by runtime.cpp). Inputs come through sim_env channels the Circuit's
// stimuli name (firmware_sim._accessory): 1 temperature, 4 grams, 5 watts, 6 a tag in range, 7 a GPS fix, 8 a radio packet waiting.
// What leaves the board with nothing else to show for it (keys typed, packets sent, tracks played) is logged like a serial line, so
// the run sees an input change something.
#include <GxEPD2_BW.h>
#include <Adafruit_SPITFT.h>
#include <FS.h>
#include <HX711.h>
#include <RTClib.h>
#include <MFRC522.h>
#include <TinyGPS++.h>
#include <LoRa.h>
#include <PZEM004Tv30.h>
#include <DFRobotDFPlayerMini.h>
#include <AccelStepper.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <SPI.h>
#include <ESP32Servo.h>
#include <U8g2lib.h>
#include <LiquidCrystal_I2C.h>
#include <FastLED.h>
#include <DHT.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <ESPmDNS.h>
#include <fw_sim_api.h>
#include <BleKeyboard.h>
#if !defined(CONFIG_IDF_TARGET_ESP32C3)
#include <USBHIDKeyboard.h>
#include <USBHIDMouse.h>
#include <USBHIDConsumerControl.h>
#endif

static void said(const std::string &what) { emit("S " + i2s(now_us) + " " + what); }
static float env_value(int ch) { return sim_env(ch, now_us) / 100.0f; }

// ---------------------------------------------------------------- e-paper
GxEPD2_Display::GxEPD2_Display(int16_t w, int16_t h) : Adafruit_GFX(w, h) {}
void GxEPD2_Display::init(uint32_t) { g_begin(G(this), 0x3C); }
void GxEPD2_Display::init(uint32_t, bool, uint16_t, bool) { g_begin(G(this), 0x3C); }
void GxEPD2_Display::drawPixel(int16_t, int16_t, uint16_t) { G(this).drew = true; }
void GxEPD2_Display::fillScreen(uint16_t) {
  G(this).runs.clear();
  G(this).drew = false;
}
void GxEPD2_Display::setFullWindow() {}
void GxEPD2_Display::setPartialWindow(uint16_t, uint16_t, uint16_t, uint16_t) {}
void GxEPD2_Display::firstPage() {
  G(this).runs.clear();
  G(this).drew = false;
}
bool GxEPD2_Display::nextPage() {
  advance(2000000);
  g_frame(G(this));
  return false;
}
void GxEPD2_Display::display(bool partial) {
  advance(partial ? 400000 : 2000000);
  g_frame(G(this));
}
void GxEPD2_Display::displayWindow(uint16_t, uint16_t, uint16_t, uint16_t) { display(true); }
void GxEPD2_Display::refresh(bool partial) { display(partial); }
void GxEPD2_Display::clearScreen(uint8_t) {
  G(this).runs.clear();
  display(false);
}
void GxEPD2_Display::writeScreenBuffer(uint8_t) { G(this).runs.clear(); }
void GxEPD2_Display::hibernate() { emit("L " + i2s(now_us) + " " + std::to_string(G(this).addr) + " 0"); }
void GxEPD2_Display::powerOff() { emit("L " + i2s(now_us) + " " + std::to_string(G(this).addr) + " 0"); }

// ---------------------------------------------------------------- colour TFTs
FwTft::FwTft(int16_t w, int16_t h) : Adafruit_GFX(w, h) {}
void FwTft::started() { g_begin(G(this), 0x3C); }
void FwTft::drawPixel(int16_t, int16_t, uint16_t) { G(this).drew = true; }
void FwTft::fillScreen(uint16_t) {
  G(this).runs.clear();
  G(this).drew = false;
  advance(20000);
  g_frame(G(this));
}
size_t FwTft::write(uint8_t c) {
  size_t n = Adafruit_GFX::write(c);
  g_frame(G(this));
  return n;
}
void FwTft::invertDisplay(bool) {}
void FwTft::enableDisplay(bool on) { emit("L " + i2s(now_us) + " " + std::to_string(G(this).addr) + (on ? " 1" : " 0")); }

// ---------------------------------------------------------------- files
struct SimFile { std::string name, *data; size_t at; };
static std::map<std::string, std::string> sim_files;
static std::vector<SimFile> sim_open;
namespace fs {
File FS::open(const char *path, const char *mode, bool create) {
  std::string p(path), m(mode ? mode : "r");
  if (m[0] == 'r' && !sim_files.count(p)) return File();
  std::string &d = sim_files[p];
  if (m[0] == 'w') d.clear();
  advance(2000);
  sim_open.push_back({p, &d, m[0] == 'a' ? d.size() : 0});
  return File((int)sim_open.size() - 1);
}
bool FS::exists(const char *path) { return sim_files.count(path) > 0; }
bool FS::remove(const char *path) { return sim_files.erase(path) > 0; }
bool FS::rename(const char *a, const char *b) {
  if (!sim_files.count(a)) return false;
  sim_files[b] = sim_files[a];
  sim_files.erase(a);
  return true;
}
uint64_t FS::usedBytes() {
  uint64_t n = 0;
  for (auto &f : sim_files) n += f.second.size();
  return n;
}
size_t File::write(uint8_t c) { return write(&c, 1); }
size_t File::write(const uint8_t *b, size_t n) {
  if (h < 0) return 0;
  SimFile &f = sim_open[h];
  if (f.at + n > f.data->size()) f.data->resize(f.at + n);
  std::copy(b, b + n, f.data->begin() + f.at);
  f.at += n;
  advance(n / 4 + 1);
  return n;
}
int File::available() { return h < 0 ? 0 : (int)(sim_open[h].data->size() - sim_open[h].at); }
int File::peek() { return available() > 0 ? (uint8_t)(*sim_open[h].data)[sim_open[h].at] : -1; }
int File::read() {
  int c = peek();
  if (c >= 0) sim_open[h].at++;
  return c;
}
size_t File::read(uint8_t *buf, size_t n) {
  size_t got = 0;
  for (int c; got < n && (c = read()) >= 0; got++) buf[got] = (uint8_t)c;
  advance(got / 4 + 1);
  return got;
}
bool File::seek(uint32_t pos) {
  if (h < 0 || pos > sim_open[h].data->size()) return false;
  sim_open[h].at = pos;
  return true;
}
size_t File::position() { return h < 0 ? 0 : sim_open[h].at; }
size_t File::size() { return h < 0 ? 0 : sim_open[h].data->size(); }
void File::close() {
  if (h >= 0) advance(1000);
  h = -1;
}
const char *File::name() { return h < 0 ? "" : sim_open[h].name.c_str(); }
const char *File::path() { return name(); }
}

// ---------------------------------------------------------------- DS18B20 on OneWire
OneWire::OneWire() {}
OneWire::OneWire(uint8_t) {}
void OneWire::begin(uint8_t) {}
uint8_t OneWire::reset(void) { return 1; }
void OneWire::select(const uint8_t *) {}
void OneWire::skip(void) {}
void OneWire::write(uint8_t, uint8_t) {}
void OneWire::write_bytes(const uint8_t *, uint16_t, bool) {}
uint8_t OneWire::read(void) { return 0; }
void OneWire::read_bytes(uint8_t *b, uint16_t n) { memset(b, 0, n); }
void OneWire::write_bit(uint8_t) {}
uint8_t OneWire::read_bit(void) { return 0; }
void OneWire::depower(void) {}
void OneWire::reset_search() {}
void OneWire::target_search(uint8_t) {}
bool OneWire::search(uint8_t *a, bool) { return false; }
uint8_t OneWire::crc8(const uint8_t *, uint8_t) { return 0; }
DallasTemperature::DallasTemperature() {}
DallasTemperature::DallasTemperature(OneWire *) {}
DallasTemperature::DallasTemperature(OneWire *, uint8_t) {}
void DallasTemperature::setOneWire(OneWire *) {}
void DallasTemperature::setPullupPin(uint8_t) {}
void DallasTemperature::begin(void) {}
uint8_t DallasTemperature::getDeviceCount(void) { return 1; }
uint8_t DallasTemperature::getDS18Count(void) { return 1; }
bool DallasTemperature::validAddress(const uint8_t *) { return true; }
bool DallasTemperature::validFamily(const uint8_t *) { return true; }
bool DallasTemperature::getAddress(uint8_t *a, uint8_t) {
  memset(a, 0x28, 8);
  return true;
}
bool DallasTemperature::isConnected(const uint8_t *) { return true; }
uint8_t DallasTemperature::getResolution() { return 12; }
void DallasTemperature::setResolution(uint8_t) {}
uint8_t DallasTemperature::getResolution(const uint8_t *) { return 12; }
bool DallasTemperature::setResolution(const uint8_t *, uint8_t, bool) { return true; }
void DallasTemperature::setWaitForConversion(bool) {}
bool DallasTemperature::getWaitForConversion(void) { return true; }
void DallasTemperature::setCheckForConversion(bool) {}
bool DallasTemperature::getCheckForConversion(void) { return true; }
DallasTemperature::request_t DallasTemperature::requestTemperatures(void) {
  advance(750000);
  return {true, (unsigned long)(now_us / 1000)};
}
DallasTemperature::request_t DallasTemperature::requestTemperaturesByAddress(const uint8_t *) { return requestTemperatures(); }
DallasTemperature::request_t DallasTemperature::requestTemperaturesByIndex(uint8_t) { return requestTemperatures(); }
int32_t DallasTemperature::getTemp(const uint8_t *) { return (int32_t)(env_value(1) * 128); }
float DallasTemperature::getTempC(const uint8_t *) { return env_value(1); }
float DallasTemperature::getTempF(const uint8_t *) { return env_value(1) * 1.8f + 32; }
float DallasTemperature::getTempCByIndex(uint8_t) { return env_value(1); }
float DallasTemperature::getTempFByIndex(uint8_t) { return env_value(1) * 1.8f + 32; }
bool DallasTemperature::isParasitePowerMode(void) { return false; }
bool DallasTemperature::isConversionComplete(void) { return true; }
uint16_t DallasTemperature::millisToWaitForConversion(uint8_t) { return 750; }
uint16_t DallasTemperature::millisToWaitForConversion() { return 750; }
float DallasTemperature::toFahrenheit(float c) { return c * 1.8f + 32; }
float DallasTemperature::toCelsius(float f) { return (f - 32) / 1.8f; }
float DallasTemperature::rawToCelsius(int32_t r) { return r / 128.0f; }
float DallasTemperature::rawToFahrenheit(int32_t r) { return r / 128.0f * 1.8f + 32; }

// ---------------------------------------------------------------- weight, energy
long HX711::read() {
  advance(100000);
  return (long)(env_value(4) * scale) + offset;
}
float PZEM004Tv30::power() {
  advance(50000);
  return env_value(5);
}

// ---------------------------------------------------------------- a real-time clock from a fixed date
static int32_t rtc_shift = 0;
static const uint32_t RTC_EPOCH = 1793750400UL;  // 2026-11-04 00:00:00 UTC
static const uint8_t DAYS_IN[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
static bool leap(int y) { return y % 4 == 0 && (y % 100 != 0 || y % 400 == 0); }
DateTime::DateTime(uint32_t t) {
  ss = t % 60;
  t /= 60;
  mm = t % 60;
  t /= 60;
  hh = t % 24;
  uint32_t days = t / 24;
  for (y = 1970;; y++) {
    uint32_t n = leap(y) ? 366 : 365;
    if (days < n) break;
    days -= n;
  }
  for (m = 1;; m++) {
    uint32_t n = DAYS_IN[m - 1] + (m == 2 && leap(y));
    if (days < n) break;
    days -= n;
  }
  d = days + 1;
}
DateTime::DateTime(uint16_t yr, uint8_t mo, uint8_t da, uint8_t h, uint8_t mi, uint8_t s) : y(yr), m(mo), d(da), hh(h), mm(mi), ss(s) {}
DateTime::DateTime(const char *, const char *) : DateTime(RTC_EPOCH) {}
DateTime::DateTime(const __FlashStringHelper *, const __FlashStringHelper *) : DateTime(RTC_EPOCH) {}
uint32_t DateTime::unixtime() const {
  uint32_t days = d - 1;
  for (int yy = 1970; yy < y; yy++) days += leap(yy) ? 366 : 365;
  for (int mo = 1; mo < m; mo++) days += DAYS_IN[mo - 1] + (mo == 2 && leap(y));
  return days * 86400UL + hh * 3600UL + mm * 60UL + ss;
}
uint8_t DateTime::dayOfTheWeek() const { return (unixtime() / 86400UL + 4) % 7; }
void FwRtc::adjust(const DateTime &dt) { rtc_shift = (int32_t)(dt.unixtime() - RTC_EPOCH) - (int32_t)(now_us / 1000000); }
DateTime FwRtc::now() {
  advance(500);
  return DateTime((uint32_t)(RTC_EPOCH + rtc_shift + now_us / 1000000));
}

// ---------------------------------------------------------------- tags
bool MFRC522::PICC_IsNewCardPresent() {
  advance(5000);
  bool here = sim_env(6, now_us) > 0;
  bool fresh = here && !was;
  was = here;
  return fresh;
}
bool MFRC522::PICC_ReadCardSerial() {
  uid.size = 4;
  uid.sak = 8;
  const uint8_t id[4] = {0xDE, 0xAD, 0xBE, 0xEF};
  memcpy(uid.uidByte, id, 4);
  return true;
}

// ---------------------------------------------------------------- position
static bool gps_fix() { return sim_env(7, now_us) > 0; }
bool FwGpsLocation::isValid() const { return gps_fix(); }
bool FwGpsDecimal::isValid() const { return gps_fix(); }
bool FwGpsDate::isValid() const { return gps_fix(); }
bool FwGpsTime::isValid() const { return gps_fix(); }
uint8_t FwGpsTime::hour() { return now_us / 3600000000LL % 24; }
uint8_t FwGpsTime::minute() { return now_us / 60000000LL % 60; }
uint8_t FwGpsTime::second() { return now_us / 1000000LL % 60; }
uint32_t TinyGPSPlus::sentencesWithFix() const { return gps_fix() ? 10 : 0; }
double TinyGPSPlus::distanceBetween(double a, double b, double c, double e) {
  const double k = 111195.0;
  double dy = (c - a) * k, dx = (e - b) * k * cos(a * 0.0174533);
  return sqrt(dx * dx + dy * dy);
}

// ---------------------------------------------------------------- radio
LoRaClass LoRa;
static std::string lora_tx, lora_rx;
static size_t lora_at = 0;
static bool lora_was = false;
int LoRaClass::begin(long) {
  advance(5000);
  return 1;
}
int LoRaClass::beginPacket(int) {
  lora_tx.clear();
  return 1;
}
size_t LoRaClass::write(uint8_t c) {
  lora_tx.push_back((char)c);
  return 1;
}
size_t LoRaClass::write(const uint8_t *b, size_t n) {
  lora_tx.append((const char *)b, n);
  return n;
}
int LoRaClass::endPacket(bool) {
  advance(60000 + 2000 * (int64_t)lora_tx.size());
  said("radio sent: " + lora_tx);
  return 1;
}
int LoRaClass::parsePacket(int) {
  advance(200);
  bool here = sim_env(8, now_us) > 0;
  bool fresh = here && !lora_was;
  lora_was = here;
  if (!fresh) return 0;
  lora_rx = "1";
  lora_at = 0;
  return (int)lora_rx.size();
}
int LoRaClass::available() { return (int)(lora_rx.size() - lora_at); }
int LoRaClass::peek() { return available() > 0 ? (uint8_t)lora_rx[lora_at] : -1; }
int LoRaClass::read() {
  int c = peek();
  if (c >= 0) lora_at++;
  return c;
}
void LoRaClass::sleep() {}

// ---------------------------------------------------------------- sound
void DFRobotDFPlayerMini::play(int f) { said("plays track " + std::to_string(f)); }
void DFRobotDFPlayerMini::playMp3Folder(int f) { said("plays track " + std::to_string(f)); }
void DFRobotDFPlayerMini::playFolder(uint8_t a, uint8_t f) { said("plays track " + std::to_string(a) + "/" + std::to_string(f)); }
void DFRobotDFPlayerMini::loop(int f) { said("loops track " + std::to_string(f)); }
void DFRobotDFPlayerMini::stop() { said("sound stops"); }
void DFRobotDFPlayerMini::pause() { said("sound pauses"); }
void DFRobotDFPlayerMini::start() { said("sound starts"); }
void DFRobotDFPlayerMini::next() { said("next track"); }
void DFRobotDFPlayerMini::previous() { said("previous track"); }

// ---------------------------------------------------------------- steppers: pulses on the pin
AccelStepper::AccelStepper(uint8_t, uint8_t p1, uint8_t p2, uint8_t, uint8_t, bool) : stepPin(p1), dirPin(p2) {
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
}
bool AccelStepper::step(float s) {
  if (s == 0) return false;
  unsigned long gap = (unsigned long)(1000000.0f / fabsf(s));
  unsigned long t = micros();
  if (t - last < gap) return false;
  last = t;
  digitalWrite(dirPin, s > 0);
  digitalWrite(stepPin, HIGH);
  digitalWrite(stepPin, LOW);
  pos += s > 0 ? 1 : -1;
  return true;
}
bool AccelStepper::run() {
  if (target == pos) return false;
  step(target > pos ? maxs : -maxs);
  return target != pos;
}
bool AccelStepper::runSpeed() { return step(spd); }
void AccelStepper::runToPosition() {
  while (run()) advance(50);
}

// ---------------------------------------------------------------- USB: what is typed
#if !defined(CONFIG_IDF_TARGET_ESP32C3)
size_t USBHIDKeyboard::press(uint8_t k) {
  said("USB key " + std::to_string(k));
  return 1;
}
size_t USBHIDKeyboard::write(uint8_t k) {
  said("USB key " + std::to_string(k));
  return 1;
}
size_t USBHIDKeyboard::write(const uint8_t *b, size_t n) {
  said("USB types " + std::string((const char *)b, n));
  return n;
}
size_t USBHIDConsumerControl::press(uint16_t k) {
  said("USB media key " + std::to_string(k));
  return 1;
}
void USBHIDMouse::click(uint8_t b) { said("USB mouse click " + std::to_string(b)); }
void USBHIDMouse::move(int8_t x, int8_t y, int8_t, int8_t) { said("USB mouse moves"); }
#endif

// ---------------------------------------------------------------- Bluetooth: what is typed
size_t BleKeyboard::press(uint8_t k) {
  said("BLE key " + std::to_string(k));
  return 1;
}
size_t BleKeyboard::press(const MediaKeyReport k) {
  said("BLE media key " + std::to_string(k[0]));
  return 1;
}
size_t BleKeyboard::write(uint8_t k) {
  said("BLE key " + std::to_string(k));
  return 1;
}
size_t BleKeyboard::write(const MediaKeyReport k) {
  said("BLE media key " + std::to_string(k[0]));
  return 1;
}
size_t BleKeyboard::write(const uint8_t *b, size_t n) {
  said("BLE types " + std::string((const char *)b, n));
  return n;
}

// ---------------------------------------------------------------- what the stubs with inline bodies call
float fw_env_value(int ch) { return ch == 3 ? (float)sim_env(3, now_us) : env_value(ch); }
void fw_said(const char *what) { said(what); }
void fw_wait(long us) { advance(us); }
bool fw_has_i2c(int addr) { return sim_has_i2c(addr); }

#include "libs_auto.inc"
SPIClass SPI;

// ---------------------------------------------------------------- servos: 50 Hz PWM on the pin, as the driver makes it
struct SimServo { int pin = -1, angle = 90, min = 500, max = 2400; };
static std::map<const void *, SimServo> servos;
static void servo_us(SimServo &s, int us) {
  if (s.pin >= 0) ledcWrite(s.pin, (uint32_t)(us * 65535LL / 20000));
}
Servo::Servo() {}
Servo::~Servo() {}
int Servo::attach(int pin) { return attach(pin, 500, 2400); }
int Servo::attach(int pin, int lo, int hi) {
  SimServo &s = servos[this];
  s.pin = pin;
  s.min = lo;
  s.max = hi;
  ledcAttach(pin, 50, 16);
  return 0;
}
void Servo::detach() {
  SimServo &s = servos[this];
  if (s.pin >= 0) ledcWrite(s.pin, 0);
  s.pin = -1;
}
void Servo::write(int v) {
  SimServo &s = servos[this];
  if (v < 200) {
    s.angle = v < 0 ? 0 : v > 180 ? 180 : v;
    servo_us(s, s.min + (s.max - s.min) * s.angle / 180);
  } else {
    writeMicroseconds(v);
  }
}
void Servo::writeMicroseconds(int us) {
  SimServo &s = servos[this];
  s.angle = (us - s.min) * 180 / (s.max - s.min ? s.max - s.min : 1);
  servo_us(s, us);
}
void Servo::release() {}
int Servo::read() { return servos[this].angle; }
int Servo::readMicroseconds() { SimServo &s = servos[this]; return s.min + (s.max - s.min) * s.angle / 180; }
bool Servo::attached() { return servos[this].pin >= 0; }
void Servo::setTimerWidth(int) {}
int Servo::readTimerWidth() { return 16; }
void Servo::setPeriodHertz(int) {}

// ---------------------------------------------------------------- text displays: where it lands, as on the GFX ones
static void g_text(Gfx &g, int x, int y, const char *s) {
  if (!s) return;
  g.runs.push_back({x, y, 1, std::string(s)});
}
static void g_char(Gfx &g, uint8_t c, int step) {
  if (c == '\n' || c == '\r') return;
  if (!g.runs.empty() && g.runs.back().y == g.y && g.runs.back().x + (int)g.runs.back().text.size() * step == g.x)
    g.runs.back().text += (char)c;
  else
    g.runs.push_back({g.x, g.y, 1, std::string(1, (char)c)});
  g.x += step;
}

// U8g2: a buffer sent as a whole
void U8G2::setI2CAddress(uint8_t a) { G(this).addr = a >> 1; }
void U8G2::setPowerSave(uint8_t off) { emit("L " + i2s(now_us) + " " + std::to_string(G(this).addr ? G(this).addr : 0x3C) + (off ? " 0" : " 1")); }
bool U8G2::begin(void) { return g_begin(G(this), G(this).addr ? G(this).addr : 0x3C); }
bool U8G2::begin(uint8_t, uint8_t, uint8_t, uint8_t, uint8_t, uint8_t) { return begin(); }
void U8G2::clearBuffer(void) { G(this).runs.clear(); }
void U8G2::clearDisplay(void) { G(this).runs.clear(); g_frame(G(this)); }
void U8G2::clear(void) { clearDisplay(); }
void U8G2::sendBuffer(void) { advance(25000); g_frame(G(this)); }
void U8G2::updateDisplay(void) { sendBuffer(); }
void U8G2::firstPage(void) { G(this).runs.clear(); }
uint8_t U8G2::nextPage(void) { sendBuffer(); return 0; }
u8g2_uint_t U8G2::drawStr(u8g2_uint_t x, u8g2_uint_t y, const char *s) { g_text(G(this), x, y, s); return s ? 6 * strlen(s) : 0; }
u8g2_uint_t U8G2::drawStrX2(u8g2_uint_t x, u8g2_uint_t y, const char *s) { return drawStr(x, y, s); }
u8g2_uint_t U8G2::drawUTF8(u8g2_uint_t x, u8g2_uint_t y, const char *s) { return drawStr(x, y, s); }
u8g2_uint_t U8G2::drawUTF8X2(u8g2_uint_t x, u8g2_uint_t y, const char *s) { return drawStr(x, y, s); }
void U8G2::setCursor(u8g2_uint_t x, u8g2_uint_t y) { G(this).x = x; G(this).y = y; }
size_t U8G2::write(uint8_t c) { g_char(G(this), c, 6); return 1; }
size_t U8G2::write(const uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) g_char(G(this), b[i], 6); return n; }
u8g2_uint_t U8G2::getDisplayWidth(void) { return G(this).w; }
u8g2_uint_t U8G2::getDisplayHeight(void) { return G(this).h; }
u8g2_uint_t U8G2::getStrWidth(const char *s) { return s ? 6 * strlen(s) : 0; }
u8g2_uint_t U8G2::getUTF8Width(const char *s) { return getStrWidth(s); }
int8_t U8G2::getMaxCharHeight(void) { return 10; }
int8_t U8G2::getMaxCharWidth(void) { return 6; }

// U8x8: characters on a grid, seen at once
void U8X8::setI2CAddress(uint8_t a) { G(this).addr = a >> 1; }
void U8X8::setPowerSave(uint8_t off) { emit("L " + i2s(now_us) + " " + std::to_string(G(this).addr ? G(this).addr : 0x3C) + (off ? " 0" : " 1")); }
bool U8X8::begin(void) { return g_begin(G(this), G(this).addr ? G(this).addr : 0x3C); }
void U8X8::clear(void) { G(this).runs.clear(); g_frame(G(this)); }
void U8X8::clearDisplay(void) { clear(); }
void U8X8::drawString(uint8_t x, uint8_t y, const char *s) { g_text(G(this), x * 8, y * 8, s); g_frame(G(this)); }
uint8_t U8X8::drawUTF8(uint8_t x, uint8_t y, const char *s) { drawString(x, y, s); return s ? strlen(s) : 0; }
void U8X8::setCursor(uint8_t x, uint8_t y) { G(this).x = x * 8; G(this).y = y * 8; }
size_t U8X8::write(uint8_t c) { g_char(G(this), c, 8); g_frame(G(this)); return 1; }
size_t U8X8::write(const uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) g_char(G(this), b[i], 8); g_frame(G(this)); return n; }

// a character LCD on I2C
static std::map<const void *, int> lcd_addr;
LiquidCrystal_I2C::LiquidCrystal_I2C(uint8_t a, uint8_t, uint8_t, uint8_t) { lcd_addr[this] = a; }
void LiquidCrystal_I2C::begin() { g_begin(G(this), lcd_addr[this]); }
void LiquidCrystal_I2C::begin(uint8_t, uint8_t, uint8_t) { begin(); }
void LiquidCrystal_I2C::init() { begin(); }
void LiquidCrystal_I2C::clear() { G(this).runs.clear(); G(this).x = G(this).y = 0; advance(2000); g_frame(G(this)); }
void LiquidCrystal_I2C::home() { G(this).x = G(this).y = 0; }
void LiquidCrystal_I2C::setCursor(uint8_t c, uint8_t r) { G(this).x = c * 6; G(this).y = r * 8; }
size_t LiquidCrystal_I2C::write(uint8_t c) { g_char(G(this), c, 6); g_frame(G(this)); return 1; }
void LiquidCrystal_I2C::display() { emit("L " + i2s(now_us) + " " + std::to_string(lcd_addr[this]) + " 1"); }
void LiquidCrystal_I2C::noDisplay() { emit("L " + i2s(now_us) + " " + std::to_string(lcd_addr[this]) + " 0"); }
void LiquidCrystal_I2C::backlight() {}
void LiquidCrystal_I2C::noBacklight() {}

// ---------------------------------------------------------------- FastLED: the same log line as a NeoPixel's show
struct SimStrip { CRGB *data; int n, pin; };
static std::vector<SimStrip> strips;
static uint8_t fl_bright = 255;
CFastLED FastLED;
static CLEDController fl_controller;
CLEDController &fw_fastled_add(CRGB *data, int n, int pin) {
  strips.push_back({data, n, pin});
  pins[pin].mode = OUTPUT;
  return fl_controller;
}
void CFastLED::setBrightness(uint8_t b) { fl_bright = b; }
uint8_t CFastLED::getBrightness() { return fl_bright; }
void CFastLED::show() { show(fl_bright); }
void CFastLED::show(uint8_t scale) {
  for (auto &s : strips) {
    std::string cs;
    char b[8];
    for (int i = 0; i < s.n; i++) {
      snprintf(b, sizeof b, "%02x%02x%02x", (unsigned)(s.data[i].r * scale / 255), (unsigned)(s.data[i].g * scale / 255), (unsigned)(s.data[i].b * scale / 255));
      if (!cs.empty()) cs += ',';
      cs += b;
    }
    emit("X " + i2s(now_us) + " " + std::to_string(s.pin) + " " + std::to_string(s.n) + " " + cs);
    advance(30LL * s.n + 50);
  }
}
void CFastLED::clear(bool write) {
  for (auto &s : strips) memset((void *)s.data, 0, sizeof(CRGB) * s.n);
  if (write) show();
}
void CFastLED::clearData() { clear(false); }
void CFastLED::showColor(const CRGB &c, uint8_t scale) {
  for (auto &s : strips) for (int i = 0; i < s.n; i++) s.data[i] = c;
  show(scale);
}
void CFastLED::showColor(const CRGB &c) { showColor(c, fl_bright); }
void CFastLED::delay(unsigned long ms) { show(); ::delay(ms); }
int CFastLED::count() { return (int)strips.size(); }
int CFastLED::size() { return strips.empty() ? 0 : strips[0].n; }

// ---------------------------------------------------------------- DHT: temperature and humidity as the run sets them
DHT::DHT(uint8_t, uint8_t, uint8_t) {}
void DHT::begin(uint8_t) {}
float DHT::readTemperature(bool f, bool) { advance(2000); float c = env_value(1); return f ? c * 1.8f + 32 : c; }
float DHT::readHumidity(bool) { advance(2000); return env_value(2); }
float DHT::computeHeatIndex(float t, float, bool) { return t; }
float DHT::computeHeatIndex(bool) { return env_value(1); }
float DHT::convertCtoF(float c) { return c * 1.8f + 32; }
float DHT::convertFtoC(float f) { return (f - 32) / 1.8f; }
bool DHT::read(bool) { return true; }

// ---------------------------------------------------------------- FastLED's colours and helpers
void hsv2rgb_rainbow(const CHSV &c, CRGB &o) {
  int region = c.h / 43, rem = (c.h - region * 43) * 6;
  uint8_t p = c.v * (255 - c.s) / 255, q = c.v * (255 - c.s * rem / 255) / 255, t = c.v * (255 - c.s * (255 - rem) / 255) / 255;
  switch (region) {
    case 0: o.r = c.v; o.g = t; o.b = p; break;
    case 1: o.r = q; o.g = c.v; o.b = p; break;
    case 2: o.r = p; o.g = c.v; o.b = t; break;
    case 3: o.r = p; o.g = q; o.b = c.v; break;
    case 4: o.r = t; o.g = p; o.b = c.v; break;
    default: o.r = c.v; o.g = p; o.b = q;
  }
}
CRGB::CRGB(const CHSV &c) { hsv2rgb_rainbow(c, *this); }
CRGB &CRGB::operator=(const CHSV &c) { hsv2rgb_rainbow(c, *this); return *this; }
CRGB &CRGB::operator=(const uint32_t v) { return setColorCode(v); }
CRGB &CRGB::setRGB(uint8_t a, uint8_t c, uint8_t d) { r = a; g = c; b = d; return *this; }
CRGB &CRGB::setHSV(uint8_t h, uint8_t s_, uint8_t v) { hsv2rgb_rainbow(CHSV(h, s_, v), *this); return *this; }
CRGB &CRGB::setHue(uint8_t h) { return setHSV(h, 255, 255); }
CRGB &CRGB::setColorCode(uint32_t v) { r = v >> 16; g = v >> 8; b = v; return *this; }
static uint8_t add8(int a, int c) { return a + c > 255 ? 255 : a + c; }
static uint8_t sub8(int a, int c) { return a < c ? 0 : a - c; }
CRGB &CRGB::operator+=(const CRGB &o) { r = add8(r, o.r); g = add8(g, o.g); b = add8(b, o.b); return *this; }
CRGB &CRGB::operator-=(const CRGB &o) { r = sub8(r, o.r); g = sub8(g, o.g); b = sub8(b, o.b); return *this; }
CRGB &CRGB::operator%=(uint8_t k) { return nscale8(k); }
CRGB &CRGB::operator|=(const CRGB &o) { r = r > o.r ? r : o.r; g = g > o.g ? g : o.g; b = b > o.b ? b : o.b; return *this; }
CRGB &CRGB::operator&=(const CRGB &o) { r = r < o.r ? r : o.r; g = g < o.g ? g : o.g; b = b < o.b ? b : o.b; return *this; }
CRGB &CRGB::nscale8(uint8_t k) { r = r * k / 256; g = g * k / 256; b = b * k / 256; return *this; }
CRGB &CRGB::nscale8_video(uint8_t k) { return nscale8(k); }
CRGB &CRGB::fadeToBlackBy(uint8_t k) { return nscale8(255 - k); }
CRGB &CRGB::fadeLightBy(uint8_t k) { return nscale8(255 - k); }
uint8_t CRGB::getLuma() const { return (54 * r + 183 * g + 18 * b) / 256; }
uint8_t &CRGB::operator[](uint8_t x) { return x == 0 ? r : x == 1 ? g : b; }
CRGB::operator bool() const { return r || g || b; }
CRGB::operator uint32_t() const { return (uint32_t)r << 16 | (uint32_t)g << 8 | b; }
CRGB operator+(const CRGB &a, const CRGB &c) { CRGB o = a; o += c; return o; }
CRGB operator-(const CRGB &a, const CRGB &c) { CRGB o = a; o -= c; return o; }
CRGB operator*(const CRGB &a, uint8_t d) { return CRGB(add8(0, a.r * d > 255 ? 255 : a.r * d), a.g * d > 255 ? 255 : a.g * d, a.b * d > 255 ? 255 : a.b * d); }
bool operator==(const CRGB &a, const CRGB &c) { return a.r == c.r && a.g == c.g && a.b == c.b; }
bool operator!=(const CRGB &a, const CRGB &c) { return !(a == c); }
CLEDController &CLEDController::setCorrection(CRGB) { return *this; }
CLEDController &CLEDController::setCorrection(LEDColorCorrection) { return *this; }
CLEDController &CLEDController::setTemperature(CRGB) { return *this; }
CLEDController &CLEDController::setTemperature(ColorTemperature) { return *this; }
CLEDController &CLEDController::setDither(uint8_t) { return *this; }
int CLEDController::size() { return strips.empty() ? 0 : strips[0].n; }
CRGB *CLEDController::leds() { return strips.empty() ? nullptr : strips[0].data; }
CRGB &CLEDController::operator[](int x) { return strips[0].data[x]; }
CLEDController &CFastLED::operator[](int) { return fl_controller; }
void fill_solid(CRGB *a, int n, const CRGB &c) { for (int i = 0; i < n; i++) a[i] = c; }
void fill_solid(CHSV *a, int n, const CHSV &c) { for (int i = 0; i < n; i++) a[i] = c; }
void fill_rainbow(CRGB *a, int n, uint8_t h, uint8_t d) { for (int i = 0; i < n; i++, h += d) a[i] = CHSV(h, 240, 255); }
void fill_gradient_RGB(CRGB *a, uint16_t n, const CRGB &x, const CRGB &y) { for (int i = 0; i < n; i++) a[i] = blend(x, y, n > 1 ? i * 255 / (n - 1) : 0); }
void fadeToBlackBy(CRGB *a, uint16_t n, uint8_t k) { for (int i = 0; i < n; i++) a[i].fadeToBlackBy(k); }
void fadeLightBy(CRGB *a, uint16_t n, uint8_t k) { for (int i = 0; i < n; i++) a[i].fadeLightBy(k); }
void nscale8(CRGB *a, uint16_t n, uint8_t k) { for (int i = 0; i < n; i++) a[i].nscale8(k); }
void blur1d(CRGB *, uint16_t, fract8) {}
CRGB blend(const CRGB &p, const CRGB &q, fract8 k) { return CRGB((p.r * (255 - k) + q.r * k) / 255, (p.g * (255 - k) + q.g * k) / 255, (p.b * (255 - k) + q.b * k) / 255); }
CRGB HeatColor(uint8_t t) { return CRGB(t, t > 128 ? (t - 128) * 2 : 0, 0); }
uint8_t scale8(uint8_t i, fract8 k) { return i * k / 256; }
uint8_t scale8_video(uint8_t i, fract8 k) { return i * k / 256; }
uint8_t qadd8(uint8_t a, uint8_t c) { return add8(a, c); }
uint8_t qsub8(uint8_t a, uint8_t c) { return sub8(a, c); }
uint8_t sin8(uint8_t t) { return (uint8_t)(127.5 + 127.5 * sin(t * 6.2831853 / 256)); }
uint8_t cos8(uint8_t t) { return (uint8_t)(127.5 + 127.5 * cos(t * 6.2831853 / 256)); }
int16_t sin16(uint16_t t) { return (int16_t)(32767 * sin(t * 6.2831853 / 65536)); }
uint8_t random8() { return random(256); }
uint8_t random8(uint8_t lim) { return random(lim); }
uint8_t random8(uint8_t a, uint8_t c) { return random(a, c); }
uint16_t random16() { return random(65536); }
uint16_t random16(uint16_t lim) { return random(lim); }
uint16_t random16(uint16_t a, uint16_t c) { return random(a, c); }
void random16_add_entropy(uint16_t) {}
uint8_t beat8(accum88 bpm, uint32_t) { return (uint8_t)(millis() * bpm / 60000 * 256 / 1000 % 256); }
uint8_t beatsin8(accum88 bpm, uint8_t lo, uint8_t hi, uint32_t tb, uint8_t) { return lo + (hi - lo) * sin8(beat8(bpm, tb)) / 255; }
uint16_t beatsin16(accum88 bpm, uint16_t lo, uint16_t hi, uint32_t tb, uint16_t) { return lo + (hi - lo) * sin8(beat8(bpm, tb)) / 255; }
uint8_t ease8InOutQuad(uint8_t i) { return i; }
