// ============================================================================
// TEST MOTOR — QUAY TỰ DO 2 CHIỀU, ĐƠN GIẢN NHẤT
// ============================================================================
// Flash:   pio run -e test_motor_free --target upload
// Monitor: pio device monitor -e test_motor_free
//
// Phím lệnh:
//   'a' → quay chiều A (CW)
//   'd' → quay chiều B (CCW)
//   's' → DỪNG
//
// Không IR, không timeout, không chống xoắn — chỉ để xoay tay ống lúc lắp
// ráp/hiệu chỉnh. Driver: DRV8871. GPIO 25→IN1, GPIO 26→IN2 (xem config.h).
// ============================================================================

#include <Arduino.h>
#include "config.h"

static int currentDir = -1;   // -1 = dừng, MOTOR_DIR_CW/CCW khi đang quay

static void motorAttach() {
    ledcSetup(MOTOR_LEDC_CH_IN1, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcSetup(MOTOR_LEDC_CH_IN2, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcAttachPin(PIN_MOTOR_IN1, MOTOR_LEDC_CH_IN1);
    ledcAttachPin(PIN_MOTOR_IN2, MOTOR_LEDC_CH_IN2);
    ledcWrite(MOTOR_LEDC_CH_IN1, 0);
    ledcWrite(MOTOR_LEDC_CH_IN2, 0);
}

static void motorStop() {
    ledcWrite(MOTOR_LEDC_CH_IN1, 0);
    ledcWrite(MOTOR_LEDC_CH_IN2, 0);
    currentDir = -1;
    Serial.println("[STOP] Da dung.");
}

static void motorRun(int dir) {
    // Đổi chiều lúc rotor còn quay tạo back-EMF cộng vào 12V — dừng hẳn rồi
    // chờ MOTOR_DEADTIME_MS trước khi đảo chiều để tránh sụt rail/brownout ESP32.
    if (currentDir != -1 && currentDir != dir) {
        ledcWrite(MOTOR_LEDC_CH_IN1, 0);
        ledcWrite(MOTOR_LEDC_CH_IN2, 0);
        vTaskDelay(pdMS_TO_TICKS(MOTOR_DEADTIME_MS));
    }
    bool cw = (dir == MOTOR_DIR_CW) != (bool)MOTOR_DIR_INVERTED;
    ledcWrite(MOTOR_LEDC_CH_IN1, cw ? MOTOR_SPEED : 0);
    ledcWrite(MOTOR_LEDC_CH_IN2, cw ? 0 : MOTOR_SPEED);
    currentDir = dir;
    Serial.printf("[RUN] Quay chieu %s.\n", dir == MOTOR_DIR_CW ? "A (CW)" : "B (CCW)");
}

static void printMenu() {
    Serial.println("--- 'a'=chieu A (CW) | 'd'=chieu B (CCW) | 's'=DUNG ---");
}

void setup() {
    Serial.begin(115200);
    delay(300);

    motorAttach();

    Serial.println("=== TEST MOTOR QUAY TU DO 2 CHIEU ===");
    Serial.printf("DRV8871: IN1=GPIO%d IN2=GPIO%d | speed=%d\n",
                  PIN_MOTOR_IN1, PIN_MOTOR_IN2, MOTOR_SPEED);
    printMenu();
}

void loop() {
    if (!Serial.available()) return;

    char cmd = Serial.read();
    if (cmd == '\n' || cmd == '\r') return;

    switch (cmd) {
        case 'a': motorRun(MOTOR_DIR_CW);  break;
        case 'd': motorRun(MOTOR_DIR_CCW); break;
        case 's': motorStop();             break;
        default:
            Serial.printf("[?] Chi nhan 'a', 'd', 's'. Da nhan '%c'.\n", cmd);
            break;
    }

    printMenu();
}
