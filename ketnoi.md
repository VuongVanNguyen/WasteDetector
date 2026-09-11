# WasteDetector — Sơ Đồ Kết Nối Linh Kiện ESP32

Tài liệu này tổng hợp toàn bộ sơ đồ kết nối chân (Pin Mapping), điện áp hoạt động và lưu ý kỹ thuật cho **ESP32 Dev Module** trong hệ thống **WasteDetector** (không bao gồm các linh kiện nối với Raspberry Pi).

---

## 1. Tổng Quan Sơ Đồ Chân ESP32 (Pinout Overview)

| Linh kiện | Chức năng | Chân ESP32 (GPIO) | Điện áp / Tín hiệu |
|-----------|-----------|-------------------|-------------------|
| **Driver L298N Mini** | Điều khiển Động cơ GA25-370 (IN1) | `GPIO 25` | Output Digital |
| | Điều khiển Động cơ GA25-370 (IN2) | `GPIO 26` | Output Digital |
| | Băm xung tốc độ motor (ENA) | `GPIO 27` | Output PWM (LEDC Ch4, 5kHz) |
| **Servo SG90** | Gõ vật thể tạo âm thanh | `GPIO 18` | Output PWM (LEDC Ch0, 50Hz) |
| **Servo MG90S** | Cửa trượt đáy ống | `GPIO 19` | Output PWM (LEDC Ch1, 50Hz) |
| **HC-SR04** | Phát xung siêu âm (TRIG) | `GPIO 5` | Output Digital (5V) |
| | Nhận phản hồi siêu âm (ECHO) | `GPIO 4` | Input Digital (**Qua phân áp 3.3V**) |
| **4× TCRT5000** | Cảm biến vị trí Ngăn Nhựa (#1) | `GPIO 34` | Input Analog/Digital (Input Only) |
| | Cảm biến vị trí Ngăn Thủy tinh (#2) | `GPIO 35` | Input Analog/Digital (Input Only) |
| | Cảm biến vị trí Ngăn Giấy (#3) | `GPIO 32` | Input Analog/Digital |
| | Cảm biến vị trí Ngăn Kim loại (#4) | `GPIO 33` | Input Analog/Digital |
| **Relay Module** | Bật/Tắt đèn chiếu sáng | `GPIO 23` | Output Digital |
| **Cổng UART2** | Tín hiệu nhận UART (RX2) | `GPIO 16` | Input Serial (3.3V Logic) |
| | Tín hiệu gửi UART (TX2) | `GPIO 17` | Output Serial (3.3V Logic) |

---

## 2. Chi Tiết Kết Nối Từng Khối Linh Kiện

### 2.1. ESP32 ↔ Driver Motor L298N Mini (Động cơ GA25-370 12V)
Điều khiển động cơ xoay ống PVC 4 ngăn.

| Chân ESP32 | Chân L298N Mini | Chức năng | Ghi chú |
|------------|-----------------|-----------|---------|
| `GPIO 25` | IN1 | Tín hiệu chiều quay A | HIGH/LOW |
| `GPIO 26` | IN2 | Tín hiệu chiều quay B | HIGH/LOW |
| `GPIO 27` | ENA | Điều khiển tốc độ (PWM) | PWM 8-bit (0 - 255), LEDC Channel 4 |
| `GND` | GND | Mass chung | Nối chung GND ESP32 và nguồn 12V |
| *(Không nối)* | VMS / +12V | Nguồn động cơ | **Nối với cực + Nguồn 12V ngoài** |
| *(Không nối)* | MOTOR A / B | Đầu ra động cơ DC | Nối vào 2 chân của động cơ GA25-370 |

---

### 2.2. ESP32 ↔ Servo SG90 (Cơ cấu gõ vật thể)
Gõ vào vật thể trong ống để tạo âm thanh phục vụ phân tích.

| Chân ESP32 | Chân Servo SG90 | Mầu dây | Chức năng / Ghi chú |
|------------|-----------------|---------|----------------------|
| `GPIO 18` | Signal | Cam / Vàng | PWM 50Hz (LEDC Channel 0) |
| *(Không nối)* | VCC (+5V) | Đỏ | **Nối Nguồn 5V ngoài** (Không lấy trực tiếp từ 3.3V ESP32) |
| `GND` | GND | Nâu / Đen | Mass chung |

---

### 2.3. ESP32 ↔ Servo MG90S (Cửa trượt xả rác đáy ống)
Mở/đóng cửa đáy để thả rác vào ngăn tương ứng.

| Chân ESP32 | Chân Servo MG90S | Mầu dây | Chức năng / Ghi chú |
|------------|------------------|---------|----------------------|
| `GPIO 19` | Signal | Cam / Vàng | PWM 50Hz (LEDC Channel 1) |
| *(Không nối)* | VCC (+5V) | Đỏ | **Nối Nguồn 5V ngoài** |
| `GND` | GND | Nâu / Đen | Mass chung |

---

### 2.4. ESP32 ↔ 4× Cảm biến hồng ngoại TCRT5000 (Định vị góc xoay)
Xác định chính xác vị trí ống xoay dừng lại tại 4 ngăn rác qua phản xạ hồng ngoại.

| Chân ESP32 | Cảm biến TCRT5000 | Vị trí ngăn rác | Ghi chú |
|------------|-------------------|-----------------|---------|
| `GPIO 34` | OUT (Digital/Analog) | Ngăn #1: Nhựa (Plastic) | Chân Input-only trên ESP32 |
| `GPIO 35` | OUT (Digital/Analog) | Ngăn #2: Thủy tinh (Glass) | Chân Input-only trên ESP32 |
| `GPIO 32` | OUT (Digital/Analog) | Ngăn #3: Giấy (Paper) | GPIO ADC/Touch |
| `GPIO 33` | OUT (Digital/Analog) | Ngăn #4: Kim loại (Metal) | GPIO ADC/Touch |
| `3.3V` / `5V` | VCC | Cấp nguồn cảm biến | Nguồn 3.3V hoặc 5V |
| `GND` | GND | Mass chung | Nối mass chung |

> 💡 **Lưu ý cơ khí:** Tấm phản quang được dán lệch một góc $\theta_{lag}$ so với vị trí dừng thực tế để bù quán tính của động cơ khi ngắt điện.

---

### 2.5. ESP32 ↔ Cảm biến khoảng cách siêu âm HC-SR04
Phát hiện khi có rác rơi vào ống phân loại.

| Chân ESP32 | Chân HC-SR04 | Chức năng | Ghi chú điện áp |
|------------|--------------|-----------|------------------|
| `GPIO 5` | TRIG | Phát xung kích siêu âm | Tín hiệu Output 3.3V/5V |
| `GPIO 4` | ECHO | Nhận xung phản hồi | **CẦN MẠCH PHÂN ÁP (Voltage Divider)** |
| *(Không nối)* | VCC (+5V) | Nguồn cảm biến | **Nối Nguồn 5V** |
| `GND` | GND | Mass chung | Nối mass chung |

#### ⚠️ Mạch Phân Áp Bảo Vệ Chân ECHO (`GPIO 4`):
Tín hiệu chân ECHO của HC-SR04 ra mức **5V**, trong khi các chân GPIO ESP32 chỉ chịu được tối đa **3.3V**. Cần dùng 2 điện trở để hạ áp:

```
Chân ECHO (HC-SR04 5V) ─── [ R1 = 10kΩ ] ───┬───> Chân GPIO 4 (ESP32 3.3V)
                                             │
                                      [ R2 = 20kΩ ]
                                             │
                                            GND
```
$$\text{V}_{\text{out}} = 5\text{V} \times \frac{20\text{k}\Omega}{10\text{k}\Omega + 20\text{k}\Omega} = 3.33\text{V}$$

---

### 2.6. ESP32 ↔ Relay Module SONGLE (Đèn chiếu sáng)
Bật/tắt đèn khoang chụp ảnh khi bắt đầu quá trình phân loại.

| Chân ESP32 | Chân Relay Module | Chức năng | Ghi chú |
|------------|-------------------|-----------|---------|
| `GPIO 23` | IN / SIG | Tín hiệu kích Relay | High/Low Trigger |
| `3.3V` / `5V` | VCC | Nguồn cuộn dây Relay | SRD-03VDC (3.3V) hoặc SRD-05VDC (5V) |
| `GND` | GND | Mass chung | Nối mass chung |
| *(Bên tải)* | COM / NO | Nối nối tiếp với Đèn | Điều khiển nguồn cấp cho đèn |

---

### 2.7. Cổng UART2 Trên ESP32 (Giao tiếp Serial)
Cổng nối tiếp cứng UART2 dùng để truyền/nhận lệnh dạng chuỗi JSON ở tốc độ **115200 baud**.

| Chân ESP32 | Tên hằng số trong code | Chức năng | Ghi chú |
|------------|------------------------|-----------|---------|
| `GPIO 16` | `PIN_UART_RX` (RX2) | Nhận dữ liệu Serial | Mức logic 3.3V |
| `GPIO 17` | `PIN_UART_TX` (TX2) | Gửi dữ liệu Serial | Mức logic 3.3V |
| `GND` | GND | Mass chung truyền thông | **Bắt buộc nối chung Mass** với thiết bị giao tiếp |

---

## 3. Sơ Đồ Nguyên Lý Cấp Nguồn (Power Distribution & Common GND)

Để hệ thống vận hành ổn định, tránh tình trạng ESP32 bị sụt áp sụt nguồn (Reset/Brownout) do động cơ hoặc Servo rút dòng:

```
[ Nguồn Độc Lập 12V DC ] ────────┬───────────────────────────> L298N Mini (VMS)
                                 │
                                 └─> [ Mạch Hạ Áp LM2596 / Buck ] ──┬──> Nguồn 5V Servo SG90 / MG90S
                                                                    ├──> Nguồn 5V HC-SR04
                                                                    └──> Nguồn 5V ESP32 (Chân Vin/5V)

[ ESP32 Chân 3V3 ] ───────────────────────────────────────────────> Nguồn 3.3V TCRT5000 / Relay

===================================================================================
TẤT CẢ CHÂN GND (Nguồn 12V, Buck 5V, ESP32, L298N, Servos, Cảm biến) BẮT BUỘC NỐI CHUNG MASS (COMMON GND)
===================================================================================
```

---

## 4. Lưu Ý Kỹ Thuật Khi Lắp Ráp & Calibration

1. **Chân Input-Only trên ESP32 (`GPIO 34`, `GPIO 35`):**
   - Các chân này không có điện trở Pull-up / Pull-down nội và không hỗ trợ đầu ra (Output). Rất thích hợp làm chân đọc tín hiệu Analog/Digital từ TCRT5000.
2. **Tránh Nhiễu Động Cơ DC (GA25-370):**
   - Hàn thêm 1 tụ gốm `104` ($0.1\mu\text{F}$) song song giữa 2 cực của động cơ GA25-370 để triệt tiêu nhiễu cao tần phát ra từ chổi quét.
3. **Nguồn Dòng Cho Servo:**
   - SG90 và MG90S có dòng tức thời khi khởi động (Stall Current) lên tới $500\text{mA} - 1\text{A}$. Không bao giờ cấp nguồn cho Servo trực tiếp từ chân `3V3` của ESP32.
