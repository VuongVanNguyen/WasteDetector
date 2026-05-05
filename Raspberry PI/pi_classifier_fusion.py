"""
pi_classifier_fusion.py — Kết hợp kết quả âm thanh + camera

Nhận đầu vào từ AudioClassifier và CameraClassifier,
kết hợp 2 nguồn để đưa ra quyết định phân loại cuối cùng.

Chiến lược dự kiến:
  - Weighted voting: audio_weight * audio_result + camera_weight * camera_result
  - Nếu 2 nguồn đồng thuận → confidence cao hơn
  - Nếu 2 nguồn mâu thuẫn → chọn nguồn có confidence cao hơn, hoặc WASTE_NONE

TODO:
  - class ClassifierFusion
    - fuse(audio_type, audio_conf, camera_type, camera_conf)
        -> (final_type, final_confidence)
  - Cho phép điều chỉnh trọng số audio vs camera qua config
"""
