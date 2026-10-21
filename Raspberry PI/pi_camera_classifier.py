"""
pi_camera_classifier.py — Phân loại LOẠI rác từ ảnh Pi Camera
================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Đây là **bộ phân loại HÌNH ẢNH** (1 trong 2 nguồn của quyết định cuối).
- KHÔNG dùng để phát hiện vật thể — việc đó do HC-SR04 (qua ESP32) đảm nhiệm.
- Chạy SAU khi ESP32 đã gõ xong (KNOCK_DONE seq==KNOCK_COUNT), lúc vật
  thể đang nằm yên trong ống PVC.
- Output gửi vào ClassifierFusion ([[pi_classifier_fusion]]) để kết hợp với
  kết quả âm thanh từ AudioClassifier ([[pi_audio_classifier]]).


MODEL: YOLO26n-cls (OpenVINO) — xem [[pi_yolo_classifier]]
----------------------------------------------------------
- 5 lớp CARTON / GLASS / HDPE / METAL / PET → 4 mã WASTE_* qua
  CAMERA_CLASS_MAP (pi_config). Nhựa = HDPE + PET: xác suất CỘNG lại, rồi
  mới argmax trên 4 mã — vật "HDPE 0.35 / PET 0.30 / GLASS 0.35" là Nhựa
  0.65, không phải Thủy tinh.
- ⚠️ Độ chính xác 97% đo trên dataset MPEC, KHÔNG phải ảnh chụp trong ống
  PVC dưới LED 1W. Ảnh vận hành khác hẳn (nền ống, góc chụp, ánh sáng) →
  phải thu dataset trong ống (Mode 3) và fine-tune lại trước khi tin con số.


LUỒNG 1 LẦN classify()
----------------------
  1. picamera2: start camera (khi CHƯA bật LED) → bật LED, chờ settle →
     capture_request(flush=True): chỉ nhận frame BẮT ĐẦU phơi sáng sau lúc
     gọi, tức chắc chắn trọn dưới LED → tắt LED → stop camera.
     Không stream liên tục giữa các chu kỳ (tiết kiệm CPU/nhiệt cho Pi 4).
     Frame đen / lỗi → chụp lại, tối đa CAMERA_CAPTURE_RETRIES lần.
  2. Cắt ROI (camera_roi.json) — vùng lòng ống, bỏ thành ống/nền.
  3. Model: resize cạnh ngắn 224 → cắt giữa → softmax 5 lớp (timeout 2s).
  4. Gộp 5 lớp → 4 mã, trả (waste_type, confidence ∈ [0,1]).
  LED chỉ sáng ở bước 1 (kể cả retry), KHÔNG trong lúc inference.

- LUÔN trả argmax kể cả confidence thấp — fusion tự cân trọng số; hệ luôn
  xả vào ngăn khả năng nhất ("CHÍNH SÁCH: LUÔN XẢ" ở pi_classifier_fusion).
- (WASTE_NONE, 0.0) CHỈ khi camera/model lỗi hoặc timeout. Không bao giờ
  raise ra main_controller.
- Lỗi lúc khởi tạo (không có camera, thiếu openvino, model hỏng, lớp model
  không có trong CAMERA_CLASS_MAP) → log ERROR, `available` = False, mọi
  classify() trả NONE. Hệ vẫn chạy bằng audio (fusion Case C).


PHƠI SÁNG
---------
Ống PVC kín → LED là nguồn sáng duy nhất → phơi sáng + white balance KHÓA
cứng (CAMERA_EXPOSURE_US / CAMERA_ANALOGUE_GAIN / CAMERA_COLOUR_GAINS):
ảnh ổn định giữa các vật, và LED chỉ cần sáng LED_SETTLE_S. Chưa đo (None)
→ AE/AWB tự động, LED phải sáng CAMERA_AUTO_SETTLE_S mỗi lần để AE hội tụ.
Đo bằng Mode 4. Phải khóa TRƯỚC khi thu dataset.

OpenCV VideoCapture (USB webcam) chỉ để thử trên máy dev: không khóa được
phơi sáng một cách khả chuyển, nên luôn chờ CAMERA_AUTO_SETTLE_S.


ROI — camera_roi.json (cùng thư mục file này)
---------------------------------------------
  {"x": int, "y": int, "w": int, "h": int, "frame_w": int, "frame_h": int}
frame_w/frame_h = kích thước khung lúc vẽ ROI; đổi CAMERA_RESOLUTION thì ROI
tự co giãn theo. Chưa có file → dùng cả khung (log warning). Nên vẽ ROI
VUÔNG: model cắt giữa thành vuông, ROI chữ nhật sẽ mất phần dư cạnh dài.


TEST ĐỘC LẬP — python3 pi_camera_classifier.py [mode]
-----------------------------------------------------
  0 (mặc định)  nháy LED 5 lần — kiểm tra dây MOSFET/LED.
  1             chụp + phân loại 1 ảnh, in xác suất từng lớp, lưu
                camera_last.jpg (ảnh model thấy, sau khi cắt ROI).
  1 <ảnh.jpg>   phân loại 1 file ảnh có sẵn (không cần camera — máy dev).
  2             vẽ ROI bằng chuột → camera_roi.json (không có màn hình
                thì lưu roi_frame.jpg và nhập số tay).
  3             thu dataset: Enter = chụp, q = thoát. Ảnh cắt ROI vào
                dataset/<LỚP>/, khung đầy đủ vào dataset_raw/<LỚP>/ (để vẽ
                lại ROI sau này mà không phải chụp lại).
  4             đo phơi sáng dưới LED (cần picamera2, đặt 1 vật trong ống)
                → in giá trị để dán vào pi_config.


THƯ VIỆN
--------
- picamera2 — cài qua apt (python3-picamera2), có sẵn trên Pi OS. Chạy
  trong venv thì tạo venv bằng --system-site-packages (giống gpiozero).
- openvino, Pillow, PyYAML, numpy, opencv-python (requirements.txt).
- gpiozero (LED — có sẵn trên Raspberry Pi OS).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

import cv2
import numpy as np

from pi_config import (
    WASTE_NONE, WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL, WASTE_NAMES,
    CAMERA_BACKEND, CAMERA_ID, CAMERA_RESOLUTION,
    CAMERA_EXPOSURE_US, CAMERA_ANALOGUE_GAIN, CAMERA_COLOUR_GAINS, CAMERA_AUTO_SETTLE_S,
    CAMERA_CAPTURE_TIMEOUT_S, CAMERA_CAPTURE_RETRIES, CAMERA_BLACK_MEAN, CAMERA_OPENCV_FLUSH,
    CAMERA_MODEL_DIR, CAMERA_INFER_THREADS, CAMERA_INFER_TIMEOUT_S, CAMERA_CLASS_MAP,
    LED_PIN, LED_SETTLE_S,
)

log = logging.getLogger(__name__)

try:
    from gpiozero import LED as _GpioLED
except ImportError:  # máy dev không phải Pi
    _GpioLED = None

# Cùng thư mục với file này — không phụ thuộc cwd khi autostart từ rc.local.
_HERE = os.path.dirname(os.path.abspath(__file__))
ROI_FILE = os.path.join(_HERE, "camera_roi.json")
MODEL_DIR = os.path.join(_HERE, CAMERA_MODEL_DIR)
DATASET_DIR = os.path.join(_HERE, "dataset")
DATASET_RAW_DIR = os.path.join(_HERE, "dataset_raw")

# Thứ tự cố định để log/hiển thị — cũng là thứ tự phá hòa khi argmax.
_WASTE_TYPES = (WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL)

_AE_LOCKED = CAMERA_EXPOSURE_US is not None and CAMERA_ANALOGUE_GAIN is not None
_AWB_LOCKED = CAMERA_COLOUR_GAINS is not None


class CaptureLight:
    """LED chiếu sáng lúc chụp. Dùng: `with light: frame = ...`

    Bật LED → chờ settle_s → chụp → tắt (kể cả khi chụp raise).
    Không có gpiozero / không mở được chân → chụp không đèn (log warning),
    KHÔNG raise: thiếu đèn chỉ làm ảnh tối, không được làm đứng chu kỳ.
    """

    def __init__(self, pin: int = LED_PIN, settle_s: float = LED_SETTLE_S):
        self._settle_s = settle_s
        self._led = None
        if _GpioLED is None:
            log.warning("[LED] Không có gpiozero — chụp không đèn")
            return
        try:
            self._led = _GpioLED(pin)
        except Exception as e:
            log.warning("[LED] Không mở được GPIO %d: %s — chụp không đèn", pin, e)

    def __enter__(self):
        if self._led is not None:
            self._led.on()
        # Chờ cả khi không có đèn: AE tự động vẫn cần thời gian hội tụ
        time.sleep(self._settle_s)
        return self

    def __exit__(self, *exc):
        if self._led is not None:
            self._led.off()
        return False

    def close(self):
        if self._led is not None:
            self._led.off()
            self._led.close()
            self._led = None


# ----------------------------------------------------------------------
# ROI
# ----------------------------------------------------------------------

def load_roi(path: str = ROI_FILE) -> dict | None:
    """Đọc camera_roi.json. Không có / hỏng → None (dùng cả khung)."""
    if not os.path.isfile(path):
        log.warning("[Camera] Chưa có %s — dùng cả khung (chạy Mode 2 để vẽ ROI)",
                    os.path.basename(path))
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        roi = {k: int(data[k]) for k in ("x", "y", "w", "h")}
        if roi["w"] <= 0 or roi["h"] <= 0 or roi["x"] < 0 or roi["y"] < 0:
            raise ValueError(f"giá trị không hợp lệ: {roi}")
        if "frame_w" in data and "frame_h" in data:
            roi["frame_w"], roi["frame_h"] = int(data["frame_w"]), int(data["frame_h"])
        return roi
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.error("[Camera] %s hỏng (%s) — dùng cả khung", path, e)
        return None


def save_roi(roi: dict, frame_shape, path: str = ROI_FILE):
    data = {k: int(roi[k]) for k in ("x", "y", "w", "h")}
    data["frame_w"], data["frame_h"] = int(frame_shape[1]), int(frame_shape[0])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class CameraClassifier:
    """Chụp ảnh trong ống + phân loại bằng YOLO26n-cls. Tạo đúng 1 instance."""

    def __init__(self, camera_id=CAMERA_ID, model_dir: str = MODEL_DIR,
                 backend: str = CAMERA_BACKEND, open_camera: bool = True):
        self._camera_id = camera_id
        self._backend = None          # "picamera2" | "opencv" | None (không có camera)
        self._cam = None
        self._capture_controls = {}   # controls picamera2 lúc chụp — Mode 4 khôi phục lại
        self._model = None
        self._class_to_waste: list[int] = []   # chỉ số lớp model → WASTE_*
        self._roi = load_roi()
        self._roi_warned = False

        if open_camera:
            self._open_camera(backend)
        locked = self._backend == "picamera2" and _AE_LOCKED and _AWB_LOCKED
        if self._backend == "picamera2" and not locked:
            log.warning("[Camera] Phơi sáng CHƯA khóa — AE/AWB tự động, LED sáng %.1fs mỗi lần chụp. "
                        "Đo bằng Mode 4 rồi điền CAMERA_EXPOSURE_US/ANALOGUE_GAIN/COLOUR_GAINS.",
                        CAMERA_AUTO_SETTLE_S)
        self._light = CaptureLight(settle_s=LED_SETTLE_S if locked else CAMERA_AUTO_SETTLE_S)
        self._load_model(model_dir)

    # ------------------------------------------------------------------
    # Khởi tạo
    # ------------------------------------------------------------------

    def _open_camera(self, backend: str):
        if backend not in ("auto", "picamera2", "opencv"):
            log.error("[Camera] CAMERA_BACKEND=%r không hợp lệ — tắt camera", backend)
            return
        if backend in ("auto", "picamera2"):
            try:
                self._open_picamera2()
                self._backend = "picamera2"
                return
            except ImportError:
                hint = ("sudo apt install python3-picamera2; venv phải tạo bằng "
                        "--system-site-packages")
                if backend == "picamera2":
                    log.error("[Camera] Không có picamera2 (%s) — tắt camera", hint)
                    return
                log.warning("[Camera] Không có picamera2 (%s) — thử OpenCV VideoCapture", hint)
            except Exception as e:
                log.error("[Camera] Không mở được Pi Camera %r: %s", self._camera_id, e)
                self._close_camera()
                if backend == "picamera2":
                    return
        try:
            cap = cv2.VideoCapture(self._camera_id)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError("VideoCapture không mở được")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
            self._cam = cap
            self._backend = "opencv"
            log.info("[Camera] OpenCV VideoCapture(%r) — chỉ dùng để thử trên máy dev", self._camera_id)
        except Exception as e:
            log.error("[Camera] Không mở được camera OpenCV %r: %s — tắt camera", self._camera_id, e)

    def _open_picamera2(self):
        from picamera2 import Picamera2   # ImportError → để _open_camera xử lý

        # Cấu hình still mặc định cho FrameDurationLimits tới 1000s — AE trong ống tối
        # sẽ kéo phơi sáng hàng giây. Chặn ở 100 ms/frame (hoặc vừa đủ cho phơi sáng
        # đã khóa nếu dài hơn).
        max_frame_us = 100000
        controls = {"AeEnable": not _AE_LOCKED, "AwbEnable": not _AWB_LOCKED}
        if _AE_LOCKED:
            controls["ExposureTime"] = int(CAMERA_EXPOSURE_US)
            controls["AnalogueGain"] = float(CAMERA_ANALOGUE_GAIN)
            max_frame_us = max(max_frame_us, int(CAMERA_EXPOSURE_US) + 5000)
        controls["FrameDurationLimits"] = (33333, max_frame_us)
        if _AWB_LOCKED:
            controls["ColourGains"] = (float(CAMERA_COLOUR_GAINS[0]), float(CAMERA_COLOUR_GAINS[1]))

        self._cam = Picamera2(camera_num=self._camera_id)
        # "RGB888" của libcamera = byte [B, G, R] → mảng BGR đúng chuẩn OpenCV.
        # ("BGR888" — mặc định của still config — mới là RGB.)
        config = self._cam.create_still_configuration(
            main={"size": tuple(CAMERA_RESOLUTION), "format": "RGB888"},
            buffer_count=2,
            controls=controls,
        )
        self._cam.configure(config)
        self._capture_controls = controls
        log.info("[Camera] Pi Camera %r — %s, AE %s, AWB %s", self._camera_id,
                 config["main"]["size"], "khóa" if _AE_LOCKED else "tự động",
                 "khóa" if _AWB_LOCKED else "tự động")

    def _load_model(self, model_dir: str):
        try:
            from pi_yolo_classifier import YoloClassifier
            model = YoloClassifier(model_dir, num_threads=CAMERA_INFER_THREADS,
                                   timeout_s=CAMERA_INFER_TIMEOUT_S)
            missing = [n for n in model.class_names if n not in CAMERA_CLASS_MAP]
            if missing:
                raise ValueError(f"lớp {missing} không có trong CAMERA_CLASS_MAP (pi_config)")
            bad = {n: t for n, t in CAMERA_CLASS_MAP.items() if t not in _WASTE_TYPES}
            if bad:
                raise ValueError(f"CAMERA_CLASS_MAP trỏ tới mã không hợp lệ: {bad}")
        except Exception as e:
            log.error("[Camera] Không nạp được model %s: %s — camera classifier TẮT", model_dir, e)
            return
        self._model = model
        self._class_to_waste = [CAMERA_CLASS_MAP[n] for n in model.class_names]
        log.info("[Camera] Model %s: %s", os.path.basename(model_dir),
                 ", ".join(f"{n}→{WASTE_NAMES[t]}" for n, t in zip(model.class_names, self._class_to_waste)))

    @property
    def available(self) -> bool:
        """True khi cả camera lẫn model đều sẵn sàng."""
        return self._backend is not None and self._model is not None

    @property
    def class_names(self) -> list[str]:
        return list(self._model.class_names) if self._model is not None else []

    # ------------------------------------------------------------------
    # Chụp
    # ------------------------------------------------------------------

    def capture_frame(self) -> np.ndarray:
        """Chụp 1 frame BGR uint8 HxWx3 dưới LED. Raise RuntimeError nếu fail."""
        if self._backend is None:
            raise RuntimeError("Không có camera")
        if self._backend == "picamera2":
            self._cam.start()
            try:
                with self._light:
                    return self._grab_with_retry(self._grab_picamera2)
            finally:
                self._cam.stop()
        with self._light:
            return self._grab_with_retry(self._grab_opencv)

    def _grab_with_retry(self, grab) -> np.ndarray:
        last = "?"
        for attempt in range(1, CAMERA_CAPTURE_RETRIES + 1):
            try:
                frame = grab()
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if frame is None or frame.size == 0:
                    last = "frame rỗng"
                else:
                    mean = float(frame.mean())
                    if mean >= CAMERA_BLACK_MEAN:
                        return frame
                    last = f"frame đen (độ sáng TB {mean:.1f} < {CAMERA_BLACK_MEAN})"
            log.warning("[Camera] Lần chụp %d/%d hỏng: %s", attempt, CAMERA_CAPTURE_RETRIES, last)
        raise RuntimeError(f"Chụp hỏng {CAMERA_CAPTURE_RETRIES} lần liên tiếp — {last}")

    def _grab_picamera2(self) -> np.ndarray:
        try:
            request = self._cam.capture_request(wait=CAMERA_CAPTURE_TIMEOUT_S, flush=True)
        except TypeError:
            # picamera2 cũ chưa có tham số flush — frame có thể bắt đầu phơi sáng
            # trước lúc LED bật hết; settle vẫn bù được phần lớn.
            request = self._cam.capture_request(wait=CAMERA_CAPTURE_TIMEOUT_S)
        try:
            frame = request.make_array("main")    # make_array đã copy — release an toàn
        finally:
            request.release()
        return frame[:, :, :3]

    def _grab_opencv(self) -> np.ndarray | None:
        for _ in range(CAMERA_OPENCV_FLUSH):
            self._cam.grab()
        ok, frame = self._cam.read()
        return frame if ok else None

    # ------------------------------------------------------------------
    # Tiền xử lý + phân loại
    # ------------------------------------------------------------------

    def crop_roi(self, frame: np.ndarray) -> np.ndarray:
        """Cắt vùng lòng ống. Không có ROI / ROI lệch khung → trả cả khung."""
        if self._roi is None:
            return frame
        fh, fw = frame.shape[:2]
        x, y, w, h = self._roi["x"], self._roi["y"], self._roi["w"], self._roi["h"]
        rw, rh = self._roi.get("frame_w", fw), self._roi.get("frame_h", fh)
        if (rw, rh) != (fw, fh):
            sx, sy = fw / rw, fh / rh
            x, y, w, h = round(x * sx), round(y * sy), round(w * sx), round(h * sy)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(fw, x + w), min(fh, y + h)
        if x1 - x0 < 16 or y1 - y0 < 16:
            if not self._roi_warned:
                log.error("[Camera] ROI %s nằm ngoài khung %dx%d — dùng cả khung", self._roi, fw, fh)
                self._roi_warned = True
            return frame
        return frame[y0:y1, x0:x1]

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Frame BGR → blob [1, 3, 224, 224] float32 đúng như model nhận."""
        if self._model is None:
            raise RuntimeError("Model chưa nạp")
        return self._model.preprocess(self.crop_roi(frame))

    def analyze(self, frame: np.ndarray | None = None) -> dict:
        """Như classify() nhưng trả đầy đủ để debug/calibrate. Raise nếu lỗi.

        {"waste_type", "confidence", "scores": {WASTE_*: p}, "class_probs": {lớp: p},
         "latency_ms", "roi_image"}
        """
        if self._model is None:
            raise RuntimeError("Model chưa nạp")
        if frame is None:
            frame = self.capture_frame()
        roi_image = self.crop_roi(frame)
        probs = self._model.predict(roi_image)

        scores = {t: 0.0 for t in _WASTE_TYPES}
        for idx, p in enumerate(probs):
            scores[self._class_to_waste[idx]] += float(p)
        best = max(_WASTE_TYPES, key=lambda t: scores[t])
        return {
            "waste_type": best,
            "confidence": min(1.0, max(0.0, scores[best])),
            "scores": scores,
            "class_probs": {n: float(p) for n, p in zip(self._model.class_names, probs)},
            "latency_ms": self._model.last_latency_ms,
            "roi_image": roi_image,
        }

    def classify(self, frame: np.ndarray | None = None) -> tuple[int, float]:
        """(waste_type, confidence). frame=None thì tự chụp. Không bao giờ raise.

        (WASTE_NONE, 0.0) chỉ khi camera/model lỗi hoặc timeout.
        """
        if self._model is None or (frame is None and self._backend is None):
            log.error("[Camera] Không khả dụng (camera=%s, model=%s) → NONE",
                      self._backend, "OK" if self._model is not None else "không có")
            return WASTE_NONE, 0.0
        t0 = time.monotonic()
        try:
            r = self.analyze(frame)
        except Exception as e:
            log.error("[Camera] Phân loại lỗi: %s → NONE", e)
            return WASTE_NONE, 0.0

        log.info("[Camera] Lớp model: %s",
                 ", ".join(f"{n}={p:.2f}" for n, p in r["class_probs"].items()))
        log.info("[Camera] >> Kết quả: %s (conf=%.2f) — inference %.0f ms, tổng %.0f ms",
                 WASTE_NAMES[r["waste_type"]], r["confidence"], r["latency_ms"],
                 (time.monotonic() - t0) * 1000)
        return r["waste_type"], r["confidence"]

    # ------------------------------------------------------------------
    # Hiệu chuẩn phơi sáng (Mode 4)
    # ------------------------------------------------------------------

    def measure_exposure(self, settle_s: float = 3.0) -> dict:
        """Bật LED, để AE/AWB tự hội tụ settle_s giây, đọc giá trị đã hội tụ.

        Chỉ picamera2. Khôi phục controls chụp sau khi đo.
        """
        if self._backend != "picamera2":
            raise RuntimeError("Đo phơi sáng cần Pi Camera (picamera2)")
        self._cam.set_controls({"AeEnable": True, "AwbEnable": True,
                                "FrameDurationLimits": (33333, 100000)})
        self._cam.start()
        try:
            # Dùng chính self._light — tạo LED thứ hai trên cùng chân thì gpiozero
            # báo GPIOPinInUse.
            with self._light:
                time.sleep(settle_s)
                md = self._cam.capture_metadata(wait=CAMERA_CAPTURE_TIMEOUT_S)
                frame = self._grab_picamera2()
        finally:
            self._cam.stop()
            self._cam.set_controls(self._capture_controls)
        return {
            "ExposureTime": md.get("ExposureTime"),
            "AnalogueGain": md.get("AnalogueGain"),
            "ColourGains": md.get("ColourGains"),
            "Lux": md.get("Lux"),
            "mean": float(frame.mean()),
            "frame": frame,
        }

    # ------------------------------------------------------------------
    # Dọn dẹp
    # ------------------------------------------------------------------

    def _close_camera(self):
        cam, self._cam = self._cam, None
        if cam is None:
            return
        try:
            if self._backend == "opencv" or isinstance(cam, cv2.VideoCapture):
                cam.release()
            else:
                cam.close()
        except Exception as e:
            log.warning("[Camera] Lỗi khi đóng camera: %s", e)

    def close(self):
        """Giải phóng camera, model, LED. Gọi từ main_controller._shutdown()."""
        self._close_camera()
        self._backend = None
        self._model = None
        self._light.close()


# ----------------------------------------------------------------------
# Test độc lập
# ----------------------------------------------------------------------

def _mode_led():
    light = CaptureLight()
    for i in range(5):
        print(f"LED nháy {i + 1}/5")
        with light:
            time.sleep(0.3)
        time.sleep(0.7)
    light.close()


def _print_result(r: dict):
    print("\nXác suất từng lớp của model:")
    for n, p in sorted(r["class_probs"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:8s} {p * 100:6.2f}%  → {WASTE_NAMES[CAMERA_CLASS_MAP[n]]}")
    print("Gộp theo ngăn:")
    for t in _WASTE_TYPES:
        print(f"  {WASTE_NAMES[t]:12s} {r['scores'][t] * 100:6.2f}%")
    print(f"\n>> {WASTE_NAMES[r['waste_type']]} — {r['confidence'] * 100:.1f}% "
          f"(inference {r['latency_ms']:.1f} ms)")


def _mode_classify(image_path: str | None):
    clf = CameraClassifier(open_camera=image_path is None)
    try:
        if clf._model is None:
            print("Model không nạp được — xem log.")
            return
        if image_path is not None:
            frame = cv2.imread(image_path)
            if frame is None:
                print(f"Không đọc được ảnh: {image_path}")
                return
        else:
            frame = clf.capture_frame()
        r = clf.analyze(frame)
        out = os.path.join(_HERE, "camera_last.jpg")
        cv2.imwrite(out, r["roi_image"])
        _print_result(r)
        print(f"Ảnh model thấy (sau ROI): {out}")
    finally:
        clf.close()


def _ask_roi_manually(frame) -> dict | None:
    path = os.path.join(_HERE, "roi_frame.jpg")
    cv2.imwrite(path, frame)
    print(f"Không mở được cửa sổ — đã lưu khung {frame.shape[1]}x{frame.shape[0]} vào {path}.")
    print("Mở ảnh trên máy khác, đo vùng lòng ống rồi nhập 'x y w h' (Enter trống = hủy):")
    line = input("> ").strip()
    if not line:
        return None
    x, y, w, h = (int(v) for v in line.split())
    return {"x": x, "y": y, "w": w, "h": h}


def _mode_roi():
    clf = CameraClassifier()
    try:
        frame = clf.capture_frame()
    except RuntimeError as e:
        print(f"Chụp lỗi: {e}")
        return
    finally:
        clf.close()
    fh, fw = frame.shape[:2]
    try:
        # Thu nhỏ để vừa màn hình, rồi quy đổi ROI về khung gốc
        scale = min(1.0, 1000 / fw, 750 / fh)
        shown = cv2.resize(frame, (round(fw * scale), round(fh * scale)), interpolation=cv2.INTER_AREA)
        print("Kéo chuột chọn vùng LÒNG ỐNG (nên vuông), Enter/Space = lưu, c = hủy.")
        x, y, w, h = cv2.selectROI("ROI - long ong", shown, showCrosshair=True)
        cv2.destroyAllWindows()
        roi = None if w == 0 or h == 0 else {
            "x": round(x / scale), "y": round(y / scale), "w": round(w / scale), "h": round(h / scale)}
    except cv2.error:
        roi = _ask_roi_manually(frame)
    if roi is None:
        print("Hủy — không lưu.")
        return
    save_roi(roi, frame.shape)
    print(f"Đã lưu {ROI_FILE}: {roi} (khung {fw}x{fh})")
    if abs(roi["w"] - roi["h"]) > 0.1 * max(roi["w"], roi["h"]):
        print("⚠️ ROI không vuông — model sẽ cắt giữa, mất phần dư ở cạnh dài.")


def _mode_dataset():
    clf = CameraClassifier()
    try:
        names = clf.class_names or sorted(CAMERA_CLASS_MAP)
        print("Lớp:", ", ".join(f"{i}={n}" for i, n in enumerate(names)))
        choice = input("Chọn lớp (số hoặc tên): ").strip()
        if choice.isdigit():
            cls = names[int(choice)] if int(choice) < len(names) else choice
        else:
            cls = choice.upper()
        if cls not in names:
            print(f"Lớp '{cls}' không có trong {names}")
            return
        out_dir = os.path.join(DATASET_DIR, cls)
        raw_dir = os.path.join(DATASET_RAW_DIR, cls)
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)
        print(f"Lưu vào {out_dir}. Đặt vật vào ống; Enter = chụp, q = thoát. "
              "Đổi tư thế vật sau MỖI lần chụp.")
        n = 0
        while input(f"[{cls} #{n + 1}] ").strip().lower() != "q":
            try:
                frame = clf.capture_frame()
            except RuntimeError as e:
                print(f"Chụp lỗi: {e}")
                continue
            name = f"{cls}_{time.strftime('%Y%m%d_%H%M%S')}_{n:04d}.jpg"
            cv2.imwrite(os.path.join(out_dir, name), clf.crop_roi(frame), [cv2.IMWRITE_JPEG_QUALITY, 95])
            cv2.imwrite(os.path.join(raw_dir, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            n += 1
            msg = f"  lưu {name}"
            if clf._model is not None:
                try:
                    r = clf.analyze(frame)
                    msg += f" — model hiện tại đoán {WASTE_NAMES[r['waste_type']]} ({r['confidence']:.2f})"
                except Exception as e:
                    msg += f" — model lỗi: {e}"
            print(msg)
        print(f"Xong: {n} ảnh lớp {cls}.")
    finally:
        clf.close()


def _mode_exposure():
    clf = CameraClassifier()
    try:
        print("Đặt 1 vật ĐIỂN HÌNH vào ống, đóng nắp. Bật LED 3s để AE/AWB hội tụ...")
        r = clf.measure_exposure()
    finally:
        clf.close()
    out = os.path.join(_HERE, "exposure_check.jpg")
    cv2.imwrite(out, r["frame"])
    gains = r["ColourGains"]
    print(f"\nĐộ sáng TB khung: {r['mean']:.0f}/255 — ảnh: {out}")
    print("Dán vào pi_config.py:")
    print(f"  CAMERA_EXPOSURE_US   = {int(r['ExposureTime'])}")
    print(f"  CAMERA_ANALOGUE_GAIN = {float(r['AnalogueGain']):.2f}")
    print(f"  CAMERA_COLOUR_GAINS  = ({float(gains[0]):.3f}, {float(gains[1]):.3f})")
    print("Xem ảnh: kim loại/thủy tinh cháy trắng thì giảm EXPOSURE_US, tối quá thì tăng.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    mode = sys.argv[1] if len(sys.argv) > 1 else "0"
    if mode == "0":
        _mode_led()
    elif mode == "1":
        _mode_classify(sys.argv[2] if len(sys.argv) > 2 else None)
    elif mode == "2":
        _mode_roi()
    elif mode == "3":
        _mode_dataset()
    elif mode == "4":
        _mode_exposure()
    else:
        print("TEST ĐỘC LẬP" + __doc__.split("TEST ĐỘC LẬP")[1].split("THƯ VIỆN")[0].rstrip())
