// U8g2 (U8g2lib.h): the U8G2 and U8X8 methods; the display classes (U8G2_SSD1306_128X64_NONAME_F_HW_I2C ...) and the
// fonts a sketch names are declared by the checker in fw_u8g2_gen.h (there are thousands of each), with the constructor
// arguments their bus takes. print() writes UTF-8 only after enableUTF8Print(), and only with a font that has the
// glyphs (u8g2_font_6x13_t_cyrillic for Cyrillic); drawStr() is single-byte, drawUTF8() is UTF-8.
#pragma once
#include "Arduino.h"
#include "Wire.h"
#include "SPI.h"

typedef uint16_t u8g2_uint_t;
typedef struct u8g2_cb_struct { int dummy; } u8g2_cb_t;
typedef struct u8g2_struct { int dummy; } u8g2_t;
typedef struct u8x8_struct { int dummy; } u8x8_t;
extern const u8g2_cb_t u8g2_cb_r0;
extern const u8g2_cb_t u8g2_cb_r1;
extern const u8g2_cb_t u8g2_cb_r2;
extern const u8g2_cb_t u8g2_cb_r3;
extern const u8g2_cb_t u8g2_cb_mirror;
extern const u8g2_cb_t u8g2_cb_mirror_vertical;
#define U8G2_R0 (&u8g2_cb_r0)
#define U8G2_R1 (&u8g2_cb_r1)
#define U8G2_R2 (&u8g2_cb_r2)
#define U8G2_R3 (&u8g2_cb_r3)
#define U8G2_MIRROR (&u8g2_cb_mirror)
#define U8G2_MIRROR_VERTICAL (&u8g2_cb_mirror_vertical)
#define U8X8_PIN_NONE 255
#define U8G2_DRAW_UPPER_RIGHT 0x01
#define U8G2_DRAW_UPPER_LEFT 0x02
#define U8G2_DRAW_LOWER_LEFT 0x04
#define U8G2_DRAW_LOWER_RIGHT 0x08
#define U8G2_DRAW_ALL (U8G2_DRAW_UPPER_RIGHT | U8G2_DRAW_UPPER_LEFT | U8G2_DRAW_LOWER_RIGHT | U8G2_DRAW_LOWER_LEFT)
#define U8G2_BTN_SHADOW0 0x08
#define U8G2_BTN_INV 0x20
#define U8G2_BTN_BW1 0x01
#define U8G2_BTN_HCENTER 0x40
#define U8G2_FONT_SECTION(name)
#define U8X8_FONT_SECTION(name)

class U8X8 : public Print {
public:
  u8x8_t *getU8x8(void);
  uint32_t getBusClock(void);
  void setBusClock(uint32_t clock_speed);
  void setI2CAddress(uint8_t adr);
  uint8_t getCols(void);
  uint8_t getRows(void);
  void drawTile(uint8_t x, uint8_t y, uint8_t cnt, uint8_t *tile_ptr);
  void initDisplay(void);
  void sendF(const char *fmt, ...);
  void clearDisplay(void);
  void fillDisplay(void);
  void setPowerSave(uint8_t is_enable);
  void setFlipMode(uint8_t mode);
  void setContrast(uint8_t value);
  void refreshDisplay(void);
  bool begin(void);
  void setFont(const uint8_t *font_8x8);
  void drawGlyph(uint8_t x, uint8_t y, uint8_t encoding);
  void draw2x2Glyph(uint8_t x, uint8_t y, uint8_t encoding);
  void drawString(uint8_t x, uint8_t y, const char *s);
  void draw2x2String(uint8_t x, uint8_t y, const char *s);
  void draw1x2String(uint8_t x, uint8_t y, const char *s);
  uint8_t drawUTF8(uint8_t x, uint8_t y, const char *s);
  uint8_t draw2x2UTF8(uint8_t x, uint8_t y, const char *s);
  uint8_t draw1x2UTF8(uint8_t x, uint8_t y, const char *s);
  uint8_t getUTF8Len(const char *s);
  void clearLine(uint8_t line);
  void setInverseFont(uint8_t value);
  void inverse(void);
  void noInverse(void);
  void enableUTF8Print(void);
  void disableUTF8Print(void);
  void setCursor(uint8_t x, uint8_t y);
  size_t write(uint8_t v);
  size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  void clear(void);
  void home(void);
  void noDisplay(void);
  void display(void);
};

class U8G2 : public Print {
public:
  u8g2_t *getU8g2(void);
  u8x8_t *getU8x8(void);
  uint32_t getBusClock(void);
  void setBusClock(uint32_t clock_speed);
  void setI2CAddress(uint8_t adr);
  void enableUTF8Print(void);
  void disableUTF8Print(void);
  uint8_t getCols(void);
  uint8_t getRows(void);
  void drawTile(uint8_t x, uint8_t y, uint8_t cnt, uint8_t *tile_ptr);
  void initDisplay(void);
  void clearDisplay(void);
  void setPowerSave(uint8_t is_enable);
  void setFlipMode(uint8_t mode);
  void setContrast(uint8_t value);
  void setDisplayRotation(const u8g2_cb_t *u8g2_cb);
  bool begin(void);
  bool begin(uint8_t menu_select_pin, uint8_t menu_next_pin, uint8_t menu_prev_pin, uint8_t menu_up_pin = U8X8_PIN_NONE,
             uint8_t menu_down_pin = U8X8_PIN_NONE, uint8_t menu_home_pin = U8X8_PIN_NONE);
  void beginSimple(void);
  void setMaxClipWindow(void);
  void setClipWindow(u8g2_uint_t clip_x0, u8g2_uint_t clip_y0, u8g2_uint_t clip_x1, u8g2_uint_t clip_y1);
  u8g2_uint_t getDisplayHeight(void);
  u8g2_uint_t getDisplayWidth(void);
  void sendBuffer(void);
  void clearBuffer(void);
  void firstPage(void);
  uint8_t nextPage(void);
  uint8_t *getBufferPtr(void);
  uint8_t getBufferTileHeight(void);
  uint8_t getBufferTileWidth(void);
  void setAutoPageClear(uint8_t mode);
  void updateDisplayArea(uint8_t tx, uint8_t ty, uint8_t tw, uint8_t th);
  void updateDisplay(void);
  void refreshDisplay(void);
  void setDrawColor(uint8_t color_index);
  uint8_t getDrawColor(void);
  void drawPixel(u8g2_uint_t x, u8g2_uint_t y);
  void drawHLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w);
  void drawVLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t h);
  void drawHVLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t len, uint8_t dir);
  void drawFrame(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h);
  void drawRFrame(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, u8g2_uint_t r);
  void drawBox(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h);
  void drawRBox(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, u8g2_uint_t r);
  void drawButtonUTF8(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t flags, u8g2_uint_t width, u8g2_uint_t padding_h, u8g2_uint_t padding_v,
                      const char *text);
  void drawCircle(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rad, uint8_t opt = U8G2_DRAW_ALL);
  void drawDisc(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rad, uint8_t opt = U8G2_DRAW_ALL);
  void drawEllipse(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rx, u8g2_uint_t ry, uint8_t opt = U8G2_DRAW_ALL);
  void drawFilledEllipse(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rx, u8g2_uint_t ry, uint8_t opt = U8G2_DRAW_ALL);
  void drawLine(u8g2_uint_t x1, u8g2_uint_t y1, u8g2_uint_t x2, u8g2_uint_t y2);
  void setBitmapMode(uint8_t is_transparent);
  void drawBitmap(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t cnt, u8g2_uint_t h, const uint8_t *bitmap);
  void drawXBM(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, const uint8_t *bitmap);
  void drawXBMP(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, const uint8_t *bitmap);
  void drawTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2);
  void setFont(const uint8_t *font);
  void setFontMode(uint8_t is_transparent);
  void setFontDirection(uint8_t dir);
  int8_t getAscent(void);
  int8_t getDescent(void);
  void setFontPosBaseline(void);
  void setFontPosBottom(void);
  void setFontPosTop(void);
  void setFontPosCenter(void);
  void setFontRefHeightText(void);
  void setFontRefHeightExtendedText(void);
  void setFontRefHeightAll(void);
  u8g2_uint_t drawGlyph(u8g2_uint_t x, u8g2_uint_t y, uint16_t encoding);
  u8g2_uint_t drawGlyphX2(u8g2_uint_t x, u8g2_uint_t y, uint16_t encoding);
  u8g2_uint_t drawStr(u8g2_uint_t x, u8g2_uint_t y, const char *s);
  u8g2_uint_t drawStrX2(u8g2_uint_t x, u8g2_uint_t y, const char *s);
  u8g2_uint_t drawUTF8(u8g2_uint_t x, u8g2_uint_t y, const char *s);
  u8g2_uint_t drawUTF8X2(u8g2_uint_t x, u8g2_uint_t y, const char *s);
  u8g2_uint_t drawExtUTF8(u8g2_uint_t x, u8g2_uint_t y, uint8_t to_left, const uint16_t *kerning_table, const char *s);
  u8g2_uint_t getStrWidth(const char *s);
  u8g2_uint_t getUTF8Width(const char *s);
  int8_t getMaxCharHeight(void);
  int8_t getMaxCharWidth(void);
  void setCursor(u8g2_uint_t x, u8g2_uint_t y);
  u8g2_uint_t getCursorX(void);
  u8g2_uint_t getCursorY(void);
  size_t write(uint8_t v);
  size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  void sleepOn(void);
  void sleepOff(void);
  void clear(void);
  void noDisplay(void);
  void display(void);
  void home(void);
  uint8_t userInterfaceSelectionList(const char *title, uint8_t start_pos, const char *sl);
  uint8_t userInterfaceMessage(const char *title1, const char *title2, const char *title3, const char *buttons);
  uint8_t userInterfaceInputValue(const char *title, const char *pre, uint8_t *value, uint8_t lo, uint8_t hi, uint8_t digits, const char *post);
  uint8_t getMenuEvent(void);
};

// display classes by bus, as U8g2lib.h declares them
#define FW_U8G2_HW_I2C(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t reset = U8X8_PIN_NONE, uint8_t clock = U8X8_PIN_NONE, uint8_t data = U8X8_PIN_NONE); };
#define FW_U8G2_2ND_HW_I2C(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_SW_I2C(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t clock, uint8_t data, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_4W_SW_SPI(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t clock, uint8_t data, uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_4W_HW_SPI(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_2ND_4W_HW_SPI(n) FW_U8G2_4W_HW_SPI(n)
#define FW_U8G2_3W_SW_SPI(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t clock, uint8_t data, uint8_t cs, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_3W_HW_SPI(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t cs, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8G2_PARALLEL(n) class n : public U8G2 { public: n(const u8g2_cb_t *rotation, uint8_t d0, uint8_t d1, uint8_t d2, uint8_t d3, uint8_t d4, uint8_t d5, uint8_t d6, uint8_t d7, uint8_t enable, uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_HW_I2C(n) class n : public U8X8 { public: n(uint8_t reset = U8X8_PIN_NONE, uint8_t clock = U8X8_PIN_NONE, uint8_t data = U8X8_PIN_NONE); };
#define FW_U8X8_2ND_HW_I2C(n) class n : public U8X8 { public: n(uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_SW_I2C(n) class n : public U8X8 { public: n(uint8_t clock, uint8_t data, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_4W_SW_SPI(n) class n : public U8X8 { public: n(uint8_t clock, uint8_t data, uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_4W_HW_SPI(n) class n : public U8X8 { public: n(uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_2ND_4W_HW_SPI(n) FW_U8X8_4W_HW_SPI(n)
#define FW_U8X8_3W_SW_SPI(n) class n : public U8X8 { public: n(uint8_t clock, uint8_t data, uint8_t cs, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_3W_HW_SPI(n) class n : public U8X8 { public: n(uint8_t cs, uint8_t reset = U8X8_PIN_NONE); };
#define FW_U8X8_PARALLEL(n) class n : public U8X8 { public: n(uint8_t d0, uint8_t d1, uint8_t d2, uint8_t d3, uint8_t d4, uint8_t d5, uint8_t d6, uint8_t d7, uint8_t enable, uint8_t cs, uint8_t dc, uint8_t reset = U8X8_PIN_NONE); };
#if __has_include("fw_u8g2_gen.h")
#include "fw_u8g2_gen.h"
#endif
