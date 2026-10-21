#include <Arduino.h>
#include <ArduinoJson.h>
#include "config.h"
#include "tasks.h"

// HC-SR04
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

static void sendEvent(const char* event) {
    JsonDocument doc;
    doc["event"] = event;
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

static void sendEventInt(const char* event, const char* key, int value) {
    JsonDocument doc;
    doc["event"] = event;
    doc[key]     = value;
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

static const char* errorCodeName(int param) {
    switch (param) {
        case 1:  return "INVALID_CMD";
        case 2:  return "HOME_FAILED";
        case 3:  return "MOTION_FAULT";   // engine da KHOA — xem tasks.h
        default: return "MOTOR_TIMEOUT";
    }
}

static void sendResponse(const Response_t& resp) {
    JsonDocument doc;
    doc["event"] = resp.event;
    if (strcmp(resp.event, "KNOCK_DONE") == 0)
        doc["seq"]      = resp.param;
    else if (strcmp(resp.event, "ROTATE_DONE") == 0 || strcmp(resp.event, "READY") == 0)
        doc["position"] = resp.param;
    else if (strcmp(resp.event, "ERROR") == 0)
        doc["code"]     = errorCodeName(resp.param);
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

void taskComms(void* pvParameters) {
    pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_ECHO, INPUT);

    String inputBuffer;
    inputBuffer.reserve(128);

    bool objectPresent = false;

    // BẢO VỆ: chỉ báo OBJECT_DETECTED khi ống ĐÃ đậu tại HOME và không có chu
    // kỳ nào đang chạy. Core 1 bật cờ này bằng event READY (sau boot-home và
    // sau mỗi lần xả). Thiếu cổng chặn này thì một vật rơi vào lúc ống còn đang
    // quay sẽ khởi động chu kỳ thứ hai chồng lên chu kỳ đang dở — rác xuống sai
    // ngăn, và lệnh ROTATE thứ hai vào hàng đợi lúc vị trí chưa chốt.
    bool readyForObject = false;

    for (;;) {
        int dist     = measureDistanceCm();
        bool detected = (dist > 0 && dist < ULTRASONIC_DETECT_CM);

        if (detected && !objectPresent) {
            objectPresent = true;
            if (readyForObject) {
                sendEventInt("OBJECT_DETECTED", "distance", dist);
                readyForObject = false;     // khoá cho tới READY kế tiếp
            }
        } else if (!detected && objectPresent) {
            objectPresent = false;
        }
        // Đọc UART từ Pi 
        while (UART_PI.available()) {
            char ch = UART_PI.read();

            if (ch == '\n') {
                if (inputBuffer.length() == 0) continue;

                JsonDocument doc;
                DeserializationError err = deserializeJson(doc, inputBuffer);
                inputBuffer.clear();

                if (err) continue;  

                const char* cmd = doc["cmd"];
                if (!cmd) continue;

                if (strcmp(cmd, "KNOCK") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "KNOCK", sizeof(msg.cmd));
                    msg.param = doc["count"] | 1;
                    xQueueSend(commandQueue, &msg, pdMS_TO_TICKS(10));

                } else if (strcmp(cmd, "ROTATE") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "ROTATE", sizeof(msg.cmd));
                    msg.param = doc["target"] | WASTE_NONE;
                    xQueueSend(commandQueue, &msg, pdMS_TO_TICKS(10));

                } else if (strcmp(cmd, "DISCHARGE") == 0) {
                    Command_t msg;
                    strlcpy(msg.cmd, "DISCHARGE", sizeof(msg.cmd));
                    msg.param = 0;
                    xQueueSend(commandQueue, &msg, pdMS_TO_TICKS(10));

                } else if (strcmp(cmd, "HOME") == 0) {
                    // Lối khôi phục cho Pi: ép ống về HOME (ngăn Thủy tinh) mà
                    // không cần một chu kỳ đầy đủ. Dùng sau khi Pi huỷ chu kỳ
                    // giữa chừng. KHÔNG gỡ được chốt FAULT — cái đó cần người.
                    Command_t msg;
                    strlcpy(msg.cmd, "HOME", sizeof(msg.cmd));
                    msg.param = 0;
                    xQueueSend(commandQueue, &msg, pdMS_TO_TICKS(10));

                } else if (strcmp(cmd, "PING") == 0) {
                    sendEvent("ALIVE");
                }

            } else if (ch != '\r') {
                if (inputBuffer.length() < 256)
                    inputBuffer += ch;
            }
        }

        Response_t resp;
        while (xQueueReceive(responseQueue, &resp, 0) == pdTRUE) {
            // READY = ống đã đậu tại HOME → mở cổng nhận vật. ERROR không mở
            // cổng: khi Core 1 báo lỗi (nhất là MOTION_FAULT) thì phải có người
            // xử lý, không được tự nhận vật tiếp.
            if (strcmp(resp.event, "READY") == 0) readyForObject = true;
            sendResponse(resp);
        }

        vTaskDelay(pdMS_TO_TICKS(ULTRASONIC_POLL_MS));
    }
}

