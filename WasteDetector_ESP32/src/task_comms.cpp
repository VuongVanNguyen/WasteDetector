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

static void sendResponse(const Response_t& resp) {
    JsonDocument doc;
    doc["event"] = resp.event;
    if (strcmp(resp.event, "KNOCK_DONE") == 0)
        doc["seq"]      = resp.param;
    else if (strcmp(resp.event, "ROTATE_DONE") == 0)
        doc["position"] = resp.param;
    else if (strcmp(resp.event, "ERROR") == 0)
        doc["code"]     = (resp.param == 1) ? "INVALID_CMD" : "MOTOR_TIMEOUT";
    serializeJson(doc, UART_PI);
    UART_PI.print('\n');
}

void taskComms(void* pvParameters) {
    pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_ECHO, INPUT);
    pinMode(PIN_RELAY, OUTPUT);
    digitalWrite(PIN_RELAY, LOW);   

    String inputBuffer;
    inputBuffer.reserve(128);

    bool objectPresent = false;

    for (;;) {
        int dist     = measureDistanceCm();
        bool detected = (dist > 0 && dist < ULTRASONIC_DETECT_CM);

        if (detected && !objectPresent) {
            sendEventInt("OBJECT_DETECTED", "distance", dist);
            objectPresent = true;
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

                } else if (strcmp(cmd, "LIGHT") == 0) {
                    const char* state = doc["state"];
                    if (state && strcmp(state, "ON") == 0)
                        digitalWrite(PIN_RELAY, HIGH);
                    else
                        digitalWrite(PIN_RELAY, LOW);

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
            sendResponse(resp);
        }

        vTaskDelay(pdMS_TO_TICKS(ULTRASONIC_POLL_MS));
    }
}

