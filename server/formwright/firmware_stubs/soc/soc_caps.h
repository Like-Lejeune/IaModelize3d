// What the chip has (ESP-IDF 5.x soc_caps.h, the parts sketches and these stubs test): the ESP32-C3 has no touch, no
// ext0/ext1 or ULP wake-up and no RTC IO (it wakes from deep sleep on GPIO0-5 instead); the ESP32-S3 has them all
// but the deep-sleep GPIO wake-up.
#pragma once
#if defined(CONFIG_IDF_TARGET_ESP32C3)
#define SOC_GPIO_SUPPORT_DEEPSLEEP_WAKEUP 1
#define SOC_GPIO_PIN_COUNT 22
#else
#define SOC_TOUCH_SENSOR_SUPPORTED 1
#define SOC_PM_SUPPORT_EXT0_WAKEUP 1
#define SOC_PM_SUPPORT_EXT1_WAKEUP 1
#define SOC_PM_SUPPORT_TOUCH_SENSOR_WAKEUP 1
#define SOC_ULP_SUPPORTED 1
#define SOC_RTCIO_INPUT_OUTPUT_SUPPORTED 1
#define SOC_RTCIO_HOLD_SUPPORTED 1
#define SOC_RTCIO_WAKE_SUPPORTED 1
#define SOC_GPIO_PIN_COUNT 49
#endif
#define SOC_TEMP_SENSOR_SUPPORTED 1
#define SOC_PM_SUPPORT_WIFI_WAKEUP 1
#define SOC_PM_SUPPORT_BT_WAKEUP 1
#define SOC_GPIO_SUPPORT_HOLD_IO_IN_DSLP 1
