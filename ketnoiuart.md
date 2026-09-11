# Hướng Dẫn Kết Nối UART Giữa ESP32 và Raspberry Pi 4

Tài liệu này hướng dẫn chi tiết cách kết nối phần cứng, cấu hình hệ điều hành và kiểm tra giao tiếp nối tiếp hai chiều (UART Serial) qua giao thức JSON giữa **ESP32 Dev Module** và **Raspberry Pi 4** trong hệ thống **WasteDetector**.

---

## 1. Sơ Đồ Đấu Nối Phần Cứng (Wiring Diagram)

### 1.1. Bảng phân công chân kết nối

| Thiết bị | Tên chân | Vị trí Pin vật lý | Mức điện áp | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **ESP32** | `GPIO 16` (RX2) | Chân GPIO 16 | 3.3V Logic | Nhận dữ liệu từ Pi |
| **Raspberry Pi 4** | `GPIO 14` (TXD) | **Pin 8** | 3.3V Logic | Truyền dữ liệu sang ESP32 |
| **ESP32** | `GPIO 17` (TX2) | Chân GPIO 17 | 3.3V Logic | Truyền dữ liệu sang Pi |
| **Raspberry Pi 4** | `GPIO 15` (RXD) | **Pin 10** | 3.3V Logic | Nhận dữ liệu từ ESP32 |
| **ESP32** | `GND` | Chân GND | 0V | **Bắt buộc chung Mass** |
| **Raspberry Pi 4** | `GND` | **Pin 6** (hoặc 9, 14, 20) | 0V | **Bắt buộc chung Mass** |

> ⚠️ **LƯU Ý QUAN TRỌNG:**
> 1. Cả ESP32 và Raspberry Pi 4 đều hoạt động ở chuẩn **logic 3.3V**, do đó đấu chéo dây trực tiếp `TX -> RX` và `RX -> TX` mà **KHÔNG CẦN mạch chuyển mức (Level Shifter)**.
> 2. **Chân GND của hai thiết bị bắt buộc phải nối với nhau** để có cùng điện thế tham chiếu. Nếu không chung GND, tín hiệu Serial sẽ bị lỗi hoặc không thể đọc được.

---

### 1.2. Sơ đồ đấu dây trực quan

```
         ESP32 Dev Module                            Raspberry Pi 4 (Header 40 Pin)
      ┌────────────────────┐                          ┌─────────────────────────────┐
      │                    │                          │   (Pin 2)  5V    5V (Pin 4) │
      │                    │                          │   (Pin 6)  GND   ...        │
      │        GND ────────┼──────────────────────────┼── (Pin 6)  GND              │
      │                    │                          │   (Pin 8)  TXD (GPIO 14) ───┼──┐
      │  GPIO 16 (RX2) ────┼──────────────────────────┼─────────────────────────────┘  │
      │         ▲          │                                                           │
      │         └──────────┼───────────────────────────────────────────────────────────┘
      │                    │
      │  GPIO 17 (TX2) ────┼──────────────────────────┐
      │                    │                          │
      │                    │                          ▼
      │                    │                 ┌─────────────────────────────┐
      │                    │                 │  (Pin 10) RXD (GPIO 15)     │
      └────────────────────┘                 └─────────────────────────────┘
```

---

## 2. Cấu Hình Phần Mềm Trên Raspberry Pi

Mặc định trên Raspberry Pi OS, cổng UART phần cứng được hệ điều hành chiếm dụng để xuất thông tin khởi động Linux (Serial Console). Cần giải phóng cổng này cho ứng dụng:

### Bước 2.1: Tắt Serial Console & Kích hoạt UART phần cứng

Chạy công cụ cấu hình hệ thống:
```bash
sudo raspi-config
```

1. Chọn mục **`Interface Options`** (hoặc `Interfacing Options`).
2. Chọn mục **`Serial Port`**.
3. Khi được hỏi: *"Would you like a login shell to be accessible over serial?"*  
   $\rightarrow$ Chọn **`<No>`**.
4. Khi được hỏi: *"Would you like the serial port hardware to be enabled?"*  
   $\rightarrow$ Chọn **`<Yes>`**.
5. Chọn **`<Finish>`**.

### Bước 2.2: Kiểm tra cấu hình boot

Mở file cấu hình boot:
* Trên Raspberry Pi OS cũ (Bullseye trở về trước): `/boot/config.txt`
* Trên Raspberry Pi OS mới (Bookworm trở lên): `/boot/firmware/config.txt`

```bash
sudo nano /boot/firmware/config.txt
# hoặc sudo nano /boot/config.txt
```

Đảm bảo các thông số sau đã có trong file:
```ini
enable_uart=1
dtoverlay=disable-bt
```
*(Tùy chọn `dtoverlay=disable-bt` giúp gán UART chính PL011 chất lượng cao `/dev/ttyAMA0` cho GPIO 14/15 thay vì miniUART `/dev/ttyS0`)*.

### Bước 2.3: Phân quyền truy cập cổng Serial cho User

Thêm user hiện tại vào nhóm `dialout` để có quyền đọc/ghi cổng serial mà không cần quyền `sudo`:
```bash
sudo usermod -aG dialout $USER
```

### Bước 2.4: Khởi động lại Raspberry Pi

```bash
sudo reboot
```

Sau khi Pi khởi động lại, kiểm tra cổng serial đã sẵn sàng:
```bash
ls -l /dev/serial0 /dev/ttyS0
```
Thường đường dẫn mặc định giao tiếp sẽ là `/dev/serial0` (hoặc `/dev/ttyS0`).

---

## 3. Cấu Hình Phần Mềm Trên ESP32

Trên ESP32, cổng phần cứng **UART2** (`Serial2`) được cấu hình độc lập với cổng nạp Serial0 qua USB.

### Trong mã nguồn ESP32 (`include/config.h` & `src/main.cpp`):

```cpp
// include/config.h
#define UART_PI         Serial2
#define PIN_UART_RX     16
#define PIN_UART_TX     17
#define UART_BAUD       115200

// src/main.cpp
void setup() {
    // Khởi tạo UART2 nối với Raspberry Pi
    UART_PI.begin(UART_BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
    
    // Cổng Serial USB dùng để in log gỡ lỗi ra máy tính
    Serial.begin(115200); 
    Serial.println("[ESP32] System Booted & UART2 Initialized.");
}
```

---

## 4. Định Dạng Giao Thức Truyền Nhận (JSON Protocol)

* **Baudrate:** `115200`
* **Data bits:** `8`, **Parity:** `None`, **Stop bits:** `1` (`8N1`)
* **Ký tự kết thúc mỗi thông điệp:** Bắt buộc có ký tự xuống dòng `\n` (newline).

### 4.1. Lệnh từ Raspberry Pi gửi sang ESP32 (Command)

```json
{"cmd": "PING"}
{"cmd": "LIGHT", "state": "ON"}
{"cmd": "LIGHT", "state": "OFF"}
{"cmd": "KNOCK", "count": 3}
{"cmd": "ROTATE", "target": 1}
{"cmd": "DISCHARGE"}
```
*Ghi chú `target`: `1`: Nhựa, `2`: Thủy tinh, `3`: Giấy/Carton, `4`: Kim loại.*

### 4.2. Phản hồi và sự kiện từ ESP32 gửi lên Raspberry Pi (Event)

```json
{"event": "ALIVE"}
{"event": "OBJECT_DETECTED", "distance": 12}
{"event": "KNOCK_DONE", "seq": 1}
{"event": "ROTATE_DONE", "position": 1}
{"event": "DISCHARGE_DONE"}
{"event": "ERROR", "code": "MOTOR_TIMEOUT"}
{"event": "ERROR", "code": "INVALID_CMD"}
```

---

## 5. Kiểm Tra Hoạt Động (Testing & Verification)

### Cách 1: Chạy kịch bản Smoke Test tự động có sẵn trên Pi

Hệ thống đã viết sẵn file kiểm tra độc lập `pi_communication.py`. Trên Raspberry Pi, mở terminal và chạy:

```bash
cd "/path/to/WasteDetector/Raspberry PI"
python3 pi_communication.py
```

**Tiến trình chạy mẫu:**
1. Pi kết nối đến `/dev/ttyS0` hoặc `/dev/serial0` ở tốc độ 115200.
2. Pi gửi `{"cmd": "PING"}` $\rightarrow$ Nhận phản hồi `{"event": "ALIVE"}` từ ESP32.
3. Pi gửi lệnh bật/tắt đèn `LIGHT ON` / `LIGHT OFF` $\rightarrow$ Relay trên ESP32 đóng/ngắt có tiếng tạch.
4. Pi lắng nghe phản hồi trong 5 giây. Nếu bạn đưa tay lại gần cảm biến HC-SR04, terminal sẽ in ra sự kiện `OBJECT_DETECTED`.

---

### Cách 2: Kiểm tra thủ công bằng Terminal Serial (Minicom)

Cài đặt minicom trên Pi để gõ lệnh trực tiếp:
```bash
sudo apt update
sudo apt install minicom -y
```

Mở cổng kết nối:
```bash
minicom -b 115200 -o -D /dev/serial0
```
* Gõ: `{"cmd": "PING"}` rồi nhấn Enter.
* Nếu kết nối tốt, ESP32 sẽ lập tức trả về chuỗi `{"event":"ALIVE"}`.
* Nhấn `Ctrl + A` rồi nhấn `X` để thoát khỏi minicom.

---

## 6. Xử Lý Các Sự Cố Thường Gặp (Troubleshooting)

| Hiện tượng | Nguyên nhân có thể | Cách khắc phục |
| :--- | :--- | :--- |
| **Báo lỗi `Permission denied: '/dev/ttyS0'`** | User chưa có quyền truy cập cổng nối tiếp | Chạy lệnh `sudo usermod -aG dialout $USER` rồi đăng xuất/đăng nhập lại hoặc khởi động lại Pi. |
| **Không nhận được phản hồi (`Ping timeout`)** | 1. Cắm lộn chéo dây TX/RX<br>2. Chưa chung dây GND<br>3. Chưa nạp đúng code ESP32 | 1. Đổi vị trí 2 dây RX2 và TX2 trên ESP32.<br>2. Kiểm tra dây GND giữa Pi và ESP32.<br>3. Mở Serial Monitor của ESP32 qua USB xem firmware có đang chạy bình thường không. |
| **ESP32 nhận ký tự lạ, rác dữ liệu** | 1. Sai Baudrate<br>2. Chưa tắt Serial Console của Linux | 1. Đảm bảo cả Pi và ESP32 đều đặt tốc độ `115200`.<br>2. Vào lại `sudo raspi-config` kiểm tra tắt login shell over serial. |
| **ESP32 tự khởi động lại (Brownout Reset)** | Nguồn 5V/3.3V cấp cho ESP32 hoặc Pi bị sụt áp khi động cơ chạy | Tách nguồn riêng cho động cơ, dùng tụ lọc nguồn và nối chung Mass chuẩn. |
