// LiquidCrystal_I2C (HD44780 behind a PCF8574): the character ROM is ASCII plus Japanese, no Cyrillic.
#pragma once
#include "Arduino.h"
#include "Wire.h"

#define LCD_5x10DOTS 0x04
#define LCD_5x8DOTS 0x00

class LiquidCrystal_I2C : public Print {
public:
  LiquidCrystal_I2C(uint8_t lcd_Addr, uint8_t lcd_cols, uint8_t lcd_rows, uint8_t charsize = LCD_5x8DOTS);
  void begin();
  void begin(uint8_t cols, uint8_t rows, uint8_t charsize = LCD_5x8DOTS);
  void init();
  void clear();
  void home();
  void noDisplay();
  void display();
  void noBlink();
  void blink();
  void noCursor();
  void cursor();
  void scrollDisplayLeft();
  void scrollDisplayRight();
  void leftToRight();
  void rightToLeft();
  void noBacklight();
  void backlight();
  bool getBacklight();
  void setBacklight(uint8_t new_val);
  void autoscroll();
  void noAutoscroll();
  void createChar(uint8_t, uint8_t[]);
  void createChar(uint8_t location, const char *charmap);
  void setCursor(uint8_t, uint8_t);
  virtual size_t write(uint8_t);
  using Print::write;
  void command(uint8_t);
  void printstr(const char[]);
};
