// WiFi (arduino-esp32 libraries/WiFi): station, access point, scan, events; WiFiClient/Server/UDP come with it.
#pragma once
#include <functional>
#include "Arduino.h"
#include "WiFiClient.h"
#include "WiFiServer.h"
#include "WiFiUdp.h"

typedef enum {
  WL_NO_SHIELD = 255, WL_STOPPED = 254, WL_IDLE_STATUS = 0, WL_NO_SSID_AVAIL = 1, WL_SCAN_COMPLETED = 2, WL_CONNECTED = 3,
  WL_CONNECT_FAILED = 4, WL_CONNECTION_LOST = 5, WL_DISCONNECTED = 6
} wl_status_t;
typedef enum { WIFI_MODE_NULL = 0, WIFI_MODE_STA, WIFI_MODE_AP, WIFI_MODE_APSTA, WIFI_MODE_MAX } wifi_mode_t;
#define WIFI_OFF WIFI_MODE_NULL
#define WIFI_STA WIFI_MODE_STA
#define WIFI_AP WIFI_MODE_AP
#define WIFI_AP_STA WIFI_MODE_APSTA
typedef enum {
  WIFI_AUTH_OPEN = 0, WIFI_AUTH_WEP, WIFI_AUTH_WPA_PSK, WIFI_AUTH_WPA2_PSK, WIFI_AUTH_WPA_WPA2_PSK, WIFI_AUTH_WPA2_ENTERPRISE,
  WIFI_AUTH_WPA3_PSK, WIFI_AUTH_WPA2_WPA3_PSK, WIFI_AUTH_MAX
} wifi_auth_mode_t;
typedef enum {
  WIFI_POWER_21dBm = 84, WIFI_POWER_20_5dBm = 82, WIFI_POWER_20dBm = 80, WIFI_POWER_19_5dBm = 78, WIFI_POWER_19dBm = 76,
  WIFI_POWER_18_5dBm = 74, WIFI_POWER_17dBm = 68, WIFI_POWER_15dBm = 60, WIFI_POWER_13dBm = 52, WIFI_POWER_11dBm = 44,
  WIFI_POWER_8_5dBm = 34, WIFI_POWER_7dBm = 28, WIFI_POWER_5dBm = 20, WIFI_POWER_2dBm = 8, WIFI_POWER_MINUS_1dBm = -4
} wifi_power_t;
typedef enum { WIFI_PS_NONE, WIFI_PS_MIN_MODEM, WIFI_PS_MAX_MODEM } wifi_ps_type_t;
typedef enum {
  ARDUINO_EVENT_WIFI_READY = 0, ARDUINO_EVENT_WIFI_SCAN_DONE, ARDUINO_EVENT_WIFI_STA_START, ARDUINO_EVENT_WIFI_STA_STOP,
  ARDUINO_EVENT_WIFI_STA_CONNECTED, ARDUINO_EVENT_WIFI_STA_DISCONNECTED, ARDUINO_EVENT_WIFI_STA_AUTHMODE_CHANGE,
  ARDUINO_EVENT_WIFI_STA_GOT_IP, ARDUINO_EVENT_WIFI_STA_GOT_IP6, ARDUINO_EVENT_WIFI_STA_LOST_IP, ARDUINO_EVENT_WIFI_AP_START,
  ARDUINO_EVENT_WIFI_AP_STOP, ARDUINO_EVENT_WIFI_AP_STACONNECTED, ARDUINO_EVENT_WIFI_AP_STADISCONNECTED,
  ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED, ARDUINO_EVENT_MAX
} arduino_event_id_t;
typedef arduino_event_id_t WiFiEvent_t;
typedef struct { arduino_event_id_t event_id; } arduino_event_t;
typedef union { int dummy; } arduino_event_info_t;
typedef arduino_event_info_t WiFiEventInfo_t;
typedef void (*WiFiEventCb)(arduino_event_id_t event);
typedef std::function<void(arduino_event_id_t event, arduino_event_info_t info)> WiFiEventFuncCb;
typedef void (*WiFiEventSysCb)(arduino_event_t *event);
typedef size_t wifi_event_id_t;

class WiFiClass {
public:
  wl_status_t begin(const char *ssid, const char *passphrase = NULL, int32_t channel = 0, const uint8_t *bssid = NULL, bool connect = true);
  wl_status_t begin(const String &ssid, const String &passphrase = (const char *)NULL, int32_t channel = 0, const uint8_t *bssid = NULL,
                    bool connect = true);
  wl_status_t begin();
  wl_status_t status();
  bool config(IPAddress local_ip, IPAddress gateway, IPAddress subnet, IPAddress dns1 = (uint32_t)0x00000000, IPAddress dns2 = (uint32_t)0x00000000);
  bool disconnect(bool wifioff = false, bool eraseap = false);
  bool reconnect();
  bool eraseAP(void);
  bool isConnected();
  bool setAutoConnect(bool autoConnect);
  bool getAutoConnect();
  bool setAutoReconnect(bool autoReconnect);
  bool getAutoReconnect();
  uint8_t waitForConnectResult(unsigned long timeoutLength = 60000);
  IPAddress localIP();
  IPAddress subnetMask();
  IPAddress gatewayIP();
  IPAddress dnsIP(uint8_t dns_no = 0);
  IPAddress broadcastIP();
  uint8_t *macAddress(uint8_t *mac);
  String macAddress();
  String SSID() const;
  String psk() const;
  uint8_t *BSSID(uint8_t *bssid = NULL);
  String BSSIDstr();
  int8_t RSSI();
  int32_t channel(void);
  const char *getHostname();
  bool setHostname(const char *hostname);
  bool mode(wifi_mode_t);
  wifi_mode_t getMode();
  bool enableSTA(bool enable);
  bool enableAP(bool enable);
  bool setSleep(bool enabled);
  bool setSleep(wifi_ps_type_t sleepType);
  bool getSleep();
  bool setTxPower(wifi_power_t power);
  wifi_power_t getTxPower();
  bool softAP(const char *ssid, const char *passphrase = NULL, int channel = 1, int ssid_hidden = 0, int max_connection = 4, bool ftm_responder = false);
  bool softAP(const String &ssid, const String &passphrase = emptyString, int channel = 1, int ssid_hidden = 0, int max_connection = 4,
              bool ftm_responder = false);
  bool softAPConfig(IPAddress local_ip, IPAddress gateway, IPAddress subnet, IPAddress dhcp_lease_start = (uint32_t)0);
  bool softAPdisconnect(bool wifioff = false);
  uint8_t softAPgetStationNum();
  IPAddress softAPIP();
  IPAddress softAPBroadcastIP();
  String softAPmacAddress(void);
  String softAPSSID(void) const;
  bool softAPsetHostname(const char *hostname);
  int16_t scanNetworks(bool async = false, bool show_hidden = false, bool passive = false, uint32_t max_ms_per_chan = 300, uint8_t channel = 0,
                       const char *ssid = nullptr, const uint8_t *bssid = nullptr);
  int16_t scanComplete();
  void scanDelete();
  String SSID(uint8_t networkItem);
  wifi_auth_mode_t encryptionType(uint8_t networkItem);
  int32_t RSSI(uint8_t networkItem);
  uint8_t *BSSID(uint8_t networkItem);
  String BSSIDstr(uint8_t networkItem);
  int32_t channel(uint8_t networkItem);
  int hostByName(const char *aHostname, IPAddress &aResult);
  wifi_event_id_t onEvent(WiFiEventCb cbEvent, arduino_event_id_t event = ARDUINO_EVENT_MAX);
  wifi_event_id_t onEvent(WiFiEventFuncCb cbEvent, arduino_event_id_t event = ARDUINO_EVENT_MAX);
  wifi_event_id_t onEvent(WiFiEventSysCb cbEvent, arduino_event_id_t event = ARDUINO_EVENT_MAX);
  void removeEvent(wifi_event_id_t id);
  void printDiag(Print &dest);
};

extern WiFiClass WiFi;
// the IDF calls (esp_wifi_set_ps ...) come along, as they reach most sketches through the core's own headers
#include "esp_wifi.h"
