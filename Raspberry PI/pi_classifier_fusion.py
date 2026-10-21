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


GIAO DIỆN LỚP (CLASS INTERFACE)
-------------------------------
class ClassifierFusion:
    def __init__(self,
                 audio_weight: float = AUDIO_WEIGHT,     # 0.4
                 camera_weight: float = CAMERA_WEIGHT,   # 0.6
                 min_confidence: float = MIN_CONFIDENCE,
                 fallback_type: int = FALLBACK_WASTE_TYPE):
        # - Trọng số mặc định ưu tiên CAMERA: model AI đã đo 97% chạy thật
        #   trên Pi, còn ngưỡng FFT chưa calibrate. Ngoài ra audio_conf chỉ
        #   đo độ ĐỒNG THUẬN giữa các lần gõ (3 lần gõ yếu cùng loại vẫn
        #   = 1.0), nên audio nặng ký dễ lấn một camera đang rất chắc.
        #   Đánh giá lại sau khi calibrate cả hai nguồn trên vật thật.
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
    (D1 chỉ tính lần gõ có conf > 0 — tổng bằng 0 thì tỉ lệ không xác định,
    và một type với conf 0 không mang thông tin → rơi xuống D2.)


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


CẤU HÌNH (pi_config.py)
-----------------------
- AUDIO_WEIGHT       = 0.4
- CAMERA_WEIGHT      = 0.6
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

from __future__ import annotations

import logging

from pi_config import (
    WASTE_NONE, WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL, WASTE_NAMES,
    MIN_CONFIDENCE, AUDIO_WEIGHT, CAMERA_WEIGHT, FUSION_BONUS_AGREE,
    FUSION_PENALTY_DISAGREE, AUDIO_PER_KNOCK_MIN_CONF, FALLBACK_WASTE_TYPE,
)

log = logging.getLogger(__name__)

# Thứ tự cố định — cũng là thứ tự phá hòa khi hai nhóm có tổng conf bằng nhau.
_WASTE_TYPES = (WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL)

STRATEGY_AGREE = "AGREE"
STRATEGY_DISAGREE = "DISAGREE"
STRATEGY_AUDIO_ONLY = "AUDIO_ONLY"
STRATEGY_CAMERA_ONLY = "CAMERA_ONLY"
STRATEGY_AUDIO_WEAK = "AUDIO_WEAK"   # Case D1
STRATEGY_FALLBACK = "FALLBACK"       # Case D2 — mic + camera cùng hỏng


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def _group(results) -> tuple[int, float, float]:
    """Nhóm (type, conf) theo type → (type có tổng cao nhất, tổng đó, tổng toàn bộ)."""
    sums = {t: 0.0 for t in _WASTE_TYPES}
    for t, c in results:
        sums[t] += c
    best = max(_WASTE_TYPES, key=lambda t: sums[t])
    return best, sums[best], sum(sums.values())


class ClassifierFusion:
    """Gộp audio (nhiều lần gõ) + camera (1 ảnh) → (final_type, final_conf)."""

    def __init__(self,
                 audio_weight: float = AUDIO_WEIGHT,
                 camera_weight: float = CAMERA_WEIGHT,
                 min_confidence: float = MIN_CONFIDENCE,
                 fallback_type: int = FALLBACK_WASTE_TYPE,
                 bonus_agree: float = FUSION_BONUS_AGREE,
                 penalty_disagree: float = FUSION_PENALTY_DISAGREE,
                 per_knock_min_conf: float = AUDIO_PER_KNOCK_MIN_CONF):
        if fallback_type not in _WASTE_TYPES:
            raise ValueError(f"fallback_type={fallback_type!r} phải là 1 ngăn thật {_WASTE_TYPES}")
        if audio_weight < 0 or camera_weight < 0:
            raise ValueError("audio_weight / camera_weight phải ≥ 0")
        if abs(audio_weight + camera_weight - 1.0) > 1e-6:
            log.warning("[Fusion] audio_weight + camera_weight = %.3f (nên = 1.0)",
                        audio_weight + camera_weight)
        self.audio_weight = float(audio_weight)
        self.camera_weight = float(camera_weight)
        self.min_confidence = float(min_confidence)
        self.fallback_type = fallback_type
        self.bonus_agree = float(bonus_agree)
        self.penalty_disagree = float(penalty_disagree)
        self.per_knock_min_conf = float(per_knock_min_conf)

    @staticmethod
    def _sanitize(results) -> list[tuple[int, float]]:
        """Bỏ type ngoài 1..4 (gồm WASTE_NONE), kẹp conf về [0, 1]."""
        return [(t, _clamp01(c)) for t, c in results if t in _WASTE_TYPES]

    def audio_consensus(self, audio_results) -> tuple[int, float]:
        """Bước 1: gộp nhiều lần gõ → (audio_type, audio_conf); không có gì → NONE."""
        valid = [(t, c) for t, c in self._sanitize(audio_results) if c >= self.per_knock_min_conf]
        if not valid:
            return WASTE_NONE, 0.0
        best, best_sum, total = _group(valid)
        return best, best_sum / total   # total ≥ per_knock_min_conf > 0

    def decide_detailed(self, audio_results, camera_result) -> tuple[int, float, str]:
        """Như decide() nhưng trả thêm strategy (STRATEGY_*) để controller đếm FALLBACK."""
        audio_results = list(audio_results or [])
        audio_type, audio_conf = self.audio_consensus(audio_results)

        cam_type, cam_conf = camera_result if camera_result else (WASTE_NONE, 0.0)
        if cam_type not in _WASTE_TYPES:
            cam_type, cam_conf = WASTE_NONE, 0.0
        cam_conf = _clamp01(cam_conf)

        if audio_type != WASTE_NONE and cam_type != WASTE_NONE:
            if audio_type == cam_type:                                   # Case A
                strategy = STRATEGY_AGREE
                final_type = audio_type
                final_conf = (self.audio_weight * audio_conf + self.camera_weight * cam_conf
                              + self.bonus_agree)
            else:                                                        # Case B
                strategy = STRATEGY_DISAGREE
                audio_score = self.audio_weight * audio_conf
                camera_score = self.camera_weight * cam_conf
                # Hòa → camera (không phụ thuộc chất lượng cú gõ)
                final_type = cam_type if camera_score >= audio_score else audio_type
                final_conf = max(audio_score, camera_score) - self.penalty_disagree
        elif audio_type != WASTE_NONE:                                   # Case C
            strategy = STRATEGY_AUDIO_ONLY
            final_type, final_conf = audio_type, audio_conf * self.audio_weight
        elif cam_type != WASTE_NONE:                                     # Case C
            strategy = STRATEGY_CAMERA_ONLY
            final_type, final_conf = cam_type, cam_conf * self.camera_weight
        else:                                                            # Case D
            weak = [(t, c) for t, c in self._sanitize(audio_results) if c > 0.0]
            if weak:                                                     # D1
                strategy = STRATEGY_AUDIO_WEAK
                final_type, best_sum, total = _group(weak)
                final_conf = (best_sum / total) * self.audio_weight * 0.5
            else:                                                        # D2
                strategy = STRATEGY_FALLBACK
                final_type, final_conf = self.fallback_type, 0.0

        final_conf = _clamp01(final_conf)

        log.info("[Fusion] Audio consensus: %s (conf=%.2f, %d lần gõ)",
                 WASTE_NAMES[audio_type], audio_conf, len(audio_results))
        log.info("[Fusion] Camera:          %s (conf=%.2f)", WASTE_NAMES[cam_type], cam_conf)
        log.log(logging.WARNING if strategy == STRATEGY_FALLBACK else logging.INFO,
                "[Fusion] Strategy:        %s%s", strategy,
                " — mic VÀ camera cùng hỏng" if strategy == STRATEGY_FALLBACK else "")
        log.info("[Fusion] >> Final:        %s (conf=%.2f)%s", WASTE_NAMES[final_type], final_conf,
                 " KHÔNG CHẮC" if final_conf < self.min_confidence else "")
        return final_type, final_conf, strategy

    def decide(self, audio_results, camera_result) -> tuple[int, float]:
        """(final_type ∈ 1..4, final_conf ∈ [0, 1]). Pure — không I/O ngoài log."""
        final_type, final_conf, _ = self.decide_detailed(audio_results, camera_result)
        return final_type, final_conf


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    P, G, R, M, N = WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL, WASTE_NONE
    fusion = ClassifierFusion()

    cases = [
        # (tên, audio_results, camera_result, type mong đợi, strategy mong đợi)
        ("A  đồng thuận",            [(M, .8), (M, .7), (M, .9)], (M, .9),  M, STRATEGY_AGREE),
        ("B  mâu thuẫn, audio thắng", [(G, .9), (G, .8), (G, .9)], (P, .5),  G, STRATEGY_DISAGREE),
        ("B  mâu thuẫn, camera thắng", [(G, .5), (R, .5), (R, .3)], (P, .95), P, STRATEGY_DISAGREE),
        # 3 lần gõ YẾU nhưng đồng thuận → audio_conf = 1.0; camera rất chắc phải thắng
        ("B  gõ yếu đồng thuận vs camera chắc", [(G, .25), (G, .25), (G, .25)], (P, .97), P, STRATEGY_DISAGREE),
        ("C  chỉ audio",             [(R, .6), (R, .5)],          (N, 0.0), R, STRATEGY_AUDIO_ONLY),
        ("C  chỉ camera (mic hỏng)", [],                          (G, .8),  G, STRATEGY_CAMERA_ONLY),
        ("C  audio lọc hết",          [(M, .1), (P, .15)],         (R, .7),  R, STRATEGY_CAMERA_ONLY),
        ("D1 audio yếu",             [(M, .1), (M, .15), (P, .05)], (N, 0.0), M, STRATEGY_AUDIO_WEAK),
        ("D2 không có gì",           [],                          (N, 0.0), FALLBACK_WASTE_TYPE, STRATEGY_FALLBACK),
        ("D2 audio toàn NONE/0",     [(N, .9), (P, 0.0)],         (N, 0.0), FALLBACK_WASTE_TYPE, STRATEGY_FALLBACK),
        ("rác: type lạ, conf > 1",   [(7, .9), (M, 1.7)],         (9, .9),  M, STRATEGY_AUDIO_ONLY),
    ]
    for name, audio, cam, want_type, want_strategy in cases:
        print(f"\n=== {name}")
        t, c, s = fusion.decide_detailed(audio, cam)
        assert t in _WASTE_TYPES, (name, t)
        assert 0.0 <= c <= 1.0, (name, c)
        assert (t, s) == (want_type, want_strategy), (name, t, s, want_type, want_strategy)

    # Hòa điểm → camera. Trọng số 0.5/0.5 để hai điểm bằng nhau đúng tuyệt đối (0.5 × 1.0)
    print("\n=== B  hòa điểm → camera")
    t, _, s = ClassifierFusion(audio_weight=0.5, camera_weight=0.5).decide_detailed([(G, .9)], (P, 1.0))
    assert (t, s) == (P, STRATEGY_DISAGREE), (t, s)

    try:
        ClassifierFusion(fallback_type=WASTE_NONE)
        raise AssertionError("fallback_type=WASTE_NONE phải raise")
    except ValueError:
        pass
    print("\nOK — mọi case đều trả ngăn 1..4, conf ∈ [0, 1].")
