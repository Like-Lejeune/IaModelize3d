// FreeRTOS as arduino-esp32 exposes it (tasks, delays, semaphores, queues); the macros are functions here.
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef uint32_t TickType_t;
typedef int BaseType_t;
typedef unsigned int UBaseType_t;
typedef uint32_t StackType_t;
typedef void *TaskHandle_t;
typedef void (*TaskFunction_t)(void *);
typedef void *SemaphoreHandle_t;
typedef void *QueueHandle_t;
typedef void *TimerHandle_t;
typedef void (*TimerCallbackFunction_t)(TimerHandle_t xTimer);
typedef struct { uint32_t owner; uint32_t count; } portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED {0, 0}
#define pdMS_TO_TICKS(xTimeInMs) ((TickType_t)(xTimeInMs))
#define pdTICKS_TO_MS(xTicks) ((uint32_t)(xTicks))
#define portTICK_PERIOD_MS ((TickType_t)1)
#define portTICK_RATE_MS portTICK_PERIOD_MS
#define configTICK_RATE_HZ 1000
#define portMAX_DELAY ((TickType_t)0xffffffffUL)
#define pdTRUE ((BaseType_t)1)
#define pdFALSE ((BaseType_t)0)
#define pdPASS (pdTRUE)
#define pdFAIL (pdFALSE)
#define tskIDLE_PRIORITY ((UBaseType_t)0U)
#define tskNO_AFFINITY ((BaseType_t)0x7FFFFFFF)
#define configMAX_PRIORITIES 25
#define configMINIMAL_STACK_SIZE 768
#define portENTER_CRITICAL(mux) ((void)(mux))
#define portEXIT_CRITICAL(mux) ((void)(mux))
#define portENTER_CRITICAL_ISR(mux) ((void)(mux))
#define portEXIT_CRITICAL_ISR(mux) ((void)(mux))
#define taskENTER_CRITICAL(mux) ((void)(mux))
#define taskEXIT_CRITICAL(mux) ((void)(mux))
#define portYIELD_FROM_ISR(...) ((void)0)
#define taskYIELD() ((void)0)
