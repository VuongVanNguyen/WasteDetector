#include <Arduino.h>
#include "config.h"
#include "tasks.h"

QueueHandle_t commandQueue;
QueueHandle_t responseQueue;

void setup() {
    UART_PI.begin(UART_BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
    Serial.begin(115200);  // debug

    commandQueue  = xQueueCreate(CMD_QUEUE_SIZE,      sizeof(Command_t));
    responseQueue = xQueueCreate(RESPONSE_QUEUE_SIZE, sizeof(Response_t));

    // Core 1 — real-time mechanical control
    xTaskCreatePinnedToCore(taskRealtime, "taskRealtime", 4096, NULL, 2, NULL, 1); //Real-time chạy ở đây

    // Core 0 — communication & sensing
    xTaskCreatePinnedToCore(taskComms, "taskComms", 4096, NULL, 1, NULL, 0); //Comms chạy ở đây
}

void loop() {
    // All logic runs in FreeRTOS tasks
    vTaskDelete(NULL);
}
