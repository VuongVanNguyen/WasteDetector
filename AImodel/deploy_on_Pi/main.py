from yolov26_classifier import YOLOv26Classifier

# 1. NẠP MÔ HÌNH VÀO RAM (CHỈ CHẠY 1 LẦN DUY NHẤT KHI KHỞI ĐỘNG CHƯƠNG TRÌNH)
print("[*] Đang nạp mô hình và danh sách class từ metadata lên RAM...")
clf = YOLOv26Classifier("best_openvino_model")
print(f"[+] Đã sẵn sàng! Danh sách nhãn tự động nhận diện: {clf.class_names}")

# -------------------------------------------------------------
# 2. GỌI DỰ ĐOÁN BẤT KỲ LÚC NÀO
# -------------------------------------------------------------

# Cách 1: Dự đoán từ đường dẫn file ảnh
res = clf.predict("test.jpg", top_k=3)

print("\n--- KẾT QUẢ ---")
print(f"Nhãn dự đoán      : {res.label}")
print(f"Độ tin cậy        : {res.confidence * 100:.2f}%")
print(f"Thời gian xử lý   : {res.latency_ms:.2f} ms")

print("\nTop 3 khả năng cao nhất:")
for item in res.top_k:
    print(f" - {item['label']}: {item['confidence'] * 100:.2f}%")

# Cách 2: Nếu bạn đọc ảnh bằng OpenCV hoặc từ cảm biến
# import cv2
# frame = cv2.imread("test.jpg")
# res = clf.predict(frame)
# print(f"Nhãn: {res.label}")
