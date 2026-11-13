// DFPlayer Mini: what it is told to play shows in the run's log.
#pragma once
#include "Arduino.h"
#include "Stream.h"
class DFRobotDFPlayerMini {
public:
  bool begin(Stream &stream, bool isACK = true, bool doReset = true) { return true; }
  void volume(uint8_t v) {}
  void play(int file = 1);
  void playMp3Folder(int file);
  void playFolder(uint8_t folder, uint8_t file);
  void loop(int file);
  void stop();
  void pause();
  void start();
  void next();
  void previous();
  void EQ(uint8_t) {}
  bool available() { return false; }
  uint8_t readType() { return 0; }
  int read() { return 0; }
  int readState() { return 0; }
};
