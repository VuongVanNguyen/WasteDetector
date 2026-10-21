#pragma once

// ============================================================
// Pin Mapping
// ============================================================

// Motor GA25-370 via DRV8871 — thay cho L298N Mini đã chết cả hai kênh
//
// DRV8871 KHÔNG có chân enable. PWM đánh THẲNG vào hai chân chiều, nên mỗi
// chân cần MỘT kênh LEDC riêng:
//
//     IN1     IN2     Trạng thái
//     PWM     0       quay chiều A
//     0       PWM     quay chiều B
//     max     max     PHANH chủ động (nối tắt hai đầu motor qua low-side)
//     0       0       THẢ TRÔI (Hi-Z)
//
// ⚠️ Chân đã gắn LEDC thì `digitalWrite` KHÔNG còn tác dụng — LEDC chiếm quyền
//    điều khiển chân qua GPIO matrix. Mọi thao tác chiều/phanh/thả trôi đều
//    phải làm bằng `ledcWrite`, kể cả trong ISR (và vì ledcWrite không an toàn
//    trong ISR nên phần phanh đã chuyển hết về task).
#define PIN_MOTOR_IN1   25   // → DRV8871 IN1
#define PIN_MOTOR_IN2   26   // → DRV8871 IN2
// GPIO 27 (ENA cũ của L298N) nay BỎ TRỐNG — DRV8871 không có chân enable.

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
#define WASTE_ANY       (-1)    // "cam bien bat ky" — dung cho homing/do chieu

// ============================================================
// Timing constants (ms) — calibrate with real hardware
// ============================================================
#define KNOCK_INTERVAL_MS       700     // period between knock starts (ms)
                                        // PHAI >= DWELL + SETTLE + margin
#define KNOCK_STRIKE_ANGLE      90      // SG90 strike angle (deg)
#define KNOCK_REST_ANGLE        12      // SG90 rest angle (deg)
                                        // KHONG de 0: xung 500-600us thuong vuot gioi han
                                        // co khi cua SG90 -> servo stall lien tuc khi "nghi".
#define KNOCK_DWELL_MS          300     // time held at strike position
                                        // SG90 ~0.1s/60deg khong tai => 90deg can >=150ms;
                                        // co tai phai du hao. Qua ngan = servo bi goi ve
                                        // khi chua di het hanh trinh.
#define KNOCK_SETTLE_MS         250     // time for servo to return to rest

#define DOOR_OPEN_ANGLE         0       // MG90S open angle (deg) — inverted mount
#define DOOR_CLOSE_ANGLE        90      // MG90S closed angle (deg) — inverted mount
#define DOOR_HOLD_MS            1500    // how long door stays open
#define DOOR_SETTLE_MS          500     // settle time after door closes

#define MOTOR_SPEED             180     // duty PWM 0-255 vào chân chiều — calibrate
#define MOTOR_TIMEOUT_MS        5000    // max rotation time per step before error
#define MOTOR_BRAKE_MS          80      // thời gian GIỮ phanh chủ động
                                        // DRV8871: phanh = CẢ HAI chân ở duty max.
                                        // Cả hai ở 0 là THẢ TRÔI, không phải phanh.
#define MOTOR_DEADTIME_MS       150     // chờ rotor đứng hẳn TRƯỚC khi đảo chiều.
                                        // Đảo chiều lúc đang quay: back-EMF cộng vào
                                        // nguồn 12V => dòng đỉnh vài A, sụt rail chung,
                                        // ESP32 có thể brownout-reset.
#define MOTOR_FREE_JOG_MAX_MS   20000   // trần an toàn cho quay tự do THÁO XOẮN
                                        // (test_motor_ir, lệnh '['/']'). Không phải
                                        // canh giờ vị trí — chỉ để tự dừng nếu quên
                                        // bấm SPACE / rớt Serial.
#define MOTOR_SETTLE_MS         120     // chờ ổn định rồi mới đọc lại cảm biến
#define MOTOR_LEDC_CH_IN1      4       // LEDC channel cho PIN_MOTOR_IN1
#define MOTOR_LEDC_CH_IN2       5       // LEDC channel cho PIN_MOTOR_IN2
#define MOTOR_LEDC_FREQ         5000    // PWM frequency for motor control (Hz)
                                        // DRV8871 chịu tới 100kHz. Nâng lên 20000
                                        // sẽ hết tiếng rít nghe được — nhưng chỉnh
                                        // SAU khi hệ đã chạy ổn ở 5kHz.
#define MOTOR_LEDC_BITS         8       // PWM resolution for motor control (bits)
#define MOTOR_DUTY_MAX          ((1 << MOTOR_LEDC_BITS) - 1)

#define ULTRASONIC_DETECT_CM    17      // object present if distance < this
#define ULTRASONIC_POLL_MS      100     // HC-SR04 poll interval

#define IR_THRESHOLD            500     // ADC value — CHỈ dùng cho lệnh monitor 'm'
                                        // khi hiệu chỉnh biến trở. Không dùng để dừng motor.
#define IR_DEBOUNCE_US          2000    // bỏ qua cạnh mới trong vòng 2ms sau cạnh trước
                                        // (nhiễu chổi than là xung µs; vật đi qua cảm biến
                                        //  thật kéo dài hàng chục ms)

// ============================================================
// Chống xoắn dây — CUNG 270° + ĐIỂM ĐẬU (HOME) TẠI CẢM BIẾN THỦY TINH
// ============================================================
// Dây điện bắc ngang ống trụ nên ống không được xoay quá 1 vòng. Ta CẤM ống đi
// qua MỘT mối nối giữa hai ngăn — cung trở thành một ĐƯỜNG THẲNG. Mối nối cấm
// nằm giữa Kim loại và Nhựa, và HOME là chính cảm biến THỦY TINH:
//
//     Kim loại ─── Giấy ─── THỦY TINH ─── Nhựa      ╳ cấm khép vòng
//       +180°      +90°     0° (HOME)     −90°         (Kim loại ↔ Nhựa)
//       idx 0      idx 1       idx 2      idx 3
//
//                  <──────── CW ────────   ──── CCW ───>
//
// Thủy tinh vừa là ĐIỂM ĐẬU (sau mỗi chu kỳ ống luôn quay về đây) vừa là NGĂN
// XẢ của rác thủy tinh — xả thủy tinh nghĩa là "đã ở sẵn HOME, xả tại chỗ".
//
// Chiều quay TỪ HOME, đúng như yêu cầu vận hành:
//     Giấy      → CW,  vượt 1 cảm biến
//     Kim loại  → CW,  vượt 2 cảm biến (đi xuyên qua Giấy)
//     Nhựa      → CCW, vượt 1 cảm biến
//     Thủy tinh → không quay, đã ở HOME
//
// Độ xoắn CÓ DẤU, gốc tại HOME:  xoắn = STATION_TWIST_DEG[idx] ∈ [−90°, +180°].
//
// ⚠️ ĐIỀU KIỆN VẬT LÝ BẮT BUỘC
//    1. Bốn ngăn phải nằm quanh ống ĐÚNG dãy  Kim loại → Giấy → Thủy tinh →
//       Nhựa  ở 4 slot cách nhau 90°. Khoảng 90° còn lại (Kim loại ↔ Nhựa) là
//       VÙNG CẤM, ống không bao giờ đi qua. Hoán vị vật lý khác đi thì phép trừ
//       chỉ số trong doRotate/motionGoHome chọn sai chiều và ống vượt vùng cấm.
//       Muốn đổi thứ tự: sửa DUY NHẤT mảng STATION_POS[] trong motion.cpp —
//       mọi thứ khác suy ra từ nó.
//    2. Dây cáp phải được dress THẲNG HOÀN TOÀN khi ống đứng TẠI THỦY TINH.
//       Neo thẳng ở chỗ khác thì toàn bộ dải xoắn dịch đi theo — neo tại Kim
//       loại chẳng hạn sẽ biến biên +180° thành +360°, quá một vòng.
//
// HOME có cảm biến riêng: về HOME là một lệnh quay bình thường tới cảm biến
// Thủy tinh. Canh giờ CHỈ dùng khi một cảm biến bị đánh dấu chết (xem khối
// "Dự phòng IR hỏng" bên dưới).
#define IR_POSITION_COUNT       4       // số cảm biến TCRT5000 (= số ngăn)
#define STATION_COUNT           4       // MỖI station có đúng 1 cảm biến — HOME
                                        // không còn là điểm ảo chen giữa dãy nữa.
#define STATION_HOME_IDX        2       // chỉ số của Thủy tinh trong dãy station
#define HOME_POS                WASTE_GLASS   // HOME == ngăn Thủy tinh
#define DEGREES_PER_STEP        90      // góc giữa 2 ngăn kề nhau
#define MAX_TWIST_DEG           180     // |xoắn| lớn nhất — đầu mút Kim loại
#define MOTOR_DIR_CW            0       // chiều thuận (IN1=PWM, IN2=0) — GIẢM chỉ số,
                                        // tức HOME → Giấy → Kim loại
#define MOTOR_DIR_CCW           1       // chiều nghịch (IN1=0, IN2=PWM) — TĂNG chỉ số,
                                        // tức HOME → Nhựa
#define MOTOR_DIR_INVERTED      0       // đặt 1 nếu ống quay NGƯỢC chiều mong muốn.
                                        // CW/CCW chỉ là TÊN của hai tổ hợp cấp điện,
                                        // không hứa hẹn gì về chiều kim đồng hồ thật —
                                        // chiều vật lý phụ thuộc cách cắm 2 dây ở
                                        // terminal MOTOR. Đảo 2 dây đó tương đương
                                        // hoàn toàn với việc đặt cờ này.
                                        // Cách dò an toàn: từ HOME (Thủy tinh) ra lệnh
                                        // '3' (Giấy). Tới Giấy là đúng; đi về phía
                                        // Nhựa là sai -> đặt 1. Chọn '3' vì Giấy kề
                                        // HOME nên dù sai chiều ống cũng chỉ lệch 1
                                        // ngăn, không bao giờ chạm vùng cấm.

// --- Dò vị trí khi chưa biết (boot giữa chừng / sau khi jog / sau dừng khẩn) ---
// Mặc định dò theo CW. Ngoại lệ DUY NHẤT: NVS nói ống ở phía Kim loại (bị ngắt
// khi đang đi tới Kim loại, hoặc lần cuối đứng ở Kim loại) → dò CCW, để không
// đi sâu thêm vào vùng cấm. Chi tiết: motion.cpp mục (5).
#define SEEK_BLIND_MS           2500    // trần thời gian cho MỘT đoạn 90° khi CHƯA có
                                        // số đo thật (chưa chạy 'c' / chưa quay đủ
                                        // các chặng). Phải LỚN HƠN thời gian quay 90°
                                        // nhưng NHỎ HƠN thời gian quay 180°. Khi đã có
                                        // số đo, engine tự dùng t90 × MOTION_MISS_PCT.
#define BOOT_HOME_GRACE_MS      1500    // độ trễ TRƯỚC KHI tự quay về HOME lúc khởi
                                        // động. Đây là lần motor tự chạy DUY NHẤT mà
                                        // không do người bấm lệnh — cho người dùng kịp
                                        // rút nguồn nếu dây/cơ cấu chưa sẵn sàng ngay
                                        // sau khi flash/reset.

// ============================================================
// Bảo vệ hệ thống — chốt FAULT khi logic đi chệch
// ============================================================
// Mọi cơ chế dưới đây có chung một mục đích: khi một điểm logic hỏng (cảm biến
// chết, sai chiều, tấm phản quang rơi, ống kẹt), hệ PHẢI dừng hẳn thay vì chạy
// tiếp và cuốn dây. Motor là thứ duy nhất trong máy này có thể tự phá hỏng mình.
#ifndef MOTION_FAULT_LATCH
#define MOTION_FAULT_LATCH      1       // 0 = KHÔNG chốt FAULT: lỗi chỉ phanh + in cảnh
                                        // báo, lệnh kế tiếp vẫn chạy được (tiện khi
                                        // test). 1 = chốt như thiết kế gốc — BẬT LẠI
                                        // cho production vì đó là thứ chặn cuốn đứt dây.
#endif
#define MOTION_MAX_CONSEC_FAIL  2       // số lần quay lỗi LIÊN TIẾP trước khi chốt
                                        // FAULT. Một lần lỗi có thể là kẹt rác nhất
                                        // thời; hai lần liên tiếp thì phải có người
                                        // nhìn vào.

// ============================================================
// Dự phòng IR hỏng — canh giờ dựa trên số đo thật
// ============================================================
// Engine đo liên tục hai loại thời gian cho MỖI chiều (lưu NVS):
//   tFirst = từ lúc motor khởi động trên một station tới cạnh IR station kề
//   tMid   = giữa hai cạnh IR liên tiếp khi đang chạy đều
// Một cảm biến bị đánh dấu chết thì đoạn tới nó được CANH GIỜ bằng các số này,
// tính từ cạnh IR SỐNG gần nhất. Không bao giờ canh giờ hai đoạn liên tiếp.
#define MOTION_MISS_PCT         135     // cạnh IR trễ quá 135% thời gian đã đo → lỡ
#define MOTION_ENDPOINT_PCT     90      // canh giờ tới Kim loại/Nhựa (đầu mút cạnh
                                        // vùng cấm): phanh ở 90% — thà thiếu hơn lố
#define MOTION_PROBE_MIN_PCT    90      // lùi kiểm chứng: phải mất ≥90% t90 mới kết
                                        // luận "IR chết"; ngắn hơn là ống bị KẸT
#define MOTION_EMA_SHIFT        2       // EMA: mới = cũ + (đo − cũ) / 2^shift
#define IR_STABLE_SAMPLES       10      // đọc mức IR lúc đứng yên: N mẫu phải trùng
#define IR_STABLE_INTERVAL_MS   2

// ============================================================
// FreeRTOS queues
// ============================================================
#define CMD_QUEUE_SIZE      8
#define RESPONSE_QUEUE_SIZE 8
