"""
pi_audio_classifier.py — Phân loại vật liệu bằng âm thanh gõ (FFT)
====================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Là **1 trong 2 nguồn** của ClassifierFusion ([[pi_classifier_fusion]]).
- Được kích hoạt SAU mỗi sự kiện KNOCK_DONE từ ESP32 (xem flow trong
  main_controller._process_waste): mở cửa sổ thu âm ngắn (~AUDIO_WINDOW_S
  = 0.3s từ pi_config) ngay lập tức để bắt impulse cộng hưởng.
- Chạy KNOCK_COUNT lần (mặc định 3) → trả về 3 cặp (type, conf) → fusion
  gộp lại thành 1 audio_consensus.
- Hoàn toàn không can thiệp cơ cấu — chỉ đọc tín hiệu, xử lý số.

NGUYÊN LÝ PHÂN LOẠI
-------------------
Khi va đập, mỗi vật liệu cộng hưởng ở dải tần khác nhau và phân rã
(decay) ở tốc độ khác nhau:

  | Vật liệu  | Dải tần chủ đạo | Sustain   | Đặc trưng phổ          |
  |-----------|-----------------|-----------|------------------------|
  | Kim loại  | 2000–6000 Hz    | DÀI       | Đỉnh nhọn, hài rõ ràng |
  | Thủy tinh | 1500–4000 Hz    | TRUNG BÌNH| Trong, ít hài bậc cao  |
  | Nhựa      |  500–2000 Hz    | NGẮN      | Đục, broadband nhẹ     |
  | Giấy/Carton| 100– 800 Hz    | RẤT NGẮN  | "Bùm bục", noisy       |

Hai feature CHÍNH dùng để phân loại:
  (a) **Energy distribution** trong 4 dải tần đặc trưng — tính tỷ lệ
      energy[band] / total_energy.
  (b) **Sustain time** — thời gian envelope vượt 10% peak. Kim loại > Giấy.

Confidence = tỷ lệ năng lượng của dải thắng cuộc / tổng năng lượng 4 dải.


PIPELINE XỬ LÝ TÍN HIỆU
-----------------------
5. **Trích đặc trưng**:
   - dominant_freq = freq tại argmax(magnitude).
   - energy_bands[type] = Σ magnitude[band]² trong từng dải đặc trưng.
   - sustain_time = (số mẫu envelope > 10% peak) / sample_rate.

6. **Phân loại** (rule-based, có thể nâng cấp sang SVM/MLP nhỏ sau):
   - ratios = energy_bands / total_energy.
   - best_type = argmax(ratios), confidence = ratios[best_type].
   - Tinh chỉnh tùy chọn: cộng/trừ điểm dựa trên sustain_time
     (vd sustain > 0.2s → boost score METAL).


GIAO DIỆN LỚP — yêu cầu (đã có và CẦN BỔ SUNG)
----------------------------------------------

ĐÃ CÓ (giữ nguyên, chỉ sửa nhược điểm liệt kê dưới):
  - __init__(device_id=None)
  - list_devices()
  - record_knock() -> np.ndarray
  - analyze_fft(audio_data) -> dict
  - classify(audio_data) -> (waste_type, confidence, analysis)
  - calibrate(waste_type, num_samples=10)
  - save_calibration() / load_calibration()

YÊU CẦU KỸ THUẬT / RÀNG BUỘC
-----------------------------
- record_knock() là BLOCKING (sd.wait) → main_controller phải gọi từ
  worker thread, KHÔNG gọi từ Tkinter main thread.
- Tổng thời gian record_and_classify() phải < KNOCK_INTERVAL (khoảng
  cách giữa 2 lần gõ của ESP32, ~500ms) để không bỏ lỡ lần gõ tiếp
  theo. Hiện AUDIO_WINDOW_S=0.3 + FFT ~50ms → đạt yêu cầu.
- confidence trả về phải nằm trong [0,1], cùng thang với
  CameraClassifier để ClassifierFusion so sánh được.
- Khi calibration file tồn tại, freq_ranges nên cập nhật từ file
  (đã có logic load_calibration) — nhưng phải đảm bảo key dùng cùng
  mã WASTE_* sau khi sửa.
- M-306 là USB audio class device chuẩn; sounddevice/pyaudio đọc qua
  ALSA và trả thẳng float32 — không cần xử lý raw bit như mic I2S.
- noise_threshold (=0.01) cần re-calibrate cho M-306 — độ nhạy/gain
  khác thiết bị cũ (INMP441/MAX9814). Khuyến nghị: chạy đo nhiễu nền
  5s ở môi trường thực và set threshold = 3 × RMS nhiễu nền.
- Nếu Pi có nhiều USB audio device (vd thêm loa USB), cần chọn đúng
  index bằng tên thiết bị (`sounddevice.query_devices()`) thay vì
  hardcode index — index có thể đổi giữa các lần cắm lại.


KỊCH BẢN LỖI CẦN XỬ LÝ
----------------------
- Không có thiết bị input → sd.rec raise → catch trong
  record_and_classify, trả (WASTE_NONE, 0.0), log lỗi rõ ràng.
- Clip âm thanh (max > 0.99): vẫn classify nhưng giảm confidence —
  vì FFT bị méo. Cảnh báo trong log.
- Không có âm vượt noise_threshold (gõ trượt, vật quá nhẹ): trả
  (WASTE_NONE, 0.0) — fusion sẽ tự bù bằng camera.
- Filter Butterworth fail (mảng quá ngắn): bypass filter, dùng raw.


TEST ĐỘC LẬP
------------
- Mode 1 (đã có): interactive — Enter để gõ và phân loại.
- Mode 2 (đã có): calibrate từng loại — thu N mẫu, lưu JSON.
- (Đề xuất thêm) Mode 3: đo noise floor 5s, in RMS và đề xuất
  noise_threshold mới.

"""

import enum

import sounddevice as sd
import numpy as np
import scipy.signal as signal
import scipy.fft as fft

import logging

from pi_config import (
    WASTE_NONE,
    WASTE_PLASTIC,
    WASTE_GLASS,
    WASTE_PAPER,
    WASTE_METAL,
    WASTE_NAMES,
    AUDIO_WINDOW_S,
    AUDIO_DEVICE_ID,  
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_FILTER_LOW,
    AUDIO_FILTER_HIGH
)

AUDIO_OK = "OK"
AUDIO_SILENT = "SILENT"
AUDIO_CLIPPED = "CLIPPED"

log = logging.getLogger(__name__)

class ESP32AudioClassifier:

    def __init__(self, device_id = AUDIO_DEVICE_ID):
        self.device_id = device_id
        self.sample_rate = AUDIO_SAMPLE_RATE
        self.record_duration = AUDIO_WINDOW_S  
        self.channels = AUDIO_CHANNELS
        self.filter_low = AUDIO_FILTER_LOW
        self.filter_high = AUDIO_FILTER_HIGH

        self.freq_ranges = {
            WASTE_METAL: (2000, 6000),
            WASTE_GLASS: (1500, 4000),
            WASTE_PLASTIC: (500, 2000),
            WASTE_PAPER: (100, 800),
        }

        self.noise_min_threshold = 0.01  
        self.noise_max_threshold = 0.99
        
    def list_devices(self):
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            print(f"{i}: {dev['name']} (input: {dev['max_input_channels']}, output: {dev['max_output_channels']})")

    def record_knock(self):
        window_samples = int(self.sample_rate * self.record_duration)
        try:
            audio_data = sd.rec(
                window_samples, samplerate=self.sample_rate, channels=self.channels, dtype='float32', device=self.device_id
                )
            sd.wait()  
            return audio_data.flatten()
        except sd.PortAudioError as e:
            log.error(f"Error recording audio: {e}")
            return np.array([])

    def remove_dc_offset(self, audio_data):
        return audio_data - np.mean(audio_data)

    def check_audio_confidence(self, audio_data):
        if np.max(np.abs(audio_data)) > self.noise_max_threshold:
            log.warning("Audio clipping detected! Confidence may be reduced.")
            return AUDIO_CLIPPED
        elif np.max(np.abs(audio_data)) < self.noise_min_threshold:
            log.info("Audio below noise threshold. Likely no valid knock detected.")
            return AUDIO_SILENT
        else:
            log.info("Audio signal is within acceptable range.")
            return AUDIO_OK

    def filter_audio(self, audio_data):
        sos = signal.butter(
            4, [self.filter_low, self.filter_high], btype='bandpass', output='sos', fs = self.sample_rate
            )
        try:
            filtered_audio = signal.sosfiltfilt(sos, audio_data)
            return filtered_audio
        except ValueError as e:
            log.error(f"Error filtering audio: {e}. Bypassing filter.")
            return audio_data

    def analyze_fft(self, audio_data):
        
        
            
    

    