// PubSubClient (knolleary): MQTT over a Client; the callback is std::function<void(char*, uint8_t*, unsigned int)>.
#pragma once
#include <functional>
#include "Arduino.h"
#include "Client.h"

#define MQTT_VERSION_3_1 3
#define MQTT_VERSION_3_1_1 4
#define MQTT_VERSION MQTT_VERSION_3_1_1
#define MQTT_MAX_PACKET_SIZE 256
#define MQTT_KEEPALIVE 15
#define MQTT_SOCKET_TIMEOUT 15
#define MQTT_CONNECTION_TIMEOUT -4
#define MQTT_CONNECTION_LOST -3
#define MQTT_CONNECT_FAILED -2
#define MQTT_DISCONNECTED -1
#define MQTT_CONNECTED 0
#define MQTT_CONNECT_BAD_PROTOCOL 1
#define MQTT_CONNECT_BAD_CLIENT_ID 2
#define MQTT_CONNECT_UNAVAILABLE 3
#define MQTT_CONNECT_BAD_CREDENTIALS 4
#define MQTT_CONNECT_UNAUTHORIZED 5
#define MQTTQOS0 (0 << 1)
#define MQTTQOS1 (1 << 1)
#define MQTTQOS2 (2 << 1)
#define MQTT_CALLBACK_SIGNATURE std::function<void(char *, uint8_t *, unsigned int)> callback

class PubSubClient : public Print {
public:
  PubSubClient();
  PubSubClient(Client &client);
  PubSubClient(IPAddress, uint16_t, Client &client);
  PubSubClient(IPAddress, uint16_t, MQTT_CALLBACK_SIGNATURE, Client &client);
  PubSubClient(uint8_t *, uint16_t, Client &client);
  PubSubClient(const char *, uint16_t, Client &client);
  PubSubClient(const char *, uint16_t, MQTT_CALLBACK_SIGNATURE, Client &client);
  ~PubSubClient();
  PubSubClient &setServer(IPAddress ip, uint16_t port);
  PubSubClient &setServer(uint8_t *ip, uint16_t port);
  PubSubClient &setServer(const char *domain, uint16_t port);
  PubSubClient &setCallback(MQTT_CALLBACK_SIGNATURE);
  PubSubClient &setClient(Client &client);
  PubSubClient &setStream(Stream &stream);
  PubSubClient &setKeepAlive(uint16_t keepAlive);
  PubSubClient &setSocketTimeout(uint16_t timeout);
  bool setBufferSize(uint16_t size);
  uint16_t getBufferSize();
  bool connect(const char *id);
  bool connect(const char *id, const char *user, const char *pass);
  bool connect(const char *id, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage);
  bool connect(const char *id, const char *user, const char *pass, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage);
  bool connect(const char *id, const char *user, const char *pass, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage,
               bool cleanSession);
  void disconnect();
  bool publish(const char *topic, const char *payload);
  bool publish(const char *topic, const char *payload, bool retained);
  bool publish(const char *topic, const uint8_t *payload, unsigned int plength);
  bool publish(const char *topic, const uint8_t *payload, unsigned int plength, bool retained);
  bool publish_P(const char *topic, const char *payload, bool retained);
  bool publish_P(const char *topic, const uint8_t *payload, unsigned int plength, bool retained);
  bool beginPublish(const char *topic, unsigned int plength, bool retained);
  int endPublish();
  virtual size_t write(uint8_t);
  virtual size_t write(const uint8_t *buffer, size_t size);
  using Print::write;
  bool subscribe(const char *topic);
  bool subscribe(const char *topic, uint8_t qos);
  bool unsubscribe(const char *topic);
  bool loop();
  bool connected();
  int state();
};
