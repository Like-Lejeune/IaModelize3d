// ESP-IDF 5.x RTC IO (driver/rtc_io.h): the ESP32-C3 has no dedicated RTC IO, so only rtc_gpio_is_valid_gpio() exists
// there; it keeps levels through deep sleep with gpio_pullup_en()/gpio_hold_en() + gpio_deep_sleep_hold_en() instead.
#pragma once
#include "../soc/soc_caps.h"
#include "gpio.h"
typedef enum { RTC_GPIO_MODE_INPUT_ONLY, RTC_GPIO_MODE_OUTPUT_ONLY, RTC_GPIO_MODE_INPUT_OUTPUT, RTC_GPIO_MODE_DISABLED,
               RTC_GPIO_MODE_OUTPUT_OD, RTC_GPIO_MODE_INPUT_OUTPUT_OD } rtc_gpio_mode_t;
#ifdef __cplusplus
extern "C" {
#endif
bool rtc_gpio_is_valid_gpio(gpio_num_t gpio_num);
#if defined(SOC_RTCIO_INPUT_OUTPUT_SUPPORTED)
int rtc_io_number_get(gpio_num_t gpio_num);
esp_err_t rtc_gpio_init(gpio_num_t gpio_num);
esp_err_t rtc_gpio_deinit(gpio_num_t gpio_num);
uint32_t rtc_gpio_get_level(gpio_num_t gpio_num);
esp_err_t rtc_gpio_set_level(gpio_num_t gpio_num, uint32_t level);
esp_err_t rtc_gpio_set_direction(gpio_num_t gpio_num, rtc_gpio_mode_t mode);
esp_err_t rtc_gpio_set_direction_in_sleep(gpio_num_t gpio_num, rtc_gpio_mode_t mode);
esp_err_t rtc_gpio_pullup_en(gpio_num_t gpio_num);
esp_err_t rtc_gpio_pullup_dis(gpio_num_t gpio_num);
esp_err_t rtc_gpio_pulldown_en(gpio_num_t gpio_num);
esp_err_t rtc_gpio_pulldown_dis(gpio_num_t gpio_num);
#endif
#if defined(SOC_RTCIO_HOLD_SUPPORTED)
esp_err_t rtc_gpio_hold_en(gpio_num_t gpio_num);
esp_err_t rtc_gpio_hold_dis(gpio_num_t gpio_num);
esp_err_t rtc_gpio_force_hold_en_all(void);
esp_err_t rtc_gpio_force_hold_dis_all(void);
esp_err_t rtc_gpio_isolate(gpio_num_t gpio_num);
#endif
#if defined(SOC_RTCIO_WAKE_SUPPORTED)
esp_err_t rtc_gpio_wakeup_enable(gpio_num_t gpio_num, gpio_int_type_t intr_type);
esp_err_t rtc_gpio_wakeup_disable(gpio_num_t gpio_num);
#endif
#ifdef __cplusplus
}
#endif
