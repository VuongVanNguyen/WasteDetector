// Standalone servo test — SG90 (knock) + MG90S (door)
// Flash với: pio run -e test_servo --target upload
// Quan sát:  pio device monitor -e test_servo
//
// Lệnh Serial:
//   'k' → test knock (3 lần)
//   'd' → test door (mở/đóng)
//   'a' → test cả 2 tuần tự với delay 10s giữa (mô phỏng workflow)
//
// Điều chỉnh các góc/thời gian trong config.h, sau đó flash lại.

#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"

static Servo servoKnock;
static Servo servoDoor;

static void testKnock(int count) {
    Serial.printf("[KNOCK] Gõ %d lần...\n", count);
    for (int i = 1; i <= count; i++) {
        Serial.printf("  lần %d: strike → %d°", i, KNOCK_STRIKE_ANGLE);
        servoKnock.write(KNOCK_STRIKE_ANGLE);
        delay(KNOCK_DWELL_MS);

        Serial.printf(" → rest %d°\n", KNOCK_REST_ANGLE);
        servoKnock.write(KNOCK_REST_ANGLE);
        delay(KNOCK_SETTLE_MS);

        if (i < count) {
            delay(KNOCK_INTERVAL_MS - KNOCK_DWELL_MS - KNOCK_SETTLE_MS);
        }
    }
    Serial.println("[KNOCK] Xong.");
}

static void testDoor() {
    Serial.printf("[DOOR] Mở cửa → %d°\n", DOOR_OPEN_ANGLE);
    servoDoor.write(DOOR_OPEN_ANGLE);
    delay(DOOR_HOLD_MS);

    Serial.printf("[DOOR] Đóng cửa → %d°\n", DOOR_CLOSE_ANGLE);
    servoDoor.write(DOOR_CLOSE_ANGLE);
    delay(DOOR_SETTLE_MS);

    Serial.println("[DOOR] Xong.");
}

static void printMenu() {
    Serial.println("\n--- Lệnh: 'k'=knock | 'd'=door | 'a'=cả 2 ---");
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== TEST SERVO (SG90 + MG90S) ===");
    Serial.printf("SG90  → GPIO %d | rest=%d° strike=%d°\n",
                  PIN_SERVO_KNOCK, KNOCK_REST_ANGLE, KNOCK_STRIKE_ANGLE);
    Serial.printf("MG90S → GPIO %d | close=%d° open=%d°\n",
                  PIN_SERVO_DOOR, DOOR_CLOSE_ANGLE, DOOR_OPEN_ANGLE);

    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);

    servoKnock.setPeriodHertz(50);
    servoKnock.attach(PIN_SERVO_KNOCK, 500, 2400);
    servoKnock.write(KNOCK_REST_ANGLE);

    servoDoor.setPeriodHertz(50);
    servoDoor.attach(PIN_SERVO_DOOR, 500, 2400);
    servoDoor.write(DOOR_CLOSE_ANGLE);

    delay(1000);  // cho servo về vị trí ban đầu
    printMenu();
}

void loop() {
    if (!Serial.available()) return;

    char cmd = Serial.read();
    // Bỏ qua newline/carriage return
    if (cmd == '\n' || cmd == '\r') return;

    switch (cmd) {
        case 'k':
            testKnock(3);
            break;

        case 'd':
            testDoor();
            break;

        case 'a':
            Serial.println("[AUTO] Knock → chờ 10s (mô phỏng AI+xoay) → Door");
            testKnock(3);
            Serial.println("[AUTO] Chờ 10s...");
            delay(10000);
            testDoor();
            Serial.println("[AUTO] Xong.");
            break;

        default:
            Serial.printf("[?] Lệnh '%c' không hợp lệ.\n", cmd);
            break;
    }

    printMenu();
}
