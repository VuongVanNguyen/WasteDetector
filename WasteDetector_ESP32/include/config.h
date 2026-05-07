#pragma once

// ============================================================
// Pin Mapping
// ============================================================

// Motor GA25-370 via L298N Mini
#define PIN_MOTOR_IN1   25
#define PIN_MOTOR_IN2   26
#define PIN_MOTOR_ENA   27   // PWM

// Servo SG90 (knock)
#define PIN_SERVO_KNOCK 18   // LEDC Channel 0

// Servo MG90S (discharge door)
#define PIN_SERVO_DOOR  19   // LEDC Channel 1

// 4x TCRT5000 IR sensors (position detection)
#define PIN_IR_PLASTIC  34
#define PIN_IR_GLASS    35
#define PIN_IR_PAPER    32
#define PIN_IR_METAL    33

// HC-SR04 ultrasonic (object detection)
#define PIN_ULTRASONIC_TRIG 5
#define PIN_ULTRASONIC_ECHO 4   // via 10k+20k voltage divider

// Relay (lighting)
#define PIN_RELAY       23

// UART2 to Raspberry Pi
#define UART_PI         Serial2
#define PIN_UART_RX     16
#define PIN_UART_TX     17
#define UART_BAUD       115200

// ============================================================
// Waste type codes (shared with Pi)
// ============================================================
#define WASTE_NONE      0
#define WASTE_PLASTIC   1
#define WASTE_GLASS     2
#define WASTE_PAPER     3
#define WASTE_METAL     4

// ============================================================
// Timing constants (ms) — calibrate with real hardware
// ============================================================
#define KNOCK_INTERVAL_MS       500     // period between knock starts (ms)
#define KNOCK_STRIKE_ANGLE      90      // SG90 strike angle (deg)
#define KNOCK_REST_ANGLE        0       // SG90 rest angle (deg)
#define KNOCK_DWELL_MS          150     // time held at strike position
#define KNOCK_SETTLE_MS         100     // time for servo to return to rest

#define DOOR_OPEN_ANGLE         90      // MG90S open angle (deg)
#define DOOR_CLOSE_ANGLE        0       // MG90S closed angle (deg)
#define DOOR_HOLD_MS            1500    // how long door stays open
#define DOOR_SETTLE_MS          500     // settle time after door closes

#define MOTOR_SPEED             180     // L298N ENA PWM 0-255 — calibrate
#define MOTOR_TIMEOUT_MS        5000    // max rotation time before error

#define ULTRASONIC_DETECT_CM    17      // object present if distance < this
#define ULTRASONIC_POLL_MS      100     // HC-SR04 poll interval

#define IR_THRESHOLD            500     // ADC value — calibrate with reflector

// ============================================================
// FreeRTOS queues
// ============================================================
#define CMD_QUEUE_SIZE      8
#define RESPONSE_QUEUE_SIZE 8
