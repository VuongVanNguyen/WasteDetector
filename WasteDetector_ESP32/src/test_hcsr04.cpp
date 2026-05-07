#include <Arduino.h>
#include "config.h"

static int measureDistanceCm() {
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(PIN_ULTRASONIC_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);

    long duration = pulseIn(PIN_ULTRASONIC_ECHO, HIGH, 30000);
    Serial.printf("[RAW] duration=%ld us\n", duration);
    if (duration == 0) return -1;
    return (int)(duration * 0.0343f / 2.0f);
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_ECHO, INPUT);
    Serial.println("=== HC-SR04 Test ===");
    Serial.println("TRIG: GPIO 5 | ECHO: GPIO 4 (qua voltage divider)");
    Serial.println("--------------------");
}

void loop() {
    int dist = measureDistanceCm();

    if (dist == -1) {
        Serial.println("Khong co vat / timeout");
    } else if (dist < ULTRASONIC_DETECT_CM) {
        Serial.printf("PHAT HIEN VAT: %d cm  <-- trong nguong %d cm\n", dist, ULTRASONIC_DETECT_CM);
    } else {
        Serial.printf("Khong co vat: %d cm  (vuot nguong %d cm)\n", dist, ULTRASONIC_DETECT_CM);
    }

    delay(ULTRASONIC_POLL_MS);
}
