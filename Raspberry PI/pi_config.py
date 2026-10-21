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

# Pi chờ phản hồi ESP32. ESP32 LUÔN trả lời (ROTATE_DONE/READY hoặc ERROR) — các
# timeout này chỉ bắt trường hợp mất UART, nên phải DÀI HƠN ca xấu nhất của motor:
# ROTATE có thể phải về HOME trước rồi mới đi tiếp (tới 4 đoạn 90° × MOTOR_TIMEOUT_MS
# 5s trong config.h, chưa kể lùi dò IR hỏng). Timeout ngắn hơn thì Pi bỏ chu kỳ trong
# khi ống vẫn đang quay → vật nằm lại ở ngăn đích, ESP32 không bao giờ push READY.
ROTATE_TIMEOUT_S     = 30.0
DISCHARGE_TIMEOUT_S  = 5.0     # cửa: DOOR_HOLD_MS + DOOR_SETTLE_MS = 2s
READY_TIMEOUT_S      = 30.0    # về HOME sau xả — cùng lý do với ROTATE_TIMEOUT_S

# ============================================================
# Fusion (pi_classifier_fusion.py)
# ============================================================
AUDIO_WEIGHT             = 0.4    # ưu tiên camera: model AI đã đo 97% trên Pi, FFT chưa calibrate
CAMERA_WEIGHT            = 0.6    # AUDIO_WEIGHT + CAMERA_WEIGHT nên = 1.0
FUSION_BONUS_AGREE       = 0.10
FUSION_PENALTY_DISAGREE  = 0.15
AUDIO_PER_KNOCK_MIN_CONF = 0.20   # ngưỡng loại nhiễu khi gộp nhiều lần gõ
FALLBACK_WASTE_TYPE      = WASTE_GLASS  # mic + camera cùng hỏng. Thủy tinh = HOME: không
                                        # quay ống → không mòn cơ cấu, không rủi ro xoắn dây

# ============================================================
# Camera
# ============================================================
CAMERA_BACKEND    = "auto"       # "auto" = picamera2 nếu có, không thì OpenCV VideoCapture
                                 # "picamera2" | "opencv" = ép một backend
CAMERA_ID         = 0            # picamera2: camera_num; OpenCV: index VideoCapture
CAMERA_RESOLUTION = (1280, 960)  # (w, h) khung chụp — ROI cắt từ khung này. Đổi độ phân
                                 # giải thì camera_roi.json tự co giãn theo (có lưu kích thước khung)

# Phơi sáng KHÓA dưới LED — đo 1 lần: `python3 pi_camera_classifier.py 4`.
# None = để AE/AWB tự động (tạm thời, trước khi đo): camera phải chờ
# CAMERA_AUTO_SETTLE_S mỗi lần chụp và ảnh thay đổi theo vật. Phải khóa TRƯỚC khi chụp
# dataset — đổi phơi sáng sau đó là ảnh train không còn khớp ảnh vận hành.
CAMERA_EXPOSURE_US   = None      # int, µs   (ExposureTime)
CAMERA_ANALOGUE_GAIN = None      # float     (AnalogueGain)
CAMERA_COLOUR_GAINS  = None      # (red, blue) (ColourGains)
CAMERA_AUTO_SETTLE_S = 1.0       # chờ AE/AWB hội tụ dưới LED khi CHƯA khóa phơi sáng

CAMERA_CAPTURE_TIMEOUT_S = 2.0   # mỗi lần lấy frame (picamera2)
CAMERA_CAPTURE_RETRIES   = 3     # frame lỗi / đen → chụp lại tối đa bấy nhiêu lần
CAMERA_BLACK_MEAN        = 8.0   # độ sáng trung bình (0-255) dưới mức này = frame đen
CAMERA_OPENCV_FLUSH      = 5     # OpenCV: bỏ bấy nhiêu frame cũ trong buffer driver

# Model YOLO26n-cls (OpenVINO IR) — thư mục tương đối so với thư mục Raspberry PI/
CAMERA_MODEL_DIR       = "models/yolo26n_cls_openvino"
CAMERA_INFER_THREADS   = 4       # 4 lõi Cortex-A72
CAMERA_INFER_TIMEOUT_S = 2.0     # quá hạn → hủy inference, trả (WASTE_NONE, 0.0)

# Lớp của model (metadata.yaml) → mã WASTE_*. Gộp theo TÊN, không theo chỉ số: train
# lại đổi thứ tự lớp vẫn đúng. Mọi lớp của model PHẢI có mặt ở đây, thiếu là camera
# bị tắt lúc khởi động. Nhựa = HDPE + PET: xác suất CỘNG lại, không lấy lớp cao nhất.
CAMERA_CLASS_MAP = {
    "CARTON": WASTE_PAPER,
    "GLASS":  WASTE_GLASS,
    "HDPE":   WASTE_PLASTIC,
    "PET":    WASTE_PLASTIC,
    "METAL":  WASTE_METAL,
}

# LED 1W chiếu sáng lúc chụp: Pi GPIO → MOSFET IRLZ44N → LED (xem CLAUDE.md)
LED_PIN      = 17     # số BCM — chân vật lý 11. Tránh 14/15 (UART ESP32)
LED_SETTLE_S = 0.1    # bật LED rồi chờ bấy nhiêu mới chụp. Chỉ đủ khi camera KHÓA phơi
                      # sáng; chưa khóa thì dùng CAMERA_AUTO_SETTLE_S. Frame lấy bằng
                      # flush=True nên luôn bắt đầu phơi sáng SAU lúc này.

# ============================================================
# Audio
# ============================================================
AUDIO_DEVICE_ID   = None   # None = mặc định (mic M-306 qua USB, xem `arecord -l` nếu cần chỉ định index)
AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNELS    = 1
AUDIO_FILTER_LOW = 100
AUDIO_FILTER_HIGH = 8000
