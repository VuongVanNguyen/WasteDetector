"""
pi_camera_classifier.py — Phân loại loại rác từ ảnh camera

Khác với pi_camera_detector.py (chỉ phát hiện CÓ vật hay không),
module này phân tích NỘI DUNG ảnh để xác định LOẠI vật liệu.

Phương pháp dự kiến:
  - Chụp ảnh tĩnh sau khi gõ (vật đang nằm yên trong ống)
  - Dùng OpenCV: phân tích màu sắc, texture, edge features
  - Hoặc dùng mô hình AI nhẹ (TFLite MobileNet) chạy trên Pi

TODO:
  - class CameraClassifier
    - capture_frame(): chụp 1 ảnh từ camera
    - preprocess(frame): crop, resize, normalize
    - classify(frame) -> (waste_type, confidence)
  - Cân nhắc train model riêng hoặc dùng pre-trained + fine-tune
"""
