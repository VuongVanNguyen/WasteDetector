"""
main_controller.py — Bộ não điều phối toàn hệ thống WasteDetector
==================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Điều phối 1 chu kỳ / 1 vật thể: ESP32 (cơ cấu) ↔ audio + camera
  (phân loại) → fusion (quyết định). Không có màn hình — trạng thái và
  kết quả chỉ ra log (stdout).
- 3 thread:
    Main thread   — chỉ giữ process sống, chờ Ctrl+C rồi _shutdown().
    Reader thread — pi_communication, gọi _on_esp32_event(). Handler CHỈ
                    set threading.Event / lưu dữ liệu, không làm việc nặng.
    Worker thread — _worker_loop → _process_waste(). Mọi lệnh blocking
                    (thu âm, chụp ảnh, chờ event) chạy ở đây.


FLOW 1 CHU KỲ (_process_waste) — đồng bộ với CLAUDE.md
------------------------------------------------------
  1. ESP32 phát hiện vật (HC-SR04) → push OBJECT_DETECTED.
     ESP32 TỰ chặn OBJECT_DETECTED cho tới READY kế tiếp → không bao giờ có
     2 chu kỳ chồng nhau, Pi không cần tự giữ cờ "đang bận".
  2. Gõ + thu âm LIÊN TỤC (xem pi_audio_classifier — "VÌ SAO KHÔNG THU
     SAU MỖI KNOCK_DONE"):
       a. Tạo mới _knock_done_events (KNOCK_COUNT Event) TRƯỚC khi gửi lệnh.
       b. audio_ok = self.audio.start_sequence(KNOCK_COUNT)   ← TRƯỚC send_knock
       c. self.esp32.send_knock(KNOCK_COUNT)
       d. Chỉ chờ Event của lần gõ CUỐI (seq == KNOCK_COUNT), timeout
          KNOCK_COUNT × KNOCK_INTERVAL_S + AUDIO_SEQUENCE_MARGIN_S + biên UART
          (~1s). Không thu/xử lý gì ở các KNOCK_DONE giữa chừng.
       e. audio_results = self.audio.finish_sequence() if audio_ok else []
          GỌI CẢ KHI TIMEOUT — buffer đã tự dừng khi đầy, dữ liệu vẫn dùng
          được. Kết quả có thể ngắn hơn KNOCK_COUNT (gõ trượt) hoặc [].
     Nếu chu kỳ bị hủy giữa b và e (exception) → self.audio.abort_sequence().
  3. cam_result = self.camera_classifier.classify()
     SAU khi gõ xong — vật nằm yên. CameraClassifier tự bật LED chỉ trong
     lúc chụp (Pi GPIO, không qua ESP32). Lỗi → (WASTE_NONE, 0.0).
  4. waste_type, confidence = self.fusion.decide(audio_results, cam_result)
     waste_type LUÔN là ngăn thật 1..4 (fusion không trả WASTE_NONE).
  5. confidence < MIN_CONFIDENCE → VẪN tiếp tục bước 6, chỉ đánh dấu
     uncertain=True (log WARNING "Không chắc chắn — xả vào <ngăn>").
     Xem mục "VẬT KHÔNG NHẬN DIỆN ĐƯỢC".
  6. send_rotate(waste_type) → chờ ROTATE_DONE (ROTATE_TIMEOUT_S).
     Rác Thủy tinh: ngăn xả = HOME, ESP32 không quay, vẫn trả ROTATE_DONE.
  7. send_discharge() → chờ DISCHARGE_DONE (DISCHARGE_TIMEOUT_S).
     → log kết quả ngay (cửa đã đóng).
  8. ESP32 TỰ quay về HOME rồi push READY — Pi KHÔNG ra lệnh HOME.
     Chờ READY (READY_TIMEOUT_S) trước khi coi chu kỳ là xong.
     DISCHARGE_DONE KHÔNG phải "xong chu kỳ".
  Timeout ROTATE/READY là 30s, không phải 10-15s: ESP32 LUÔN trả lời (DONE
  hoặc ERROR), timeout chỉ bắt mất UART — xem chú thích trong pi_config.


XỬ LÝ EVENT TỪ ESP32 (_on_esp32_event — reader thread)
------------------------------------------------------
  OBJECT_DETECTED  → _object_event.set()
  KNOCK_DONE       → _knock_done_events[seq-1].set()  (bỏ qua seq ngoài khoảng)
  ROTATE_DONE      → _rotate_done_event.set()
  DISCHARGE_DONE   → _discharge_done_event.set()
  READY            → _ready_event.set(); gỡ chốt FAULT phía Pi (xem dưới)
  ERROR            → lưu code (self._last_error) + set _error_event để
                     worker đang chờ ROTATE/DISCHARGE/READY thức dậy ngay,
                     không phải đợi hết timeout.

  Mã lỗi:
    MOTOR_TIMEOUT / HOME_FAILED — lỗi nhất thời: hủy chu kỳ, log lỗi. Không
        tự gửi lại ROTATE. ESP32 tự chốt FAULT sau 2 lỗi liên tiếp.
    MOTION_FAULT — CHỐT: engine từ chối mọi lệnh quay cho tới khi có người
        tháo xoắn dây và mở khóa. Pi phải DỪNG HẲN (không nhận chu kỳ mới),
        log lỗi ở mức ERROR, và KHÔNG BAO GIỜ tự thử lại / gửi HOME
        — thử lại chính là thứ cuốn đứt dây.
        Chốt phía Pi chỉ gỡ khi ESP32 push READY: ESP32 chỉ push READY khi
        về HOME THÀNH CÔNG, mà engine đang FAULT thì từ chối quay — tức READY
        chỉ có thể đến sau khi người đã gỡ chốt (jog + 'f', hoặc quay tay về
        Thủy tinh rồi reset). Pi không gửi gì trong suốt quá trình đó.
    INVALID_CMD — lỗi lập trình phía Pi: log, hủy chu kỳ.


VẬT KHÔNG NHẬN DIỆN ĐƯỢC — LUÔN XẢ VÀO NGĂN KHẢ NĂNG NHẤT
---------------------------------------------------------
Vật không xả thì nằm lại trong ống → ESP32 không bao giờ push READY →
máy kẹt ở trạng thái chặn OBJECT_DETECTED. Vì vậy:
  - KHÔNG có nhánh "bỏ qua, không xoay ống". Mọi chu kỳ phân loại xong
    đều ROTATE + DISCHARGE vào waste_type của fusion, dù confidence thấp.
  - Ngăn "khả năng nhất" do fusion chọn (Case B/C/D1 — audio hỏng thì
    camera bù và ngược lại). Chỉ khi CẢ mic lẫn camera cùng hỏng mới dùng
    FALLBACK_WASTE_TYPE (= Thủy tinh/HOME, không quay ống).
  - Đếm số lần FALLBACK liên tiếp; ≥ 2 → log cảnh báo "Kiểm tra
    mic/camera" (vẫn xả, nhưng phải có người xem).

Ngoại lệ DUY NHẤT vật được phép nằm lại trong ống: lỗi CƠ CẤU (ERROR khi
chờ ROTATE_DONE / DISCHARGE_DONE / READY). Khi đó vị trí ống không còn
chắc chắn → KHÔNG gửi DISCHARGE (vật có thể rơi ra ngoài ngăn), log
cần người. Lỗi cơ cấu đằng nào cũng cần người — ESP32 tự chốt FAULT sau 2
lần lỗi liên tiếp.


RÀNG BUỘC
---------
- Mọi Event chờ phải clear()/tạo mới TRƯỚC khi gửi lệnh tương ứng, không
  phải sau — event có thể về trước khi worker kịp clear.
- Exception trong 1 chu kỳ không được giết worker (_worker_loop đã bọc
  try/except); nhưng nhánh except phải abort_sequence().
- _shutdown(): abort_sequence(), camera_classifier.close(), esp32.disconnect().


Chạy:
  python3 main_controller.py
"""

from __future__ import annotations

import logging
import threading
import time
from threading import Event

from pi_config import (
    KNOCK_COUNT, KNOCK_INTERVAL_S, AUDIO_SEQUENCE_MARGIN_S, MIN_CONFIDENCE,
    ROTATE_TIMEOUT_S, DISCHARGE_TIMEOUT_S, READY_TIMEOUT_S,
    WASTE_NAMES,
)
from pi_communication import ESP32Comm
from pi_audio_classifier import ESP32AudioClassifier
from pi_camera_classifier import CameraClassifier
from pi_classifier_fusion import ClassifierFusion, STRATEGY_FALLBACK

log = logging.getLogger("main")

# Chờ KNOCK_DONE cuối: cả chuỗi gõ + đuôi thu âm + ~1s biên UART (spec bước 2d)
_KNOCK_TIMEOUT_S = KNOCK_COUNT * KNOCK_INTERVAL_S + AUDIO_SEQUENCE_MARGIN_S + 1.0
_FALLBACK_ALERT_STREAK = 2   # FALLBACK liên tiếp từ lần này → cảnh báo kiểm tra mic/camera


class MechanicalError(Exception):
    """ESP32 báo ERROR / im lặng quá timeout khi chờ ROTATE / DISCHARGE / READY."""


class WasteDetectorSystem:
    """Điều phối toàn bộ flow phân loại rác."""

    def __init__(self):
        self._running = False
        self._worker: threading.Thread | None = None

        self._knock_done_events: list[Event] = []
        self._rotate_done_event = Event()
        self._discharge_done_event = Event()
        self._ready_event = Event()
        self._error_event = Event()
        self._object_event = Event()
        self._last_error: str | None = None
        self._faulted = False          # ESP32 đã báo MOTION_FAULT — xem docstring
        self._fallback_streak = 0

        self.esp32 = ESP32Comm()
        self.esp32.on_event = self._on_esp32_event
        self.audio = ESP32AudioClassifier()
        self.camera_classifier = CameraClassifier()
        self.fusion = ClassifierFusion()

    # ----------------------------------------------------------
    # ESP32 event handler (called from reader thread)
    # ----------------------------------------------------------

    def _on_esp32_event(self, event: dict):
        name = event.get("event")

        if name == "OBJECT_DETECTED":
            self._object_event.set()

        elif name == "KNOCK_DONE":
            seq = event.get("seq")
            events = self._knock_done_events
            if isinstance(seq, int) and 1 <= seq <= len(events):
                events[seq - 1].set()

        elif name == "ROTATE_DONE":
            self._rotate_done_event.set()

        elif name == "DISCHARGE_DONE":
            self._discharge_done_event.set()

        elif name == "READY":
            if self._faulted:
                log.warning("[ESP32] READY sau MOTION_FAULT — ESP32 đã được gỡ chốt, nhận vật trở lại")
                self._faulted = False
            self._ready_event.set()

        elif name == "ERROR":
            code = str(event.get("code", "UNKNOWN"))
            self._last_error = code
            if code == "MOTION_FAULT":
                self._faulted = True
                log.error("[ESP32] MOTION_FAULT — engine quay đã KHÓA. Cần người: tháo xoắn dây "
                          "rồi gỡ chốt. Pi ngừng nhận chu kỳ mới và KHÔNG tự thử lại.")
            else:
                log.error("[ESP32] ERROR: %s", code)
            self._error_event.set()

    # ----------------------------------------------------------
    # Chờ ESP32
    # ----------------------------------------------------------

    def _arm(self, *events: Event):
        """Xóa event chờ + lỗi cũ. Gọi TRƯỚC khi gửi lệnh — event có thể về rất nhanh."""
        self._last_error = None
        self._error_event.clear()
        for e in events:
            e.clear()

    def _wait_esp32(self, done: Event, timeout_s: float, what: str):
        """Chờ `done`; ERROR từ ESP32 hoặc hết giờ → MechanicalError ngay."""
        deadline = time.monotonic() + timeout_s
        while not done.is_set():
            if self._error_event.is_set():
                raise MechanicalError(f"ESP32 báo {self._last_error} khi chờ {what}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MechanicalError(f"không nhận {what} sau {timeout_s:.0f}s (mất UART?)")
            done.wait(min(0.05, remaining))

    # ----------------------------------------------------------
    # Main processing loop
    # ----------------------------------------------------------

    def _process_waste(self):
        """Xử lý 1 vật thể từ đầu đến cuối — spec "FLOW 1 CHU KỲ" đầu file."""
        t_start = time.monotonic()
        log.info("[System] Phát hiện vật thể — bắt đầu chu kỳ")

        # 2. Gõ + thu âm LIÊN TỤC cả chuỗi
        self._knock_done_events = [Event() for _ in range(KNOCK_COUNT)]
        audio_ok = self.audio.start_sequence(KNOCK_COUNT)      # TRƯỚC send_knock
        if not audio_ok:
            log.warning("[System] Không mở được mic — phân loại chỉ bằng camera")
        try:
            self.esp32.send_knock(KNOCK_COUNT)
            if not self._knock_done_events[-1].wait(timeout=_KNOCK_TIMEOUT_S):
                log.warning("[System] Không nhận KNOCK_DONE %d/%d sau %.1fs — dùng phần âm thanh đã thu",
                            KNOCK_COUNT, KNOCK_COUNT, _KNOCK_TIMEOUT_S)
            audio_results = self.audio.finish_sequence() if audio_ok else []   # cả khi timeout
        except BaseException:
            self.audio.abort_sequence()
            raise

        # 3. Camera — vật đã nằm yên; LED chỉ sáng lúc chụp
        cam_result = self.camera_classifier.classify()

        # 4. Fusion — luôn ra 1 ngăn thật
        waste_type, confidence, strategy = self.fusion.decide_detailed(audio_results, cam_result)
        if strategy == STRATEGY_FALLBACK:
            self._fallback_streak += 1
            if self._fallback_streak >= _FALLBACK_ALERT_STREAK:
                log.warning("[System] %d chu kỳ liên tiếp mic VÀ camera cùng hỏng — kiểm tra mic/camera",
                            self._fallback_streak)
        else:
            self._fallback_streak = 0

        # 5. Không chắc chắn vẫn xả — vật nằm lại trong ống là máy kẹt
        uncertain = confidence < MIN_CONFIDENCE
        if uncertain:
            log.warning("[System] Không chắc chắn (%.0f%%) — vẫn xả vào %s",
                        confidence * 100, WASTE_NAMES[waste_type])

        # 6. Xoay ống. Lỗi ở đây → KHÔNG xả: vị trí ống không chắc, vật có thể rơi ngoài ngăn
        if self._faulted:
            raise MechanicalError("ESP32 đang MOTION_FAULT — không gửi ROTATE, vật còn trong ống")
        self._arm(self._rotate_done_event)
        self.esp32.send_rotate(waste_type)
        try:
            self._wait_esp32(self._rotate_done_event, ROTATE_TIMEOUT_S, "ROTATE_DONE")
        except MechanicalError as e:
            raise MechanicalError(f"{e} — KHÔNG xả, vật còn trong ống") from None

        # 7. Xả. READY cũng phải clear TRƯỚC lệnh này: ESP32 push READY ngay sau DISCHARGE_DONE
        self._arm(self._discharge_done_event, self._ready_event)
        self.esp32.send_discharge()
        self._wait_esp32(self._discharge_done_event, DISCHARGE_TIMEOUT_S, "DISCHARGE_DONE")
        log.info("[System] Đã xả: %s (độ tin cậy %.0f%%%s, %s)", WASTE_NAMES[waste_type],
                 confidence * 100, ", KHÔNG CHẮC" if uncertain else "", strategy)

        # 8. ESP32 tự về HOME → READY. DISCHARGE_DONE chưa phải xong chu kỳ.
        try:
            self._wait_esp32(self._ready_event, READY_TIMEOUT_S, "READY")
        except MechanicalError as e:
            raise MechanicalError(f"{e} — vật ĐÃ xả, nhưng ống chưa về HOME") from None
        log.info("[System] Chu kỳ xong (%.1fs) — sẵn sàng vật tiếp theo", time.monotonic() - t_start)

    def _worker_loop(self):
        while self._running:
            if not self._object_event.wait(timeout=0.5):
                continue
            self._object_event.clear()
            if self._faulted:
                log.error("[System] Bỏ qua vật mới: ESP32 đang MOTION_FAULT — cần người gỡ chốt")
                continue
            try:
                self._process_waste()
            except MechanicalError as e:
                log.error("[System] LỖI CƠ CẤU: %s. Hủy chu kỳ — cần người kiểm tra.", e)
            except Exception:
                log.exception("[System] Lỗi không mong đợi — hủy chu kỳ")
                self.audio.abort_sequence()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def run(self):
        self._running = True

        log.info("=" * 50)
        log.info("  MÁY PHÂN LOẠI RÁC THÔNG MINH")
        log.info("=" * 50)

        if not self.esp32.connect():
            log.warning("[System] Không kết nối được ESP32 — chạy ở chế độ hạn chế")
        if not self.camera_classifier.available:
            log.warning("[System] Camera classifier KHÔNG khả dụng — phân loại chỉ bằng âm thanh")

        self._worker = threading.Thread(target=self._worker_loop, name="worker", daemon=True)
        self._worker.start()

        log.info("✓ Hệ thống sẵn sàng. Bỏ rác vào ống để bắt đầu.")

        try:
            # join có timeout để Ctrl+C (KeyboardInterrupt) vẫn tới được main thread
            while self._worker.is_alive():
                self._worker.join(timeout=1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _shutdown(self):
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=2.0)   # chu kỳ đang chạy dở thì không chờ hết
        for name, fn in (("audio", self.audio.abort_sequence),
                         ("camera", self.camera_classifier.close),
                         ("esp32", self.esp32.disconnect)):
            try:
                fn()
            except Exception as e:
                log.error("[System] Lỗi khi tắt %s: %s", name, e)
        log.info("[System] Đã tắt.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    WasteDetectorSystem().run()
