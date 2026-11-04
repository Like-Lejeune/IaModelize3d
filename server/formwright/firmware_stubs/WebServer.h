// WebServer (arduino-esp32 libraries/WebServer): routes take std::function handlers; send() has the core's overloads.
#pragma once
#include <functional>
#include "WiFi.h"

enum HTTPMethod { HTTP_DELETE = 0, HTTP_GET = 1, HTTP_HEAD = 2, HTTP_POST = 3, HTTP_PUT = 4, HTTP_OPTIONS = 6, HTTP_PATCH = 28, HTTP_ANY = 255 };
enum HTTPUploadStatus { UPLOAD_FILE_START, UPLOAD_FILE_WRITE, UPLOAD_FILE_END, UPLOAD_FILE_ABORTED };
enum HTTPAuthMethod { BASIC_AUTH, DIGEST_AUTH, OTHER_AUTH };
#define CONTENT_LENGTH_UNKNOWN ((size_t)-1)
#define CONTENT_LENGTH_NOT_SET ((size_t)-2)

typedef struct {
  HTTPUploadStatus status;
  String filename;
  String name;
  String type;
  size_t totalSize;
  size_t currentSize;
  uint8_t buf[1436];
} HTTPUpload;

class Uri {
public:
  Uri(const char *uri);
  Uri(const String &uri);
  Uri(const __FlashStringHelper *uri);
  virtual ~Uri();
};
class UriBraces : public Uri {
public:
  explicit UriBraces(const char *uri);
  explicit UriBraces(const String &uri);
};
class UriRegex : public Uri {
public:
  explicit UriRegex(const char *uri);
  explicit UriRegex(const String &uri);
};
class RequestHandler;
namespace fs { class FS; }

class WebServer {
public:
  WebServer(IPAddress addr, int port = 80);
  WebServer(int port = 80);
  virtual ~WebServer();
  virtual void begin();
  virtual void begin(uint16_t port);
  virtual void handleClient();
  virtual void close();
  void stop();
  bool authenticate(const char *username, const char *password);
  void requestAuthentication(HTTPAuthMethod mode = BASIC_AUTH, const char *realm = NULL, const String &authFailMsg = String(""));
  typedef std::function<void(void)> THandlerFunction;
  void on(const Uri &uri, THandlerFunction fn);
  void on(const Uri &uri, HTTPMethod method, THandlerFunction fn);
  void on(const Uri &uri, HTTPMethod method, THandlerFunction fn, THandlerFunction ufn);
  void addHandler(RequestHandler *handler);
  void serveStatic(const char *uri, fs::FS &fs, const char *path, const char *cache_header = NULL);
  void onNotFound(THandlerFunction fn);
  void onFileUpload(THandlerFunction ufn);
  String uri();
  HTTPMethod method();
  virtual WiFiClient &client();
  HTTPUpload &upload();
  String pathArg(unsigned int i);
  String arg(String name);
  String arg(int i);
  String argName(int i);
  int args();
  bool hasArg(String name);
  void collectHeaders(const char *headerKeys[], const size_t headerKeysCount);
  String header(String name);
  String header(int i);
  String headerName(int i);
  int headers();
  bool hasHeader(String name);
  String hostHeader();
  void send(int code, const char *content_type = NULL, const String &content = String(""));
  void send(int code, char *content_type, const String &content);
  void send(int code, const String &content_type, const String &content);
  void send(int code, const char *content_type, const char *content);
  void send_P(int code, PGM_P content_type, PGM_P content);
  void send_P(int code, PGM_P content_type, PGM_P content, size_t contentLength);
  void send(int code, const char *content_type, const uint8_t *content, size_t contentLength);
  void enableDelay(bool value);
  void enableCORS(bool value = true);
  void enableCrossOrigin(bool value = true);
  void enableETag(bool enable);
  void setContentLength(const size_t contentLength);
  void sendHeader(const String &name, const String &value, bool first = false);
  void sendContent(const String &content);
  void sendContent(const char *content, size_t contentLength);
  void sendContent_P(PGM_P content);
  void sendContent_P(PGM_P content, size_t size);
  static String urlDecode(const String &text);
  template <typename T> size_t streamFile(T &file, const String &contentType, const int code = 200);
};
