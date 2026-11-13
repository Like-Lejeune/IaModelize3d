// HTTPClient (arduino-esp32 libraries/HTTPClient).
#pragma once
#include "WiFi.h"
#include "WiFiClientSecure.h"

#define HTTPCLIENT_DEFAULT_TCP_TIMEOUT (5000)
#define HTTPC_ERROR_CONNECTION_REFUSED (-1)
#define HTTPC_ERROR_SEND_HEADER_FAILED (-2)
#define HTTPC_ERROR_SEND_PAYLOAD_FAILED (-3)
#define HTTPC_ERROR_NOT_CONNECTED (-4)
#define HTTPC_ERROR_CONNECTION_LOST (-5)
#define HTTPC_ERROR_NO_STREAM (-6)
#define HTTPC_ERROR_NO_HTTP_SERVER (-7)
#define HTTPC_ERROR_TOO_LESS_RAM (-8)
#define HTTPC_ERROR_ENCODING (-9)
#define HTTPC_ERROR_STREAM_WRITE (-10)
#define HTTPC_ERROR_READ_TIMEOUT (-11)

typedef enum {
  HTTP_CODE_CONTINUE = 100, HTTP_CODE_OK = 200, HTTP_CODE_CREATED = 201, HTTP_CODE_ACCEPTED = 202, HTTP_CODE_NO_CONTENT = 204,
  HTTP_CODE_MOVED_PERMANENTLY = 301, HTTP_CODE_FOUND = 302, HTTP_CODE_SEE_OTHER = 303, HTTP_CODE_NOT_MODIFIED = 304,
  HTTP_CODE_TEMPORARY_REDIRECT = 307, HTTP_CODE_PERMANENT_REDIRECT = 308, HTTP_CODE_BAD_REQUEST = 400,
  HTTP_CODE_UNAUTHORIZED = 401, HTTP_CODE_FORBIDDEN = 403, HTTP_CODE_NOT_FOUND = 404, HTTP_CODE_METHOD_NOT_ALLOWED = 405,
  HTTP_CODE_REQUEST_TIMEOUT = 408, HTTP_CODE_TOO_MANY_REQUESTS = 429, HTTP_CODE_INTERNAL_SERVER_ERROR = 500,
  HTTP_CODE_NOT_IMPLEMENTED = 501, HTTP_CODE_BAD_GATEWAY = 502, HTTP_CODE_SERVICE_UNAVAILABLE = 503,
  HTTP_CODE_GATEWAY_TIMEOUT = 504
} t_http_codes;
typedef enum { HTTPC_DISABLE_FOLLOW_REDIRECTS, HTTPC_STRICT_FOLLOW_REDIRECTS, HTTPC_FORCE_FOLLOW_REDIRECTS } followRedirects_t;

class HTTPClient {
public:
  HTTPClient();
  ~HTTPClient();
  bool begin(WiFiClient &client, String url);
  bool begin(WiFiClient &client, String host, uint16_t port, String uri = "/", bool https = false);
  bool begin(String url);
  bool begin(String url, const char *CAcert);
  bool begin(String host, uint16_t port, String uri = "/");
  bool begin(String host, uint16_t port, String uri, const char *CAcert);
  void end(void);
  bool connected(void);
  void setReuse(bool reuse);
  void setUserAgent(const String &userAgent);
  void setAuthorization(const char *user, const char *password);
  void setAuthorization(const char *auth);
  void setAuthorizationType(const char *authType);
  void setConnectTimeout(int32_t connectTimeout);
  void setTimeout(uint16_t timeout);
  void setFollowRedirects(followRedirects_t follow);
  void setRedirectLimit(uint16_t limit);
  bool setURL(const String &url);
  void useHTTP10(bool usehttp10 = true);
  void addHeader(const String &name, const String &value, bool first = false, bool replace = true);
  int GET();
  int PATCH(uint8_t *payload, size_t size);
  int PATCH(String payload);
  int POST(uint8_t *payload, size_t size);
  int POST(String payload);
  int PUT(uint8_t *payload, size_t size);
  int PUT(String payload);
  int sendRequest(const char *type, String payload);
  int sendRequest(const char *type, uint8_t *payload = NULL, size_t size = 0);
  int sendRequest(const char *type, Stream *stream, size_t size = 0);
  void collectHeaders(const char *headerKeys[], const size_t headerKeysCount);
  String header(const char *name);
  String header(size_t i);
  String headerName(size_t i);
  int headers();
  bool hasHeader(const char *name);
  int getSize(void);
  const String &getLocation(void);
  WiFiClient &getStream(void);
  WiFiClient *getStreamPtr(void);
  int writeToStream(Stream *stream);
  String getString(void);
  static String errorToString(int error);
};
