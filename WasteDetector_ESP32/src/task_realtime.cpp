#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"
#include "tasks.h"

// ============================================================
// taskRealtime — Core 1, Priority 2
// Nhận lệnh từ commandQueue, điều khiển:
//   - Servo SG90  (gõ vật thể)
//   - Servo MG90S (mở/đóng cửa trượt đáy)
//   - Motor GA25-370 via L298N (xoay ống)
//   - TCRT5000 IR (xác nhận vị trí ống)
// ============================================================

// TODO: implement

void taskRealtime(void* pvParameters) {
    // TODO: init servos, motor pins, IR pins

    Command_t cmd;
    for (;;) {
        if (xQueueReceive(commandQueue, &cmd, portMAX_DELAY) == pdTRUE) {
            if (strcmp(cmd.cmd, "KNOCK") == 0) {
                // TODO: gõ SG90 cmd.param lần, push KNOCK_DONE sau mỗi lần
            } else if (strcmp(cmd.cmd, "ROTATE") == 0) {
                // TODO: quay motor, chờ TCRT5000 trigger, push ROTATE_DONE
            } else if (strcmp(cmd.cmd, "DISCHARGE") == 0) {
                // TODO: mở MG90S, giữ DOOR_HOLD_MS, đóng, push DISCHARGE_DONE
            }
        }
    }
}
