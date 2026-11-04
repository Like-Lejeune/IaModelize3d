// ArduinoJson 6/7, the basics: JsonDocument (and StaticJsonDocument<N> / DynamicJsonDocument), doc["k"] = v,
// doc["k"].as<T>(), doc["k"] | fallback, implicit reads, iteration, serializeJson / deserializeJson / measureJson.
// Lenient on purpose (variants convert to anything): a false error here costs more than a missed one.
#pragma once
#include <type_traits>
#include "Arduino.h"

class JsonVariant;
class JsonObject;
class JsonArray;
class JsonDocument;

class JsonString {
public:
  JsonString();
  JsonString(const char *);
  const char *c_str() const;
  size_t size() const;
  bool isNull() const;
  explicit operator bool() const;
  bool operator==(const char *) const;
  bool operator!=(const char *) const;
  operator String() const;
};

class DeserializationError {
public:
  enum Code { Ok, EmptyInput, IncompleteInput, InvalidInput, NoMemory, TooDeep };
  DeserializationError();
  DeserializationError(Code c);
  const char *c_str() const;
  const char *f_str() const;
  Code code() const;
  explicit operator bool() const;
  bool operator==(Code) const;
  bool operator!=(Code) const;
  friend bool operator==(const DeserializationError &, const DeserializationError &);
  friend bool operator!=(const DeserializationError &, const DeserializationError &);
};
inline Print &operator<<(Print &p, const DeserializationError &) { return p; }

class JsonPair;
template <typename T> class JsonIterator {
public:
  T operator*() const;
  T *operator->();
  JsonIterator &operator++();
  bool operator!=(const JsonIterator &) const;
  bool operator==(const JsonIterator &) const;
};

class JsonVariant : public Printable {
public:
  JsonVariant();
  template <typename T> JsonVariant &operator=(const T &);
  JsonVariant operator[](const char *key) const;
  JsonVariant operator[](const String &key) const;
  JsonVariant operator[](const JsonString &key) const;
  JsonVariant operator[](int index) const;
  JsonVariant operator[](size_t index) const;
  template <typename T> T as() const;
  template <typename T> bool is() const;
  template <typename T> operator T() const;
  template <typename T> T to();
  template <typename T> bool set(const T &);
  template <typename T> bool add(const T &);
  template <typename T> T add();
  JsonVariant add();
  template <typename T> bool containsKey(const T &) const;
  template <typename T> void remove(const T &);
  JsonObject createNestedObject() const;
  template <typename T> JsonObject createNestedObject(const T &key) const;
  JsonArray createNestedArray() const;
  template <typename T> JsonArray createNestedArray(const T &key) const;
  size_t size() const;
  size_t nesting() const;
  bool isNull() const;
  void clear() const;
  const char *operator|(const char *fallback) const;
  template <typename T> typename std::decay<T>::type operator|(const T &fallback) const;
  size_t printTo(Print &) const override;
  template <typename T> friend bool operator==(const JsonVariant &, const T &);
  template <typename T> friend bool operator!=(const JsonVariant &, const T &);
  template <typename T> friend bool operator<(const JsonVariant &, const T &);
  template <typename T> friend bool operator>(const JsonVariant &, const T &);
  template <typename T> friend bool operator<=(const JsonVariant &, const T &);
  template <typename T> friend bool operator>=(const JsonVariant &, const T &);
};
typedef JsonVariant JsonVariantConst;

class JsonPair {
public:
  JsonString key() const;
  JsonVariant value() const;
};

class JsonObject : public JsonVariant {
public:
  JsonObject();
  using JsonVariant::operator=;
  JsonIterator<JsonPair> begin() const;
  JsonIterator<JsonPair> end() const;
};
typedef JsonObject JsonObjectConst;

class JsonArray : public JsonVariant {
public:
  JsonArray();
  using JsonVariant::operator=;
  JsonIterator<JsonVariant> begin() const;
  JsonIterator<JsonVariant> end() const;
  template <typename T> bool copyFrom(const T &);
};
typedef JsonArray JsonArrayConst;

class JsonDocument : public JsonVariant {
public:
  JsonDocument();
  explicit JsonDocument(size_t capacity);
  JsonDocument(const JsonDocument &);
  using JsonVariant::operator=;
  JsonDocument &operator=(const JsonDocument &);
  size_t memoryUsage() const;
  size_t capacity() const;
  bool overflowed() const;
  void shrinkToFit();
  bool garbageCollect();
  JsonVariant as() const;
  using JsonVariant::as;
};
template <size_t N> class StaticJsonDocument : public JsonDocument {
public:
  StaticJsonDocument();
  using JsonDocument::operator=;
};
class DynamicJsonDocument : public JsonDocument {
public:
  explicit DynamicJsonDocument(size_t capa);
  using JsonDocument::operator=;
};

namespace DeserializationOption {
class Filter { public: explicit Filter(const JsonVariant &); };
class NestingLimit { public: NestingLimit(); explicit NestingLimit(uint8_t); };
}

template <typename TInput> DeserializationError deserializeJson(JsonDocument &doc, TInput &&input);
template <typename TInput, typename... Rest> DeserializationError deserializeJson(JsonDocument &doc, TInput &&input, Rest &&...);
template <typename TInput> DeserializationError deserializeMsgPack(JsonDocument &doc, TInput &&input);
size_t serializeJson(const JsonVariant &source, Print &output);
size_t serializeJson(const JsonVariant &source, String &output);
size_t serializeJson(const JsonVariant &source, char *output, size_t size);
size_t serializeJson(const JsonVariant &source, uint8_t *output, size_t size);
template <size_t N> size_t serializeJson(const JsonVariant &source, char (&output)[N]);
size_t serializeJsonPretty(const JsonVariant &source, Print &output);
size_t serializeJsonPretty(const JsonVariant &source, String &output);
size_t serializeJsonPretty(const JsonVariant &source, char *output, size_t size);
template <size_t N> size_t serializeJsonPretty(const JsonVariant &source, char (&output)[N]);
size_t serializeMsgPack(const JsonVariant &source, Print &output);
size_t measureJson(const JsonVariant &source);
size_t measureJsonPretty(const JsonVariant &source);
#define JSON_OBJECT_SIZE(n) ((n) * 16)
#define JSON_ARRAY_SIZE(n) ((n) * 16)
#define JSON_STRING_SIZE(n) ((n) + 1)
