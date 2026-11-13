// Task watchdog: IDF 5.x takes a config struct (3.x); esp_task_wdt_init(timeout_s, panic) was IDF 4.x (2.x).
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
typedef int esp_err_t;
typedef struct {
  uint32_t timeout_ms;
  uint32_t idle_core_mask;
  bool trigger_panic;
} esp_task_wdt_config_t;
#ifdef __cplusplus
extern "C" {
#endif
esp_err_t esp_task_wdt_init(const esp_task_wdt_config_t *config);
esp_err_t esp_task_wdt_reconfigure(const esp_task_wdt_config_t *config);
esp_err_t esp_task_wdt_deinit(void);
esp_err_t esp_task_wdt_add(TaskHandle_t task_handle);
esp_err_t esp_task_wdt_delete(TaskHandle_t task_handle);
esp_err_t esp_task_wdt_reset(void);
#ifdef __cplusplus
}
esp_err_t esp_task_wdt_init(uint32_t timeout_s, bool panic);
#endif
