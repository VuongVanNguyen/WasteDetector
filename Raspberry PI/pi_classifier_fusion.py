"""
pi_classifier_fusion.py — Tổng hợp kết quả Audio + Camera → quyết định cuối
=============================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Là bộ ra quyết định CUỐI CÙNG về waste_type trước khi Pi gửi lệnh
  ROTATE xuống ESP32.
- Nhận đầu vào từ 2 nguồn:
    1) AudioClassifier — KNOCK_COUNT (=3) lần gõ → 3 cặp (type, conf)
    2) CameraClassifier — 1 ảnh tĩnh sau gõ → 1 cặp (type, conf)
- Output: 1 cặp (final_type, final_confidence) duy nhất.
  final_type LUÔN là 1 ngăn thật (1..4), KHÔNG BAO GIỜ WASTE_NONE — xem
  "CHÍNH SÁCH: LUÔN XẢ".
- Được gọi 1 lần / 1 vật thể trong main_controller._process_waste().


CHÍNH SÁCH: LUÔN XẢ VÀO NGĂN KHẢ NĂNG NHẤT
------------------------------------------
Vật không được xả thì nằm lại trong ống → ESP32 không bao giờ push READY
→ máy KẸT, phải có người can thiệp. Một vật vào sai ngăn còn đỡ hơn cả
máy đứng. Hai nguồn độc lập bù cho nhau (audio hỏng thì còn camera, và
ngược lại), nên gần như luôn có một phán đoán để dùng.
  - final_confidence chỉ để BÁO độ chắc chắn (log). Dưới
    min_confidence → main_controller VẪN xả, chỉ đánh dấu "không chắc chắn".
  - fallback_type chỉ dùng khi KHÔNG còn chút thông tin nào (Case D).


GIAO DIỆN LỚP (CLASS INTERFACE) — cần triển khai
------------------------------------------------
class ClassifierFusion:
    def __init__(self,
                 audio_weight: float = 0.6,
                 camera_weight: float = 0.4,
                 min_confidence: float = MIN_CONFIDENCE,
                 fallback_type: int = FALLBACK_WASTE_TYPE):
        # - Trọng số mặc định ưu tiên audio NHẸ (vì gõ 3 lần độc lập,
        #   tổng hợp đã ổn định hơn). Có thể đảo lại sau khi calibrate
        #   thực tế và đánh giá độ chính xác từng nguồn.
        # - Tổng audio_weight + camera_weight nên = 1.0.
        # - fallback_type phải ∈ {WASTE_PLASTIC..WASTE_METAL} — raise
        #   ValueError ngay trong __init__ nếu không.

    def decide(self,
               audio_results: list[tuple[int, float]],
               camera_result: tuple[int, float]
               ) -> tuple[int, float]:
        # - audio_results: [(type, conf), (type, conf), (type, conf)]
        #   có thể thiếu nếu vài lần gõ không thu được âm (audio fail).
        # - camera_result: (type, conf), có thể là (WASTE_NONE, 0.0) nếu
        #   camera fail.
        # - Trả về (final_type, final_confidence), final_type ∈ 1..4.
        # - final_confidence < min_confidence → main_controller VẪN xả vào
        #   final_type, chỉ log "không chắc chắn".


THUẬT TOÁN FUSION — KHUYẾN NGHỊ
-------------------------------

Bước 1 — Tổng hợp nhiều lần gõ thành 1 "audio_consensus":
  - Lọc bỏ kết quả có conf < 0.2 (xem như nhiễu).
  - Nhóm các lần gõ theo waste_type.
  - Mỗi nhóm tính tổng confidence = sum(conf) của các lần thuộc nhóm đó.
  - audio_type = nhóm có tổng cao nhất.
  - audio_conf = (tổng cao nhất) / (tổng toàn bộ conf hợp lệ).
        → giá trị ∈ [0,1], cao khi các lần gõ đồng thuận.
  - Trường hợp đặc biệt: không có lần gõ nào conf ≥ 0.2 → trả về
    (WASTE_NONE, 0.0) cho audio_consensus. (Các lần gõ yếu bị lọc ở đây
    KHÔNG bị vứt hẳn — Case D còn dùng lại.)

Bước 2 — So khớp camera vs audio:

  Case A — audio và camera ĐỒNG THUẬN (audio_type == camera_type):
    final_type = chung
    final_conf = audio_weight * audio_conf + camera_weight * camera_conf
                 + bonus_agree   (bonus_agree ≈ 0.1, clamp ≤ 1.0)
    → Đây là kịch bản tự tin nhất.

  Case B — audio và camera MÂU THUẪN (cả 2 đều khác WASTE_NONE, bất kể
  conf cao hay thấp):
    audio_score  = audio_weight  * audio_conf
    camera_score = camera_weight * camera_conf
    Chọn nguồn có score cao hơn. Hòa → chọn camera (không phụ thuộc chất
    lượng cú gõ).
    final_conf = max(audio_score, camera_score)
                 - penalty_disagree   (penalty ≈ 0.15, clamp ≥ 0)
    → Trừ confidence vì có mâu thuẫn — vẫn xả, nhưng thường rơi vào
       vùng "không chắc chắn".

  Case C — 1 nguồn fail (= WASTE_NONE):
    Dùng nguồn còn lại NHƯNG nhân conf với weight tương ứng:
        Nếu chỉ có audio:  (audio_type, audio_conf * audio_weight)
        Nếu chỉ có camera: (camera_type, camera_conf * camera_weight)
    → Phản ánh việc thiếu 1 nguồn dữ liệu → ít tin cậy hơn.
    → Đây là "cứu cánh camera": mic hỏng / gõ trượt cả 3 lần vẫn phân
       loại được.

  Case D — Cả 2 nguồn fail (audio_consensus NONE VÀ camera NONE):
    D1. Còn lần gõ nào type != WASTE_NONE (kể cả conf < 0.2 đã bị lọc ở
        Bước 1) → nhóm theo type, lấy type có tổng conf cao nhất:
            (type, (tổng_cao_nhất / tổng_toàn_bộ) * audio_weight * 0.5)
                                 ← × 0.5: tín hiệu yếu, luôn "không chắc"
    D2. Không có gì → (fallback_type, 0.0).
    → KHÔNG trả WASTE_NONE.


RÀNG BUỘC / NGUYÊN TẮC
----------------------
- TUYỆT ĐỐI dùng các hằng số WASTE_* từ pi_config, không tự định nghĩa lại.
- Output final_confidence phải nằm trong [0.0, 1.0] (clamp 2 đầu).
- Hàm decide() phải pure (không I/O, không side effect, không sleep) — để
  có thể unit test dễ dàng và không block worker thread.
- KHÔNG BAO GIỜ trả WASTE_NONE — xem "CHÍNH SÁCH: LUÔN XẢ".
- Log chi tiết breakdown (logging, kiểu giống AudioClassifier) để
  debug/calibrate sau này:
      [Fusion] Audio consensus: <name> (conf=...)
      [Fusion] Camera:          <name> (conf=...)
      [Fusion] Strategy:        AGREE / DISAGREE / AUDIO_ONLY / CAMERA_ONLY
                                / AUDIO_WEAK (D1) / FALLBACK (D2)
      [Fusion] >> Final:        <name> (conf=...) [+ "KHÔNG CHẮC" nếu < min_confidence]
  FALLBACK nghĩa là cả mic lẫn camera cùng hỏng → log mức WARNING.


CẤU HÌNH (đề xuất thêm vào pi_config.py)
----------------------------------------
- AUDIO_WEIGHT       = 0.6
- CAMERA_WEIGHT      = 0.4
- FUSION_BONUS_AGREE = 0.10
- FUSION_PENALTY_DISAGREE = 0.15
- AUDIO_PER_KNOCK_MIN_CONF = 0.20   # ngưỡng loại nhiễu khi gộp nhiều lần gõ
- FALLBACK_WASTE_TYPE = WASTE_GLASS # Case D2. Thủy tinh = HOME: không quay
                                    # ống → nhanh nhất, không mòn cơ cấu,
                                    # không có rủi ro xoắn dây khi hệ đang
                                    # có vấn đề (mic + camera cùng hỏng).


TEST ĐỘC LẬP (__main__ block)
-----------------------------
- Hard-code vài bộ input giả lập cho các case A/B/C/D1/D2 ở trên và in
  kết quả. Assert: final_type luôn ∈ 1..4, final_conf ∈ [0, 1].
- Mục đích: kiểm tra logic mà không cần phần cứng.
- Không cần kết nối camera/audio/ESP32.
"""
