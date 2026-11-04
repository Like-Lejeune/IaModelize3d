// ESP-NOW. The receive callback took the sender's MAC before IDF 5 and takes esp_now_recv_info_t since (arduino-esp32 3.x);
// both are accepted here, as are both send callbacks: which core the person builds with is not known.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "esp_wifi.h"
typedef int esp_err_t;
#define ESP_NOW_ETH_ALEN 6
#define ESP_NOW_KEY_LEN 16
#define ESP_NOW_MAX_DATA_LEN 250
typedef enum { ESP_NOW_SEND_SUCCESS = 0, ESP_NOW_SEND_FAIL } esp_now_send_status_t;
typedef struct {
  uint8_t peer_addr[ESP_NOW_ETH_ALEN];
  uint8_t lmk[ESP_NOW_KEY_LEN];
  uint8_t channel;
  wifi_interface_t ifidx;
  bool encrypt;
  void *priv;
} esp_now_peer_info_t;
typedef struct {
  uint8_t *src_addr;
  uint8_t *des_addr;
  void *rx_ctrl;
} esp_now_recv_info_t;
typedef struct {
  const uint8_t *des_addr;
  const uint8_t *src_addr;
} wifi_tx_info_t;
#ifdef __cplusplus
esp_err_t esp_now_register_recv_cb(void (*cb)(const esp_now_recv_info_t *info, const uint8_t *data, int len));
esp_err_t esp_now_register_recv_cb(void (*cb)(const uint8_t *mac, const uint8_t *data, int len));
esp_err_t esp_now_register_send_cb(void (*cb)(const uint8_t *mac, esp_now_send_status_t status));
esp_err_t esp_now_register_send_cb(void (*cb)(const wifi_tx_info_t *info, esp_now_send_status_t status));
extern "C" {
#endif
esp_err_t esp_now_init(void);
esp_err_t esp_now_deinit(void);
esp_err_t esp_now_unregister_recv_cb(void);
esp_err_t esp_now_unregister_send_cb(void);
esp_err_t esp_now_send(const uint8_t *peer_addr, const uint8_t *data, size_t len);
esp_err_t esp_now_add_peer(const esp_now_peer_info_t *peer);
esp_err_t esp_now_del_peer(const uint8_t *peer_addr);
esp_err_t esp_now_mod_peer(const esp_now_peer_info_t *peer);
bool esp_now_is_peer_exist(const uint8_t *peer_addr);
esp_err_t esp_now_set_pmk(const uint8_t *pmk);
#ifdef __cplusplus
}
#endif
