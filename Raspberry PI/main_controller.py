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
  6. send_rotate(waste_type) → chờ ROTATE_DONE (timeout 10s).
     Rác Thủy tinh: ngăn xả = HOME, ESP32 không quay, vẫn trả ROTATE_DONE.
  7. send_discharge() → chờ DISCHARGE_DONE (timeout 5s).
     → log kết quả ngay (cửa đã đóng).
  8. ESP32 TỰ quay về HOME rồi push READY — Pi KHÔNG ra lệnh HOME.
     Chờ READY (timeout ~15s) trước khi coi chu kỳ là xong.
     DISCHARGE_DONE KHÔNG phải "xong chu kỳ".


XỬ LÝ EVENT TỪ ESP32 (_on_esp32_event — reader thread)
------------------------------------------------------
  OBJECT_DETECTED  → _object_event.set()
  KNOCK_DONE       → _knock_done_events[seq-1].set()  (bỏ qua seq ngoài khoảng)
  ROTATE_DONE      → _rotate_done_event.set()
  DISCHARGE_DONE   → _discharge_done_event.set()
  READY            → _ready_event.set()               ← CHƯA CÓ, cần thêm
  ERROR            → lưu code (vd self._last_error) + set một Event lỗi để
                     worker đang chờ ROTATE/DISCHARGE/READY thức dậy ngay,
                     không phải đợi hết timeout.

  Mã lỗi:
    MOTOR_TIMEOUT / HOME_FAILED — lỗi nhất thời: hủy chu kỳ, log lỗi. Không
        tự gửi lại ROTATE. ESP32 tự chốt FAULT sau 2 lỗi liên tiếp.
    MOTION_FAULT — CHỐT: engine từ chối mọi lệnh quay cho tới khi có người
        tháo xoắn dây và mở khóa. Pi phải DỪNG HẲN (không nhận chu kỳ mới),
        log lỗi ở mức ERROR, và KHÔNG BAO GIỜ tự thử lại / gửi HOME
        — thử lại chính là thứ cuốn đứt dây.
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

import threading
from threading import Event

from pi_config import (
    KNOCK_COUNT, MIN_CONFIDENCE,
    WASTE_NAMES, WASTE_NONE,
)
from pi_communication import ESP32Comm
from pi_audio_classifier import ESP32AudioClassifier
from pi_camera_classifier import CameraClassifier
from pi_classifier_fusion import ClassifierFusion


class WasteDetectorSystem:
    """Điều phối toàn bộ flow phân loại rác."""

    def __init__(self):
        self._knock_done_events: list[Event] = []
        self._rotate_done_event = Event()
        self._discharge_done_event = Event()
        self._object_event = Event()

        self.esp32 = ESP32Comm(on_event=self._on_esp32_event)
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
            seq = event.get("seq", 1) - 1
            if 0 <= seq < len(self._knock_done_events):
                self._knock_done_events[seq].set()

        elif name == "ROTATE_DONE":
            self._rotate_done_event.set()

        elif name == "DISCHARGE_DONE":
            self._discharge_done_event.set()

        elif name == "ERROR":
            code = event.get("code", "UNKNOWN")
            print(f"[ESP32] ERROR: {code}")

    # ----------------------------------------------------------
    # Main processing loop
    # ----------------------------------------------------------

    def _process_waste(self):
        """Xử lý 1 vật thể từ đầu đến cuối."""
        print("[System] Đã phát hiện vật thể")

        # Gõ + thu âm LIÊN TỤC cả chuỗi — xem spec bước 2 đầu file
        audio_results = []
        self._knock_done_events = [Event() for _ in range(KNOCK_COUNT)]

        # TODO: audio_ok = self.audio.start_sequence(KNOCK_COUNT)  ← TRƯỚC send_knock
        self.esp32.send_knock(KNOCK_COUNT)

        for i, done_event in enumerate(self._knock_done_events):
            done_event.wait(timeout=5)
        # TODO: chỉ chờ Event lần gõ cuối, rồi (kể cả khi timeout):
        # audio_results = self.audio.finish_sequence() if audio_ok else []

        # Chụp ảnh
        # cam_result = self.camera_classifier.classify()

        # Fusion
        # waste_type, confidence = self.fusion.decide(audio_results, cam_result)
        waste_type, confidence = WASTE_NONE, 0.0  # placeholder

        # TODO: LỖI THỜI — bỏ nhánh này. Không bao giờ giữ vật lại trong ống;
        # confidence thấp vẫn xả, chỉ đánh dấu "không chắc chắn" (spec bước 5).
        if waste_type == WASTE_NONE or confidence < MIN_CONFIDENCE:
            print("[System] Không nhận diện được")
            return

        # Xoay ống
        self._rotate_done_event.clear()
        self.esp32.send_rotate(waste_type)
        self._rotate_done_event.wait(timeout=10)

        # Thả rác
        self._discharge_done_event.clear()
        self.esp32.send_discharge()
        self._discharge_done_event.wait(timeout=5)

        # Hoàn thành
        print(f"[System] Phân loại: {WASTE_NAMES[waste_type]} "
              f"(độ tin cậy {confidence:.1%})")

    def _worker_loop(self):
        while self._running:
            self._object_event.wait()
            self._object_event.clear()
            try:
                self._process_waste()
            except Exception as e:
                print(f"[ERROR] {e}")

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def run(self):
        self._running = True

        print("=" * 50)
        print("  MÁY PHÂN LOẠI RÁC THÔNG MINH")
        print("  Khởi tạo hệ thống...")
        print("=" * 50)

        if not self.esp32.connect():
            print("[WARN] Không kết nối được ESP32 — chạy ở chế độ hạn chế")

        worker = threading.Thread(target=self._worker_loop, daemon=True)
        worker.start()

        print("\n✓ Hệ thống sẵn sàng. Bỏ rác vào ống để bắt đầu.\n")

        try:
            # join có timeout để Ctrl+C (KeyboardInterrupt) vẫn tới được main thread
            while worker.is_alive():
                worker.join(timeout=1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _shutdown(self):
        self._running = False
        self.esp32.disconnect()
        print("[System] Đã tắt.")


if __name__ == "__main__":
    WasteDetectorSystem().run()
