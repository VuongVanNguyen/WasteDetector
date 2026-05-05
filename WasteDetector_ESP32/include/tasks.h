#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// ============================================================
// Command structure passed through commandQueue
// Core 0 (taskComms) → Core 1 (taskRealtime)
// ============================================================
typedef struct {
    char cmd[16];   // "KNOCK", "ROTATE", "DISCHARGE"
    int  param;     // KNOCK: count | ROTATE: waste target | DISCHARGE: unused
} Command_t;

extern QueueHandle_t commandQueue;

// ============================================================
// Task entry points
// ============================================================
void taskRealtime(void* pvParameters);   // Core 1 — servo, motor, IR
void taskComms(void* pvParameters);      // Core 0 — UART, HC-SR04, relay
