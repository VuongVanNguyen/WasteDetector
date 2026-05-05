#include <Arduino.h>
#include "config.h"
#include "tasks.h"

QueueHandle_t commandQueue;

void setup() {
    UART_PI.begin(UART_BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
    Serial.begin(115200);  // debug

    commandQueue = xQueueCreate(CMD_QUEUE_SIZE, sizeof(Command_t));

    // Core 1 — real-time mechanical control
    xTaskCreatePinnedToCore(taskRealtime, "taskRealtime", 4096, NULL, 2, NULL, 1);

    // Core 0 — communication & sensing
    xTaskCreatePinnedToCore(taskComms, "taskComms", 4096, NULL, 1, NULL, 0);
}

void loop() {
    // All logic runs in FreeRTOS tasks
    vTaskDelete(NULL);
}
