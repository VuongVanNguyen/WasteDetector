// Standalone servo test — SG90 (knock) + MG90S (door)
// Flash với: pio run -e test_servo --target upload
// Quan sát:  pio device monitor -e test_servo
//
// Lệnh Serial:
//   'k' → test knock (3 lần)
//   'd' → test door (mở/đóng)
//   'a' → test cả 2 tuần tự với delay 10s giữa (mô phỏng workflow)
//
// Lệnh CHẨN ĐOÁN (áp cho servo đang chọn, mặc định SG90):
//   '1' / '2' → chọn SG90 (GPIO knock) / MG90S (GPIO door)
//   'i' → in trạng thái attach, độ rộng xung hiện tại
//   's' → quét chậm 0°→180°→0°, bước 10°, mỗi bước 400ms
//   'p' → THỬ DÂY: bỏ PWM, đảo chân 0V/3.3V mỗi 1s trong 10s. Đo VOM tại ĐẦU
//         CẮM servo (dây tín hiệu ↔ GND servo): phải nhảy 0 ↔ 3.3V.
//   'l' → BỎ QUA THƯ VIỆN: phát xung servo bằng LEDC thô (16 bit, 50Hz),
//         1000us ↔ 2000us mỗi 1s trong 10s. Servo chạy ở đây mà không chạy
//         với 'k'/'d' thì lỗi nằm ở ESP32Servo; không chạy thì lỗi phần cứng.
//   'x' → detach: servo mất tín hiệu, trục phải LỎNG khi xoay tay
//   'r' → attach lại và về góc nghỉ: trục phải CỨNG, ghì lại tay
//   '+' / '-' → nhích servo đang chọn ±5°;  '>' / '<' → ±1°. In ra góc hiện tại.
//         Dùng để DÒ GÓC: nhích tới vị trí đúng rồi chép số vào config.h
//         (KNOCK_REST/STRIKE_ANGLE, DOOR_CLOSE/OPEN_ANGLE).
//   Bấm phím bất kỳ để dừng 'p' / 'l' giữa chừng.
//
// Điều chỉnh các góc/thời gian trong config.h, sau đó flash lại.

#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"

static Servo servoKnock;
static Servo servoDoor;

// LEDC thô cho lệnh 'l' — kênh 7 (timer 3), không đụng timer 0/1 của ESP32Servo
static constexpr int RAW_LEDC_CH   = 7;
static constexpr int RAW_LEDC_BITS = 16;

static int selected = 1;  // 1 = SG90 (knock), 2 = MG90S (door)

static Servo&      selServo() { return selected == 1 ? servoKnock : servoDoor; }
static int         selPin()   { return selected == 1 ? PIN_SERVO_KNOCK : PIN_SERVO_DOOR; }
static int         selRest()  { return selected == 1 ? KNOCK_REST_ANGLE : DOOR_CLOSE_ANGLE; }
static const char* selName()  { return selected == 1 ? "SG90 (knock)" : "MG90S (door)"; }

static void attachServo(Servo& s, int pin, int angle) {
    s.setPeriodHertz(50);
    int ch = s.attach(pin, SERVO_MIN_US, SERVO_MAX_US);
    s.write(angle);
    Serial.printf("  attach GPIO %d → kenh LEDC %d, attached=%d, xung=%dus\n",
                  pin, ch, s.attached(), s.readMicroseconds());
}

// Chờ tối đa ms; trả về true nếu người dùng bấm phím (để hủy)
static bool waitOrKey(uint32_t ms) {
    uint32_t t0 = millis();
    while (millis() - t0 < ms) {
        if (Serial.available()) return true;
        delay(10);
    }
    return false;
}

static void flushInput() { while (Serial.available()) Serial.read(); }

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
            // delay() nhan uint32_t: neu hieu am se tran thanh ~49 ngay.
            int gap = KNOCK_INTERVAL_MS - KNOCK_DWELL_MS - KNOCK_SETTLE_MS;
            if (gap > 0) delay(gap);
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

static void printInfo() {
    Serial.printf("[INFO] SG90  GPIO %d attached=%d xung=%dus\n",
                  PIN_SERVO_KNOCK, servoKnock.attached(), servoKnock.readMicroseconds());
    Serial.printf("[INFO] MG90S GPIO %d attached=%d xung=%dus\n",
                  PIN_SERVO_DOOR, servoDoor.attached(), servoDoor.readMicroseconds());
    Serial.printf("[INFO] Dang chon: %s\n", selName());
}

static void sweep() {
    Servo& s = selServo();
    if (!s.attached()) { Serial.println("[SWEEP] Servo chua attach — bam 'r' truoc."); return; }
    Serial.printf("[SWEEP] %s: 0 → 180 → 0\n", selName());
    for (int a = 0; a <= 180; a += 10) {
        s.write(a);
        Serial.printf("  %3d° (%dus)\n", a, s.readMicroseconds());
        delay(400);
    }
    for (int a = 170; a >= 0; a -= 10) {
        s.write(a);
        Serial.printf("  %3d° (%dus)\n", a, s.readMicroseconds());
        delay(400);
    }
    s.write(selRest());
    Serial.println("[SWEEP] Xong, ve goc nghi.");
}

static void jog(int delta) {
    Servo& s = selServo();
    if (!s.attached()) { Serial.println("[JOG] Servo chua attach — bam 'r' truoc."); return; }
    // 600-2400us / 180deg = 10us moi do -> read() tra dung goc da write(), khong troi
    int a = constrain(s.read() + delta, 0, 180);
    s.write(a);
    Serial.printf("[JOG] %s → %d° (%dus)\n", selName(), a, s.readMicroseconds());
}

static void pinToggleTest() {
    int pin = selPin();
    selServo().detach();
    pinMode(pin, OUTPUT);
    flushInput();
    Serial.printf("[PIN] GPIO %d dao 0V/3.3V moi 1s (10s). Do VOM tai dau cam servo.\n", pin);

    for (int i = 0; i < 10; i++) {
        bool level = (i % 2 == 0);
        digitalWrite(pin, level);
        Serial.printf("  GPIO %d = %s\n", pin, level ? "HIGH (3.3V)" : "LOW  (0V)");
        if (waitOrKey(1000)) break;
    }
    flushInput();
    digitalWrite(pin, LOW);
    Serial.println("[PIN] Xong. Attach lai servo:");
    attachServo(selServo(), pin, selRest());
}

static void rawLedcTest() {
    int pin = selPin();
    selServo().detach();

    // Không qua ESP32Servo: tự tính duty cho 50Hz / 16 bit (chu kỳ 20000us)
    auto usToDuty = [](int us) { return (uint32_t)((uint64_t)us * ((1 << RAW_LEDC_BITS) - 1) / 20000); };
    double f = ledcSetup(RAW_LEDC_CH, 50, RAW_LEDC_BITS);
    ledcAttachPin(pin, RAW_LEDC_CH);
    Serial.printf("[RAW] GPIO %d, LEDC kenh %d, tan so thuc %.2fHz\n", pin, RAW_LEDC_CH, f);
    flushInput();

    for (int i = 0; i < 10; i++) {
        int us = (i % 2 == 0) ? 1000 : 2000;
        ledcWrite(RAW_LEDC_CH, usToDuty(us));
        Serial.printf("  xung %dus (duty %u)\n", us, usToDuty(us));
        if (waitOrKey(1000)) break;
    }
    flushInput();
    ledcWrite(RAW_LEDC_CH, 0);
    ledcDetachPin(pin);
    Serial.println("[RAW] Xong. Attach lai servo:");
    attachServo(selServo(), pin, selRest());
}

static void printMenu() {
    Serial.printf("\n--- 'k'=knock 'd'=door 'a'=ca 2 | chan doan [%s]: '1'/'2'=chon "
                  "'i'=info 's'=quet 'p'=thu day 'l'=LEDC tho 'x'=detach 'r'=attach "
                  "'+'/'-'=±5° '>'/'<'=±1° ---\n",
                  selName());
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

    attachServo(servoKnock, PIN_SERVO_KNOCK, KNOCK_REST_ANGLE);
    attachServo(servoDoor,  PIN_SERVO_DOOR,  DOOR_CLOSE_ANGLE);

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

        case '1': selected = 1; break;
        case '2': selected = 2; break;
        case 'i': printInfo(); break;
        case 's': sweep(); break;
        case 'p': pinToggleTest(); break;
        case 'l': rawLedcTest(); break;
        case '+': case '=': jog(+5); break;
        case '-': case '_': jog(-5); break;
        case '>': case '.': jog(+1); break;
        case '<': case ',': jog(-1); break;

        case 'x':
            selServo().detach();
            Serial.printf("[DETACH] %s — truc phai LONG khi xoay tay.\n", selName());
            break;

        case 'r':
            Serial.printf("[ATTACH] %s — truc phai CUNG, ghi lai tay.\n", selName());
            attachServo(selServo(), selPin(), selRest());
            break;

        default:
            Serial.printf("[?] Lệnh '%c' không hợp lệ.\n", cmd);
            break;
    }

    printMenu();
}
