# WasteDetector — Máy Phân Loại Rác Thông Minh

## Tổng quan kiến trúc (2 lớp)

Hệ thống tự động phân loại rác thành 4 loại: Nhựa, Thủy tinh, Giấy, Kim loại.

**Lớp 1 — SBC: Raspberry Pi 4**
- Xử lý AI/Vision (OpenCV + TFLite) — **chỉ phân loại LOẠI vật**, không phát hiện sự hiện diện
- Phân tích FFT âm thanh (NumPy/SciPy)
- Ra quyết định phân loại, điều phối toàn hệ thống
- Giao tiếp xuống ESP32: **UART Serial2 — JSON — 115200 baud**
- Cảm biến âm thanh: INMP441 qua **I2S**

**Lớp 2 — MCU: ESP32 Dev Module** (thay thế 2× Arduino Nano cũ)
- Điều khiển toàn bộ cơ cấu cơ học và cảm biến real-time
- FreeRTOS Dual-core:
  - **Core 1** (Priority 2): Servo SG90/MG90S, Motor L298N, Interrupt TCRT5000
  - **Core 0** (Priority 1): UART ↔ Pi 4, HC-SR04 polling, Relay control

---

## Danh mục linh kiện (BOM)

| Linh kiện | Model | Vai trò |
|-----------|-------|---------|
| SBC | Raspberry Pi 4 | Xử lý AI, FFT, điều phối |
| MCU | ESP32 Dev Module | Điều khiển cơ cấu, cảm biến |
| Mic âm thanh | INMP441 | Thu âm I2S → FFT phân tích vật liệu |
| Camera | Pi Camera | Chụp ảnh → AI phân loại LOẠI vật (không dùng để detect) |
| Cảm biến khoảng cách | HC-SR04 | **Duy nhất** phát hiện vật thể rơi vào ống |
| Cảm biến IR | 4× TCRT5000 | Định vị góc xoay ống (4 vị trí) |
| Servo gõ | SG90 | Gõ vật thể tạo âm thanh |
| Servo cửa | MG90S | Mở/đóng cửa trượt đáy ống |
| Motor xoay ống | GA25-370 (12V DC) | Xoay ống trụ PVC đến đúng ngăn |
| Driver motor | L298N Mini | H-Bridge điều khiển GA25-370 |
| Relay | SONGLE SRD-03VDC | Bật/tắt đèn chiếu sáng |
| Nguồn | Tách biệt 5V + 12V | 5V: Pi/ESP32/Logic — 12V: Motor |

---

## Kết nối chân (Pin Mapping)

### ESP32 → L298N Mini (Motor GA25-370)
| ESP32 GPIO | L298N Pin | Chức năng |
|------------|-----------|-----------|
| GPIO 25 | IN1 | Chiều quay A |
| GPIO 26 | IN2 | Chiều quay B |
| GPIO 27 | ENA (PWM) | Tốc độ motor |
| GND | GND | Chung mass |
| 12V ngoài | VMS | Nguồn motor |

### ESP32 → Servo SG90 (gõ vật thể)
| ESP32 GPIO | Servo Pin | Chức năng |
|------------|-----------|-----------|
| GPIO 18 | Signal (PWM) | LEDC Channel 0 — 50Hz |
| 5V | VCC | Nguồn servo |
| GND | GND | Chung mass |

### ESP32 → Servo MG90S (cửa trượt đáy)
| ESP32 GPIO | Servo Pin | Chức năng |
|------------|-----------|-----------|
| GPIO 19 | Signal (PWM) | LEDC Channel 1 — 50Hz |
| 5V | VCC | Nguồn servo |
| GND | GND | Chung mass |

### ESP32 → 4× TCRT5000 (định vị góc)
| ESP32 GPIO | TCRT5000 | Vị trí |
|------------|----------|--------|
| GPIO 34 | OUT #1 | Ngăn Nhựa |
| GPIO 35 | OUT #2 | Ngăn Thủy tinh |
| GPIO 32 | OUT #3 | Ngăn Giấy |
| GPIO 33 | OUT #4 | Ngăn Kim loại |
| 3.3V | VCC | Nguồn cảm biến |
| GND | GND | Chung mass |

> Tấm phản quang gắn lệch góc θ_lag so với vị trí thực để bù quán tính cơ học khi motor dừng (không dùng PID).

### ESP32 → HC-SR04
| ESP32 GPIO | HC-SR04 | Chức năng |
|------------|---------|-----------|
| GPIO 5 | TRIG | Phát xung |
| GPIO 4 | ECHO | Nhận phản hồi |
| 5V | VCC | Nguồn |
| GND | GND | Chung mass |

> ⚠️ ECHO trả về 5V logic → cần **voltage divider** (10kΩ + 20kΩ) xuống 3.3V trước khi vào GPIO ESP32.

### ESP32 → Relay Module (đèn chiếu sáng)
| ESP32 GPIO | Relay Pin | Chức năng |
|------------|-----------|-----------|
| GPIO 23 | IN (Signal) | Trigger relay |
| 3.3V | VCC | Nguồn coil (SRD-03VDC tương thích trực tiếp) |
| GND | GND | Chung mass |

### ESP32 ↔ Raspberry Pi 4 (UART)
| ESP32 | Raspberry Pi 4 | Chức năng |
|-------|----------------|-----------|
| GPIO 16 (RX2) | TX (GPIO 14) | Pi gửi lệnh → ESP32 nhận |
| GPIO 17 (TX2) | RX (GPIO 15) | ESP32 phản hồi → Pi nhận |
| GND | GND | Chung mass bắt buộc |

> Cả 2 đều dùng mức logic 3.3V → kết nối trực tiếp, không cần level shifter.

### Raspberry Pi 4 → INMP441 (I2S)
| Pi 4 GPIO | INMP441 Pin | Chức năng |
|-----------|-------------|-----------|
| GPIO 18 | SCK | I2S Clock |
| GPIO 19 | WS | Word Select (L/R) |
| GPIO 20 | SD | Data |
| 3.3V | VDD | Nguồn |
| GND | GND | Chung mass |

---

## Giao thức truyền thông (JSON over UART 115200 baud)

### Pi → ESP32 (lệnh điều khiển)
```json
{"cmd": "START_ANALYSIS"}
{"cmd": "KNOCK", "count": 3}
{"cmd": "ROTATE", "target": 1}
{"cmd": "DISCHARGE"}
{"cmd": "LIGHT", "state": "ON"}
{"cmd": "LIGHT", "state": "OFF"}
{"cmd": "PING"}
```

> `target`: 1=Nhựa, 2=Thủy tinh, 3=Giấy, 4=Kim loại

### ESP32 → Pi (phản hồi / push sự kiện)
```json
{"event": "OBJECT_DETECTED", "distance": 12}
{"event": "KNOCK_DONE", "seq": 1}
{"event": "ROTATE_DONE", "position": 1}
{"event": "DISCHARGE_DONE"}
{"event": "ALIVE"}
{"event": "ERROR", "code": "MOTOR_TIMEOUT"}
{"event": "ERROR", "code": "INVALID_CMD"}
```

---

## Mã loại rác (đồng bộ toàn hệ thống)

| Mã | Hằng số | Loại |
|----|---------|------|
| 0 | `WASTE_NONE` | Không xác định |
| 1 | `WASTE_PLASTIC` | Nhựa |
| 2 | `WASTE_GLASS` | Thủy tinh |
| 3 | `WASTE_PAPER` | Giấy/Carton |
| 4 | `WASTE_METAL` | Kim loại |

---

## Luồng vận hành (Workflow)

```
[ESP32] HC-SR04 phát hiện vật rơi vào ống
   → Push: {"event": "OBJECT_DETECTED", "distance": 12}
         ↓
[Pi] Nhận OBJECT_DETECTED
   → Bật đèn: {"cmd": "LIGHT", "state": "ON"}
   → Gửi: {"cmd": "KNOCK", "count": 3}
         ↓
[ESP32] Core 1: SG90 gõ 3 lần, cách nhau 500ms
   → Sau mỗi lần gõ push: {"event": "KNOCK_DONE", "seq": 1/2/3}
         ↓
[Pi] Nhận KNOCK_DONE (seq==count) → mở cửa sổ thu âm INMP441 (~300ms)
   → Thu âm → FFT → audio_type + audio_confidence
   → Chụp ảnh → AI → cam_type + cam_confidence
   → Fusion → waste_type cuối cùng
         ↓
[Pi] Gửi: {"cmd": "ROTATE", "target": waste_type}
         ↓
[ESP32] Core 1: Bật motor, TCRT5000 interrupt → dừng tại vị trí
   → Push: {"event": "ROTATE_DONE", "position": waste_type}
         ↓
[Pi] Nhận ROTATE_DONE → Gửi: {"cmd": "DISCHARGE"}
         ↓
[ESP32] Core 1: MG90S mở cửa → chờ → đóng
   → Push: {"event": "DISCHARGE_DONE"}
         ↓
[Pi] Tắt đèn, cập nhật GUI, sẵn sàng cho lần tiếp theo
```

---

## Phân công FreeRTOS (ESP32)

| Core | Task | Nội dung |
|------|------|---------|
| Core 1 (Priority 2) | `taskRealtime` | Servo SG90/MG90S, Motor L298N, Interrupt TCRT5000 |
| Core 0 (Priority 1) | `taskComms` | UART ↔ Pi 4, HC-SR04 polling, Relay control |
| Shared | `commandQueue` | FreeRTOS Queue truyền lệnh từ Core 0 → Core 1 |

---

## Cấu trúc file

```
WasteDetector/
├── CLAUDE.md                              ← file này
├── WasteDetector.code-workspace
│
├── WasteDetector_ESP32/                   ← PlatformIO — ESP32
│   ├── platformio.ini                     (esp32dev, ArduinoJson, ESP32Servo)
│   ├── include/
│   │   ├── config.h                       (pin mapping, hằng số hệ thống)
│   │   └── tasks.h                        (khai báo FreeRTOS tasks + commandQueue)
│   └── src/
│       ├── main.cpp                       (setup: khởi tạo, tạo tasks; loop rỗng)
│       ├── task_realtime.cpp              (Core 1: servo SG90/MG90S, motor, IR)
│       └── task_comms.cpp                 (Core 0: UART JSON, HC-SR04, relay)
│
└── Raspberry PI/                          ← Python — Pi orchestrator
    ├── main_controller.py                 (bộ não: điều phối toàn bộ flow)
    ├── pi_config.py                       (hằng số toàn hệ thống)
    ├── pi_audio_classifier.py             (thu âm INMP441 → FFT → phân loại)
    ├── pi_camera_classifier.py            (AI/OpenCV: phân loại LOẠI vật từ ảnh — KHÔNG dùng để detect)
    ├── pi_classifier_fusion.py            (kết hợp audio + camera → quyết định cuối)
    ├── pi_communication.py                (UART JSON với ESP32)
    ├── pi_gui_display.py                  (Tkinter fullscreen HDMI)
    └── requirements.txt                   (Python deps)
```

---

## Build & Flash

### ESP32 (PlatformIO)
```bash
cd WasteDetector_ESP32
pio run --target upload
pio device monitor --baud 115200
```

### Raspberry Pi — Setup lần đầu
```bash
pip install -r "Raspberry PI/requirements.txt"

# Bật I2S cho INMP441 — thêm vào /boot/config.txt:
#   dtparam=i2s=on
#   dtoverlay=googlevoicehat-soundcard

# Enable UART GPIO cho ESP32 — thêm vào /boot/config.txt:
#   enable_uart=1
# Disable serial console: sudo raspi-config → Interface → Serial → No console, Yes hardware

# Chạy hệ thống
cd "Raspberry PI"
python3 main_controller.py

# Autostart khi boot — thêm vào /etc/rc.local:
# cd /home/pi/WasteDetector/Raspberry\ PI && python3 main_controller.py &
```

---

## Vấn đề đã biết / TODO

### Chưa implement
- `task_realtime.cpp` — đã có code(có thể chưa đúng)
- `task_comms.cpp` — đã có code(có thể chưa đúng)
- `pi_camera_classifier.py` — chưa có code phân loại AI
- `pi_classifier_fusion.py` — chưa có code tổng hợp

### Calibration cần thực tế
- Ngưỡng TCRT5000 (`IR_THRESHOLD`) — cần đo với tấm phản quang thực tế
- Tốc độ motor (`MOTOR_SPEED`) và thời gian phanh — cần điều chỉnh theo tải
- Góc lệch θ_lag của tấm phản quang — cần đo bằng cách chạy thử
- Tần số FFT cho từng vật liệu — cần chạy `calibrate()` trên vật liệu thực

---

## Thư viện

### PlatformIO (ESP32)
- `bblanchon/ArduinoJson` — parse/serialize JSON protocol
- `madhephaestus/ESP32Servo` — PWM servo trên ESP32
- FreeRTOS — tích hợp sẵn trong Arduino-ESP32

### Python (Raspberry Pi)
- `opencv-python` — camera và image processing
- `numpy`, `scipy` — FFT và signal processing
- `sounddevice` — thu âm INMP441
- `pyserial` — UART serial với ESP32
