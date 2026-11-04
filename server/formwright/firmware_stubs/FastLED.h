// FastLED, the basic API: CRGB/CHSV, FastLED.addLeds<CHIPSET, PIN, ORDER>(leds, n), show/clear/brightness, the
// common colour helpers. The data pin is a template argument, so it must be a compile-time constant.
#pragma once
#include "Arduino.h"

enum EOrder { RGB = 0012, RBG = 0021, GRB = 0102, GBR = 0120, BRG = 0201, BGR = 0210 };
typedef uint8_t fract8;
typedef uint16_t accum88;

struct CHSV {
  union { struct { union { uint8_t hue; uint8_t h; }; union { uint8_t saturation; uint8_t sat; uint8_t s; }; union { uint8_t value; uint8_t val; uint8_t v; }; }; uint8_t raw[3]; };
  CHSV() {}
  CHSV(uint8_t ih, uint8_t is, uint8_t iv) : h(ih), s(is), v(iv) {}
};

struct CRGB {
  union { struct { union { uint8_t r; uint8_t red; }; union { uint8_t g; uint8_t green; }; union { uint8_t b; uint8_t blue; }; }; uint8_t raw[3]; };
  CRGB() {}
  CRGB(uint8_t ir, uint8_t ig, uint8_t ib) : r(ir), g(ig), b(ib) {}
  CRGB(uint32_t colorcode) : r((colorcode >> 16) & 0xFF), g((colorcode >> 8) & 0xFF), b(colorcode & 0xFF) {}
  CRGB(const CHSV &rhs);
  CRGB &operator=(const CHSV &rhs);
  CRGB &operator=(const uint32_t colorcode);
  CRGB &setRGB(uint8_t nr, uint8_t ng, uint8_t nb);
  CRGB &setHSV(uint8_t hue, uint8_t sat, uint8_t val);
  CRGB &setHue(uint8_t hue);
  CRGB &setColorCode(uint32_t colorcode);
  CRGB &operator+=(const CRGB &rhs);
  CRGB &operator-=(const CRGB &rhs);
  CRGB &operator%=(uint8_t scaledown);
  CRGB &operator|=(const CRGB &rhs);
  CRGB &operator&=(const CRGB &rhs);
  CRGB &nscale8(uint8_t scaledown);
  CRGB &nscale8_video(uint8_t scaledown);
  CRGB &fadeToBlackBy(uint8_t fadefactor);
  CRGB &fadeLightBy(uint8_t fadefactor);
  uint8_t getLuma() const;
  uint8_t &operator[](uint8_t x);
  explicit operator bool() const;
  operator uint32_t() const;
  enum HTMLColorCode {
    AliceBlue = 0xF0F8FF, Amethyst = 0x9966CC, Aqua = 0x00FFFF, Aquamarine = 0x7FFFD4, Black = 0x000000, Blue = 0x0000FF,
    BlueViolet = 0x8A2BE2, Brown = 0xA52A2A, Chartreuse = 0x7FFF00, Chocolate = 0xD2691E, Coral = 0xFF7F50, Crimson = 0xDC143C,
    Cyan = 0x00FFFF, DarkBlue = 0x00008B, DarkGreen = 0x006400, DarkOrange = 0xFF8C00, DarkRed = 0x8B0000, DeepPink = 0xFF1493,
    DeepSkyBlue = 0x00BFFF, FairyLight = 0xFFE42D, FairyLightNCC = 0xFF9D2A, ForestGreen = 0x228B22, Fuchsia = 0xFF00FF,
    Gold = 0xFFD700, Gray = 0x808080, Grey = 0x808080, Green = 0x008000, GreenYellow = 0xADFF2F, HotPink = 0xFF69B4,
    Indigo = 0x4B0082, Lavender = 0xE6E6FA, LightBlue = 0xADD8E6, LightGreen = 0x90EE90, Lime = 0x00FF00, LimeGreen = 0x32CD32,
    Magenta = 0xFF00FF, Maroon = 0x800000, Navy = 0x000080, Olive = 0x808000, Orange = 0xFFA500, OrangeRed = 0xFF4500,
    Orchid = 0xDA70D6, Pink = 0xFFC0CB, Plaid = 0xCC5533, Purple = 0x800080, Red = 0xFF0000, RoyalBlue = 0x4169E1,
    Salmon = 0xFA8072, SeaGreen = 0x2E8B57, Sienna = 0xA0522D, Silver = 0xC0C0C0, SkyBlue = 0x87CEEB, SpringGreen = 0x00FF7F,
    SteelBlue = 0x4682B4, Teal = 0x008080, Tomato = 0xFF6347, Turquoise = 0x40E0D0, Violet = 0xEE82EE, Wheat = 0xF5DEB3,
    White = 0xFFFFFF, WhiteSmoke = 0xF5F5F5, Yellow = 0xFFFF00, YellowGreen = 0x9ACD32
  };
};
CRGB operator+(const CRGB &p1, const CRGB &p2);
CRGB operator-(const CRGB &p1, const CRGB &p2);
CRGB operator*(const CRGB &p1, uint8_t d);
bool operator==(const CRGB &lhs, const CRGB &rhs);
bool operator!=(const CRGB &lhs, const CRGB &rhs);

enum LEDColorCorrection { TypicalSMD5050 = 0xFFB0F0, TypicalLEDStrip = 0xFFB0F0, Typical8mmPixel = 0xFFE08C, TypicalPixelString = 0xFFE08C, UncorrectedColor = 0xFFFFFF };
enum ColorTemperature { Candle = 0xFF9329, Tungsten40W = 0xFFC58F, Tungsten100W = 0xFFD6AA, Halogen = 0xFFF1E0, CarbonArc = 0xFFFAF4,
                        HighNoonSun = 0xFFFFFB, DirectSunlight = 0xFFFFFF, OvercastSky = 0xC9E2FF, ClearBlueSky = 0x409CFF,
                        UncorrectedTemperature = 0xFFFFFF };

class CLEDController {
public:
  CLEDController &setCorrection(CRGB correction);
  CLEDController &setCorrection(LEDColorCorrection correction);
  CLEDController &setTemperature(CRGB temperature);
  CLEDController &setTemperature(ColorTemperature temperature);
  CLEDController &setDither(uint8_t ditherMode = 1);
  void showLeds(uint8_t brightness = 255);
  void clearLeds(int nLeds = -1);
  int size();
  CRGB *leds();
  CRGB &operator[](int x);
};

#define FW_FASTLED_CHIPSET(name) template <uint8_t DATA_PIN, EOrder RGB_ORDER = RGB> class name {};
FW_FASTLED_CHIPSET(WS2812)
FW_FASTLED_CHIPSET(WS2812B)
FW_FASTLED_CHIPSET(WS2811)
FW_FASTLED_CHIPSET(WS2811_400)
FW_FASTLED_CHIPSET(WS2813)
FW_FASTLED_CHIPSET(WS2815)
FW_FASTLED_CHIPSET(SK6812)
FW_FASTLED_CHIPSET(SK6822)
FW_FASTLED_CHIPSET(APA106)
FW_FASTLED_CHIPSET(PL9823)
FW_FASTLED_CHIPSET(TM1803)
FW_FASTLED_CHIPSET(TM1804)
FW_FASTLED_CHIPSET(TM1809)
FW_FASTLED_CHIPSET(UCS1903)
FW_FASTLED_CHIPSET(GS1903)
template <uint8_t DATA_PIN> class NEOPIXEL {};

CLEDController &fw_fastled_add(CRGB *data, int n, int pin);

class CFastLED {
public:
  template <template <uint8_t DATA_PIN, EOrder RGB_ORDER> class CHIPSET, uint8_t DATA_PIN, EOrder RGB_ORDER>
  static CLEDController &addLeds(CRGB *data, int nLedsOrOffset, int nLedsIfOffset = 0) { return fw_fastled_add(data, nLedsIfOffset ? nLedsIfOffset : nLedsOrOffset, DATA_PIN); }
  template <template <uint8_t DATA_PIN, EOrder RGB_ORDER> class CHIPSET, uint8_t DATA_PIN>
  static CLEDController &addLeds(CRGB *data, int nLedsOrOffset, int nLedsIfOffset = 0) { return fw_fastled_add(data, nLedsIfOffset ? nLedsIfOffset : nLedsOrOffset, DATA_PIN); }
  template <template <uint8_t DATA_PIN> class CHIPSET, uint8_t DATA_PIN>
  static CLEDController &addLeds(CRGB *data, int nLedsOrOffset, int nLedsIfOffset = 0) { return fw_fastled_add(data, nLedsIfOffset ? nLedsIfOffset : nLedsOrOffset, DATA_PIN); }
  void setBrightness(uint8_t scale);
  uint8_t getBrightness();
  void setMaxPowerInVoltsAndMilliamps(uint8_t volts, uint32_t milliamps);
  void setMaxPowerInMilliWatts(uint32_t milliwatts);
  void show(uint8_t scale);
  void show();
  void clear(bool writeData = false);
  void clearData();
  void showColor(const CRGB &color, uint8_t scale);
  void showColor(const CRGB &color);
  void delay(unsigned long ms);
  void setTemperature(const CRGB &temp);
  void setCorrection(const CRGB &correction);
  void setDither(uint8_t ditherMode = 1);
  void setMaxRefreshRate(uint16_t refresh, bool constrain = false);
  uint16_t getFPS();
  int count();
  CLEDController &operator[](int x);
  int size();
  CRGB *leds();
};
extern CFastLED FastLED;

void fill_solid(CRGB *targetArray, int numToFill, const CRGB &color);
void fill_solid(CHSV *targetArray, int numToFill, const CHSV &color);
void fill_rainbow(CRGB *targetArray, int numToFill, uint8_t initialhue, uint8_t deltahue = 5);
void fill_gradient_RGB(CRGB *leds, uint16_t numLeds, const CRGB &c1, const CRGB &c2);
void fadeToBlackBy(CRGB *leds, uint16_t num_leds, uint8_t fadeBy);
void fadeLightBy(CRGB *leds, uint16_t num_leds, uint8_t fadeBy);
void nscale8(CRGB *leds, uint16_t num_leds, uint8_t scale);
void blur1d(CRGB *leds, uint16_t numLeds, fract8 blur_amount);
CRGB blend(const CRGB &p1, const CRGB &p2, fract8 amountOfP2);
CRGB HeatColor(uint8_t temperature);
void hsv2rgb_rainbow(const CHSV &hsv, CRGB &rgb);
uint8_t scale8(uint8_t i, fract8 scale);
uint8_t scale8_video(uint8_t i, fract8 scale);
uint8_t qadd8(uint8_t i, uint8_t j);
uint8_t qsub8(uint8_t i, uint8_t j);
uint8_t sin8(uint8_t theta);
uint8_t cos8(uint8_t theta);
int16_t sin16(uint16_t theta);
uint8_t random8();
uint8_t random8(uint8_t lim);
uint8_t random8(uint8_t min, uint8_t lim);
uint16_t random16();
uint16_t random16(uint16_t lim);
uint16_t random16(uint16_t min, uint16_t lim);
void random16_add_entropy(uint16_t entropy);
uint8_t beatsin8(accum88 beats_per_minute, uint8_t lowest = 0, uint8_t highest = 255, uint32_t timebase = 0, uint8_t phase_offset = 0);
uint16_t beatsin16(accum88 beats_per_minute, uint16_t lowest = 0, uint16_t highest = 65535, uint32_t timebase = 0, uint16_t phase_offset = 0);
uint8_t beat8(accum88 beats_per_minute, uint32_t timebase = 0);
uint8_t ease8InOutQuad(uint8_t i);
#define EVERY_N_MILLISECONDS(N) for (static uint32_t _fw_t = 0; millis() - _fw_t >= (N); _fw_t = millis())
#define EVERY_N_SECONDS(N) EVERY_N_MILLISECONDS((N) * 1000UL)
#define EVERY_N_MILLIS(N) EVERY_N_MILLISECONDS(N)
#define ARRAY_SIZE(A) (sizeof(A) / sizeof((A)[0]))
