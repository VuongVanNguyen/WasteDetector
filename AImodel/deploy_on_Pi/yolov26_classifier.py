"""
YOLOv26 Classification SDK for Raspberry Pi 4 / ARM64.
Tự động nạp OpenVINO IR, tự đọc class names từ metadata.yaml, nạp 1 lần lên RAM.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Union
import cv2
import numpy as np
import openvino as ov
import yaml


@dataclass(slots=True)
class PredictionResult:
    label: str
    confidence: float
    class_id: int
    latency_ms: float
    top_k: List[Dict[str, Union[str, float, int]]]


class YOLOv26Classifier:
    def __init__(
        self,
        model_dir_or_xml: Union[str, Path],
        num_threads: int = 4,
    ) -> None:
        """
        Nạp toàn bộ mô hình và metadata lên RAM.
        :param model_dir_or_xml: Đường dẫn đến thư mục chứa model hoặc trực tiếp file .xml
        :param num_threads: Số lõi Cortex-A72 sử dụng (mặc định tận dụng cả 4 lõi).
        """
        path = Path(model_dir_or_xml)

        if path.is_dir():
            self.xml_path = path / "best.xml"
            self.yaml_path = path / "metadata.yaml"
        else:
            self.xml_path = path
            self.yaml_path = path.parent / "metadata.yaml"

        if not self.xml_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file: {self.xml_path}")

        # 1. Tự động đọc nhãn từ file metadata.yaml
        self.class_names: Dict[int, str] = {}
        self.input_h, self.input_w = 224, 224

        if self.yaml_path.exists():
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f)
                if meta and "names" in meta:
                    # Ultralytics lưu dạng {0: 'class_a', 1: 'class_b'}
                    self.class_names = {int(k): str(v) for k, v in meta["names"].items()}
                if meta and "imgsz" in meta:
                    imgsz = meta["imgsz"]
                    if isinstance(imgsz, list):
                        self.input_h, self.input_w = imgsz[0], imgsz[1]
                    elif isinstance(imgsz, int):
                        self.input_h, self.input_w = imgsz, imgsz

        # 2. Khởi tạo OpenVINO Runtime Engine và nạp mô hình vào RAM
        self.core = ov.Core()
        self.core.set_property(
            "CPU",
            {
                "PERFORMANCE_HINT": "LATENCY",
                "INFERENCE_NUM_THREADS": str(num_threads),
            },
        )
        self.compiled_model = self.core.compile_model(str(self.xml_path), "CPU")
        self.infer_request = self.compiled_model.create_infer_request()
        self.input_port = self.compiled_model.input(0)
        self.output_port = self.compiled_model.output(0)

        # 3. Cấp phát sẵn bộ nhớ tĩnh [1, 3, H, W] trên RAM để chống phân mảnh LPDDR4
        self._blob = np.empty((1, 3, self.input_h, self.input_w), dtype=np.float32)

    def _preprocess(self, image: np.ndarray) -> None:
        """Chuẩn hóa ảnh đầu vào trực tiếp vào static RAM buffer."""
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.input_w, self.input_h), interpolation=cv2.INTER_LINEAR)
        # HWC -> CHW và chia 255.0 để đưa về khoảng [0.0, 1.0]
        self._blob[0] = resized.transpose(2, 0, 1).astype(np.float32) * (1.0 / 255.0)

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        e_x = np.exp(x - np.max(x))
        return e_x / np.sum(e_x)

    def predict(
        self,
        image_input: Union[str, Path, np.ndarray],
        top_k: int = 1,
    ) -> PredictionResult:
        """
        Gọi hàm này bất kỳ lúc nào để nhận kết quả phân loại.

        :param image_input: Đường dẫn ảnh (str/Path) hoặc mảng numpy (từ cv2.imread).
        :param top_k: Số lượng kết quả có điểm cao nhất muốn lấy.
        :return: Đối tượng PredictionResult.
        """
        if isinstance(image_input, (str, Path)):
            img = cv2.imread(str(image_input))
            if img is None:
                raise ValueError(f"Không thể đọc file ảnh: {image_input}")
        elif isinstance(image_input, np.ndarray):
            img = image_input
        else:
            raise TypeError("image_input phải là đường dẫn file hoặc numpy array.")

        # Tiền xử lý
        self._preprocess(img)

        # Suy luận
        t_start = cv2.getTickCount()
        self.infer_request.infer({self.input_port: self._blob})
        t_end = cv2.getTickCount()
        latency_ms = ((t_end - t_start) / cv2.getTickFrequency()) * 1000.0

        # Lấy vector xác suất
        raw_output = self.infer_request.get_output_tensor(0).data[0].astype(np.float32)

        if not np.isclose(np.sum(raw_output), 1.0, atol=1e-2):
            probs = self._softmax(raw_output)
        else:
            probs = raw_output

        # Trích xuất Top-K
        k = max(1, min(top_k, len(probs)))
        top_indices = np.argsort(probs)[::-1][:k]

        top_k_list = []
        for idx in top_indices:
            cls_id = int(idx)
            top_k_list.append({
                "class_id": cls_id,
                "label": self.class_names.get(cls_id, f"class_{cls_id}"),
                "confidence": float(probs[cls_id]),
            })

        best = top_k_list[0]
        return PredictionResult(
            label=best["label"],
            confidence=best["confidence"],
            class_id=best["class_id"],
            latency_ms=latency_ms,
            top_k=top_k_list,
        )