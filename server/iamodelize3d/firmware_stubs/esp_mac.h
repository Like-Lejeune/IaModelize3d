#pragma once
#include <stdint.h>
typedef int esp_err_t;
typedef enum { ESP_MAC_WIFI_STA, ESP_MAC_WIFI_SOFTAP, ESP_MAC_BT, ESP_MAC_ETH, ESP_MAC_IEEE802154, ESP_MAC_BASE, ESP_MAC_EFUSE_FACTORY,
               ESP_MAC_EFUSE_CUSTOM } esp_mac_type_t;
#ifdef __cplusplus
extern "C" {
#endif
esp_err_t esp_read_mac(uint8_t *mac, esp_mac_type_t type);
esp_err_t esp_efuse_mac_get_default(uint8_t *mac);
esp_err_t esp_base_mac_addr_get(uint8_t *mac);
esp_err_t esp_base_mac_addr_set(const uint8_t *mac);
#ifdef __cplusplus
}
#endif
