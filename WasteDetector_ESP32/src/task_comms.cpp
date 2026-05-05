#include <Arduino.h>
#include <ArduinoJson.h>
#include "config.h"
#include "tasks.h"

// ── HC-SR04 ──────────────────────────────────────────────────

// Trả về khoảng cách (cm), hoặc -1 nếu timeout (không có vật / quá xa)
static int measureDistanceCm() {
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(PIN_ULTRASONIC_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);

    // timeout 30 000 µs ≈ max ~5 m — đủ cho ống ngắn
    long duration = pulseIn(PIN_ULTRASONIC_ECHO, HIGH, 30000);
    if (duration == 0) return -1;
    return (int)(duration * 0.0343f / 2.0f);
}

// ── JSON send helpers ─────────────────────────────────────────

static void sendEvent(const char* event) {
    JsonDocument doc;
    doc["event"] = event;
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

// Gửi event kèm 1 field số nguyên (dùng cho OBJECT_DETECTED + distance)
static void sendEventInt(const char* event, const char* key, int value) {
    JsonDocument doc;
    doc["event"] = event;
    doc[key]     = value;
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

// ── taskComms — Core 0, Priority 1 ───────────────────────────
void taskComms(void* pvParameters) {
    pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_ECHO, INPUT);
    pinMode(PIN_RELAY, OUTPUT);
    digitalWrite(PIN_RELAY, LOW);   // đèn tắt khi khởi động

    String inputBuffer;
    inputBuffer.reserve(128);

    // Debounce HC-SR04: chỉ push OBJECT_DETECTED một lần khi vật xuất hiện
    bool objectPresent = false;

    for (;;) {
        // ── Poll HC-SR04 ──────────────────────────────────────
        int dist     = measureDistanceCm();
        bool detected = (dist > 0 && dist < ULTRASONIC_DETECT_CM);

        if (detected && !objectPresent) {
            // Rising edge — vật vừa rơi vào ống → báo Pi
            sendEventInt("OBJECT_DETECTED", "distance", dist);
            objectPresent = true;
        } else if (!detected && objectPresent) {
            // Falling edge — ống đã trống (sau khi xả rác xong)
            objectPresent = false;
        }

        // ── Đọc UART từ Pi ────────────────────────────────────
        while (UART_PI.available()) {
            char ch = UART_PI.read();

            if (ch == '\n') {
                if (inputBuffer.length() == 0) continue;

                JsonDocument doc;
                DeserializationError err = deserializeJson(doc, inputBuffer);
                inputBuffer.clear();

                if (err) continue;  // JSON lỗi — bỏ qua frame

                const char* cmd = doc["cmd"];
                if (!cmd) continue;

                if (strcmp(cmd, "KNOCK") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "KNOCK", sizeof(msg.cmd));
                    msg.param = doc["count"] | 1;
                    xQueueSend(commandQueue, &msg, 0);

                } else if (strcmp(cmd, "ROTATE") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "ROTATE", sizeof(msg.cmd));
                    msg.param = doc["target"] | WASTE_NONE;
                    xQueueSend(commandQueue, &msg, 0);

                } else if (strcmp(cmd, "DISCHARGE") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "DISCHARGE", sizeof(msg.cmd));
                    msg.param = 0;
                    xQueueSend(commandQueue, &msg, 0);

                } else if (strcmp(cmd, "LIGHT") == 0) {
                    // Relay điều khiển trực tiếp — không cần queue
                    const char* state = doc["state"];
                    if (state && strcmp(state, "ON") == 0)
                        digitalWrite(PIN_RELAY, HIGH);
                    else
                        digitalWrite(PIN_RELAY, LOW);

                } else if (strcmp(cmd, "PING") == 0) {
                    sendEvent("ALIVE");
                }

            } else if (ch != '\r') {
                // Giới hạn buffer tránh tràn bộ nhớ nếu Pi gửi dữ liệu không có '\n'
                if (inputBuffer.length() < 256)
                    inputBuffer += ch;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(ULTRASONIC_POLL_MS));
    }
}
// End of file
