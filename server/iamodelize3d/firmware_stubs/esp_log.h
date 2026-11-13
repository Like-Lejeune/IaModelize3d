// ESP-IDF logging and arduino-esp32's log_x macros (esp32-hal-log.h): printf-style, format checked.
#pragma once
#include <stdio.h>
typedef enum { ESP_LOG_NONE, ESP_LOG_ERROR, ESP_LOG_WARN, ESP_LOG_INFO, ESP_LOG_DEBUG, ESP_LOG_VERBOSE } esp_log_level_t;
#ifdef __cplusplus
extern "C" {
#endif
void esp_log_level_set(const char *tag, esp_log_level_t level);
void esp_log_write(esp_log_level_t level, const char *tag, const char *format, ...) __attribute__((format(printf, 3, 4)));
#ifdef __cplusplus
}
#endif
#define ESP_LOGE(tag, format, ...) esp_log_write(ESP_LOG_ERROR, tag, format, ##__VA_ARGS__)
#define ESP_LOGW(tag, format, ...) esp_log_write(ESP_LOG_WARN, tag, format, ##__VA_ARGS__)
#define ESP_LOGI(tag, format, ...) esp_log_write(ESP_LOG_INFO, tag, format, ##__VA_ARGS__)
#define ESP_LOGD(tag, format, ...) esp_log_write(ESP_LOG_DEBUG, tag, format, ##__VA_ARGS__)
#define ESP_LOGV(tag, format, ...) esp_log_write(ESP_LOG_VERBOSE, tag, format, ##__VA_ARGS__)
#define log_e(format, ...) esp_log_write(ESP_LOG_ERROR, "", format, ##__VA_ARGS__)
#define log_w(format, ...) esp_log_write(ESP_LOG_WARN, "", format, ##__VA_ARGS__)
#define log_i(format, ...) esp_log_write(ESP_LOG_INFO, "", format, ##__VA_ARGS__)
#define log_d(format, ...) esp_log_write(ESP_LOG_DEBUG, "", format, ##__VA_ARGS__)
#define log_v(format, ...) esp_log_write(ESP_LOG_VERBOSE, "", format, ##__VA_ARGS__)
#define log_n(format, ...) esp_log_write(ESP_LOG_ERROR, "", format, ##__VA_ARGS__)
