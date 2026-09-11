#!/usr/bin/env python3
"""
test_uart.py — Script kiểm tra giao tiếp UART giữa Raspberry Pi và ESP32
========================================================================
Hỗ trợ:
  1. Test bình thường với ESP32: Gửi {"cmd": "PING"} -> Chờ {"event": "ALIVE"}
  2. Test Loopback phần cứng: Nối tắt TX (Pin 8) và RX (Pin 10) với cờ --loopback

Khắc phục triệt để:
  - Lỗi nhận được {"event":"ALIVE"} nhưng vẫn báo FAIL do khoảng trắng, ký tự ẩn (\r, \n, \x00).
  - Lỗi chuỗi JSON bị kẹp giữa log khởi động của ESP32.
  - Dự phòng chuỗi (Fallback matching) khi JSON parse bị lệch nhưng nội dung chứa ALIVE.
"""

import argparse
import json
import os
import re
import sys
import time
import serial

# Thử import cấu hình từ pi_config nếu có
try:
    from pi_config import ESP32_BAUDRATE, ESP32_PORT
except ImportError:
    ESP32_PORT = "/dev/serial0"
    ESP32_BAUDRATE = 115200

# Màu hiển thị console
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def detect_default_port():
    """Tự động phát hiện cổng UART phù hợp trên hệ điều hành."""
    candidates = ["/dev/serial0", "/dev/ttyS0", "/dev/ttyAMA0", ESP32_PORT]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def clean_raw_line(raw_bytes: bytes) -> str:
    """Loại bỏ triệt để ký tự rác, null-byte, ký tự ẩn \\r, \\n và khoảng trắng."""
    if not raw_bytes:
        return ""
    # Giải mã với errors='replace' để không bị crash khi dính byte lạ
    text = raw_bytes.decode("utf-8", errors="replace")
    # Lọc bỏ ký tự null (\x00) và strip whitespace 2 đầu
    text = text.replace("\x00", "").strip("\r\n \t")
    return text


def is_alive_response(raw_text: str) -> tuple[bool, str]:
    """Kiểm tra phản hồi ALIVE qua 3 lớp:

    Lớp 1: Parse JSON trực tiếp
    Lớp 2: Trích xuất block JSON {...} nếu bị dính log debug
    Lớp 3: Fallback regex/chuỗi dự phòng
    """
    if not raw_text:
        return False, "Không nhận được dữ liệu (Chuỗi rỗng)"

    # --- Lớp 1: Parse JSON trực tiếp ---
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and data.get("event") == "ALIVE":
            return True, "Parse JSON hợp lệ: event=ALIVE"
    except json.JSONDecodeError:
        pass

    # --- Lớp 2: Trích xuất cặp ngoặc nhọn { ... } phòng khi dính log boot ---
    match = re.search(r"\{.*?\}", raw_text)
    if match:
        json_candidate = match.group(0)
        try:
            data = json.loads(json_candidate)
            if isinstance(data, dict) and data.get("event") == "ALIVE":
                return True, f"Trích xuất JSON thành công từ log: {json_candidate}"
        except json.JSONDecodeError:
            pass

    # --- Lớp 3: Fallback matching (bẫy chuỗi dự phòng) ---
    # Bắt các biến thể: {"event":"ALIVE"}, {"event": "ALIVE"}, 'event': 'ALIVE',...
    normalized = re.sub(r"\s+", "", raw_text).upper()
    if '"EVENT":"ALIVE"' in normalized or "'EVENT':'ALIVE'" in normalized or (
        "EVENT" in normalized and "ALIVE" in normalized
    ):
        return True, f"Khớp qua chuỗi dự phòng (Fallback regex): '{raw_text}'"

    return False, f"Dữ liệu không khớp ALIVE: '{raw_text}'"


def run_loopback_test(port: str, baudrate: int, timeout: float):
    """Chế độ kiểm tra Loopback TX-RX (Yêu cầu nối tắt Pin 8 TX và Pin 10 RX)."""
    print(f"{CYAN}{BOLD}[LOOPBACK TEST]{RESET} Đang mở cổng {port} @ {baudrate} baud...")
    test_msg = '{"cmd":"PING"}\n'

    try:
        with serial.Serial(port, baudrate, timeout=timeout, write_timeout=2.0) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            time.sleep(0.1)

            print(f"-> Gửi chuỗi kiểm tra: {repr(test_msg)}")
            ser.write(test_msg.encode("utf-8"))
            ser.flush()

            raw_response = ser.readline()
            received_text = clean_raw_line(raw_response)
            print(f"<- Nhận được: {repr(received_text)}")

            expected = test_msg.strip()
            if received_text == expected or '{"cmd":"PING"}' in received_text.replace(" ", ""):
                print(f"{GREEN}{BOLD}[THÀNH CÔNG]{RESET} Loopback TX-RX hoạt động hoàn hảo!")
                return True
            else:
                print(f"{RED}{BOLD}[THẤT BẠI]{RESET} Chuỗi nhận lại không khớp với chuỗi đã gửi.")
                return False
    except serial.SerialException as e:
        print(f"{RED}[LỖI]{RESET} Không thể thao tác với cổng serial: {e}")
        return False


def run_esp32_ping_test(port: str, baudrate: int, timeout: float, max_attempts: int = 3):
    """Gửi lệnh PING tới ESP32 và chờ nhận phản hồi ALIVE."""
    print(f"{CYAN}{BOLD}[ESP32 UART TEST]{RESET} Kết nối tới {port} @ {baudrate} baud (Timeout: {timeout}s)...")

    try:
        ser = serial.Serial(port, baudrate, timeout=timeout, write_timeout=2.0)
    except serial.SerialException as e:
        print(f"{RED}[LỖI]{RESET} Không thể mở cổng '{port}': {e}")
        print("Gợi ý khắc phục:")
        print("  1. Kiểm tra quyền truy cập: sudo usermod -aG dialout $USER")
        print("  2. Kiểm tra enable_uart=1 và tắt serial console bằng raspi-config")
        return False

    with ser:
        for attempt in range(1, max_attempts + 1):
            print(f"\n-> [Lần thử {attempt}/{max_attempts}] Xóa buffer & gửi lệnh PING...")
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Gửi lệnh PING chuẩn JSON kết thúc bằng \n
            ping_cmd = '{"cmd": "PING"}\n'
            ser.write(ping_cmd.encode("utf-8"))
            ser.flush()

            start_time = time.time()
            matched = False

            # Lặp đọc dòng trong khoảng thời gian timeout
            while time.time() - start_time < timeout:
                raw_bytes = ser.readline()
                if not raw_bytes:
                    continue

                cleaned_line = clean_raw_line(raw_bytes)
                if not cleaned_line:
                    continue

                print(f"   [Raw ESP32]: {repr(cleaned_line)}")

                is_ok, reason = is_alive_response(cleaned_line)
                if is_ok:
                    elapsed = (time.time() - start_time) * 1000.0
                    print(f"{GREEN}{BOLD}[THÀNH CÔNG]{RESET} Nhận phản hồi ALIVE sau {elapsed:.1f}ms!")
                    print(f"   Chi tiết: {reason}")
                    matched = True
                    break

            if matched:
                return True
            else:
                print(f"{YELLOW}[CẢNH BÁO]{RESET} Lần thử {attempt} chưa nhận được phản hồi ALIVE.")
                time.sleep(0.5)

    print(f"\n{RED}{BOLD}[THẤT BẠI]{RESET} Không nhận được phản hồi ALIVE từ ESP32 sau {max_attempts} lần thử.")
    print("Vui lòng kiểm tra:")
    print("  - Đấu chéo dây: Pi TX (Pin 8) -> ESP32 RX2 (GPIO 16) | Pi RX (Pin 10) -> ESP32 TX2 (GPIO 17)")
    print("  - Dây GND đã nối chung giữa Pi và ESP32 chưa?")
    print("  - Firmware ESP32 đã nạp bản có task_comms.cpp chưa?")
    return False


def main():
    parser = argparse.ArgumentParser(description="Script kiểm tra giao tiếp UART giữa Raspberry Pi và ESP32.")
    parser.add_argument(
        "--port",
        default=detect_default_port(),
        help="Cổng Serial (Mặc định: /dev/serial0 hoặc tự phát hiện)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=ESP32_BAUDRATE,
        help=f"Baudrate (Mặc định: {ESP32_BAUDRATE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.5,
        help="Thời gian chờ phản hồi tối đa (giây, mặc định: 2.5s)",
    )
    parser.add_argument(
        "--loopback",
        action="store_true",
        help="Chạy ở chế độ Loopback phần cứng (Nối tắt Pin 8 TX và Pin 10 RX trên Pi)",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="Số lần thử gửi PING nếu chưa nhận được ALIVE (Mặc định: 3)",
    )

    args = parser.parse_args()

    if args.loopback:
        success = run_loopback_test(args.port, args.baud, args.timeout)
    else:
        success = run_esp32_ping_test(args.port, args.baud, args.timeout, args.attempts)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
