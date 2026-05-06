#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"
#include "tasks.h"

// ============================================================
// taskRealtime — Core 1, Priority 2
// Nhận lệnh từ commandQueue, điều khiển:
//   - Servo SG90  (gõ vật thể)        → PIN_SERVO_KNOCK
//   - Servo MG90S (mở/đóng cửa đáy)   → PIN_SERVO_DOOR
//   - Motor GA25-370 via L298N (xoay)  → TODO
//   - TCRT5000 IR  (xác nhận vị trí)   → TODO
// Kết quả được đẩy vào responseQueue → taskComms gửi về Pi.
// ============================================================

static Servo servoKnock;
static Servo servoDoor;

// ---- helper: push response về taskComms (non-blocking) ----
static inline void pushResponse(const char* event, int param) {
    Response_t resp = {};
    strncpy(resp.event, event, sizeof(resp.event) - 1);
    resp.param = param;
    xQueueSend(responseQueue, &resp, pdMS_TO_TICKS(10));
}

// ============================================================
// doKnock — SG90 gõ 'count' lần
//   Mỗi lần: strike → KNOCK_DWELL_MS → rest → KNOCK_SETTLE_MS
//   Sau mỗi lần push KNOCK_DONE{seq=i}
//   Khoảng cách giữa các lần gõ đúng bằng KNOCK_INTERVAL_MS (tính từ
//   đầu lần gõ đến đầu lần gõ tiếp theo).
// ============================================================
static void doKnock(int count) {
    const TickType_t period = pdMS_TO_TICKS(KNOCK_INTERVAL_MS);

    for (int i = 1; i <= count; i++) {
        TickType_t t0 = xTaskGetTickCount();

        servoKnock.write(KNOCK_STRIKE_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_DWELL_MS));

        servoKnock.write(KNOCK_REST_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_SETTLE_MS));

        pushResponse("KNOCK_DONE", i);

        // Giữ đúng chu kỳ KNOCK_INTERVAL_MS giữa các lần gõ
        if (i < count) {
            TickType_t elapsed = xTaskGetTickCount() - t0;
            if (elapsed < period) {
                vTaskDelay(period - elapsed);
            }
        }
    }
}

// ============================================================
// doDischarge — MG90S mở cửa trượt, giữ, đóng
//   Sau khi cửa đóng và ổn định, push DISCHARGE_DONE.
// ============================================================
static void doDischarge() {
    servoDoor.write(DOOR_OPEN_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_HOLD_MS));

    servoDoor.write(DOOR_CLOSE_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_SETTLE_MS));

    pushResponse("DISCHARGE_DONE", 0);
}

// ============================================================
// taskRealtime entry point
// ============================================================
void taskRealtime(void* pvParameters) {
    // Cấp phát hardware timer cho LEDC (2 servo → 2 timer)
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);

    // SG90 — gõ vật thể
    servoKnock.setPeriodHertz(50);
    servoKnock.attach(PIN_SERVO_KNOCK, 500, 2400);
    servoKnock.write(KNOCK_REST_ANGLE);

    // MG90S — cửa trượt đáy ống
    servoDoor.setPeriodHertz(50);
    servoDoor.attach(PIN_SERVO_DOOR, 500, 2400);
    servoDoor.write(DOOR_CLOSE_ANGLE);

    Command_t cmd;
    for (;;) {
        if (xQueueReceive(commandQueue, &cmd, portMAX_DELAY) == pdTRUE) {
            if (strcmp(cmd.cmd, "KNOCK") == 0) {
                doKnock(cmd.param);
            } else if (strcmp(cmd.cmd, "ROTATE") == 0) {
                // TODO: motor + IR interrupt logic
            } else if (strcmp(cmd.cmd, "DISCHARGE") == 0) {
                doDischarge();
            }
        }
    }
}
