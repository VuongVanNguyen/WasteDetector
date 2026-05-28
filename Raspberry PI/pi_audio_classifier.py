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


KÊNH VẬT LÝ (đã thay đổi so với phiên bản cũ — CẬP NHẬT THEO CLAUDE.md)
-----------------------------------------------------------------------
- Mic: **INMP441 qua I2S** (KHÔNG còn dùng MAX9814 + USB sound card).
- Pin Pi 4: SCK=GPIO18, WS=GPIO19, SD=GPIO20, VDD=3.3V, GND chung.
- Cần `dtparam=i2s=on` + overlay phù hợp trong /boot/config.txt.
- Có thể cần wrapper sounddevice trỏ về device I2S thay vì USB.


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
1. **Thu âm**: sd.rec(window_samples, sample_rate, channels=1, dtype=float32).
   - window_samples = int(AUDIO_SAMPLE_RATE * AUDIO_WINDOW_S).
   - Block (sd.wait()) cho đến khi đủ mẫu.

2. **Tiền xử lý**:
   - DC offset removal: x -= mean(x).
   - Normalize amplitude về [-1, 1] nếu cần (sd.rec đã trả float32 chuẩn).
   - Kiểm tra im lặng: nếu max(|x|) < noise_threshold (≈0.01) → trả
     (WASTE_NONE, 0.0) ngay, không phân tích tiếp.

3. **Lọc nhiễu**: Butterworth bandpass bậc 4, 100–8000 Hz, dùng filtfilt
   (zero-phase) để không méo pha.

4. **FFT**: scipy.fft.fft, lấy nửa dương phổ (0 → Nyquist),
   magnitude = 2/N * |yf|.

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

CẦN BỔ SUNG cho tích hợp với main_controller:
  - record_and_classify() -> (waste_type, confidence)
      Tiện ích 1-call: gọi record_knock() rồi classify(), bỏ field
      `analysis` đi → trả về đúng tuple 2 phần tử mà fusion cần.
      Đây là method main_controller sẽ gọi trong vòng lặp KNOCK_COUNT.

  - (tùy chọn) trigger_async(callback): bắn record_and_classify() trên
      thread riêng và gọi callback(type, conf) khi xong. Hữu ích nếu
      main_controller muốn KNOCK + thu âm OVERLAP để không cộng dồn
      độ trễ.


VẤN ĐỀ TÍCH HỢP CẦN SỬA (QUAN TRỌNG — không sửa = sai ngăn rác!)
---------------------------------------------------------------
File hiện đang định nghĩa LẠI hằng số WASTE_* trong class với MÃ KHÁC
pi_config:

       Định nghĩa trong class (SAI):     pi_config.py (ĐÚNG):
       WASTE_METAL   = 0x01              WASTE_PLASTIC = 1
       WASTE_GLASS   = 0x02              WASTE_GLASS   = 2
       WASTE_PLASTIC = 0x03              WASTE_PAPER   = 3
       WASTE_PAPER   = 0x04              WASTE_METAL   = 4

→ Nếu classifier trả 1 thì main_controller gửi ROTATE target=1 = ngăn
  NHỰA, nhưng audio classifier đang dùng 1 với ý nghĩa KIM LOẠI.
  Kết quả: rác kim loại bị xoay sang ngăn nhựa.

SỬA: xóa block 6 dòng định nghĩa WASTE_* trong class, import từ pi_config
trước class:
       from pi_config import (WASTE_NONE, WASTE_PLASTIC, WASTE_GLASS,
                              WASTE_PAPER, WASTE_METAL, WASTE_NAMES,
                              AUDIO_SAMPLE_RATE, AUDIO_WINDOW_S,
                              AUDIO_DEVICE_ID)
Và:
  - self.sample_rate = AUDIO_SAMPLE_RATE
  - self.record_duration = AUDIO_WINDOW_S   (đang là 0.5, pi_config là 0.3)
  - Key của self.freq_ranges dùng WASTE_PLASTIC/WASTE_GLASS/... từ
    pi_config (giá trị int sẽ tự khớp).
  - Mọi `self.WASTE_*` trong code → đổi sang module-level `WASTE_*`.


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
- INMP441 trả tín hiệu I2S 24-bit signed; pyaudio/sounddevice qua
  ALSA tự chuyển sang float32 — không cần xử lý raw bit.
- noise_threshold (=0.01) cần re-calibrate cho INMP441 — gain khác
  MAX9814. Khuyến nghị: chạy đo nhiễu nền 5s ở môi trường thực và
  set threshold = 3 × RMS nhiễu nền.


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


LIÊN KẾT
--------
- Hằng số dùng chung: [[pi_config]] (WASTE_*, AUDIO_*).
- Output đi tiếp vào: [[pi_classifier_fusion]].
- Trigger từ event: [[pi_communication]] forward KNOCK_DONE →
  [[main_controller]] gọi record_and_classify().


THƯ VIỆN
--------
  pip install numpy scipy sounddevice
  (matplotlib KHÔNG cần cho production — chỉ dùng nếu vẽ phổ debug)
"""

