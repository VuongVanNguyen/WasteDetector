"""
pi_camera_classifier.py — Phân loại LOẠI rác từ ảnh Pi Camera
================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Đây là **bộ phân loại HÌNH ẢNH** (1 trong 2 nguồn của quyết định cuối).
- KHÔNG dùng để phát hiện vật thể — việc đó do HC-SR04 (qua ESP32) đảm nhiệm.
- Chạy SAU khi ESP32 đã gõ xong (KNOCK_DONE seq==KNOCK_COUNT), lúc vật
  thể đang nằm yên trong ống PVC dưới ánh đèn relay đã bật.
- Output sẽ được gửi vào ClassifierFusion ([[pi_classifier_fusion]]) để
  kết hợp với kết quả âm thanh từ AudioClassifier ([[pi_audio_classifier]]).


YÊU CẦU CHỨC NĂNG
-----------------
1. Khởi tạo camera (Pi Camera qua libcamera/picamera2, fallback USB webcam
   qua OpenCV VideoCapture nếu CAMERA_ID khác None).
2. Chụp 1 frame tĩnh khi được gọi (không stream liên tục — tiết kiệm CPU
   cho task chính trên Pi 4).
3. Tiền xử lý: crop ROI = vùng trong lòng ống PVC, loại bỏ thành ống và
   nền xung quanh. ROI cần được calibrate 1 lần và lưu vào pi_config.
4. Chạy inference → trả về (waste_type, confidence) khớp mã WASTE_* trong
   pi_config (1=Nhựa, 2=Thủy tinh, 3=Giấy, 4=Kim loại; 0 nếu không xác định).
5. Cleanup tài nguyên camera khi shutdown.


GIAO DIỆN LỚP (CLASS INTERFACE) — cần triển khai
------------------------------------------------
class CameraClassifier:
    def __init__(self, camera_id=CAMERA_ID, model_path=None):
        # - Mở camera (picamera2 ưu tiên, fallback cv2.VideoCapture)
        # - Load model TFLite (nếu dùng approach AI)
        # - Load ROI calibration từ file JSON (nếu có)

    def capture_frame(self) -> np.ndarray:
        # - Chụp 1 frame BGR (HxWx3, uint8)
        # - Tự retry tối đa 3 lần nếu frame None/đen
        # - Raise RuntimeError nếu camera fail

    def preprocess(self, frame) -> np.ndarray:
        # - Crop theo ROI (x, y, w, h) đã calibrate
        # - Resize về INPUT_SIZE (vd 224x224 cho MobileNet)
        # - Convert BGR→RGB nếu model train trên RGB
        # - Normalize: float32, [0,1] hoặc [-1,1] tùy model
        # - Thêm batch dim → shape (1, H, W, 3)

    def classify(self, frame=None) -> tuple[int, float]:
        # - Nếu frame=None thì tự capture
        # - preprocess → inference → softmax → argmax
        # - Map class index của model → mã WASTE_* của pi_config
        # - Return (waste_type, confidence ∈ [0,1])
        # - Return (WASTE_NONE, 0.0) nếu confidence < ngưỡng nội bộ

    def close(self):
        # - Giải phóng camera, model interpreter
        # - Được gọi từ main_controller._shutdown()


CHIẾN LƯỢC PHÂN LOẠI — CHỌN 1 TRONG 2
-------------------------------------

[Approach A] AI nhẹ trên TFLite (KHUYẾN NGHỊ — chính xác hơn, đỡ phụ thuộc ánh sáng)
  - Model: MobileNetV2 / EfficientNet-Lite0 quantized INT8
    + Pre-trained trên ImageNet → fine-tune 4 lớp (Nhựa/Thủy tinh/Giấy/Kim loại)
    + Hoặc dùng Teachable Machine của Google export TFLite
  - Dataset: chụp tối thiểu 50-100 ảnh/lớp TRONG CHÍNH ỐNG PVC dưới đèn relay
    (cùng góc, cùng khoảng cách, cùng ánh sáng như khi vận hành thực tế).
    Augmentation: rotation ±15°, brightness ±20%, horizontal flip.
  - Inference: dùng tflite_runtime (nhẹ hơn full TF), 4 threads.
  - Target: < 500ms/inference trên Pi 4 (2GB RAM trở lên).
  - Model size: < 5MB sau quantization.

[Approach B] Cổ điển OpenCV (FALLBACK — không cần train, nhưng kém ổn định)
  - Feature 1 — Color histogram (HSV space):
      Giấy/Carton: nâu/vàng nhạt (H≈20-40, S thấp)
      Nhựa: đa dạng màu, nhưng thường sáng và bão hòa cao
      Thủy tinh: trong suốt → đọc màu nền ống PVC bên dưới
      Kim loại: xám/bạc, S rất thấp, V cao và phản chiếu đèn (specular highlight)
  - Feature 2 — Edge density (Canny):
      Kim loại: ít edge nội bộ, viền sắc nét
      Nhựa: edge trung bình
      Giấy: nhiều edge nhỏ (texture nhăn)
      Thủy tinh: edge cong, có refraction
  - Feature 3 — Specular highlight detection (vùng V>240, S<30):
      Kim loại và thủy tinh có → tăng score 2 lớp này
  - Classifier: rule-based threshold hoặc SVM nhỏ (scikit-learn) train tay


YÊU CẦU KỸ THUẬT / RÀNG BUỘC
-----------------------------
- Phần cứng: Pi 4 (4GB hoặc 8GB khuyến nghị). KHÔNG được block GIL quá lâu
  vì main_controller chạy GUI Tkinter trên main thread.
- Inference phải có timeout — nếu > 2s thì abort và trả (WASTE_NONE, 0.0).
- Ánh sáng: relay đèn LED của ESP32 bật trước khi gọi classify(), nên
  có thể giả định ánh sáng ỔN ĐỊNH. KHÔNG cần auto white balance phức tạp.
- ROI calibration: lưu vào file `camera_roi.json` cùng thư mục, format:
      {"x": int, "y": int, "w": int, "h": int}
  Cung cấp tool calibrate riêng (__main__ block) để người dùng vẽ ROI bằng
  chuột trên 1 ảnh mẫu rồi save.
- Confidence trả về phải SO SÁNH ĐƯỢC với confidence của AudioClassifier
  (cùng thang [0,1]) để ClassifierFusion fusion đúng.
- Ngưỡng confidence nội bộ tối thiểu (suggested): 0.4. Dưới ngưỡng → NONE.
- Mã waste_type phải khớp đúng pi_config.WASTE_* — KHÔNG được tự định
  nghĩa lại constants. Import từ pi_config.


TEST ĐỘC LẬP (__main__ block)
-----------------------------
- Mode 1: capture & classify 1 ảnh, in kết quả + confidence.
- Mode 2: ROI calibration tool (hiển thị ảnh, kéo chuột chọn vùng, save JSON).
- Mode 3: thu thập dataset (chụp N ảnh cho 1 class, lưu vào folder tương ứng).


THƯ VIỆN PHỤ THUỘC (thêm vào requirements.txt nếu chưa có)
----------------------------------------------------------
- picamera2 (Pi Camera) HOẶC opencv-python (USB webcam)
- tflite-runtime  (nếu chọn Approach A)
- numpy
- (tùy chọn) scikit-learn cho Approach B với SVM
"""
