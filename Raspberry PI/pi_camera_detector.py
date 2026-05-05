"""
============================================
KHỐI 1 — Raspberry Pi — Module Camera
Chức năng: Phát hiện vật thể rơi vào ống
Phương pháp: So sánh frame liên tiếp (Motion Detection)
============================================

Kết nối:
  - Camera Module v2 → Cổng CSI trên Pi
  - Hoặc USB Webcam → Cổng USB trên Pi

Cài đặt thư viện:
  pip install opencv-python numpy picamera2
"""

import cv2
import numpy as np
import time
from threading import Thread, Event

class ObjectDetector:
    """
    Phát hiện vật thể rơi vào vùng quan sát bằng Motion Detection.
    Dùng phương pháp Background Subtraction — so sánh frame hiện tại
    với background để phát hiện có vật mới xuất hiện.
    """
    
    def __init__(self, camera_id=0, detection_area=None):
        """
        Args:
            camera_id: 0 cho camera mặc định (CSI hoặc USB)
            detection_area: (x, y, w, h) vùng quan sát trong frame
                           Nếu None, quan sát toàn bộ frame
        """
        self.camera_id = camera_id
        self.detection_area = detection_area
        
        # Cấu hình detection
        self.min_contour_area = 500    # Diện tích tối thiểu (pixel²) để coi là vật thể
        self.motion_threshold = 30      # Ngưỡng khác biệt pixel (0-255)
        self.cooldown_time = 3.0        # Thời gian chờ giữa 2 lần detect (giây)
        
        # Trạng thái
        self.cap = None
        self.is_running = False
        self.last_detection_time = 0
        self.on_object_detected = None  # Callback khi phát hiện vật thể
        
        # Background subtractor
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=50,
            detectShadows=False
        )
        
    def start(self):
        """Khởi động camera và bắt đầu detect"""
        self.cap = cv2.VideoCapture(self.camera_id)
        
        if not self.cap.isOpened():
            raise RuntimeError("Không mở được camera! Kiểm tra kết nối.")
        
        # Cấu hình camera
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
        self.is_running = True
        print("[Camera] Đã khởi động. Đang học background...")
        
        # Chờ camera ổn định + học background (2 giây đầu)
        warmup_start = time.time()
        while time.time() - warmup_start < 2.0:
            ret, frame = self.cap.read()
            if ret:
                self.bg_subtractor.apply(frame)
        
        print("[Camera] Sẵn sàng detect vật thể!")
        
    def stop(self):
        """Dừng camera"""
        self.is_running = False
        if self.cap:
            self.cap.release()
        print("[Camera] Đã dừng.")
        
    def detect_once(self):
        """
        Đọc 1 frame và kiểm tra có vật thể không.
        
        Returns:
            bool: True nếu phát hiện vật thể mới
            frame: Frame hiện tại (để hiển thị debug)
        """
        if not self.cap or not self.cap.isOpened():
            return False, None
            
        ret, frame = self.cap.read()
        if not ret:
            return False, None
        
        # Cắt vùng quan sát nếu có
        if self.detection_area:
            x, y, w, h = self.detection_area
            roi = frame[y:y+h, x:x+w]
        else:
            roi = frame
        
        # Áp dụng background subtraction
        fg_mask = self.bg_subtractor.apply(roi)
        
        # Lọc nhiễu
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        
        # Tìm contours
        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        # Kiểm tra có contour đủ lớn không
        detected = False
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > self.min_contour_area:
                # Kiểm tra cooldown
                current_time = time.time()
                if current_time - self.last_detection_time > self.cooldown_time:
                    detected = True
                    self.last_detection_time = current_time
                    
                    # Vẽ bounding box lên frame (debug)
                    bx, by, bw, bh = cv2.boundingRect(contour)
                    if self.detection_area:
                        bx += self.detection_area[0]
                        by += self.detection_area[1]
                    cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
                    cv2.putText(frame, "DETECTED!", (bx, by-10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    print(f"[Camera] Phát hiện vật thể! Diện tích: {area:.0f} px²")
                    break
        
        return detected, frame
    
    def run_loop(self, show_preview=False):
        """
        Chạy vòng lặp detect liên tục.
        
        Args:
            show_preview: True để hiển thị cửa sổ preview (chỉ khi có màn hình)
        """
        print("[Camera] Bắt đầu vòng lặp detect...")
        
        while self.is_running:
            detected, frame = self.detect_once()
            
            if detected and self.on_object_detected:
                self.on_object_detected()
            
            if show_preview and frame is not None:
                # Vẽ vùng quan sát
                if self.detection_area:
                    x, y, w, h = self.detection_area
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                    cv2.putText(frame, "Detection Zone", (x, y-10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                
                cv2.imshow("Waste Sorter - Camera", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        
        if show_preview:
            cv2.destroyAllWindows()


# ============ TEST ĐỘC LẬP ============
if __name__ == "__main__":
    detector = ObjectDetector(
        camera_id=0,
        # Định nghĩa vùng quan sát (điều chỉnh theo vị trí ống)
        # detection_area=(200, 100, 240, 300)  # x, y, width, height
    )
    
    def on_detected():
        print(">>> VẬT THỂ RƠI VÀO! Bắt đầu quy trình phân loại...")
    
    detector.on_object_detected = on_detected
    
    try:
        detector.start()
        detector.run_loop(show_preview=True)
    except KeyboardInterrupt:
        print("\nDừng bằng Ctrl+C")
    finally:
        detector.stop()
