#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// ============================================================
// Command structure: Core 0 (taskComms) → Core 1 (taskRealtime)
// ============================================================
typedef struct {
    char cmd[16];   // "KNOCK", "ROTATE", "DISCHARGE"
    int  param;     // KNOCK: count | ROTATE: waste target | DISCHARGE: unused
} Command_t;

// ============================================================
// Response structure: Core 1 (taskRealtime) → Core 0 (taskComms)
// ============================================================
typedef struct {
    char event[20]; // "KNOCK_DONE", "ROTATE_DONE", "DISCHARGE_DONE", "ERROR"
    int  param;     // KNOCK_DONE: seq | ROTATE_DONE: position | ERROR: 0=MOTOR_TIMEOUT, 1=INVALID_CMD | others: 0
} Response_t;

extern QueueHandle_t commandQueue;
extern QueueHandle_t responseQueue;

// ============================================================
// Task entry points
// ============================================================
void taskRealtime(void* pvParameters);   // Core 1 — servo, motor, IR
void taskComms(void* pvParameters);      // Core 0 — UART, HC-SR04, relay
