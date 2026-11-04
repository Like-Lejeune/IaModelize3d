// GxEPD2 (ZinggJM): the page loop, the windows and hibernate. A display is GFX text and where it lands; a refresh takes its real seconds.
#pragma once
#include "Adafruit_GFX.h"
#include "SPI.h"
#define GxEPD_BLACK 0x0000
#define GxEPD_DARKGREY 0x7BEF
#define GxEPD_LIGHTGREY 0xC618
#define GxEPD_WHITE 0xFFFF
#define GxEPD_RED 0xF800
#define GxEPD_YELLOW 0xFFE0
class GxEPD2_Panel {
public:
  int16_t cs, dc, rst, busy;
  GxEPD2_Panel(int16_t c, int16_t d, int16_t r, int16_t b) : cs(c), dc(d), rst(r), busy(b) {}
};
class GxEPD2_Display : public Adafruit_GFX {
public:
  GxEPD2_Display(int16_t w, int16_t h);
  void init(uint32_t serial_diag_bitrate = 0);
  void init(uint32_t serial_diag_bitrate, bool initial, uint16_t reset_duration = 10, bool pulldown_rst_mode = false);
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  void setFullWindow();
  void setPartialWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h);
  void firstPage();
  bool nextPage();
  void display(bool partial_update_mode = false);
  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h);
  void refresh(bool partial_update_mode = false);
  void clearScreen(uint8_t value = 0xFF);
  void writeScreenBuffer(uint8_t value = 0xFF);
  void hibernate();
  void powerOff();
};
class GxEPD2_154_D67 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 200, HEIGHT = 200, WIDTH_VISIBLE = 200, HEIGHT_VISIBLE = 200;
  GxEPD2_154_D67(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213_B72 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213_B72(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213_B73 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213_B73(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213_B74 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213_B74(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213_BN : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213_BN(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_213_GDEY0213B74 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 122, HEIGHT = 250, WIDTH_VISIBLE = 122, HEIGHT_VISIBLE = 250;
  GxEPD2_213_GDEY0213B74(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_T94 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_T94(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_T94_V2 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_T94_V2(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_BS : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_BS(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_T5 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_T5(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_T5D : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_T5D(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_M06 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_M06(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_290_GDEY029T94 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 128, HEIGHT = 296, WIDTH_VISIBLE = 128, HEIGHT_VISIBLE = 296;
  GxEPD2_290_GDEY029T94(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_420 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 400, HEIGHT = 300, WIDTH_VISIBLE = 400, HEIGHT_VISIBLE = 300;
  GxEPD2_420(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_420_GDEY042T81 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 400, HEIGHT = 300, WIDTH_VISIBLE = 400, HEIGHT_VISIBLE = 300;
  GxEPD2_420_GDEY042T81(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};
class GxEPD2_750 : public GxEPD2_Panel {
public:
  static const uint16_t WIDTH = 640, HEIGHT = 384, WIDTH_VISIBLE = 640, HEIGHT_VISIBLE = 384;
  GxEPD2_750(int16_t c, int16_t d, int16_t r, int16_t b) : GxEPD2_Panel(c, d, r, b) {}
};

template <typename Panel, uint16_t page_height>
class GxEPD2_BW : public GxEPD2_Display {
public:
  Panel epd2;
  GxEPD2_BW(Panel p) : GxEPD2_Display(Panel::WIDTH, Panel::HEIGHT), epd2(p) {}
};
template <typename Panel, uint16_t page_height>
using GxEPD2_3C = GxEPD2_BW<Panel, page_height>;
#ifndef MAX_DISPLAY_BUFFER_SIZE
#define MAX_DISPLAY_BUFFER_SIZE 65536ul
#endif
