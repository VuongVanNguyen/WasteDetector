"""
main_controller.py — Bộ não điều phối toàn hệ thống WasteDetector

Flow:
  1. ESP32 phát hiện vật (HC-SR04) → push OBJECT_DETECTED
  2. Pi bật đèn, ra lệnh gõ (KNOCK × 3)
  3. Sau mỗi KNOCK_DONE → thu âm + chụp ảnh
  4. Fusion → quyết định waste_type
  5. Ra lệnh ROTATE → chờ ROTATE_DONE
  6. Ra lệnh DISCHARGE → chờ DISCHARGE_DONE
  7. Tắt đèn, cập nhật GUI

Chạy:
  python3 main_controller.py
"""

import time
import threading
from threading import Event

from pi_config import (
    KNOCK_COUNT, MIN_CONFIDENCE, POST_CLASSIFY_DISPLAY_S,
    WASTE_NAMES, WASTE_NONE,
)
from pi_communication import ESP32Comm
from pi_audio_classifier import ESP32AudioClassifier
from pi_camera_classifier import CameraClassifier
from pi_classifier_fusion import ClassifierFusion
from pi_gui_display import WasteSorterGUI


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
        self.gui = WasteSorterGUI()

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
        self.gui.update_status("Đã phát hiện vật thể!", "#FFFF00")
        self.esp32.send_light(True)

        # Gõ + thu âm đồng thời
        audio_results = []
        self._knock_done_events = [Event() for _ in range(KNOCK_COUNT)]

        self.esp32.send_knock(KNOCK_COUNT)

        for i, done_event in enumerate(self._knock_done_events):
            done_event.wait(timeout=5)
            # TODO: trigger AudioClassifier để thu âm ngay sau mỗi lần gõ
            # audio_result = self.audio.record_and_classify()
            # audio_results.append(audio_result)

        # Chụp ảnh
        # cam_result = self.camera_classifier.classify()

        # Fusion
        # waste_type, confidence = self.fusion.decide(audio_results, cam_result)
        waste_type, confidence = WASTE_NONE, 0.0  # placeholder

        if waste_type == WASTE_NONE or confidence < MIN_CONFIDENCE:
            self.gui.update_status("Không nhận diện được", "#FF0000")
            self.esp32.send_light(False)
            time.sleep(2)
            self.gui.reset_display()
            return

        # Xoay ống
        self.gui.update_status("Đang xử lý...", "#FFFF00")
        self._rotate_done_event.clear()
        self.esp32.send_rotate(waste_type)
        self._rotate_done_event.wait(timeout=10)

        # Thả rác
        self._discharge_done_event.clear()
        self.esp32.send_discharge()
        self._discharge_done_event.wait(timeout=5)

        # Hoàn thành
        self.esp32.send_light(False)
        self.gui.update_result(waste_type, confidence)
        self.gui.update_status(f"Phân loại: {WASTE_NAMES[waste_type]}", "#00FF00")
        time.sleep(POST_CLASSIFY_DISPLAY_S)
        self.gui.reset_display()

    def _worker_loop(self):
        while self._running:
            self._object_event.wait()
            self._object_event.clear()
            try:
                self._process_waste()
            except Exception as e:
                print(f"[ERROR] {e}")
                self.gui.update_status(f"Lỗi: {e}", "#FF0000")
                time.sleep(2)
                self.gui.reset_display()

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
            self.gui.run()   # blocking — Tkinter phải chạy trên main thread
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
