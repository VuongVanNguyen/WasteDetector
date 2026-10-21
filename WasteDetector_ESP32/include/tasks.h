#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// ============================================================
// Command structure: Core 0 (taskComms) → Core 1 (taskRealtime)
// ============================================================
typedef struct {
    char cmd[16];   // "KNOCK", "ROTATE", "DISCHARGE", "HOME"
    int  param;     // KNOCK: count | ROTATE: waste target | DISCHARGE/HOME: unused
} Command_t;

// ============================================================
// Response structure: Core 1 (taskRealtime) → Core 0 (taskComms)
// ============================================================
typedef struct {
    char event[20]; // "KNOCK_DONE", "ROTATE_DONE", "DISCHARGE_DONE", "READY", "ERROR"
                    // READY = ong da ve diem dau HOME (ngan Thuy tinh) sau khi xa.
                    // Pi KHONG duoc nhan vat moi truoc khi thay event nay.
    int  param;     // KNOCK_DONE: seq | ROTATE_DONE/READY: position
                    // ERROR: 0=MOTOR_TIMEOUT, 1=INVALID_CMD, 2=HOME_FAILED,
                    //        3=MOTION_FAULT | others: 0
                    //
                    // MOTION_FAULT la CHOT: engine da khoa va se TU CHOI moi
                    // lenh quay cho toi khi co nguoi thao xoan day roi mo khoa
                    // (motionClearFault). Pi phai dung han chu ky, log loi,
                    // KHONG thu lai tu dong.
} Response_t;

extern QueueHandle_t commandQueue;
extern QueueHandle_t responseQueue;

// ============================================================
// Task entry points
// ============================================================
void taskRealtime(void* pvParameters);   // Core 1 — servo, motor, IR
void taskComms(void* pvParameters);      // Core 0 — UART, HC-SR04
