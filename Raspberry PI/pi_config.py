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
AUDIO_WINDOW_S       = 0.3     # cửa sổ thu âm sau mỗi lần gõ
POST_CLASSIFY_DISPLAY_S = 5.0  # thời gian hiển thị kết quả
MIN_CONFIDENCE       = 0.35    # ngưỡng confidence tối thiểu để chấp nhận

# ============================================================
# Camera
# ============================================================
CAMERA_ID = 0   # 0 = mặc định (USB webcam hoặc Pi Camera qua libcamera)

# ============================================================
# Audio
# ============================================================
AUDIO_DEVICE_ID   = None   # None = mặc định (mic M-306 qua USB, xem `arecord -l` nếu cần chỉ định index)
AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS    = 1
AUDIO_FILTER_LOW = 100
AUDIO_FILTER_HIGH = 8000

# ============================================================
# GUI
# ============================================================
FULLSCREEN = True
