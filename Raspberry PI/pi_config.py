"""
pi_config.py — Hằng số và cấu hình toàn hệ thống Raspberry Pi
"""

# ============================================================
# Serial UART → ESP32
# ============================================================
ESP32_PORT     = '/dev/ttyS0'   # GPIO 14/15 (UART0) — enable_uart=1 in /boot/config.txt
ESP32_BAUDRATE = 115200
ESP32_TIMEOUT  = 5.0            # giây chờ response mặc định

# ============================================================
# Mã loại rác (khớp với config.h của ESP32)
# ============================================================
WASTE_NONE    = 0
WASTE_PLASTIC = 1
WASTE_GLASS   = 2
WASTE_PAPER   = 3
WASTE_METAL   = 4

WASTE_NAMES = {
    WASTE_NONE:    "Không xác định",
    WASTE_PLASTIC: "Nhựa",
    WASTE_GLASS:   "Thủy tinh",
    WASTE_PAPER:   "Giấy/Carton",
    WASTE_METAL:   "Kim loại",
}

# ============================================================
# Timing (giây)
# ============================================================
KNOCK_COUNT          = 3       # số lần gõ mỗi vật thể
KNOCK_INTERVAL_S     = 0.7     # chu kỳ giữa 2 lần gõ — PHẢI khớp KNOCK_INTERVAL_MS (config.h ESP32)
AUDIO_WINDOW_S       = 0.15    # đoạn phân tích FFT cho MỖI lần gõ, tính từ va đập. PHẢI kết thúc
                               # TRƯỚC lúc servo bắt đầu về: ≤ KNOCK_DWELL_MS (0.3s) − thời gian
                               # servo vung tới vật (SG90 ~0.1s/60° × 78° ≈ 0.13s) − biên.
                               # Đổi KNOCK_DWELL_MS / góc gõ phía ESP32 → tính lại.
AUDIO_SEQUENCE_MARGIN_S = 0.8  # thu thêm ngoài KNOCK_COUNT × KNOCK_INTERVAL_S: trễ UART,
                               # servo vung tới vật, đuôi vang của lần gõ cuối
MIN_CONFIDENCE       = 0.35    # dưới ngưỡng: VẪN xả vào ngăn khả năng nhất, chỉ đánh dấu
                               # "không chắc chắn" trong log — không giữ vật lại trong ống

# ============================================================
# Camera
# ============================================================
CAMERA_ID = 0   # 0 = mặc định (USB webcam hoặc Pi Camera qua libcamera)

# LED 1W chiếu sáng lúc chụp: Pi GPIO → MOSFET IRLZ44N → LED (xem CLAUDE.md)
LED_PIN      = 17     # số BCM — chân vật lý 11. Tránh 14/15 (UART ESP32)
LED_SETTLE_S = 0.1    # bật LED rồi chờ bấy nhiêu mới chụp: ≥ 3 frame ở 30fps để frame
                      # chụp được phơi sáng TRỌN dưới LED. Chỉ đủ khi camera KHÓA phơi
                      # sáng; để AE tự động thì phải ~0.5-1s.

# ============================================================
# Audio
# ============================================================
AUDIO_DEVICE_ID   = None   # None = mặc định (mic M-306 qua USB, xem `arecord -l` nếu cần chỉ định index)
AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS    = 1
AUDIO_FILTER_LOW = 100
AUDIO_FILTER_HIGH = 8000
