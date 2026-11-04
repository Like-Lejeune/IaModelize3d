// Arduino String (arduino-esp32 cores/esp32/WString.h): numeric constructors are explicit, + goes through
// StringSumHelper, so `String s = 5;` fails and `"a" + String(x)` works, as on the device.
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

class __FlashStringHelper;
#define FPSTR(pstr_pointer) (reinterpret_cast<const __FlashStringHelper *>(pstr_pointer))
#define F(string_literal) (FPSTR(PSTR(string_literal)))

class StringSumHelper;

class String {
  typedef void (String::*StringIfHelperType)() const;
  void StringIfHelper() const {}

public:
  String(const char *cstr = "");
  String(const char *cstr, unsigned int length);
  String(const uint8_t *cstr, unsigned int length);
  String(const String &str);
  String(const __FlashStringHelper *str);
  String(String &&rval);
  explicit String(char c);
  explicit String(unsigned char, unsigned char base = 10);
  explicit String(int, unsigned char base = 10);
  explicit String(unsigned int, unsigned char base = 10);
  explicit String(long, unsigned char base = 10);
  explicit String(unsigned long, unsigned char base = 10);
  explicit String(float, unsigned int decimalPlaces = 2);
  explicit String(double, unsigned int decimalPlaces = 2);
  explicit String(long long, unsigned char base = 10);
  explicit String(unsigned long long, unsigned char base = 10);
  ~String(void);

  bool reserve(unsigned int size);
  unsigned int length(void) const;
  bool isEmpty(void) const;

  String &operator=(const String &rhs);
  String &operator=(const char *cstr);
  String &operator=(const __FlashStringHelper *str);
  String &operator=(String &&rval);

  bool concat(const String &str);
  bool concat(const char *cstr);
  bool concat(const char *cstr, unsigned int length);
  bool concat(const uint8_t *cstr, unsigned int length);
  bool concat(char c);
  bool concat(unsigned char c);
  bool concat(int num);
  bool concat(unsigned int num);
  bool concat(long num);
  bool concat(unsigned long num);
  bool concat(float num);
  bool concat(double num);
  bool concat(long long num);
  bool concat(unsigned long long num);
  bool concat(const __FlashStringHelper *str);

  String &operator+=(const String &rhs);
  String &operator+=(const char *cstr);
  String &operator+=(char c);
  String &operator+=(unsigned char num);
  String &operator+=(int num);
  String &operator+=(unsigned int num);
  String &operator+=(long num);
  String &operator+=(unsigned long num);
  String &operator+=(float num);
  String &operator+=(double num);
  String &operator+=(long long num);
  String &operator+=(unsigned long long num);
  String &operator+=(const __FlashStringHelper *str);

  friend StringSumHelper &operator+(const StringSumHelper &lhs, const String &rhs);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, const char *cstr);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, char c);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, unsigned char num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, int num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, unsigned int num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, long num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, unsigned long num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, float num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, double num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, long long num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, unsigned long long num);
  friend StringSumHelper &operator+(const StringSumHelper &lhs, const __FlashStringHelper *rhs);

#ifdef FW_SIM
  // firmware_sim/runtime.cpp keeps the characters here; the compile check sees no data members
  char *_b = nullptr;
  unsigned int _l = 0;
#endif
  operator StringIfHelperType() const { return 0; }
  int compareTo(const String &s) const;
  bool equals(const String &s) const;
  bool equals(const char *cstr) const;
  bool operator==(const String &rhs) const;
  bool operator==(const char *cstr) const;
  bool operator!=(const String &rhs) const;
  bool operator!=(const char *cstr) const;
  bool operator<(const String &rhs) const;
  bool operator>(const String &rhs) const;
  bool operator<=(const String &rhs) const;
  bool operator>=(const String &rhs) const;
  bool equalsIgnoreCase(const String &s) const;
  bool equalsConstantTime(const String &s) const;
  bool startsWith(const String &prefix) const;
  bool startsWith(const char *prefix) const;
  bool startsWith(const String &prefix, unsigned int offset) const;
  bool endsWith(const String &suffix) const;
  bool endsWith(const char *suffix) const;

  char charAt(unsigned int index) const;
  void setCharAt(unsigned int index, char c);
  char operator[](unsigned int index) const;
  char &operator[](unsigned int index);
  void getBytes(unsigned char *buf, unsigned int bufsize, unsigned int index = 0) const;
  void toCharArray(char *buf, unsigned int bufsize, unsigned int index = 0) const;
  const char *c_str() const;
  char *begin();
  char *end();
  const char *begin() const;
  const char *end() const;

  int indexOf(char ch) const;
  int indexOf(char ch, unsigned int fromIndex) const;
  int indexOf(const String &str) const;
  int indexOf(const String &str, unsigned int fromIndex) const;
  int lastIndexOf(char ch) const;
  int lastIndexOf(char ch, unsigned int fromIndex) const;
  int lastIndexOf(const String &str) const;
  int lastIndexOf(const String &str, unsigned int fromIndex) const;
  String substring(unsigned int beginIndex) const;
  String substring(unsigned int beginIndex, unsigned int endIndex) const;

  void replace(char find, char replace);
  void replace(const String &find, const String &replace);
  void remove(unsigned int index);
  void remove(unsigned int index, unsigned int count);
  void toLowerCase(void);
  void toUpperCase(void);
  void trim(void);

  long toInt(void) const;
  float toFloat(void) const;
  double toDouble(void) const;
};

class StringSumHelper : public String {
public:
  StringSumHelper(const String &s) : String(s) {}
  StringSumHelper(const char *p) : String(p) {}
  StringSumHelper(char c) : String(c) {}
  StringSumHelper(unsigned char num) : String(num) {}
  StringSumHelper(int num) : String(num) {}
  StringSumHelper(unsigned int num) : String(num) {}
  StringSumHelper(long num) : String(num) {}
  StringSumHelper(unsigned long num) : String(num) {}
  StringSumHelper(float num) : String(num) {}
  StringSumHelper(double num) : String(num) {}
  StringSumHelper(long long num) : String(num) {}
  StringSumHelper(unsigned long long num) : String(num) {}
};

extern const String emptyString;
