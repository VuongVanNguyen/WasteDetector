#include <Arduino.h>
#include <ESP32Servo.h>
#include "config.h"
#include "tasks.h"

static Servo servoKnock;
static Servo servoDoor;
static volatile bool irTriggered = false;
static volatile int irPosition = WASTE_NONE; 
static int currentPosition = WASTE_NONE;

static inline void pushResponse(const char* event, int param) {
    Response_t resp = {};
    strncpy(resp.event, event, sizeof(resp.event) - 1);
    resp.param = param;
    xQueueSend(responseQueue, &resp, pdMS_TO_TICKS(10));
}

static void doKnock(int count) {
    const TickType_t period = pdMS_TO_TICKS(KNOCK_INTERVAL_MS);

    for (int i = 1; i <= count; i++) {
        TickType_t t0 = xTaskGetTickCount();

        servoKnock.write(KNOCK_STRIKE_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_DWELL_MS));

        servoKnock.write(KNOCK_REST_ANGLE);
        vTaskDelay(pdMS_TO_TICKS(KNOCK_SETTLE_MS));

        pushResponse("KNOCK_DONE", i);

        if (i < count) {
            TickType_t elapsed = xTaskGetTickCount() - t0;
            if (elapsed < period) {
                vTaskDelay(period - elapsed);
            }
        }
    }
}

static void doDischarge() {
    servoDoor.write(DOOR_OPEN_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_HOLD_MS));

    servoDoor.write(DOOR_CLOSE_ANGLE);
    vTaskDelay(pdMS_TO_TICKS(DOOR_SETTLE_MS));

    pushResponse("DISCHARGE_DONE", 0);
}

static void motorRotate(uint8_t speed) {
    digitalWrite(PIN_MOTOR_IN1, HIGH);
    digitalWrite(PIN_MOTOR_IN2, LOW);
    ledcWrite(MOTOR_LEDC_CHANNEL, speed);
} 

static void motorStop() {
    digitalWrite(PIN_MOTOR_IN1, HIGH);
    digitalWrite(PIN_MOTOR_IN2, HIGH);
    ledcWrite(MOTOR_LEDC_CHANNEL, 0);
}

void IRAM_ATTR irPLASTIC() { irTriggered = true; irPosition = WASTE_PLASTIC; }
void IRAM_ATTR irGLASS()   { irTriggered = true; irPosition = WASTE_GLASS; }
void IRAM_ATTR irPAPER()   { irTriggered = true; irPosition = WASTE_PAPER; }
void IRAM_ATTR irMETAL()   { irTriggered = true; irPosition = WASTE_METAL; }

static void doRotate(int target) {
    if (target < WASTE_PLASTIC || target > WASTE_METAL) {
        pushResponse("ERROR", 1);   // 1 = INVALID_CMD
        return;
    }
    if (target == currentPosition) {
        pushResponse("ROTATE_DONE", target);
        return;
    }

    irTriggered = false;
    irPosition = WASTE_NONE;
    motorRotate(MOTOR_SPEED);
    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(MOTOR_TIMEOUT_MS);

    while (xTaskGetTickCount() < deadline) {
        if (irTriggered) {
            int pos = irPosition;
            irTriggered = false;
            if (pos == target) {
                motorStop();
                currentPosition = pos;
                vTaskDelay(pdMS_TO_TICKS(MOTOR_ROTATE_MS));
                pushResponse("ROTATE_DONE", pos);
                return;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    motorStop();
    pushResponse("ERROR", 0);
}

void taskRealtime(void* pvParameters) {
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);

    pinMode(PIN_MOTOR_IN1, OUTPUT);
    pinMode(PIN_MOTOR_IN2, OUTPUT);
    ledcSetup(MOTOR_LEDC_CHANNEL, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcAttachPin(PIN_MOTOR_ENA, MOTOR_LEDC_CHANNEL);
    motorStop();

    pinMode(PIN_IR_PLASTIC, INPUT);
    pinMode(PIN_IR_GLASS, INPUT);
    pinMode(PIN_IR_PAPER, INPUT);
    pinMode(PIN_IR_METAL, INPUT);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_PLASTIC), irPLASTIC, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_GLASS), irGLASS, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_PAPER), irPAPER, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_IR_METAL), irMETAL, FALLING);

    servoKnock.setPeriodHertz(50);
    servoKnock.attach(PIN_SERVO_KNOCK, 500, 2400);
    servoKnock.write(KNOCK_REST_ANGLE);

    servoDoor.setPeriodHertz(50);
    servoDoor.attach(PIN_SERVO_DOOR, 500, 2400);
    servoDoor.write(DOOR_CLOSE_ANGLE);

    Command_t cmd;
    for (;;) {
        if (xQueueReceive(commandQueue, &cmd, portMAX_DELAY) == pdTRUE) {
            if (strcmp(cmd.cmd, "KNOCK") == 0) {
                doKnock(cmd.param);
            } else if (strcmp(cmd.cmd, "ROTATE") == 0) {
                doRotate(cmd.param);
            } else if (strcmp(cmd.cmd, "DISCHARGE") == 0) {
                doDischarge();
            }
        }
    }
}
