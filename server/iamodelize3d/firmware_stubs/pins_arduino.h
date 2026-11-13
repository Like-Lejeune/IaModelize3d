// The board's pin names as its Arduino variant defines them (arduino-esp32 variants/XIAO_ESP32C3, XIAO_ESP32S3;
// arduino-pico variants/rpipico): the values are GPIO numbers. A name the board lacks (LED_BUILTIN on the XIAO
// ESP32-C3) is left out, so using it fails as it does for real.
#pragma once
#include <stdint.h>

#if defined(FW_BOARD_XIAO_ESP32C3)
#define NUM_DIGITAL_PINS 22
#define NUM_ANALOG_INPUTS 6
static const uint8_t TX = 21;
static const uint8_t RX = 20;
static const uint8_t SDA = 6;
static const uint8_t SCL = 7;
static const uint8_t SS = 20;
static const uint8_t MOSI = 10;
static const uint8_t MISO = 9;
static const uint8_t SCK = 8;
static const uint8_t A0 = 2;
static const uint8_t A1 = 3;
static const uint8_t A2 = 4;
static const uint8_t A3 = 5;
static const uint8_t D0 = 2;
static const uint8_t D1 = 3;
static const uint8_t D2 = 4;
static const uint8_t D3 = 5;
static const uint8_t D4 = 6;
static const uint8_t D5 = 7;
static const uint8_t D6 = 21;
static const uint8_t D7 = 20;
static const uint8_t D8 = 8;
static const uint8_t D9 = 9;
static const uint8_t D10 = 10;
#elif defined(FW_BOARD_XIAO_ESP32S3)
#define NUM_DIGITAL_PINS 49
#define NUM_ANALOG_INPUTS 20
#define LED_BUILTIN 21
#define BUILTIN_LED LED_BUILTIN
static const uint8_t TX = 43;
static const uint8_t RX = 44;
static const uint8_t SDA = 5;
static const uint8_t SCL = 6;
static const uint8_t SS = 44;
static const uint8_t MOSI = 9;
static const uint8_t MISO = 8;
static const uint8_t SCK = 7;
static const uint8_t A0 = 1;
static const uint8_t A1 = 2;
static const uint8_t A2 = 3;
static const uint8_t A3 = 4;
static const uint8_t A4 = 5;
static const uint8_t A5 = 6;
static const uint8_t A8 = 7;
static const uint8_t A9 = 8;
static const uint8_t A10 = 9;
static const uint8_t D0 = 1;
static const uint8_t D1 = 2;
static const uint8_t D2 = 3;
static const uint8_t D3 = 4;
static const uint8_t D4 = 5;
static const uint8_t D5 = 6;
static const uint8_t D6 = 43;
static const uint8_t D7 = 44;
static const uint8_t D8 = 7;
static const uint8_t D9 = 8;
static const uint8_t D10 = 9;
static const uint8_t T1 = 1;
static const uint8_t T2 = 2;
static const uint8_t T3 = 3;
static const uint8_t T4 = 4;
static const uint8_t T5 = 5;
static const uint8_t T6 = 6;
static const uint8_t T7 = 7;
static const uint8_t T8 = 8;
static const uint8_t T9 = 9;
#elif defined(FW_BOARD_PICO) || defined(FW_BOARD_PICO_W)
#define NUM_DIGITAL_PINS 30
#define NUM_ANALOG_INPUTS 4
#if defined(FW_BOARD_PICO_W)
#define LED_BUILTIN 64
#else
#define LED_BUILTIN 25
#endif
#define PIN_LED LED_BUILTIN
#define PIN_WIRE0_SDA 4u
#define PIN_WIRE0_SCL 5u
#define PIN_WIRE1_SDA 26u
#define PIN_WIRE1_SCL 27u
#define PIN_SERIAL1_TX 0u
#define PIN_SERIAL1_RX 1u
#define PIN_SPI0_MISO 16u
#define PIN_SPI0_MOSI 19u
#define PIN_SPI0_SCK 18u
#define PIN_SPI0_SS 17u
static const uint8_t SDA = 4;
static const uint8_t SCL = 5;
static const uint8_t TX = 0;
static const uint8_t RX = 1;
static const uint8_t SS = 17;
static const uint8_t MOSI = 19;
static const uint8_t MISO = 16;
static const uint8_t SCK = 18;
static const uint8_t A0 = 26;
static const uint8_t A1 = 27;
static const uint8_t A2 = 28;
static const uint8_t A3 = 29;
static const uint8_t D0 = 0;
static const uint8_t D1 = 1;
static const uint8_t D2 = 2;
static const uint8_t D3 = 3;
static const uint8_t D4 = 4;
static const uint8_t D5 = 5;
static const uint8_t D6 = 6;
static const uint8_t D7 = 7;
static const uint8_t D8 = 8;
static const uint8_t D9 = 9;
static const uint8_t D10 = 10;
static const uint8_t D11 = 11;
static const uint8_t D12 = 12;
static const uint8_t D13 = 13;
static const uint8_t D14 = 14;
static const uint8_t D15 = 15;
static const uint8_t D16 = 16;
static const uint8_t D17 = 17;
static const uint8_t D18 = 18;
static const uint8_t D19 = 19;
static const uint8_t D20 = 20;
static const uint8_t D21 = 21;
static const uint8_t D22 = 22;
static const uint8_t D26 = 26;
static const uint8_t D27 = 27;
static const uint8_t D28 = 28;
#else
// no board named: the generic ESP32 dev board's names
#define LED_BUILTIN 2
static const uint8_t TX = 1;
static const uint8_t RX = 3;
static const uint8_t SDA = 21;
static const uint8_t SCL = 22;
static const uint8_t SS = 5;
static const uint8_t MOSI = 23;
static const uint8_t MISO = 19;
static const uint8_t SCK = 18;
static const uint8_t A0 = 36;
#endif
