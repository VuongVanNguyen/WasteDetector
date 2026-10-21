"""
pi_yolo_classifier.py — Chạy model YOLO26n-cls (OpenVINO IR) trên CPU Pi 4
============================================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Lớp suy luận thuần: ảnh BGR → vector xác suất theo lớp của model. Không biết
  gì về camera, LED, ROI hay mã WASTE_* — việc đó của CameraClassifier
  ([[pi_camera_classifier]]).
- Model: YOLO26n-cls, 5 lớp (CARTON, GLASS, HDPE, METAL, PET), top-1 97.55%
  trên tập val, 97.26% (994/1022) khi chạy thật trên Pi 4 — bản tốt nhất trong
  5 cỡ n/s/m/l/x (xem VisualModel/runs_Summary). Export OpenVINO 2026.3.1, FP32.
- Tên lớp + kích thước đầu vào đọc từ metadata.yaml cạnh best.xml.


NGUỒN GỐC
---------
Viết lại từ AImodel/deploy_on_Pi/yolov26_classifier.py (giữ nguyên để tham
khảo). Khác bản gốc:
  1. Tiền xử lý khớp ĐÚNG Ultralytics 8.4 lúc val/predict
     (ultralytics/data/augment.py: classify_transforms): resize CẠNH NGẮN về
     224 bằng PIL BILINEAR → cắt giữa 224×224 → /255, RGB. Bản gốc kéo giãn
     thẳng về 224×224 bằng cv2.INTER_LINEAR: ảnh 4:3 bị méo, và INTER_LINEAR
     không lọc chống răng cưa khi thu nhỏ — lệch phân phối so với lúc train.
  2. Inference async có timeout (wait_for) + cancel — không treo worker.
  3. Warm-up 1 lần lúc nạp: lần chạy đầu không bị chậm giữa chu kỳ.
  4. Kiểm tra lúc nạp: số lớp metadata khớp đầu ra model, đầu vào tĩnh.


YÊU CẦU
-------
- openvino >= 2026.3 (bản đã export model), Pillow, PyYAML, numpy.
- Pi OS 64-bit: OpenVINO chỉ có wheel aarch64, không có armv7.
"""

from __future__ import annotations

import os
import time

import numpy as np
import openvino as ov
import yaml
from PIL import Image


class YoloClassifier:
    """Nạp model 1 lần lên RAM, gọi predict() bao nhiêu lần cũng được.

    Không thread-safe: 1 infer request dùng chung — chỉ gọi từ 1 thread
    (worker thread của main_controller).
    """

    def __init__(self, model_dir: str, num_threads: int = 4, timeout_s: float = 2.0):
        xml_path = os.path.join(model_dir, "best.xml")
        yaml_path = os.path.join(model_dir, "metadata.yaml")
        if not os.path.isfile(xml_path):
            raise FileNotFoundError(f"Không tìm thấy model: {xml_path}")
        if not os.path.isfile(yaml_path):
            raise FileNotFoundError(f"Không tìm thấy metadata: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}
        names = meta.get("names")
        if not isinstance(names, dict) or not names:
            raise ValueError(f"{yaml_path}: thiếu 'names'")
        # Ultralytics lưu {0: 'CARTON', 1: 'GLASS', ...} — chỉ số phải liền 0..n-1
        if sorted(int(k) for k in names) != list(range(len(names))):
            raise ValueError(f"{yaml_path}: chỉ số lớp không liền 0..{len(names) - 1}: {names}")
        self.class_names: list[str] = [str(names[k]) for k in sorted(names, key=int)]

        self._timeout_ms = max(1, int(timeout_s * 1000))

        core = ov.Core()
        core.set_property("CPU", {
            "PERFORMANCE_HINT": "LATENCY",
            "INFERENCE_NUM_THREADS": int(num_threads),
        })
        self._compiled = core.compile_model(xml_path, "CPU")
        self._request = self._compiled.create_infer_request()

        in_shape = self._compiled.input(0).get_partial_shape()
        out_shape = self._compiled.output(0).get_partial_shape()
        if in_shape.is_dynamic or out_shape.is_dynamic:
            raise ValueError(f"Model phải có shape tĩnh (in={in_shape}, out={out_shape})")
        n, c, self.input_h, self.input_w = (int(d) for d in self._compiled.input(0).shape)
        if n != 1 or c != 3:
            raise ValueError(f"Đầu vào model phải là [1, 3, H, W], có {list(self._compiled.input(0).shape)}")
        n_out = int(np.prod(self._compiled.output(0).shape))
        if n_out != len(self.class_names):
            raise ValueError(f"Model ra {n_out} giá trị nhưng metadata có {len(self.class_names)} lớp")

        imgsz = meta.get("imgsz")
        if isinstance(imgsz, int):
            imgsz = [imgsz, imgsz]
        if isinstance(imgsz, list) and [int(v) for v in imgsz] != [self.input_h, self.input_w]:
            raise ValueError(f"metadata imgsz={imgsz} khác đầu vào model {self.input_h}x{self.input_w}")

        self.last_latency_ms = 0.0
        self._blob = np.zeros((1, 3, self.input_h, self.input_w), dtype=np.float32)
        self._infer(self._blob)   # warm-up

    def preprocess(self, image_bgr: np.ndarray) -> np.ndarray:
        """BGR uint8 HxWx3 → blob float32 [1, 3, H, W], y hệt classify_transforms.

        Ảnh vuông đầu vào (ROI vuông) thì không mất gì ở bước cắt giữa;
        ROI chữ nhật thì phần dư ở cạnh dài bị cắt — giống hệt lúc train/val.
        """
        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3 or image_bgr.dtype != np.uint8:
            raise ValueError(f"Cần ảnh BGR uint8 HxWx3, có {image_bgr.shape} {image_bgr.dtype}")
        img = Image.fromarray(np.ascontiguousarray(image_bgr[:, :, ::-1]))   # BGR → RGB
        th, tw = self.input_h, self.input_w
        w, h = img.size

        # torchvision T.Resize: số nguyên = cạnh ngắn (giữ tỉ lệ); tuple = (h, w) chính xác
        if th == tw:
            if w <= h:
                new_w, new_h = th, int(th * h / w)
            else:
                new_w, new_h = int(th * w / h), th
        else:
            new_w, new_h = tw, th
        if (new_w, new_h) != (w, h):
            img = img.resize((new_w, new_h), Image.BILINEAR)

        # torchvision T.CenterCrop: round() của Python, như torchvision
        top = int(round((new_h - th) / 2.0))
        left = int(round((new_w - tw) / 2.0))
        img = img.crop((left, top, left + tw, top + th))

        arr = np.asarray(img, dtype=np.float32) * (1.0 / 255.0)       # T.ToTensor
        self._blob[0] = arr.transpose(2, 0, 1)                        # HWC → CHW
        return self._blob

    def predict(self, image_bgr: np.ndarray) -> np.ndarray:
        """Trả vector xác suất (len = số lớp, cùng thứ tự class_names).

        Raise TimeoutError nếu inference quá timeout_s.
        """
        return self._infer(self.preprocess(image_bgr))

    def _infer(self, blob: np.ndarray) -> np.ndarray:
        t0 = time.perf_counter()
        self._request.start_async({0: blob})
        if not self._request.wait_for(self._timeout_ms):
            self._request.cancel()
            raise TimeoutError(f"Inference quá {self._timeout_ms} ms — đã hủy")
        self.last_latency_ms = (time.perf_counter() - t0) * 1000.0

        out = np.array(self._request.get_output_tensor(0).data, dtype=np.float64).reshape(-1)
        # Head Classify của Ultralytics đã softmax lúc export. Phòng model khác: chưa
        # phải phân phối xác suất thì tự softmax.
        if out.min() < 0.0 or not np.isclose(out.sum(), 1.0, atol=1e-3):
            e = np.exp(out - out.max())
            out = e / e.sum()
        return out
