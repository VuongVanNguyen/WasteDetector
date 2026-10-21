# WasteDetector — Máy Phân Loại Rác Thông Minh

## Tổng quan kiến trúc (2 lớp)

Hệ thống tự động phân loại rác thành 4 loại: Nhựa, Thủy tinh, Giấy, Kim loại.

**Lớp 1 — SBC: Raspberry Pi 4**
- Xử lý AI/Vision (OpenCV + TFLite) — **chỉ phân loại LOẠI vật**, không phát hiện sự hiện diện
- Phân tích FFT âm thanh (NumPy/SciPy)
- Ra quyết định phân loại, điều phối toàn hệ thống
- Giao tiếp xuống ESP32: **UART Serial2 — JSON — 115200 baud**
- Cảm biến âm thanh: Micro M-306 qua **USB**

**Lớp 2 — MCU: ESP32 Dev Module** (thay thế 2× Arduino Nano cũ)
- Điều khiển toàn bộ cơ cấu cơ học và cảm biến real-time
- FreeRTOS Dual-core:
  - **Core 1** (Priority 2): Servo SG90/MG90S, Motor DRV8871, Interrupt TCRT5000
  - **Core 0** (Priority 1): UART ↔ Pi 4, HC-SR04 polling

---

## Danh mục linh kiện (BOM)

| Linh kiện | Model | Vai trò |
|-----------|-------|---------|
| SBC | Raspberry Pi 4 | Xử lý AI, FFT, điều phối |
| MCU | ESP32 Dev Module | Điều khiển cơ cấu, cảm biến |
| Mic âm thanh | M-306 (USB) | Thu âm USB → FFT phân tích vật liệu |
| Camera | Pi Camera | Chụp ảnh → AI phân loại LOẠI vật (không dùng để detect) |
| LED chiếu sáng | LED 1W trắng đế nhôm (star), ~300mA | Chỉ sáng ~0.3s lúc camera chụp — Pi điều khiển |
| MOSFET LED | **IRLZ44N** (logic-level, TO-220) | Đóng/cắt LED từ Pi GPIO 17 |
| Cảm biến khoảng cách | HC-SR04 | **Duy nhất** phát hiện vật thể rơi vào ống |
| Cảm biến IR | 4× TCRT5000 | Định vị góc xoay ống (4 vị trí) |
| Servo gõ | SG90 | Gõ vật thể tạo âm thanh |
| Servo cửa | MG90S | Mở/đóng cửa trượt đáy ống |
| Motor xoay ống | GA25-370 (12V DC) | Xoay ống trụ PVC đến đúng ngăn |
| Driver motor | **DRV8871** | H-Bridge điều khiển GA25-370 (giới hạn dòng 3.6A) |
| Nguồn chính | Adapter 12V / 4A (48W) | Nguồn duy nhất — tối thiểu 3A |
| Buck #1 | **XL4015** (12V→5V, 5A, có tản nhiệt) | Cấp riêng cho Raspberry Pi 4 |
| Buck #2 | **MP1584EN** (12V→5V, 3A) | Cấp cho ESP32 + servo + cảm biến |

> Buck #2 có thể thay bằng **XL4015** — dư dòng là vô hại. Nhưng nếu module
> XL4015 là bản **CC/CV có 2 biến trở**, phải vặn biến trở **giới hạn dòng hết
> cỡ** (đa vòng, ~15-20 vòng) TRƯỚC khi chỉnh điện áp. Để giới hạn dòng thấp
> thì khi servo giật buck sẽ tự hạ áp — triệu chứng giống hệt sụt áp nguồn.

---

## Kiến trúc nguồn

Toàn hệ thống chạy từ **một adapter 12V/4A duy nhất**, rẽ thành 3 nhánh song song.

```
                    ┌──→ DRV8871 POWER +/− ──→ Motor GA25-370 (12V)
                    │    (không cần nguồn logic riêng)
Adapter 12V / 4A ───┤
   (1 ổ cắm)        ├──→ Buck #1 XL4015  (5V/5A) ─┬──→ Raspberry Pi 4
                    │                              └──→ LED 1W (qua MOSFET)
                    │
                    └──→ Buck #2 MP1584EN (5V/3A) ─┬──→ ESP32 VIN
                                                    ├──→ SG90 + MG90S (+ tụ 1000µF)
                                                    └──→ TCRT5000, HC-SR04

GND: tất cả về MỘT điểm tại cực âm adapter (đấu hình sao)
```

### Ngân sách dòng

| Nhánh | Dòng ở 5V | Quy về 12V (η≈88%) |
|-------|-----------|--------------------|
| Pi 4 (camera + AI) | ~1.5A | ~0.7A |
| LED 1W (chỉ ~0.3s lúc chụp) | ~0.3A | ~0.15A |
| ESP32 + cảm biến (nền) | ~0.3A | ~0.15A |
| Servo SG90/MG90S (khi gõ/xả) | tới 2A đỉnh | ~0.95A |
| Motor GA25-370 (khi xoay) | — | 0.5A chạy, 2A lúc kẹt |
| **Tổng thường trực** | | **~1.7A** |
| **Tổng đỉnh** | | **~3A** |

> Servo và motor **không bao giờ chạy đồng thời** — workflow tuần tự
> KNOCK → ROTATE → DISCHARGE. Vì vậy chỉ cộng **một** trong hai vào đỉnh,
> không cộng cả hai. Đây là lý do 4A đủ thay vì 5-6A.
>
> LED cũng không cộng vào đỉnh: nó chỉ sáng lúc chụp, tức SAU khi gõ xong và
> TRƯỚC lệnh ROTATE — lúc đó cả servo lẫn motor đều đứng yên.

### Quy tắc bắt buộc

1. **Hai buck riêng, không dùng chung.** Pi 4 báo sụt áp dưới 4.63V và sụt áp lặp lại làm **hỏng thẻ SD**. Tách buck để xung dòng từ servo/motor không chạm tới Pi.
2. **Chỉnh cả hai buck về 5.2V TRƯỚC khi nối tải.** Module xuất xưởng cho ra 8-12V — nối thẳng vào ESP32/Pi là chết board. Cấp 12V vào, đo VOM ở ngõ ra, vặn biến trở, rồi mới đấu. **Đây là bước nguy hiểm nhất toàn hệ thống** — quên nó là đưa 12V vào ESP32/Pi/cổng USB laptop.
   > **Vì sao 5.2V:** cổng USB host được phép dao động 4.75-5.25V, laptop thực tế
   > cho ra 5.00-5.15V. Đặt 5.1V là quá sát, hai nguồn sẽ chia nhau cấp dòng.
   > 5.2V thắng chắc chắn mà vẫn dư biên (ESP32 chịu tới 5.5V, servo tới 6V).
   >
   > **Kiểm tra board có diode chặn không:** rút nguồn ngoài, chỉ cắm USB, đo chân
   > 5V↔GND. Đọc ~4.7V = có diode Schottky, dòng ngược bị chặn hoàn toàn, không
   > cần lo. Đọc ~5.0V = nối thẳng, dùng 5.2V hoặc cáp USB data-only.
3. **DRV8871 không có nguồn logic riêng.** Chỉ cần 12V vào terminal `POWER` và chân `GND` của board nối chung mass với ESP32. `IN1`/`IN2` nhận thẳng logic 3.3V, không cần level shifter, không có jumper nào phải cắm/rút.
4. **Sụt áp trên driver chỉ ~0.2V** (MOSFET), nên motor nhận gần đủ 12V. L298N cũ là cầu lưỡng cực, sụt ~2V — motor chỉ nhận 10V. Sau khi đổi driver, `MOTOR_SPEED` cũ sẽ cho tốc độ CAO hơn trước ở cùng giá trị duty; phải calibrate lại.
5. **Mass hình sao.** Dây mass motor và mass logic không đi chung đoạn dây, chỉ gặp nhau tại cực âm adapter. Dòng motor qua mass chung sẽ dội nhiễu vào TCRT5000 → định vị ngăn sai.
6. **Tụ 1000µF/16V** sát chân servo + **0.1µF gốm** song song. **Tụ 104 gốm hàn thẳng lên 2 chân motor** GA25-370 để dập nhiễu chổi than.
7. **Không cho đường 5V/GND công suất chạy qua breadboard.** Lò xo tiếp xúc chịu dòng kém → lỗi "lúc chạy lúc không". Dây tín hiệu thì cắm breadboard thoải mái.
8. **Pi 4 nên cấp qua cổng USB-C** (buck → jack USB-A cái → cáp USB-C) để giữ mạch bảo vệ của Pi. Đấu thẳng vào GPIO 2/6 cũng chạy nhưng bỏ qua bảo vệ.
9. **Cầu chì 5A** trên đường 12V đầu vào.
10. **Tụ 2200µF/25V** trên đường 12V gần điểm chia nhánh — bắt buộc nếu dùng adapter 3A, khuyến khích với 4A.

### Chọn dạng nguồn

Mọi adapter 12V bán hiện nay đều là **switching**, nhẹ 150-250g — loại "cục pin" nặng là biến áp tuyến tính đời cũ, không còn dùng. Ba lựa chọn:

| Dạng | Kích thước / khối lượng | Ghi chú |
|------|------------------------|---------|
| Adapter 12V/4A (kiểu nguồn camera, LED) | ~11×5×3cm, ~200g | Rẻ nhất, cắm ngoài |
| Nguồn khung nhôm (Meanwell LRS-50-12) | ~10×8×3cm, ~200g | **Gắn trong thân máy** — không lủng lẳng trên dây |
| Sạc GaN USB-C PD 65W + mạch trigger 12V | ~6×3×3cm, ~110g | Nhẹ nhất; xem cảnh báo dưới |

> ⚠️ **PD trigger:** chuẩn USB-C PD giới hạn mức 12V ở **3A (36W)** trên hầu hết
> củ sạc, kể cả củ 65W. Đủ cho hệ này nhưng không có biên — bắt buộc kèm tụ
> 2200µF. Muốn dư biên thì trigger 20V rồi hạ về 12V bằng một buck nữa,
> đổi lại thêm một tầng chuyển đổi.

### Khi test không có Pi

Cáp USB mang **dữ liệu** và **điện** trên hai đường riêng — tách được. Cấp 5.2V từ buck vào VIN, đồng thời cắm USB laptop để nạp code và xem serial monitor; nguồn ngoài cao hơn 5.00V của cổng USB nên USB không đóng góp dòng.

> ⚠️ Cổng USB laptop chỉ cho 500mA (USB 2.0) / 900mA (USB 3.0), trong khi SG90+MG90S lúc giật rút 1.2-1.5A. Nuôi cơ cấu bằng USB laptop sẽ làm polyfuse của cổng ngắt bảo vệ → servo tịt từng lúc. **Không calibrate bất kỳ thông số nào** (`IR_THRESHOLD`, `MOTOR_SPEED`, θ_lag, ngưỡng FFT) khi còn chạy bằng nguồn USB — số đo sẽ sai và phải làm lại.

Để mô phỏng Pi mà không cần Pi thật: module **USB-TTL CP2102/CH340** nối vào UART2 (TX→GPIO16, RX→GPIO17, chung GND), gửi JSON thật từ terminal. Cách này test đúng firmware production, không cấp điện cho ESP32.

---

## Kết nối chân (Pin Mapping)

### ESP32 → DRV8871 (Motor GA25-370)
| ESP32 GPIO | DRV8871 Pin | Chức năng |
|------------|-------------|-----------|
| GPIO 25 | `IN1` | PWM chiều A |
| GPIO 26 | `IN2` | PWM chiều B |
| GND | `GND` (chân header) | Chung mass — **bắt buộc** |
| 12V ngoài | `POWER +` | Nguồn motor |
| GND nguồn | `POWER −` | Về điểm sao tại cực âm adapter |
| — | `MOTOR 1` / `MOTOR 2` | Hai dây motor GA25-370 |

> **GPIO 27 nay BỎ TRỐNG.** DRV8871 không có chân enable — PWM đánh thẳng vào
> hai chân chiều, nên mỗi chân cần **một kênh LEDC riêng**
> (`MOTOR_LEDC_CH_IN1` = 4, `MOTOR_LEDC_CH_IN2` = 5).
>
> | IN1 | IN2 | Trạng thái |
> |-----|-----|-----------|
> | PWM | 0 | quay chiều A |
> | 0 | PWM | quay chiều B |
> | max | max | **PHANH** chủ động (nối tắt hai đầu motor qua low-side) |
> | 0 | 0 | **THẢ TRÔI** (Hi-Z) |
>
> ⚠️ Chân đã gắn LEDC thì `digitalWrite` **không còn tác dụng** — LEDC chiếm
> quyền điều khiển chân qua GPIO matrix. Mọi thao tác chiều/phanh/thả trôi phải
> dùng `ledcWrite`. Hệ quả: `test_motor_ir.cpp` **không phanh trong ISR** được
> nữa (`ledcWrite` không an toàn trong ISR); ISR chỉ đặt cờ, task phanh ở nhịp
> poll kế tiếp (≤ 2ms).

> **Vì sao đổi driver:** L298N Mini cũ chết **cả hai kênh**. Đo lúc chạy lệnh:
> `IN1=3.11V`, `IN2=0.1V`, `ENA=3.11V` (đúng tổ hợp quay), `VMS=12V`, rail 5V
> logic đủ, mass đã chung — mọi điều kiện đầu vào đạt, mà `OUT` chỉ lên 2V kể cả
> khi **tháo hết tải**. Tức transistor công suất còn dẫn nhưng không bão hoà nổi:
> tầng công suất đã bào mòn, không phải đứt.
>
> Board đó **có** đủ 8 diode dập dòng ngược, nên nguyên nhân không phải thiếu
> diode. Nghi vấn chính là **dâng áp trên rail VS**: diode dập chỉ đổi hướng năng
> lượng cảm kháng *lên chính rail nguồn*, không tiêu tán nó. Đường 12V chưa có tụ
> bulk 2200µF (quy tắc 10) nên không có chỗ hấp thụ, và adapter switching không
> nhận được dòng ngược → rail tự dâng mỗi lần phanh, đánh vào cả hai kênh dùng
> chung rail đó.
>
> **Bắt buộc lắp trước khi cắm DRV8871:** tụ **2200µF/25V** trên đường 12V (quy
> tắc 10) và tụ **104 gốm hàn thẳng lên hai chân motor** (quy tắc 6). Thiếu chúng
> thì driver mới chịu đúng những xung đã giết con cũ.

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
| 5V | VCC | Nguồn cảm biến |
| GND | GND | Chung mass |
Xám - Tím - Dương - Lá

> ⚠️ **TCRT5000 là module 5V** — hạ xuống 3.3V làm dòng qua LED hồng ngoại tụt
> mạnh, tín hiệu phản xạ yếu đi và cảm biến trở nên chập chờn. Cấp 5V.
>
> DO của LM393 là **open-collector**, mức HIGH hoàn toàn nhờ trở kéo trên module
> lên 5V. Nối thẳng vào GPIO sẽ bị diode ESD của ESP32 ghim xuống còn **~3.7-4V**
> — đo VOM ra con số này là bình thường, không phải chân thả nổi. Nhưng khi đó
> chân đang gánh dòng ngược vào rail 3.3V liên tục, nên nên lắp **voltage divider
> (10kΩ + 20kΩ) trên cả 4 đường DO**, giống chân ECHO của HC-SR04.
>
> LM393 **không có hysteresis**: nếu ống đứng ngay rìa vùng nhận, DO rung liên
> tục. Vặn biến trở trên module cho ngưỡng lệch hẳn khỏi điểm đứng yên.

> Tấm phản quang gắn lệch góc θ_lag so với vị trí thực để bù quán tính cơ học khi motor dừng (không dùng PID).

#### HOME = cảm biến Thủy tinh (mô hình hiện hành)

Điểm đậu **không còn là điểm ảo giữa hai cảm biến**. Ngăn Thủy tinh vừa là nơi
xả rác thủy tinh, vừa là **HOME** — sau mỗi chu kỳ ống luôn quay về đúng cảm
biến đó, và ISR của chính nó phanh ống lại.

```
   Kim loại ─── Giấy ─── THỦY TINH ─── Nhựa     ╳ cấm khép vòng
     +180°      +90°     0° (HOME)     −90°        (Kim loại ↔ Nhựa)
     idx 0      idx 1       idx 2      idx 3
              <──── CW ────   ── CCW ──>
```

Khi đủ 4 IR, **mọi lần quay đều closed-loop** (phanh trên cạnh IR thật). Canh
giờ chỉ xuất hiện khi một IR đã bị đánh dấu chết — xem mục "Bảo vệ cơ cấu".

Rác **Thủy tinh là trường hợp đặc biệt hợp lệ**: ngăn xả chính là HOME, nên bước
`ROTATE` không quay gì cả và bước về HOME sau đó cũng không.

#### Thứ tự lắp VẬT LÝ quanh ống — ràng buộc bắt buộc

Bảng GPIO ở trên là **khai báo thủ công** trong `config.h`, firmware KHÔNG tự dò.
Số GPIO tự nó không mang nghĩa gì — vai được gán bằng `#define`, rồi hai mảng
`IR_PINS[]`/`IR_CODES[]` ghép pin với mã loại rác theo **chỉ số mảng**:

| `config.h` | GPIO | Ngăn | Chỉ số cung | Xoắn dây | Chiều từ HOME |
|---|---|---|---|---|---|
| `PIN_IR_METAL` | 33 | Kim loại | 0 | **+180°** (trần) | CW, 2 cảm biến |
| `PIN_IR_PAPER` | 32 | Giấy | 1 | +90° | CW, 1 cảm biến |
| `PIN_IR_GLASS` | 35 | **Thủy tinh = HOME** | 2 | **0°** | — (đã ở đó) |
| `PIN_IR_PLASTIC` | 34 | Nhựa | 3 | −90° | CCW, 1 cảm biến |

**Cắm chân nào cũng được**, miễn sửa `#define` cho khớp thực tế. Giới hạn:

- Cả 4 chân phải **≥ GPIO32** — ISR trong `motion.cpp` đọc mức chân qua
  `GPIO_IN1_REG` (mảng `STATION_BIT[]`). `static_assert` chặn ngay lúc build.
  Giới hạn này áp cho **mọi** env dùng `motion.cpp`: `esp32dev` (production),
  `test_motor_ir`, `test_full_cycle`. Chỉ `test_motor_simple.cpp` giữ ISR riêng
  bằng `digitalRead` nên không bị ràng buộc.
- Quỹ chân khả dụng: **32, 33, 34, 35, 36, 39**. GPIO 37/38 có trong chip nhưng
  không ra header trên ESP32 DevKit — khai báo sẽ build được mà không có chân để cắm.
- GPIO 36/39 (SENSOR_VP/VN) có erratum sinh xung giả ~80ns khi RTC/SAR-ADC đọc.
  Vô hại ở đây vì bước (1) của ISR đọc lại mức chân sẽ loại xung đó (chỉ làm
  `irRejected` tăng), nhưng nên để dành 36/39 làm phương án dự phòng.

> ⚠️ **Cắm sai mà không sửa `#define` KHÔNG chỉ là in sai tên** — nó phá chống
> xoắn. Kiểm tra trước khi chạy motor: flash `test_motor_simple`, lệnh `m`
> (motor TẮT), xoay ống **bằng tay** tới từng ngăn, xem dòng nào hiện dấu `*`.
> Đứng ở ngăn Nhựa mà thấy `Thuy tinh(GPIO35)=0*` là `#define` sai.

**Thứ tự quanh ống thì KHÔNG tự do.** Mọi số học vị trí chạy trên **chỉ số
STATION**, lấy từ mảng `STATION_POS[]` ở đầu `motion.cpp`:

```c
static constexpr int STATION_POS[4] = { WASTE_METAL, WASTE_PAPER, WASTE_GLASS, WASTE_PLASTIC };

dir       = (idxTarget > idxCur) ? MOTOR_DIR_CCW : MOTOR_DIR_CW;
crossings = abs(idxTarget - idxCur);
```

Hệ quả cơ khí bắt buộc:

1. Bốn ngăn phải nằm đúng dãy **Kim loại → Giấy → Thủy tinh → Nhựa** ở 4 slot cách nhau 90°.
2. Kim loại và Nhựa là **hai đầu mút** của cung → chúng kề nhau về vật lý,
   và khoảng **90° giữa chúng là vùng CẤM**, ống không bao giờ đi qua.
3. **Thủy tinh là HOME** — slot thứ 3, xoắn 0°. Dây cáp phải dress **thẳng hoàn
   toàn** khi ống đứng ở đây.

Hoán vị vật lý khác đi mà không sửa `STATION_POS[]` → `runMove` chọn sai chiều
và ống lao vào vùng cấm. Hệ bắt được chuyện đó: cạnh IR không đúng station kế
tiếp → phanh ngay ở cạnh ĐẦU TIÊN (`sequenceError`), và dừng ở đầu mút bên kia
→ chốt FAULT.

> Muốn đổi thứ tự lắp: sửa **duy nhất** ba mảng `STATION_POS[]`,
> `STATION_TWIST_DEG[]`, `STATION_PIN[]` đầu `motion.cpp`. Chiều quay, số cảm biến phải vượt, và toàn bộ
> kiểm tra bảo vệ đều suy ra từ hai mảng đó — không còn chỗ nào làm số học trên
> mã loại rác nữa.

#### Lắp CW hay CCW đều chạy — chỉ `MOTOR_DIR_INVERTED` phải đúng

Ở tầng logic, HOME→Giấy và HOME→Kim loại **luôn** là `MOTOR_DIR_CW`, HOME→Nhựa
**luôn** là `MOTOR_DIR_CCW`. Nhưng `MOTOR_DIR_CW`/`CCW` chỉ là **tên của hai tổ
hợp cấp điện** — chúng không hứa hẹn gì về chiều kim đồng hồ thật. Chiều vật lý
phụ thuộc cách cắm 2 dây ở terminal `MOTOR 1/2`, chiều hộp số GA25-370, và bạn
nhìn ống từ phía nào.

Nên **lắp theo chiều tay nào cũng chạy**. Chỉ có đúng một bit phải chỉnh:
`MOTOR_DIR_INVERTED` trong `config.h` — nó phải làm cho `MOTOR_DIR_CW` thực sự
đẩy ống theo hướng Thủy tinh→Giấy→Kim loại. Thay cho việc sửa cờ này, có thể đảo
2 dây tại terminal `MOTOR` của DRV8871 — tương đương hoàn toàn.

**Cách dò `MOTOR_DIR_INVERTED` an toàn nhất khi dây đã lắp:**

1. Flash `test_motor_ir`. Ống tự về HOME (Thủy tinh) lúc boot.
2. Bấm `'3'` (sang Giấy) — `dir = CW`, vượt 1 cảm biến.
3. Ống tới **Giấy** → cờ đúng, để nguyên.
   Ống đi về phía **Nhựa** → sai: hệ huỷ lệnh ngay ở cảm biến đầu tiên và in
   `[ERROR] Sai thu tu: ...`. Đặt `MOTOR_DIR_INVERTED = 1` rồi thử lại.

> Chọn `'3'` chứ không phải `'4'`: Giấy kề HOME nên dù cờ sai, ống cũng chỉ lệch
> đúng 1 ngăn (sang Nhựa, xoắn −90°) và bị chặn ngay — không bao giờ chạm vùng
> cấm. `'4'` (Kim loại, 2 bước) mà sai chiều thì cảm biến thứ hai đã nằm ngoài
> cung. An toàn nhất vẫn là dò chiều khi **chưa bắc dây** qua ống.

> ⚠️ **KHÔNG dùng lệnh `'7'`/`'8'` của `test_motor_simple` để dò chiều.**
> `doRawDir` chạy **5 giây ở duty 255 và bỏ qua hoàn toàn IR** — thừa sức quay
> ống vài vòng và **đứt dây**. Hai lệnh đó sinh ra để cầm VOM đo IN1/IN2 lúc
> chẩn đoán driver chết, dùng khi ống chưa bắc dây.

### ESP32 → HC-SR04
| ESP32 GPIO | HC-SR04 | Chức năng |
|------------|---------|-----------|
| GPIO 5 | TRIG | Phát xung |
| GPIO 4 | ECHO | Nhận phản hồi |
| 5V | VCC | Nguồn |
| GND | GND | Chung mass |

> ⚠️ ECHO trả về 5V logic → cần **voltage divider** (10kΩ + 20kΩ) xuống 3.3V trước khi vào GPIO ESP32.

### ESP32 ↔ Raspberry Pi 4 (UART)
| ESP32 | Raspberry Pi 4 | Chức năng |
|-------|----------------|-----------|
| GPIO 16 (RX2) | TX (GPIO 14) | Pi gửi lệnh → ESP32 nhận |
| GPIO 17 (TX2) | RX (GPIO 15) | ESP32 phản hồi → Pi nhận |
| GND | GND | Chung mass bắt buộc |

> Cả 2 đều dùng mức logic 3.3V → kết nối trực tiếp, không cần level shifter.

### Raspberry Pi 4 → LED 1W chiếu sáng (qua MOSFET IRLZ44N)
| Kết nối | Chức năng |
|---------|-----------|
| Pi GPIO 17 (chân 11) → trở **100Ω** → `G` | Tín hiệu bật/tắt (`LED_PIN` trong `pi_config.py`) |
| `G` → trở **10kΩ** → GND | Kéo xuống: LED chắc chắn TẮT khi Pi boot / chương trình chết |
| 5V Buck #1 → trở **5.6Ω 1W** → LED `+` | Hạn dòng ~300mA |
| LED `−` → `D` | |
| `S` → GND | Về điểm sao, chung mass với Pi |

```
5V (Buck #1) ──[5.6Ω 1W]──►|── LED 1W ── D ┐
                                           IRLZ44N
Pi GPIO17 ──[100Ω]──┬────────────────── G ┤
                  [10kΩ]                   S ┘
GND ────────────────┴──────────────────────┴── điểm sao
```

> ⚠️ Phải là **IRLZ44N** (chữ **L** = logic-level, dẫn bão hoà ở 3.3V). IRFZ44N
> và module "IRF520" bán sẵn **không** phải logic-level — ở 3.3V chúng chỉ dẫn
> nửa vời, LED sáng yếu và MOSFET nóng.
>
> **Vì sao LED 1W, không phải LED 5mm:** ống PVC kín nên LED là nguồn sáng duy
> nhất. LED 5mm (~20mA) chỉ ~5-8 lumen và chùm hẹp → ảnh tối, một điểm chói giữa
> vật. LED 1W ~100 lumen, đế nhôm cho góc chiếu rộng. Vì chỉ sáng ~0.3s mỗi chu
> kỳ nên không cần tản nhiệt thêm.
>
> **Lắp đặt:** đặt LED cạnh ống kính, hơi lệch trục, và dán một lớp **giấy can /
> nhựa mờ** trước LED để khuếch tán. Chiếu thẳng trục thì thủy tinh/kim loại
> phản xạ ngược vào ống kính thành vùng cháy trắng.
>
> Trở 5.6Ω tính cho Vf ≈ 3.2V: (5 − 3.2) / 5.6 ≈ 0.3A. LED khác lô có Vf từ 3.0
> đến 3.4V nên dòng thật dao động 0.25-0.35A. Muốn chắc thì đo dòng bằng VOM.
>
> Kiểm tra dây: `python3 pi_camera_classifier.py` — LED nháy 5 lần.

### Raspberry Pi 4 → Micro M-306 (USB)
| Kết nối | Chức năng |
|---------|-----------|
| Cổng USB-A bất kỳ trên Pi 4 | Cắm trực tiếp M-306 — nhận diện tự động như 1 USB sound card (ALSA), không cần GPIO/wiring |

> Không dùng I2S, không cần `dtoverlay` cho card âm thanh. Kiểm tra bằng `arecord -l` để lấy card/device index, cấu hình vào `AUDIO_DEVICE_ID` trong `pi_config.py` nếu không dùng mặc định.

---

## Giao thức truyền thông (JSON over UART 115200 baud)

### Pi → ESP32 (lệnh điều khiển)
```json
{"cmd": "START_ANALYSIS"}
{"cmd": "KNOCK", "count": 3}
{"cmd": "ROTATE", "target": 1}
{"cmd": "DISCHARGE"}
{"cmd": "HOME"}
{"cmd": "PING"}
```

> `target`: 1=Nhựa, 2=Thủy tinh, 3=Giấy, 4=Kim loại
>
> `HOME`: lối khôi phục — ép ống về ngăn Thủy tinh mà không cần chạy hết chu kỳ.
> Dùng khi Pi hủy chu kỳ giữa chừng. **Không gỡ được chốt FAULT** (xem dưới).

### ESP32 → Pi (phản hồi / push sự kiện)
```json
{"event": "OBJECT_DETECTED", "distance": 12}
{"event": "KNOCK_DONE", "seq": 1}
{"event": "ROTATE_DONE", "position": 1}
{"event": "DISCHARGE_DONE"}
{"event": "READY", "position": 2}
{"event": "ALIVE"}
{"event": "ERROR", "code": "MOTOR_TIMEOUT"}
{"event": "ERROR", "code": "INVALID_CMD"}
{"event": "ERROR", "code": "HOME_FAILED"}
{"event": "ERROR", "code": "MOTION_FAULT"}
```

> **`READY`** = ống đã đậu tại HOME (Thủy tinh) và máy sẵn sàng nhận vật tiếp
> theo. ESP32 push nó sau boot-home và sau mỗi lần xả. ESP32 **tự chặn**
> `OBJECT_DETECTED` cho tới khi có `READY` — Pi không phải tự giữ trạng thái,
> nhưng cũng không được coi `DISCHARGE_DONE` là "xong chu kỳ".
>
> **`MOTION_FAULT`** là một **CHỐT**, không phải lỗi nhất thời: engine đã khóa
> và sẽ **từ chối mọi lệnh quay** cho tới khi có người tháo xoắn dây rồi mở khóa
> (phím `'f'` trong `test_motor_ir`, hoặc reset nguồn sau khi đã quay tay ống về
> Thủy tinh). Pi phải **dừng hẳn** chu kỳ, log lỗi, và **KHÔNG thử lại tự
> động** — thử lại chính là thứ cuốn đứt dây.

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
   → BẮT ĐẦU THU ÂM LIÊN TỤC M-306 (audio.start_sequence)
   → Gửi: {"cmd": "KNOCK", "count": 3}
         ↓
[ESP32] Core 1: SG90 gõ 3 lần, chu kỳ KNOCK_INTERVAL_MS (700ms)
   → Sau mỗi lần gõ push: {"event": "KNOCK_DONE", "seq": 1/2/3}
         ↓
[Pi] Nhận KNOCK_DONE (seq==count) → DỪNG THU (audio.finish_sequence)
   → Tách 3 va đập trong bản ghi → FFT từng lần → 3 × (audio_type, conf)
   → Bật LED → chụp ảnh → tắt LED → AI → cam_type + cam_confidence
     (LED do Pi tự bật qua GPIO 17, không qua ESP32)
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
[Pi] Log kết quả  (KHÔNG nhận vật mới — chưa xong)
         ↓
[ESP32] Core 1: TỰ quay ống về HOME (cảm biến Thủy tinh), ISR phanh tại đó
   → Push: {"event": "READY", "position": 2}
         ↓
[Pi] Nhận READY → sẵn sàng cho lần tiếp theo
```

> Bước về HOME do **ESP32 tự làm**, Pi không ra lệnh. Tách `DISCHARGE_DONE` và
> `READY` làm 2 event để Pi biết cửa đã đóng ngay, không phải chờ cả
> quãng quay chỉ để biết cửa đã đóng.
>
> Rác **Thủy tinh**: cả bước `ROTATE` lẫn bước về HOME đều không quay — ngăn xả
> chính là HOME.
>
> **Vì sao thu liên tục, không mở cửa sổ sau mỗi `KNOCK_DONE`:** ESP32 push
> `KNOCK_DONE` sau khi servo đã gõ (`KNOCK_DWELL_MS`) **và** đã về
> (`KNOCK_SETTLE_MS`) — tức ~0.45s sau va đập. Thu từ lúc đó chỉ còn đuôi vang.
> Pi thu từ TRƯỚC lệnh `KNOCK`, rồi định vị va đập bằng đỉnh envelope (không
> bằng thời điểm event). `KNOCK_INTERVAL_S` trong `pi_config.py` **phải khớp**
> `KNOCK_INTERVAL_MS` trong `config.h`.
>
> Mỗi lần gõ chỉ GIỮ đoạn `[va đập, va đập + AUDIO_WINDOW_S)` — phải kết thúc
> **trước lúc servo bắt đầu về** (`KNOCK_DWELL_MS` − thời gian vung ~0.13s), nếu
> không phổ dính tiếng motor servo. Đây là "thu ngắt nghỉ" làm bằng phần mềm:
> không bật/tắt stream thật vì Pi không biết lúc servo bắt đầu vung, và mở
> stream ALSA trễ hàng chục ms sẽ mất sườn va đập.
>
> **Luôn xả.** Fusion luôn chọn một ngăn thật (khả năng nhất); confidence thấp
> chỉ được log là "không chắc chắn". Vật không được xả sẽ nằm lại trong ống →
> ESP32 không bao giờ push `READY` → máy kẹt. Mic và camera bù cho nhau; chỉ khi
> cả hai cùng hỏng mới xả vào `FALLBACK_WASTE_TYPE` (Thủy tinh = HOME). Ngoại lệ
> duy nhất: lỗi cơ cấu (ROTATE/HOME lỗi) → không xả, chờ người.

---

## Phân công FreeRTOS (ESP32)

| Core | Task | Nội dung |
|------|------|---------|
| Core 1 (Priority 2) | `taskRealtime` | Servo SG90/MG90S, Motor DRV8871, Interrupt TCRT5000 |
| Core 0 (Priority 1) | `taskComms` | UART ↔ Pi 4, HC-SR04 polling |
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
│   │   ├── config.h                       (pin mapping, hằng số hệ thống, mô hình cung)
│   │   ├── motion.h                       (API engine quay ống)
│   │   └── tasks.h                        (khai báo FreeRTOS tasks + commandQueue)
│   └── src/
│       ├── main.cpp                       (setup: khởi tạo, tạo tasks; loop rỗng)
│       ├── motion.cpp                     ★ engine quay: ISR/IR, chống xoắn, HOME, FAULT
│       ├── task_realtime.cpp              (Core 1: servo SG90/MG90S — gọi motion.cpp)
│       ├── task_comms.cpp                 (Core 0: UART JSON, HC-SR04)
│       ├── test_motor_ir.cpp              (harness bàn phím cho motion.cpp)
│       ├── test_motor_simple.cpp          (đo phần cứng thô: 'm'/'n'/'0'/'7'/'8')
│       ├── test_full_cycle.cpp            (mô phỏng cả Pi lẫn ESP32, không cần Pi)
│       ├── test_servo.cpp / test_hcsr04.cpp
│
└── Raspberry PI/                          ← Python — Pi orchestrator
    ├── main_controller.py                 (bộ não: điều phối toàn bộ flow)
    ├── pi_config.py                       (hằng số toàn hệ thống)
    ├── pi_audio_classifier.py             (thu âm mic M-306 (USB) → FFT → phân loại)
    ├── pi_camera_classifier.py            (AI/OpenCV: phân loại LOẠI vật từ ảnh — KHÔNG dùng để detect; LED chụp)
    ├── pi_classifier_fusion.py            (kết hợp audio + camera → quyết định cuối)
    ├── pi_communication.py                (UART JSON với ESP32)
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

# Cắm mic M-306 vào cổng USB — không cần chỉnh /boot/config.txt
# Kiểm tra thiết bị được nhận diện:
#   arecord -l
# Nếu cần chọn đúng card thay vì mặc định, set trong pi_config.py:
#   AUDIO_DEVICE_ID = <index lấy từ arecord -l>
# Nếu bị ESP32/serial USB tranh index gây lẫn lộn, có thể cố định
# tên card bằng /etc/asound.conf hoặc lấy theo tên qua
# sounddevice.query_devices() thay vì hardcode index.

# Enable UART GPIO cho ESP32 — thêm vào /boot/config.txt:
#   enable_uart=1
# Disable serial console: sudo raspi-config → Interface → Serial → No console, Yes hardware

# LED (gpiozero + lgpio) có sẵn trên Raspberry Pi OS. Nếu chạy trong venv thì tạo
# venv bằng --system-site-packages, không thì gpiozero thiếu pin factory → hệ chạy
# KHÔNG đèn (chỉ log warning "[LED] Không mở được GPIO").

# Chạy hệ thống
cd "Raspberry PI"
python3 main_controller.py

# Autostart khi boot — thêm vào /etc/rc.local:
# cd /home/pi/WasteDetector/Raspberry\ PI && python3 main_controller.py &
```

---

## Vấn đề đã biết / TODO

### Chưa implement
- `pi_camera_classifier.py` — chưa có code phân loại AI
- `pi_classifier_fusion.py` — chưa có code tổng hợp
- Phía Pi chưa xử lý event `READY` và mã lỗi `MOTION_FAULT` (xem phần giao thức)
- `main_controller.py` chưa nối audio (`start_sequence`/`finish_sequence`),
  camera, fusion — spec đầy đủ ở docstring đầu file. Nhánh "không nhận diện
  được → return" hiện tại là SAI (vật nằm lại trong ống → máy kẹt), phải bỏ.

### Calibration cần thực tế
- Ngưỡng TCRT5000 (`IR_THRESHOLD`) — cần đo với tấm phản quang thực tế.
  Chạy lệnh `m` trong `test_motor_simple` (motor TẮT, xoay ống bằng tay): mỗi
  cảm biến phải đọc `0` khi có tấm phản quang và `1` khi không. Lệnh `n` (motor
  CHẠY) so số cạnh với `m` để biết nhiễu có đến từ motor hay không.
- Tốc độ motor (`MOTOR_SPEED`) và thời gian phanh — cần điều chỉnh theo tải.
  **Phải calibrate LẠI sau khi đổi sang DRV8871**: sụt áp giảm từ ~2V xuống
  ~0.2V nên cùng một duty sẽ cho tốc độ cao hơn rõ rệt so với thời L298N.
- **Hiệu chuẩn thời gian quay** — lệnh `'c'` trong `test_motor_ir` (HOME → Kim
  loại → Nhựa → HOME) đo `tFirst`/`tMid` mỗi chiều, lưu NVS. **Bắt buộc chạy 1 lần
  khi cả 4 IR còn tốt**, và chạy lại sau khi đổi `MOTOR_SPEED`/tải. Chưa có số đo
  thì chế độ canh giờ khi IR hỏng bị vô hiệu (hệ báo lỗi thay vì đoán).
- `SEEK_BLIND_MS` — chỉ dùng khi CHƯA có số đo: trần cho một đoạn 90°. Phải
  **lớn hơn** thời gian quay 90° nhưng **nhỏ hơn** 180°; `'c'` in ra khoảng gợi ý.
- Góc lệch θ_lag của tấm phản quang — cần đo bằng cách chạy thử
- Phơi sáng camera dưới LED 1W (`ExposureTime`/`AnalogueGain` cố định, tắt
  AE/AWB) — đo 1 lần với vật thật trong ống. Phải xong TRƯỚC khi chụp dataset,
  vì đổi phơi sáng sau đó là ảnh train không còn khớp ảnh vận hành.
- Tần số FFT cho từng vật liệu — cần chạy `calibrate()` trên vật liệu thực

### Bảo vệ cơ cấu — `motion.cpp` (viết lại 2026-09-30)

Motor là thứ duy nhất trong máy có thể tự phá hỏng mình (cuốn đứt dây), nên mọi
nghi ngờ đều xử theo hướng **dừng**, không theo hướng chạy tiếp. Chi tiết cơ chế:
comment mục (1)-(6) đầu `motion.cpp`.

**Mọi chu kỳ xuất phát từ HOME:** tới ngăn → xả → về HOME. `motionRotateTo()`
thấy ống đang ở ngăn khác HOME (chu kỳ trước bị ngắt) thì tự về HOME trước, không
bao giờ đi tắt ngăn→ngăn. Mọi logic "đang đứng ở Nhựa/Giấy/Kim loại" dưới đây
chỉ để khôi phục sau khi bị ngắt giữa chừng.

**Boot bắt buộc về HOME.** Đọc IR ngay: đứng trên Nhựa → CW về, trên Giấy/Kim
loại → CCW về. Lưng chừng → dò **CW** tới IR gần nhất rồi về như trên. Ngoại lệ
duy nhất của chiều dò: NVS nói ống ở phía Kim loại (bị ngắt khi đang đi **tới**
Kim loại, hoặc lần cuối đứng ở Kim loại) → dò **CCW**, vì lố qua Kim loại là đã
vào vùng cấm và dò CW tiếp sẽ ra Nhựa ở +270°.

**NVS (Preferences, namespace `motion`)** nhớ: station cuối / lệnh đang chạy dở,
mặt nạ IR chết, `tFirst`/`tMid`. Lý do: một IR không cho biết độ xoắn — Nhựa ở
−90° và Nhựa ở +270° (lố qua Kim loại, xuyên vùng cấm) trông y hệt. Dò CW mà gặp
Nhựa trước tiên, hoặc boot thấy Nhựa trong khi NVS nói phía Kim loại → **FAULT,
không đoán**. Chỉ ghi NVS khi motor **đứng yên** (ghi flash tắt cache → ISR GPIO
bị hoãn). Thủy tinh luôn được chấp nhận — lối khôi phục "quay tay về Thủy tinh
rồi reset".

**IR hỏng → canh giờ** (tối đa MỘT IR chết; cái thứ hai → FAULT). Không có
encoder nên "kẹt" và "IR chết" trông giống nhau; phân biệt bằng bằng chứng:

| Tình huống | Cách xác nhận | Phản ứng |
|---|---|---|
| Lỡ cạnh giữa đường | Station SAU nó tới đúng giờ | Đánh dấu chết, chạy tiếp |
| Lỡ cạnh ĐÍCH | Phanh, **lùi** về IR vừa qua, đo giờ. Lùi ≥ 90% t90 → đã đi quá đích | Đánh dấu chết, quay lại bằng canh giờ |
| — | Lùi nhanh | Ống **kẹt**, báo lỗi |
| IR xuất phát vẫn báo CÓ VẬT khi đã tới ngăn kế | — | Kẹt mức thấp → đánh dấu chết |
| IR đã đánh dấu chết lại lên cạnh đúng chỗ | — | Tự gỡ đánh dấu |

Canh giờ luôn tính từ cạnh IR **sống** gần nhất, không bao giờ hai đoạn liên
tiếp. Đích là đầu mút (Kim loại/Nhựa) → phanh ở 90% (thà thiếu hơn lố vào vùng cấm).

**Dừng khẩn:** `SPACE` trong `test_motor_ir` — tác dụng ở mọi lúc motor chạy
(quay, dò, hiệu chuẩn, jog, đếm ngược boot), hủy cả chuỗi thao tác.

Hai lỗi thường liên tiếp (`MOTION_MAX_CONSEC_FAIL`) cũng chốt FAULT: một lần có
thể là kẹt rác nhất thời, hai lần thì phải có người nhìn vào.

**FAULT là một chốt.** `motionRotateTo()` / `motionGoHome()` từ chối chạy cho tới
khi gọi `motionClearFault()`. Jog tháo xoắn (`'['` / `']'`) **vẫn chạy được** —
nó chính là lối thoát khi đã FAULT. Trình tự khôi phục: tháo xoắn bằng jog → bấm
`'f'` để mở khóa (hệ tự dò lại vị trí) → bấm `'0'` về HOME.

---

## Thư viện

### PlatformIO (ESP32)
- `bblanchon/ArduinoJson` — parse/serialize JSON protocol
- `madhephaestus/ESP32Servo` — PWM servo trên ESP32
- FreeRTOS — tích hợp sẵn trong Arduino-ESP32

### Python (Raspberry Pi)
- `opencv-python` — camera và image processing
- `numpy`, `scipy` — FFT và signal processing
- `sounddevice` — thu âm mic M-306 (USB)
- `pyserial` — UART serial với ESP32
