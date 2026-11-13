// Serial ports. On the XIAO ESP32-C3/S3 (USB CDC on boot) and the Pico, Serial is the USB port: begin() takes an
// optional baud rate; Serial1 is a UART whose begin() needs the baud and may take its RX/TX pins.
#pragma once
#include <functional>
#include "Stream.h"

#define SERIAL_5N1 0x8000010
#define SERIAL_6N1 0x8000014
#define SERIAL_7N1 0x8000018
#define SERIAL_8N1 0x800001c
#define SERIAL_8N2 0x800003c
#define SERIAL_8E1 0x800001e
#define SERIAL_8O1 0x800001f
#define SERIAL_7E1 0x800001a

class HardwareSerial : public Stream {
public:
  HardwareSerial(uint8_t uart_nr);
  void begin(unsigned long baud, uint32_t config = SERIAL_8N1, int8_t rxPin = -1, int8_t txPin = -1, bool invert = false,
             unsigned long timeout_ms = 20000UL, uint8_t rxfifo_full_thrhd = 112);
  void end(void);
  void updateBaudRate(unsigned long baud);
  uint32_t baudRate(void);
  int available(void);
  int availableForWrite(void);
  int peek(void);
  int read(void);
  size_t read(uint8_t *buffer, size_t size);
  size_t read(char *buffer, size_t size);
  void flush(void);
  void flush(bool txOnly);
  size_t write(uint8_t);
  size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  operator bool() const;
  bool setPins(int8_t rxPin, int8_t txPin, int8_t ctsPin = -1, int8_t rtsPin = -1);
  size_t setRxBufferSize(size_t new_size);
  size_t setTxBufferSize(size_t new_size);
  void setDebugOutput(bool);
  void onReceive(std::function<void(void)> function, bool onlyOnTimeout = false);
};

class USBSerialPort : public Stream {
public:
  void begin(unsigned long baud = 0);
  void end(void);
  int available(void);
  int availableForWrite(void);
  int peek(void);
  int read(void);
  size_t read(uint8_t *buffer, size_t size);
  size_t read(char *buffer, size_t size);
  void flush(void);
  size_t write(uint8_t);
  size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  operator bool() const;
  bool isConnected(void);
  bool isPlugged(void);
  void setTxTimeoutMs(uint32_t timeout);
  size_t setRxBufferSize(size_t);
  size_t setTxBufferSize(size_t);
  void setDebugOutput(bool);
  void onReceive(std::function<void(void)> function, bool onlyOnTimeout = false);
  uint32_t baudRate(void);
};

extern USBSerialPort Serial;
extern HardwareSerial Serial0;
extern HardwareSerial Serial1;
#if defined(FW_BOARD_XIAO_ESP32S3) || defined(FW_BOARD_PICO) || defined(FW_BOARD_PICO_W)
extern HardwareSerial Serial2;
#endif
