#pragma once
#include <stdint.h>
typedef struct esp_timer *esp_timer_handle_t;
typedef void (*esp_timer_cb_t)(void *arg);
typedef enum { ESP_TIMER_TASK, ESP_TIMER_ISR } esp_timer_dispatch_t;
typedef struct {
  esp_timer_cb_t callback;
  void *arg;
  esp_timer_dispatch_t dispatch_method;
  const char *name;
  bool skip_unhandled_events;
} esp_timer_create_args_t;
#ifdef __cplusplus
extern "C" {
#endif
int64_t esp_timer_get_time(void);
int esp_timer_create(const esp_timer_create_args_t *create_args, esp_timer_handle_t *out_handle);
int esp_timer_start_once(esp_timer_handle_t timer, uint64_t timeout_us);
int esp_timer_start_periodic(esp_timer_handle_t timer, uint64_t period);
int esp_timer_stop(esp_timer_handle_t timer);
int esp_timer_delete(esp_timer_handle_t timer);
#ifdef __cplusplus
}
#endif
