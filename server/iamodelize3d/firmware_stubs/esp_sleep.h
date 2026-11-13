// ESP-IDF 5.x sleep (esp_sleep.h), arduino-esp32 3.x includes it with Arduino.h. Common to every chip: timer, UART,
// Wi-Fi/BT and light-sleep GPIO wake-up, deep/light sleep, the wake-up cause. Per chip (soc_caps.h): ext0/ext1, touch
// pad and ULP wake-up on the ESP32-S3; the deep-sleep GPIO wake-up (GPIO0-5) on the ESP32-C3. Calling the other chip's
// fails to compile there too.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "soc/soc_caps.h"
#include "driver/gpio.h"

typedef enum {
  ESP_SLEEP_WAKEUP_UNDEFINED, ESP_SLEEP_WAKEUP_ALL, ESP_SLEEP_WAKEUP_EXT0, ESP_SLEEP_WAKEUP_EXT1, ESP_SLEEP_WAKEUP_TIMER,
  ESP_SLEEP_WAKEUP_TOUCHPAD, ESP_SLEEP_WAKEUP_ULP, ESP_SLEEP_WAKEUP_GPIO, ESP_SLEEP_WAKEUP_UART, ESP_SLEEP_WAKEUP_WIFI,
  ESP_SLEEP_WAKEUP_COCPU, ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG, ESP_SLEEP_WAKEUP_BT,
} esp_sleep_source_t;
typedef esp_sleep_source_t esp_sleep_wakeup_cause_t;
typedef enum { ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_DOMAIN_RTC_SLOW_MEM, ESP_PD_DOMAIN_RTC_FAST_MEM, ESP_PD_DOMAIN_XTAL, ESP_PD_DOMAIN_VDDSDIO,
               ESP_PD_DOMAIN_MAX } esp_sleep_pd_domain_t;
typedef enum { ESP_PD_OPTION_OFF, ESP_PD_OPTION_ON, ESP_PD_OPTION_AUTO } esp_sleep_pd_option_t;
typedef enum { ESP_GPIO_WAKEUP_GPIO_LOW = 0, ESP_GPIO_WAKEUP_GPIO_HIGH = 1 } esp_deepsleep_gpio_wake_up_mode_t;
typedef enum { ESP_EXT1_WAKEUP_ALL_LOW = 0, ESP_EXT1_WAKEUP_ANY_LOW = 0, ESP_EXT1_WAKEUP_ANY_HIGH = 1 } esp_sleep_ext1_wakeup_mode_t;
typedef int touch_pad_t;

#ifdef __cplusplus
extern "C" {
#endif
void esp_deep_sleep_start(void) __attribute__((noreturn));
esp_err_t esp_deep_sleep_try_to_start(void);
void esp_deep_sleep(uint64_t time_in_us) __attribute__((noreturn));
esp_err_t esp_light_sleep_start(void);
esp_err_t esp_sleep_enable_timer_wakeup(uint64_t time_in_us);
esp_err_t esp_sleep_enable_gpio_wakeup(void);
esp_err_t esp_sleep_enable_uart_wakeup(int uart_num);
esp_err_t esp_sleep_enable_wifi_wakeup(void);
esp_err_t esp_sleep_disable_wifi_wakeup(void);
esp_err_t esp_sleep_enable_bt_wakeup(void);
esp_err_t esp_sleep_disable_bt_wakeup(void);
esp_err_t esp_sleep_disable_wakeup_source(esp_sleep_source_t source);
esp_sleep_wakeup_cause_t esp_sleep_get_wakeup_cause(void);
esp_err_t esp_sleep_pd_config(esp_sleep_pd_domain_t domain, esp_sleep_pd_option_t option);
bool esp_sleep_is_valid_wakeup_gpio(gpio_num_t gpio_num);
void esp_sleep_config_gpio_isolate(void);
void esp_sleep_enable_gpio_switch(bool enable);
#if defined(SOC_GPIO_SUPPORT_DEEPSLEEP_WAKEUP)
esp_err_t esp_deep_sleep_enable_gpio_wakeup(uint64_t gpio_pin_mask, esp_deepsleep_gpio_wake_up_mode_t mode);
uint64_t esp_sleep_get_gpio_wakeup_status(void);
#endif
#if defined(SOC_PM_SUPPORT_EXT0_WAKEUP)
esp_err_t esp_sleep_enable_ext0_wakeup(gpio_num_t gpio_num, int level);
#endif
#if defined(SOC_PM_SUPPORT_EXT1_WAKEUP)
esp_err_t esp_sleep_enable_ext1_wakeup(uint64_t io_mask, esp_sleep_ext1_wakeup_mode_t level_mode);
esp_err_t esp_sleep_enable_ext1_wakeup_io(uint64_t io_mask, esp_sleep_ext1_wakeup_mode_t level_mode);
esp_err_t esp_sleep_disable_ext1_wakeup_io(uint64_t io_mask);
uint64_t esp_sleep_get_ext1_wakeup_status(void);
#endif
#if defined(SOC_PM_SUPPORT_TOUCH_SENSOR_WAKEUP)
esp_err_t esp_sleep_enable_touchpad_wakeup(void);
touch_pad_t esp_sleep_get_touchpad_wakeup_status(void);
#endif
#if defined(SOC_ULP_SUPPORTED)
esp_err_t esp_sleep_enable_ulp_wakeup(void);
#endif
#ifdef __cplusplus
}
#endif
