// ============================================================
// TEST TONG — Mo phong toan bo tac vu ESP32 (khong can Raspberry Pi)
// ============================================================
// Flash:   pio run -e test_full_cycle --target upload
// Monitor: pio device monitor -e test_full_cycle
//
// Phim lenh (go vao Serial Monitor):
//   'a' -> Nhua      (WASTE_PLASTIC)
//   'b' -> Thuy tinh (WASTE_GLASS)
//   'c' -> Giay      (WASTE_PAPER)
//   'd' -> Kim loai  (WASTE_METAL)
//   'u' -> Doc 1 lan HC-SR04
//   'r' -> Ve HOME thu cong
//   's' -> In trang thai he thong
//   'h' -> In lai menu
//
// Khi bam a/b/c/d, ESP32 chay full quy trinh nhu khi nhan lenh tu Pi:
//   OBJECT_DETECTED (gia lap) -> KNOCK x3 -> (gia lap Pi thu am + chup anh
//   + fusion) -> ROTATE -> DISCHARGE -> VE HOME
//
// DIEM DAU HOME = NGAN THUY TINH. Sau moi chu ky ong tu quay ve dung cam bien
// Thuy tinh; ISR cua chinh cam bien do phanh ong lai. Viec nay do ESP32 TU LAM
// ngay sau khi cua dong, Pi khong phai ra lenh — Pi chi doi them event READY,
// va KHONG duoc nhan vat moi truoc do.
//
//   Kim loai ─── Giay ─── THUY TINH ─── Nhua    ╳ cam khep vong
//     +180°      +90°     0° (HOME)     −90°
//            <──── CW ────   ── CCW ──>
//
// Rac THUY TINH la truong hop dac biet: ngan xa CHINH LA HOME, nen buoc ROTATE
// khong quay gi ca va buoc ve HOME sau do cung khong. Chi tiet xem motion.cpp.
//
// Kien truc giong het production:
//   Core 1 (prio 2) taskRealtime  — servo, motor, IR interrupt
//   Core 0 (prio 1) taskPiSim     — dong vai Raspberry Pi, dieu phoi
//   commandQueue / responseQueue  — hang doi FreeRTOS giua 2 core
//
// Cac moc thoi gian mo phong Pi chinh trong khoi SIM_* ben duoi.
// ============================================================

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "config.h"
#include "motion.h"
#include "tasks.h"

// ------------------------------------------------------------
// Thoi gian mo phong phia Pi (ms) — canh cho giong thuc te
// ------------------------------------------------------------
#define SIM_AUDIO_WINDOW_MS     300   // cua so thu am M-306 sau khi go
#define SIM_FFT_MS              250   // NumPy/SciPy FFT
#define SIM_CAMERA_CAPTURE_MS   400   // Pi Camera chup anh
#define SIM_AI_INFERENCE_MS     600   // TFLite phan loai
#define SIM_FUSION_MS           100   // tong hop audio + camera
#define SIM_PRE_ROTATE_MS       200   // do tre truoc khi gui ROTATE
#define SIM_POST_CYCLE_MS       500   // nghi truoc khi san sang chu ky moi
#define SIM_KNOCK_COUNT         3     // so lan go moi chu ky

// Timeout cho cho su kien tu Core 1 (an toan hon cho vinh vien)
#define WAIT_EVENT_TIMEOUT_MS   (MOTOR_TIMEOUT_MS + 3000)
#define WAIT_MOTION_TIMEOUT_MS  30000

QueueHandle_t commandQueue;
QueueHandle_t responseQueue;

static inline const char* wasteName(int code) { return motionPosName(code); }

// ============================================================
// PHAN 2 — Core 0: taskPiSim (dong vai Raspberry Pi dieu phoi)
// ============================================================
static volatile bool cycleRunning = false;
static uint32_t cycleCount = 0;

static int measureDistanceCm() {
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(PIN_ULTRASONIC_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
    long duration = pulseIn(PIN_ULTRASONIC_ECHO, HIGH, 30000);
    if (duration == 0) return -1;
    return (int)(duration * 0.0343f / 2.0f);
}

static void sendCommand(const char* cmd, int param) {
    Command_t msg = {};
    strlcpy(msg.cmd, cmd, sizeof(msg.cmd));
    msg.param = param;
    xQueueSend(commandQueue, &msg, pdMS_TO_TICKS(10));
}

// Cho 1 event cu the tu Core 1. Tra ve true neu nhan dung event.
// Cac event khac (vd KNOCK_DONE trung gian) van duoc in ra.
static bool waitEvent(const char* wanted, int* outParam, uint32_t timeoutMs) {
    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeoutMs);
    Response_t resp;

    while ((int32_t)(deadline - xTaskGetTickCount()) > 0) {
        TickType_t remain = deadline - xTaskGetTickCount();
        if (xQueueReceive(responseQueue, &resp, remain) != pdTRUE) break;

        if (strcmp(resp.event, "ERROR") == 0) {
            const char* code = resp.param == 1 ? "INVALID_CMD"
                             : resp.param == 2 ? "HOME_FAILED"
                             : resp.param == 3 ? "MOTION_FAULT"
                                               : "MOTOR_TIMEOUT";
            Serial.printf("  <-- [ESP32] ERROR code=%s\n", code);
            if (resp.param == 3)
                Serial.println("      => Engine da KHOA. Quay tay ong ve Thuy tinh (thao xoan) roi reset.");
            return false;
        }
        if (strcmp(resp.event, "KNOCK_DONE") == 0)
            Serial.printf("  <-- [ESP32] KNOCK_DONE seq=%d\n", resp.param);
        else if (strcmp(resp.event, "ROTATE_DONE") == 0)
            Serial.printf("  <-- [ESP32] ROTATE_DONE position=%d (%s)\n",
                          resp.param, wasteName(resp.param));
        else if (strcmp(resp.event, "READY") == 0)
            Serial.printf("  <-- [ESP32] READY position=%s (xoan %+d do)\n",
                          wasteName(resp.param), motionTwistDeg(resp.param));
        else
            Serial.printf("  <-- [ESP32] %s\n", resp.event);

        if (strcmp(resp.event, wanted) == 0) {
            if (outParam) *outParam = resp.param;
            return true;
        }
    }
    Serial.printf("  !!! TIMEOUT khi cho su kien %s\n", wanted);
    return false;
}

static void drainResponses() {
    Response_t resp;
    while (xQueueReceive(responseQueue, &resp, 0) == pdTRUE) { /* bo qua */ }
}

static void runFullCycle(int wasteType) {
    uint32_t t0 = millis();
    cycleCount++;
    drainResponses();

    Serial.println("\n================================================");
    Serial.printf("CHU KY #%lu — Mo phong rac loai: %s (code %d)\n",
                  (unsigned long)cycleCount, wasteName(wasteType), wasteType);
    Serial.println("================================================");

    // --- B0: Ong phai dang dau o HOME truoc khi nhan vat moi ---
    // Trong production day la bat buoc: taskComms chan OBJECT_DETECTED cho toi
    // khi nhan duoc READY. O day ta lam ro dieu do bang mot lan ve HOME.
    if (!motionIsHome()) {
        Serial.printf("[0] Ong dang o %s, chua dau tai HOME -> ve HOME truoc khi nhan vat.\n",
                      wasteName(motionPosition()));
        sendCommand("HOME", 0);
        if (!waitEvent("READY", NULL, WAIT_MOTION_TIMEOUT_MS)) {
            Serial.println("[X] Khong ve duoc HOME -> huy chu ky.");
            cycleRunning = false;
            return;
        }
    }

    // --- B1: HC-SR04 phat hien vat (gia lap neu chua gan cam bien) ---
    int dist = measureDistanceCm();
    if (dist <= 0 || dist >= ULTRASONIC_DETECT_CM) {
        Serial.printf("[1] HC-SR04 doc %d cm -> gia lap vat roi vao ong (12 cm)\n", dist);
        dist = 12;
    } else {
        Serial.printf("[1] HC-SR04 doc %d cm -> co vat trong ong\n", dist);
    }
    Serial.printf("  --> {\"event\":\"OBJECT_DETECTED\",\"distance\":%d}\n", dist);

    // --- B2: Pi gui KNOCK ---
    Serial.printf("[2]{\"cmd\":\"KNOCK\",\"count\":%d}  (SG90 GPIO %d)\n",
                  SIM_KNOCK_COUNT, PIN_SERVO_KNOCK);
    sendCommand("KNOCK", SIM_KNOCK_COUNT);

    int seq = 0;
    bool knockOk = false;
    for (int i = 0; i < SIM_KNOCK_COUNT; i++) {
        if (!waitEvent("KNOCK_DONE", &seq, WAIT_EVENT_TIMEOUT_MS)) break;
        if (seq == SIM_KNOCK_COUNT) { knockOk = true; break; }
    }
    if (!knockOk) {
        Serial.println("[X] Khong nhan du KNOCK_DONE -> huy chu ky.");
        cycleRunning = false;
        return;
    }

    // --- B3: Pi thu am + FFT (mo phong) ---
    Serial.printf("[3]Mo cua so thu am M-306 (%d ms)...\n", SIM_AUDIO_WINDOW_MS);
    vTaskDelay(pdMS_TO_TICKS(SIM_AUDIO_WINDOW_MS));
    Serial.printf("    Phan tich FFT (%d ms)...\n", SIM_FFT_MS);
    vTaskDelay(pdMS_TO_TICKS(SIM_FFT_MS));
    Serial.printf("    -> audio_type=%s  audio_confidence=0.82\n", wasteName(wasteType));

    // --- B4: Pi chup anh + AI (mo phong) ---
    Serial.printf("[4]Pi Camera chup anh (%d ms)...\n", SIM_CAMERA_CAPTURE_MS);
    vTaskDelay(pdMS_TO_TICKS(SIM_CAMERA_CAPTURE_MS));
    Serial.printf("    TFLite inference (%d ms)...\n", SIM_AI_INFERENCE_MS);
    vTaskDelay(pdMS_TO_TICKS(SIM_AI_INFERENCE_MS));
    Serial.printf("    -> cam_type=%s  cam_confidence=0.91\n", wasteName(wasteType));

    // --- B5: Fusion ---
    vTaskDelay(pdMS_TO_TICKS(SIM_FUSION_MS));
    Serial.printf("[5]Fusion -> waste_type = %d (%s)\n", wasteType, wasteName(wasteType));
    vTaskDelay(pdMS_TO_TICKS(SIM_PRE_ROTATE_MS));

    // --- B6: Pi gui ROTATE ---
    Serial.printf("[6]{\"cmd\":\"ROTATE\",\"target\":%d}  (motor + TCRT5000)\n", wasteType);
    sendCommand("ROTATE", wasteType);
    int pos = 0;
    if (!waitEvent("ROTATE_DONE", &pos, WAIT_MOTION_TIMEOUT_MS)) {
        Serial.println("[X] ROTATE that bai -> huy chu ky.");
        cycleRunning = false;
        return;
    }

    // --- B7: Pi gui DISCHARGE (ESP32 tu ve HOME ngay sau khi cua dong) ---
    Serial.printf("[7]{\"cmd\":\"DISCHARGE\"}  (MG90S GPIO %d, giu %d ms)\n",
                  PIN_SERVO_DOOR, DOOR_HOLD_MS);
    sendCommand("DISCHARGE", 0);
    if (!waitEvent("DISCHARGE_DONE", NULL, WAIT_EVENT_TIMEOUT_MS)) {
        Serial.println("[X] DISCHARGE that bai -> huy chu ky.");
        cycleRunning = false;
        return;
    }

    // --- B8: Doi ong ve diem dau. Chua co READY thi CHUA duoc nhan vat moi ---
    Serial.println("[8]Cho ong ve HOME (cam bien Thuy tinh)...");
    if (!waitEvent("READY", NULL, WAIT_MOTION_TIMEOUT_MS)) {
        Serial.println("[X] Khong ve duoc HOME — chu ky sau se tu thu lai o buoc [0].");
        cycleRunning = false;
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(SIM_POST_CYCLE_MS));

    Serial.println("------------------------------------------------");
    Serial.printf("HOAN TAT chu ky #%lu — %s — tong %lu ms\n",
                  (unsigned long)cycleCount, wasteName(wasteType),
                  (unsigned long)(millis() - t0));
    Serial.println("San sang cho vat tiep theo.\n");
    cycleRunning = false;
}

static void printMenu() {
    Serial.println("+----------------------------------------------+");
    Serial.println("|  a = Nhua       b = Thuy tinh                 |");
    Serial.println("|  c = Giay       d = Kim loai                  |");
    Serial.println("|  u = doc HC-SR04                              |");
    Serial.println("|  r = ve HOME        s = trang thai   h = menu |");
    Serial.println("+----------------------------------------------+");
}

static void printStatus() {
    int pos = motionPosition();
    Serial.println("\n--- TRANG THAI HE THONG ---");
    Serial.printf("  Vi tri ong hien tai : %s", wasteName(pos));
    if (motionTwistDeg(pos) != MOTION_TWIST_UNKNOWN)
        Serial.printf(" (xoan %+d do, tran +%d/-90)", motionTwistDeg(pos), MAX_TWIST_DEG);
    Serial.println();
    Serial.printf("  Chu ky da chay      : %lu\n", (unsigned long)cycleCount);
    Serial.printf("  Dang chay chu ky    : %s\n", cycleRunning ? "CO" : "KHONG");
    Serial.printf("  Uptime              : %lu s\n", (unsigned long)(millis() / 1000));
    if (motionFaulted())
        Serial.printf("  !! ENGINE DA KHOA   : %s\n", motionFaultReason());
    motionPrintState();
    Serial.println("---------------------------\n");
}

static void taskPiSim(void* pvParameters) {
    pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_ECHO, INPUT);

    Serial.println("\n=== TEST TONG — MO PHONG TOAN BO TAC VU ESP32 ===");
    Serial.println("Doi Core 1 khoi tao xong va tu dua ong ve HOME...");
    // Cho READY thay vi doan mot khoang delay co dinh: boot-home co the mat
    // vai giay (grace + xoay thuc te), lau hon nhieu so voi 800ms doan truoc.
    if (!waitEvent("READY", NULL, WAIT_MOTION_TIMEOUT_MS + BOOT_HOME_GRACE_MS)) {
        Serial.println("[X] Boot KHONG ve duoc HOME — xem log motion phia tren.");
        Serial.println("    Motor co 12V chua? Sua xong bam 'r' de thu lai.");
    }
    Serial.println("Core 1: taskRealtime (prio 2) | Core 0: taskPiSim (prio 1)");
    Serial.printf("Servo go=GPIO%d  Servo cua=GPIO%d  Motor IN1/IN2=GPIO%d/%d\n",
                  PIN_SERVO_KNOCK, PIN_SERVO_DOOR,
                  PIN_MOTOR_IN1, PIN_MOTOR_IN2);
    printMenu();

    for (;;) {
        if (!Serial.available()) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        char key = Serial.read();
        if (key == '\n' || key == '\r' || key == ' ') continue;

        switch (key) {
            case 'a': case 'A': cycleRunning = true; runFullCycle(WASTE_PLASTIC); break;
            case 'b': case 'B': cycleRunning = true; runFullCycle(WASTE_GLASS);   break;
            case 'c': case 'C': cycleRunning = true; runFullCycle(WASTE_PAPER);   break;
            case 'd': case 'D': cycleRunning = true; runFullCycle(WASTE_METAL);   break;

            case 'u': case 'U': {
                int d = measureDistanceCm();
                if (d < 0) Serial.println("[HC-SR04] Khong co echo (timeout)");
                else       Serial.printf("[HC-SR04] %d cm — %s\n", d,
                                d < ULTRASONIC_DETECT_CM ? "CO VAT" : "trong");
                break;
            }

            case 'r': case 'R':
                Serial.println("[HOME] {\"cmd\":\"HOME\"} thu cong...");
                drainResponses();
                sendCommand("HOME", 0);
                waitEvent("READY", NULL, WAIT_MOTION_TIMEOUT_MS);
                break;

            case 's': case 'S': printStatus(); break;
            case 'h': case 'H': printMenu();   break;

            default:
                Serial.printf("[?] Phim '%c' khong hop le. Bam 'h' de xem menu.\n", key);
                break;
        }
    }
}

// ============================================================
// setup / loop
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(300);

    commandQueue  = xQueueCreate(CMD_QUEUE_SIZE,      sizeof(Command_t));
    responseQueue = xQueueCreate(RESPONSE_QUEUE_SIZE, sizeof(Response_t));

    xTaskCreatePinnedToCore(taskRealtime, "taskRealtime", 8192, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(taskPiSim,    "taskPiSim",    8192, NULL, 1, NULL, 0);
}

void loop() {
    vTaskDelete(NULL);
}
