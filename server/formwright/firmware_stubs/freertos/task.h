#pragma once
#include "FreeRTOS.h"
#ifdef __cplusplus
extern "C" {
#endif
BaseType_t xTaskCreate(TaskFunction_t pxTaskCode, const char *const pcName, const uint32_t usStackDepth, void *const pvParameters,
                       UBaseType_t uxPriority, TaskHandle_t *const pxCreatedTask);
BaseType_t xTaskCreatePinnedToCore(TaskFunction_t pxTaskCode, const char *const pcName, const uint32_t usStackDepth,
                                   void *const pvParameters, UBaseType_t uxPriority, TaskHandle_t *const pxCreatedTask,
                                   const BaseType_t xCoreID);
void vTaskDelay(const TickType_t xTicksToDelay);
void vTaskDelayUntil(TickType_t *const pxPreviousWakeTime, const TickType_t xTimeIncrement);
BaseType_t xTaskDelayUntil(TickType_t *const pxPreviousWakeTime, const TickType_t xTimeIncrement);
void vTaskDelete(TaskHandle_t xTaskToDelete);
void vTaskSuspend(TaskHandle_t xTaskToSuspend);
void vTaskResume(TaskHandle_t xTaskToResume);
TickType_t xTaskGetTickCount(void);
TickType_t xTaskGetTickCountFromISR(void);
TaskHandle_t xTaskGetCurrentTaskHandle(void);
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t xTask);
BaseType_t xTaskNotifyGive(TaskHandle_t xTaskToNotify);
uint32_t ulTaskNotifyTake(BaseType_t xClearCountOnExit, TickType_t xTicksToWait);
void vTaskNotifyGiveFromISR(TaskHandle_t xTaskToNotify, BaseType_t *pxHigherPriorityTaskWoken);
BaseType_t xPortGetCoreID(void);
#ifdef __cplusplus
}
#endif
