#!/usr/bin/env python3
"""
test_uart_interactive.py — Công cụ kiểm tra giao tiếp UART và điều khiển ESP32 từ Raspberry Pi
=============================================================================================

Sử dụng script này để:
  1. Kiểm tra kết nối UART giữa Pi và ESP32 (gửi PING nhận ALIVE)
  2. Điều khiển Servo gõ SG90 (lệnh KNOCK)
  3. Điều khiển Motor xoay ống GA25-370 đến các ngăn rác (lệnh ROTATE)
  4. Điều khiển Servo cửa xả MG90S (lệnh DISCHARGE)
  5. Điều khiển Relay bật/tắt đèn (lệnh LIGHT)
  6. Chạy kịch bản tự động tuần tự

Cách chạy trên Raspberry Pi:
  cd "Raspberry PI"
  python3 test_uart_interactive.py
"""

import sys
import time
from pi_communication import ESP32Comm
from pi_config import (
    WASTE_NONE,
    WASTE_PLASTIC,
    WASTE_GLASS,
    WASTE_PAPER,
    WASTE_METAL,
    WASTE_NAMES,
)

# In màu terminal cho dễ quan sát
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def on_esp32_event(event: dict):
    """Callback nhận và hiển thị phản hồi/sự kiện từ ESP32 theo thời gian thực."""
    ev_type = event.get("event", "UNKNOWN")

    if ev_type == "ALIVE":
        print(f"\n{GREEN}[ESP32 -> Pi]{RESET} ESP32 đang hoạt động bình thường ({BOLD}ALIVE{RESET})")
    elif ev_type == "KNOCK_DONE":
        seq = event.get("seq", 0)
        print(f"\n{GREEN}[ESP32 -> Pi]{RESET} Đã gõ xong nhịp số: {BOLD}{seq}{RESET}")
    elif ev_type == "ROTATE_DONE":
        pos = event.get("position", 0)
        pos_name = WASTE_NAMES.get(pos, f"Mã {pos}")
        print(f"\n{GREEN}[ESP32 -> Pi]{RESET} Đã xoay xong và dừng chính xác tại ngăn: {BOLD}{pos_name}{RESET}")
    elif ev_type == "DISCHARGE_DONE":
        print(f"\n{GREEN}[ESP32 -> Pi]{RESET} Cửa xả rác đã mở và đóng lại hoàn tất ({BOLD}DISCHARGE_DONE{RESET})")
    elif ev_type == "OBJECT_DETECTED":
        dist = event.get("distance", 0)
        print(f"\n{YELLOW}[ESP32 CẢNH BÁO]{RESET} Phát hiện vật thể trong ống! Khoảng cách: {BOLD}{dist} cm{RESET}")
    elif ev_type == "ERROR":
        code = event.get("code", "UNKNOWN")
        print(f"\n{RED}[ESP32 LỖI]{RESET} Mã lỗi: {BOLD}{code}{RESET}")
    else:
        print(f"\n{CYAN}[ESP32 -> Pi]{RESET} Nhận gói tin: {event}")

    print(f"\n{BOLD}Chọn thao tác [1-7, q]: {RESET}", end="", flush=True)


def print_menu():
    print(f"\n{BOLD}===================================================={RESET}")
    print(f"{BOLD}   MENU KIỂM TRA GIAO TIẾP UART: PI 4 <--> ESP32    {RESET}")
    print(f"{BOLD}===================================================={RESET}")
    print(f" {BOLD}1.{RESET} Gửi PING kiểm tra kết nối (Ping -> ALIVE)")
    print(f" {BOLD}2.{RESET} Điều khiển {CYAN}Servo gõ SG90{RESET} (KNOCK)")
    print(f" {BOLD}3.{RESET} Điều khiển {YELLOW}Motor xoay GA25-370{RESET} (ROTATE)")
    print(f" {BOLD}4.{RESET} Điều khiển {CYAN}Servo cửa xả MG90S{RESET} (DISCHARGE)")
    print(f" {BOLD}5.{RESET} Điều khiển {BOLD}Đèn / Relay{RESET} (LIGHT ON / OFF)")
    print(f" {BOLD}6.{RESET} Chạy kịch bản tự động tuần tự (Test chu trình)")
    print(f" {BOLD}7.{RESET} Lắng nghe cảm biến siêu âm HC-SR04")
    print(f" {BOLD}q.{RESET} Thoát chương trình")
    print(f"----------------------------------------------------")


def main():
    print(f"{CYAN}Đang khởi tạo kết nối UART tới ESP32...{RESET}")
    comm = ESP32Comm()
    comm.on_event = on_esp32_event

    if not comm.connect():
        print(f"{RED}[LỖI] Không thể mở cổng Serial {comm._port}!{RESET}")
        print("Vui lòng kiểm tra:")
        print("  1. Dây TX/RX và GND đã cắm chắc chắn chưa?")
        print("  2. Đã bật enable_uart=1 và phân quyền 'sudo usermod -aG dialout $USER' chưa?")
        sys.exit(1)

    print(f"{GREEN}[OK] Đã mở cổng {comm._port} @ {comm._baudrate} baud thành công.{RESET}")

    try:
        while True:
            print_menu()
            choice = input(f"{BOLD}Chọn thao tác [1-7, q]: {RESET}").strip().lower()

            if choice == "1":
                print(f"{CYAN}-> Gửi lệnh PING...{RESET}")
                if comm.ping():
                    print(f"{GREEN}-> [THÀNH CÔNG] ESP32 phản hồi ALIVE ngay lập tức!{RESET}")
                else:
                    print(f"{RED}-> [THẤT BẠI] Quá thời gian chờ phản hồi ALIVE từ ESP32.{RESET}")

            elif choice == "2":
                raw_count = input("Nhập số lần muốn servo gõ [mặc định: 3]: ").strip()
                count = int(raw_count) if raw_count.isdigit() and int(raw_count) > 0 else 3
                print(f"{CYAN}-> Gửi lệnh KNOCK (số lần = {count})...{RESET}")
                comm.send_knock(count)

            elif choice == "3":
                print(f"\n{BOLD}Chọn ngăn muốn xoay đến:{RESET}")
                print(f"  1. Ngăn Nhựa ({WASTE_NAMES[WASTE_PLASTIC]})")
                print(f"  2. Ngăn Thủy tinh ({WASTE_NAMES[WASTE_GLASS]})")
                print(f"  3. Ngăn Giấy/Carton ({WASTE_NAMES[WASTE_PAPER]})")
                print(f"  4. Ngăn Kim loại ({WASTE_NAMES[WASTE_METAL]})")
                raw_target = input(f"{BOLD}Nhập lựa chọn [1-4]: {RESET}").strip()

                if raw_target in ["1", "2", "3", "4"]:
                    target = int(raw_target)
                    print(f"{YELLOW}-> Gửi lệnh ROTATE (target = {target} - {WASTE_NAMES[target]})...{RESET}")
                    print(f"-> Motor đang quay và chờ ngắt TCRT5000 tại ngăn {WASTE_NAMES[target]}...")
                    comm.send_rotate(target)
                else:
                    print(f"{RED}Lựa chọn không hợp lệ!{RESET}")

            elif choice == "4":
                print(f"{CYAN}-> Gửi lệnh DISCHARGE mở cửa xả rác...{RESET}")
                comm.send_discharge()

            elif choice == "5":
                sub = input("Chọn trạng thái đèn (1: BẬT đèn, 0: TẮT đèn): ").strip()
                if sub == "1":
                    print(f"{YELLOW}-> Gửi lệnh BẬT đèn (LIGHT ON)...{RESET}")
                    comm.send_light(True)
                elif sub == "0":
                    print(f"{YELLOW}-> Gửi lệnh TẮT đèn (LIGHT OFF)...{RESET}")
                    comm.send_light(False)
                else:
                    print(f"{RED}Lựa chọn không hợp lệ!{RESET}")

            elif choice == "6":
                print(f"\n{BOLD}--- BẮT ĐẦU KỊCH BẢN TEST TUẦN TỰ ---{RESET}")
                print(f"1. Bật đèn...")
                comm.send_light(True)
                time.sleep(1.0)

                print(f"2. Gõ servo 3 lần...")
                comm.send_knock(3)
                time.sleep(2.5)

                print(f"3. Xoay motor đến ngăn 1 (Nhựa)...")
                comm.send_rotate(1)
                time.sleep(3.0)

                print(f"4. Mở cửa xả rác...")
                comm.send_discharge()
                time.sleep(2.5)

                print(f"5. Tắt đèn...")
                comm.send_light(False)
                print(f"{GREEN}--- HOÀN THÀNH KỊCH BẢN TEST! ---{RESET}")

            elif choice == "7":
                print(f"{CYAN}Đang ở chế độ lắng nghe cảm biến siêu âm HC-SR04...{RESET}")
                print("Hãy đưa tay lại gần cảm biến khoảng cách (< 17cm) để kiểm tra.")
                print("Nhấn Enter để quay lại menu chính.")
                input()

            elif choice == "q":
                print("Đang đóng cổng kết nối...")
                break

            else:
                print(f"{RED}Lệnh không hợp lệ, vui lòng chọn lại!{RESET}")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nNgười dùng hủy bỏ.")
    finally:
        comm.disconnect()
        print(f"{GREEN}Đã ngắt kết nối an toàn.{RESET}")


if __name__ == "__main__":
    main()
