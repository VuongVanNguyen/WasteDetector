// Standalone Motor Test — GA25-370 via L298N Mini & 4x TCRT5000 IR Sensors
// Lấy cấu hình chân & logic xoay định vị từ WasteDetector_ESP32/src/task_realtime.cpp & config.h
//
// Flash với: pio run -e test_motor --target upload
// Quan sát:  pio device monitor -e test_motor
//
// Lệnh Serial:
//   '1' → Xoay đến ngăn Nhựa (PLASTIC - GPIO 34)
//   '2' → Xoay đến ngăn Thủy tinh (GLASS - GPIO 35)
//   '3' → Xoay đến ngăn Giấy (PAPER - GPIO 32)
//   '4' → Xoay đến ngăn Kim loại (METAL - GPIO 33)
//   'f' → Quay tiến (Forward) 1 giây
//   'b' → Quay lùi (Reverse) 1 giây
//   's' → Dừng động cơ (Stop) ngay lập tức
//   'i' → Kiểm tra đọc trực tiếp 4 cảm biến IR (Digital Read)
//   'c' → Chạy tự động chu trình qua 4 ngăn (1 -> 2 -> 3 -> 4 -> 1)
//   '+' / '-' → Tăng / Giảm tốc độ Motor PWM (mặc định trong config.h là MOTOR_SPEED)
//
// Điều chỉnh các tham số trong config.h nếu cần.

#include <Arduino.h>
#include "config.h"

static volatile bool irTriggered = false;
static volatile int irPosition = WASTE_NONE;
static int currentPosition = WASTE_NONE;
static uint8_t testMotorSpeed = MOTOR_SPEED;

// Tên các ngăn rác để in log dễ hiểu
static const char* getWasteName(int pos) {
    switch (pos) {
        case WASTE_PLASTIC: return "NHỰA (Plastic)";
        case WASTE_GLASS:   return "THỦY TINH (Glass)";
        case WASTE_PAPER:   return "GIẤY (Paper)";
        case WASTE_METAL:   return "KIM LOẠI (Metal)";
        default:            return "KHÔNG XÁC ĐỊNH (None)";
    }
}

// ============================================================
// Điều khiển Động cơ DC (L298N Mini)
// ============================================================
static void motorRotateForward(uint8_t speed) {
    digitalWrite(PIN_MOTOR_IN1, HIGH);
    digitalWrite(PIN_MOTOR_IN2, LOW);
    ledcWrite(MOTOR_LEDC_CHANNEL, speed);
}

static void motorRotateReverse(uint8_t speed) {
    digitalWrite(PIN_MOTOR_IN1, LOW);
    digitalWrite(PIN_MOTOR_IN2, HIGH);
    ledcWrite(MOTOR_LEDC_CHANNEL, speed);
}

static void motorStop() {
    digitalWrite(PIN_MOTOR_IN1, HIGH);
    digitalWrite(PIN_MOTOR_IN2, HIGH);
    ledcWrite(MOTOR_LEDC_CHANNEL, 0);
}

// ============================================================
// Interrupt Handlers cảm biến IR (giống task_realtime.cpp)
// ============================================================
void IRAM_ATTR irPLASTIC() { irTriggered = true; irPosition = WASTE_PLASTIC; }
void IRAM_ATTR irGLASS()   { irTriggered = true; irPosition = WASTE_GLASS; }
void IRAM_ATTR irPAPER()   { irTriggered = true; irPosition = WASTE_PAPER; }
void IRAM_ATTR irMETAL()   { irTriggered = true; irPosition = WASTE_METAL; }

// ============================================================
// Logic Xoay vị trí có Auto-Stop theo IR (giống task_realtime.cpp)
// ============================================================
static bool doRotate(int target) {
    if (target < WASTE_PLASTIC || target > WASTE_METAL) {
        Serial.println("[ERROR] Vị trí target không hợp lệ!");
        return false;
    }

    Serial.printf("\n[ROTATE] Bắt đầu xoay đến: %s (Vị trí hiện tại: %s, Speed: %d)...\n",
                  getWasteName(target), getWasteName(currentPosition), testMotorSpeed);

    if (target == currentPosition) {
        Serial.printf("[ROTATE] Đã ở sẵn vị trí target (%s). Không cần xoay.\n", getWasteName(target));
        return true;
    }

    irTriggered = false;
    irPosition = WASTE_NONE;
    
    unsigned long startTime = millis();
    unsigned long deadline = startTime + MOTOR_TIMEOUT_MS;

    motorRotateForward(testMotorSpeed);

    while (millis() < deadline) {
        if (irTriggered) {
            int pos = irPosition;
            irTriggered = false;

            Serial.printf("  -> Phát hiện cảm biến IR vị trí: %s (sau %lu ms)\n", 
                          getWasteName(pos), millis() - startTime);

            if (pos == target) {
                motorStop();
                currentPosition = pos;
                delay(MOTOR_ROTATE_MS);
                Serial.printf("[ROTATE OK] Đã dừng chính xác tại %s (Tổng thời gian: %lu ms)\n",
                              getWasteName(pos), millis() - startTime);
                return true;
            }
        }
        delay(5);
    }

    motorStop();
    Serial.printf("[ROTATE TIMEOUT] Quá thời hạn %d ms mà chưa kích hoạt IR %s!\n",
                  MOTOR_TIMEOUT_MS, getWasteName(target));
    return false;
}

// ============================================================
// Đọc trực tiếp trạng thái 4 cảm biến IR
// ============================================================
static void readIRSensors() {
    int p = digitalRead(PIN_IR_PLASTIC);
    int g = digitalRead(PIN_IR_GLASS);
    int pa = digitalRead(PIN_IR_PAPER);
    int m = digitalRead(PIN_IR_METAL);

    Serial.println("\n--- TRẠNG THÁI CẢM BIẾN IR (0 = Detected/Active LOW, 1 = Idle/HIGH) ---");
    Serial.printf("  GPIO %d [PLASTIC]  : %d (%s)\n", PIN_IR_PLASTIC, p, p == LOW ? "ACTIVE" : "IDLE");
    Serial.printf("  GPIO %d [GLASS]    : %d (%s)\n", PIN_IR_GLASS, g, g == LOW ? "ACTIVE" : "IDLE");
    Serial.printf("  GPIO %d [PAPER]    : %d (%s)\n", PIN_IR_PAPER, pa, pa == LOW ? "ACTIVE" : "IDLE");
    Serial.printf("  GPIO %d [METAL]    : %d (%s)\n", PIN_IR_METAL, m, m == LOW ? "ACTIVE" : "IDLE");
}

// ============================================================
// In Menu Lệnh
// ============================================================
static void printMenu() {
    Serial.println("\n-----------------------------------------------------------");
    Serial.println(" LỆNH TEST MOTOR:");
    Serial.println("  '1'..'4' : Xoay đến ngăn 1 (Plastic), 2 (Glass), 3 (Paper), 4 (Metal)");
    Serial.println("  'f'      : Quay tiến (Forward) 1s");
    Serial.println("  'b'      : Quay lùi (Reverse) 1s");
    Serial.println("  's'      : Dừng khẩn cấp");
    Serial.println("  'i'      : Đọc trực tiếp 4 cảm biến IR");
    Serial.println("  'c'      : Test chu trình xoay liên tục 1 -> 2 -> 3 -> 4 -> 1");
    Serial.printf( "  '+' / '-' : Tăng/Giảm tốc độ PWM (Hiện tại: %d)\n", testMotorSpeed);
    Serial.println("-----------------------------------------------------------");
}

void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println("=================================================");
    Serial.println("   WASTE DETECTOR - TEST GA25-370 MOTOR & IR     ");
    Serial.println("=================================================");
    Serial.printf("IN1: GPIO %d | IN2: GPIO %d | ENA: GPIO %d (LEDC Ch%d, %dHz, %d-bit)\n",
                  PIN_MOTOR_IN1, PIN_MOTOR_IN2, PIN_MOTOR_ENA,
                  MOTOR_LEDC_CHANNEL, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    Serial.printf("IR Pins -> Plastic:%d, Glass:%d, Paper:%d, Metal:%d\n",
                  PIN_IR_PLASTIC, PIN_IR_GLASS, PIN_IR_PAPER, PIN_IR_METAL);

    // Cấu hình chân điều khiển Động cơ
    pinMode(PIN_MOTOR_IN1, OUTPUT);
    pinMode(PIN_MOTOR_IN2, OUTPUT);
    ledcSetup(MOTOR_LEDC_CHANNEL, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcAttachPin(PIN_MOTOR_ENA, MOTOR_LEDC_CHANNEL);
    motorStop();

    // Cấu hình chân IR + Interrupt
    pinMode(PIN_IR_PLASTIC, INPUT);
    pinMode(PIN_IR_GLASS, INPUT);
    pinMode(PIN_IR_PAPER, INPUT);
    pinMode(PIN_IR_METAL, INPUT);

    attachInterrupt(digitalPinToInterrupt(PIN_IR_PLASTIC), irPLASTIC, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_GLASS), irGLASS, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_PAPER), irPAPER, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_METAL), irMETAL, FALLING);

    delay(500);
    printMenu();
}

void loop() {
    if (!Serial.available()) return;

    char cmd = Serial.read();
    if (cmd == '\n' || cmd == '\r') return;

    switch (cmd) {
        case '1':
            doRotate(WASTE_PLASTIC);
            break;
        case '2':
            doRotate(WASTE_GLASS);
            break;
        case '3':
            doRotate(WASTE_PAPER);
            break;
        case '4':
            doRotate(WASTE_METAL);
            break;

        case 'f':
            Serial.printf("[MANUAL] Quay tiến với tốc độ PWM = %d trong 1s...\n", testMotorSpeed);
            motorRotateForward(testMotorSpeed);
            delay(1000);
            motorStop();
            Serial.println("[MANUAL] Đã dừng.");
            break;

        case 'b':
            Serial.printf("[MANUAL] Quay lùi với tốc độ PWM = %d trong 1s...\n", testMotorSpeed);
            motorRotateReverse(testMotorSpeed);
            delay(1000);
            motorStop();
            Serial.println("[MANUAL] Đã dừng.");
            break;

        case 's':
            motorStop();
            Serial.println("[STOP] Đã ngắt điện động cơ.");
            break;

        case 'i':
            readIRSensors();
            break;

        case 'c':
            Serial.println("\n[CYCLE TEST] Chạy chu trình thử nghiệm 4 ngăn...");
            for (int target = WASTE_PLASTIC; target <= WASTE_METAL; target++) {
                if (!doRotate(target)) {
                    Serial.println("[CYCLE TEST] Thất bại giữa chừng, dừng chu trình!");
                    break;
                }
                Serial.println("[CYCLE TEST] Tạm dừng 2 giây trước khi xoay tiếp...");
                delay(2000);
            }
            Serial.println("[CYCLE TEST] Hoàn thành chu trình.");
            break;

        case '+':
            if (testMotorSpeed <= 245) testMotorSpeed += 10;
            else testMotorSpeed = 255;
            Serial.printf("[PWM] Tốc độ PWM mới: %d\n", testMotorSpeed);
            break;

        case '-':
            if (testMotorSpeed >= 10) testMotorSpeed -= 10;
            else testMotorSpeed = 0;
            Serial.printf("[PWM] Tốc độ PWM mới: %d\n", testMotorSpeed);
            break;

        default:
            Serial.printf("[?] Lệnh '%c' không hợp lệ.\n", cmd);
            break;
    }

    printMenu();
}
