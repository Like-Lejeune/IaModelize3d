// MFRC522 (miguelbalboa): a tag comes into range when the run says so; its UID is fixed.
#pragma once
#include "Arduino.h"
#include "SPI.h"
class MFRC522 {
public:
  typedef uint8_t PICC_Type;
  enum { PICC_TYPE_MIFARE_MINI = 1, PICC_TYPE_MIFARE_1K = 2, PICC_TYPE_MIFARE_4K = 3 };
  struct Uid { uint8_t size; uint8_t uidByte[10]; uint8_t sak; };
  Uid uid;
  MFRC522() {}
  MFRC522(uint8_t ss, uint8_t rst) {}
  void PCD_Init() {}
  void PCD_Init(uint8_t ss, uint8_t rst) {}
  void PCD_Reset() {}
  void PCD_AntennaOn() {}
  void PCD_AntennaOff() {}
  void PCD_SetAntennaGain(uint8_t) {}
  void PCD_DumpVersionToSerial() {}
  bool PCD_PerformSelfTest() { return true; }
  bool PICC_IsNewCardPresent();
  bool PICC_ReadCardSerial();
  uint8_t PICC_HaltA() { return 0; }
  void PCD_StopCrypto1() {}
  PICC_Type PICC_GetType(uint8_t sak) { return PICC_TYPE_MIFARE_1K; }
  const __FlashStringHelper *PICC_GetTypeName(PICC_Type) { return (const __FlashStringHelper *)"MIFARE 1KB"; }
private:
  bool was = false;
};
