// ESP-IDF Wi-Fi calls sketches make directly (power save, TX power, MAC, channel); the types come with WiFi.h.
#pragma once
#include "WiFi.h"
typedef int esp_err_t;
typedef enum { WIFI_IF_STA = 0, WIFI_IF_AP = 1 } wifi_interface_t;
typedef enum { WIFI_SECOND_CHAN_NONE = 0, WIFI_SECOND_CHAN_ABOVE, WIFI_SECOND_CHAN_BELOW } wifi_second_chan_t;
#define WIFI_PROTOCOL_11B 1
#define WIFI_PROTOCOL_11G 2
#define WIFI_PROTOCOL_11N 4
#define WIFI_PROTOCOL_LR 8
#ifdef __cplusplus
extern "C" {
#endif
esp_err_t esp_wifi_start(void);
esp_err_t esp_wifi_stop(void);
esp_err_t esp_wifi_connect(void);
esp_err_t esp_wifi_disconnect(void);
esp_err_t esp_wifi_set_mode(wifi_mode_t mode);
esp_err_t esp_wifi_get_mode(wifi_mode_t *mode);
esp_err_t esp_wifi_set_ps(wifi_ps_type_t type);
esp_err_t esp_wifi_get_ps(wifi_ps_type_t *type);
esp_err_t esp_wifi_set_max_tx_power(int8_t power);
esp_err_t esp_wifi_get_max_tx_power(int8_t *power);
esp_err_t esp_wifi_set_channel(uint8_t primary, wifi_second_chan_t second);
esp_err_t esp_wifi_get_channel(uint8_t *primary, wifi_second_chan_t *second);
esp_err_t esp_wifi_set_promiscuous(bool en);
esp_err_t esp_wifi_set_protocol(wifi_interface_t ifx, uint8_t protocol_bitmap);
esp_err_t esp_wifi_get_mac(wifi_interface_t ifx, uint8_t mac[6]);
esp_err_t esp_wifi_set_mac(wifi_interface_t ifx, const uint8_t mac[6]);
#ifdef __cplusplus
}
#endif
