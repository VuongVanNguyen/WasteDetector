// ============================================================================
// Core 1 (priority 2) — servo SG90/MG90S + motor GA25-370 + IR TCRT5000
// ============================================================================
// HOME = ngăn Thủy tinh. Sau khi xả, Core 1 TỰ đưa ống về HOME rồi đẩy event
// READY — Pi không phải ra lệnh, nhưng KHÔNG được nhận vật mới trước READY.

#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"
#include "motion.h"
#include "tasks.h"

static Servo servoKnock;
static Servo servoDoor;

static inline void pushResponse(const char* event, int param) {
    Response_t resp = {};
    strncpy(resp.event, event, sizeof(resp.event) - 1);
    resp.param = param;
    xQueueSend(responseQueue, &resp, pdMS_TO_TICKS(10));
}

static void doKnock(int count) {
    const TickType_t period = pdMS_TO_TICKS(KNOCK_INTERVAL_MS);

    for (int i = 1; i <= count; i++) {
        TickType_t t0 = xTaskGetTickCount();

        servoKnock.write(KNOCK_STRIKE_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_DWELL_MS));

        servoKnock.write(KNOCK_REST_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_SETTLE_MS));

        pushResponse("KNOCK_DONE", i);

        if (i < count) {
            TickType_t elapsed = xTaskGetTickCount() - t0;
            if (elapsed < period) vTaskDelay(period - elapsed);
        }
    }
}

// Closed-loop hoàn toàn: ISR phanh trên cạnh IR thật của đúng cảm biến đích.
// Rác Thủy tinh là trường hợp hợp lệ mà ống KHÔNG quay — ngăn xả chính là HOME.
static void doRotate(int target) {
    if (target < WASTE_PLASTIC || target > WASTE_METAL) {
        pushResponse("ERROR", 1);   // 1 = INVALID_CMD
        return;
    }
    if (motionRotateTo(target)) pushResponse("ROTATE_DONE", motionPosition());
    else if (motionFaulted())   pushResponse("ERROR", 3);   // 3 = MOTION_FAULT
    else                        pushResponse("ERROR", 0);   // 0 = MOTOR_TIMEOUT
}

static void reportHome(bool ok) {
    if (ok)                   pushResponse("READY", motionPosition());
    else if (motionFaulted()) pushResponse("ERROR", 3);
    else                      pushResponse("ERROR", 2);   // 2 = HOME_FAILED
}

// Xả rác rồi TỰ ĐƯA ỐNG VỀ HOME (Thủy tinh). Pi nhận DISCHARGE_DONE rồi đợi READY
// trước khi cho phép vật mới rơi vào ống. Tách làm 2 event để Pi không phải chờ cả quãng quay chỉ để biết cửa đã đóng.
static void doDischarge() {
    servoDoor.write(DOOR_OPEN_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_HOLD_MS));

    servoDoor.write(DOOR_CLOSE_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_SETTLE_MS));

    pushResponse("DISCHARGE_DONE", 0);
    reportHome(motionGoHome());
}

static void doGoHome() {
    reportHome(motionGoHome());
}

void taskRealtime(void* pvParameters) {
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);

    motionBegin();      // LEDC motor + pinMode/ISR cho 4 chân IR + đọc vị trí đầu

    servoKnock.setPeriodHertz(50);
    servoKnock.attach(PIN_SERVO_KNOCK, SERVO_MIN_US, SERVO_MAX_US);
    servoKnock.write(KNOCK_REST_ANGLE);

    servoDoor.setPeriodHertz(50);
    servoDoor.attach(PIN_SERVO_DOOR, SERVO_MIN_US, SERVO_MAX_US);
    servoDoor.write(DOOR_CLOSE_ANGLE);

    // Tự về HOME NGAY KHI KHỞI ĐỘNG — không đợi lệnh đầu tiên từ Pi. Quan trọng
    // sau brownout/crash giữa chu kỳ: ống có thể đang đứng trên một ngăn khác.
    reportHome(motionHomeOnBoot());

    Command_t cmd;
    for (;;) {
        if (xQueueReceive(commandQueue, &cmd, portMAX_DELAY) == pdTRUE) {
            if      (strcmp(cmd.cmd, "KNOCK")     == 0) doKnock(cmd.param);
            else if (strcmp(cmd.cmd, "ROTATE")    == 0) doRotate(cmd.param);
            else if (strcmp(cmd.cmd, "DISCHARGE") == 0) doDischarge();
            else if (strcmp(cmd.cmd, "HOME")      == 0) doGoHome();
            else                                        pushResponse("ERROR", 1);
        }
    }
}
