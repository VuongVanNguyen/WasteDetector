"""
pi_communication.py — Giao tiếp UART JSON 2 chiều với ESP32
==============================================================

VAI TRÒ TRONG HỆ THỐNG
----------------------
- Là **cầu nối DUY NHẤT** giữa lớp Pi (bộ não — AI, fusion, GUI) và
  lớp ESP32 (cơ cấu — motor, servo, sensor).
- Mất file này = toàn hệ thống đứng: Pi không bật được đèn, không ra
  lệnh gõ, không biết khi nào có vật rơi vào ống.
- Được khởi tạo 1 lần trong main_controller, dùng xuyên suốt vòng đời
  chương trình. KHÔNG tạo nhiều instance — serial port là tài nguyên
  độc quyền.


KÊNH VẬT LÝ
-----------
- Pi GPIO 14 (TX, /dev/ttyS0) → ESP32 GPIO 16 (RX2)
- Pi GPIO 15 (RX, /dev/ttyS0) → ESP32 GPIO 17 (TX2)
- GND chung BẮT BUỘC.
- Cả 2 đều logic 3.3V → KHÔNG dùng level shifter.
- Trước khi chạy: `enable_uart=1` trong /boot/config.txt + tắt serial
  console bằng raspi-config (nếu chưa đã làm khi setup).


GIAO THỨC (đồng bộ với CLAUDE.md)
---------------------------------
- Encoding: UTF-8 JSON, MỖI thông điệp kết thúc bằng '\n' (newline).
- Baudrate: 115200, 8N1, không flow control.
- Hai chiều độc lập, không request/response chặt — phần lớn event
  ESP32 push không đồng bộ → cần reader thread riêng.

  Pi → ESP32 (cmd):
    {"cmd": "PING"}
    {"cmd": "LIGHT", "state": "ON"|"OFF"}
    {"cmd": "KNOCK", "count": 3}
    {"cmd": "ROTATE", "target": 1..4}
    {"cmd": "DISCHARGE"}

  ESP32 → Pi (event):
    {"event": "ALIVE"}
    {"event": "OBJECT_DETECTED", "distance": <cm>}
    {"event": "KNOCK_DONE", "seq": 1..count}
    {"event": "ROTATE_DONE", "position": 1..4}
    {"event": "DISCHARGE_DONE"}
    {"event": "ERROR", "code": "<MOTOR_TIMEOUT|INVALID_CMD|...>"}


KIẾN TRÚC ĐA LUỒNG
------------------
- Main thread: gọi các send_* khi cần ra lệnh (blocking ngắn — chỉ
  ghi vào serial).
- Reader thread (daemon=True): vòng lặp đọc readline() blocking,
  parse JSON, gọi callback `on_event(dict)` — KHÔNG xử lý logic ở
  đây, chỉ dispatch.
- main_controller dùng threading.Event() để chờ event tương ứng
  (KNOCK_DONE, ROTATE_DONE, DISCHARGE_DONE) → mô hình producer/consumer.
- **Lock cho send**: serial.write() KHÔNG thread-safe khi nhiều thread
  gửi cùng lúc — phải bọc bằng threading.Lock trong _send().


GIAO DIỆN LỚP — chi tiết cần implement
--------------------------------------

connect() -> bool:
  1. Mở serial.Serial(port, baudrate, timeout=ESP32_TIMEOUT, write_timeout=2).
  2. Drain buffer (reset_input_buffer + reset_output_buffer).
  3. Khởi tạo và start reader_thread (daemon).
  4. Gọi self.ping() — chờ tối đa 3s ALIVE. Nếu fail → log warning
     nhưng VẪN return True (để main_controller chạy ở chế độ hạn chế
     theo handler hiện tại). Trả False CHỈ khi không mở được serial.
  5. Set self._running = True.

disconnect():
  - self._running = False → reader_loop thoát.
  - Join reader_thread với timeout (ví dụ 2s) — không block vĩnh viễn.
  - close() serial nếu còn mở. Nuốt exception lúc đóng.

ping() -> bool:
  - Tạo threading.Event cục bộ, đăng ký tạm vào dict chờ event "ALIVE"
    (hoặc đơn giản: gửi PING rồi sleep ngắn quan sát flag set bởi
    reader). Cách đơn giản nhất: cho reader set 1 flag riêng
    `self._alive_event = Event()`, ping() clear + send + wait(3s).
  - Trả True nếu nhận ALIVE trong timeout.

send_knock(count: int):
  - Clamp count ∈ [1, 10] để chống lệnh sai.
  - _send({"cmd": "KNOCK", "count": int(count)}).

send_rotate(waste_type: int):
  - Validate waste_type ∈ {1,2,3,4} (WASTE_PLASTIC..WASTE_METAL theo
    pi_config). Nếu không hợp lệ → log error, KHÔNG gửi (tránh ESP32
    xoay sai ngăn).
  - _send({"cmd": "ROTATE", "target": waste_type}).

send_discharge():
  - _send({"cmd": "DISCHARGE"}).

send_light(state: bool):
  - _send({"cmd": "LIGHT", "state": "ON" if state else "OFF"}).

_send(payload: dict):
  - Nếu self._ser is None hoặc không mở → log + return (no-op),
    KHÔNG raise — main_controller có thể đang chạy chế độ "no ESP32".
  - Với self._send_lock:
      line = json.dumps(payload, ensure_ascii=False) + '\n'
      self._ser.write(line.encode('utf-8'))
      self._ser.flush()
  - Wrap try/except serial.SerialException → log + set cờ lỗi
    (không crash worker).

_reader_loop():
  - Vòng while self._running:
      try:
          raw = self._ser.readline()   # bị block tối đa timeout
          if not raw: continue          # timeout — quay lại check flag
          line = raw.decode('utf-8', errors='replace').strip()
          if not line: continue
          event = json.loads(line)
          # Xử lý ALIVE nội bộ (set self._alive_event nếu có)
          name = event.get("event")
          if name == "ALIVE" and self._alive_event:
              self._alive_event.set()
          # Dispatch ra ngoài
          if self.on_event:
              try: self.on_event(event)
              except Exception as e: log("[ESP32] on_event raised: %s", e)
      except json.JSONDecodeError:
          log("[ESP32] Dòng không phải JSON, bỏ qua: %r", line)
      except serial.SerialException as e:
          log("[ESP32] Lỗi serial: %s", e)
          break   # để main_controller phát hiện và có thể reconnect
      except Exception as e:
          log("[ESP32] Lỗi không mong đợi: %s", e)
  - Khi thoát: nếu self._running vẫn True (= thoát do lỗi, không phải
    do disconnect chủ động) → có thể bật cờ reconnect_needed.


YÊU CẦU KỸ THUẬT / RÀNG BUỘC
-----------------------------
- Toàn bộ I/O serial phải TOLERANT — port có thể rớt bất kỳ lúc nào
  (rút USB, ESP32 reset, brown-out). Không bao giờ để exception trồi
  lên main_controller gây crash GUI Tkinter.
- Reader thread phải là **daemon** để không chặn process exit.
- Reader callback `on_event` CHẠY TRÊN READER THREAD — main_controller
  hiện chỉ set threading.Event trong handler → an toàn. Tuyệt đối
  không gọi Tkinter widget trực tiếp trong on_event (Tk không
  thread-safe) — nếu cần update GUI thì dùng .after(0, fn) hoặc queue.
- Không retry tự động trên send — main_controller chịu trách nhiệm
  timeout (.wait(timeout=5/10/5)) và quyết định fallback. Triết lý:
  truyền thông "fire and forget" cho cmd, "event-driven" cho phản hồi.
- JSON dùng `ensure_ascii=False` để không escape ký tự — tiết kiệm
  byte, nhưng nội dung lệnh hiện không có Unicode → tùy chọn.
- Mỗi message ≤ 256 byte (khuyến nghị) — phía ESP32 có buffer giới hạn.
- Sau connect(): bắt buộc drain buffer vì ESP32 in vài dòng debug
  lúc boot có thể không phải JSON.
- Lock phải bao bọc CẢ write + flush (không chỉ write).


KỊCH BẢN LỖI CẦN XỬ LÝ
----------------------
- Port không tồn tại / permission denied → connect() trả False, log
  hướng dẫn (kiểm tra /dev/ttyS0, dialout group).
- ESP32 chưa khởi động xong → ping() fail → connect() vẫn True nhưng
  chế độ hạn chế. Main_controller có thể retry ping định kỳ.
- ESP32 gửi dòng không phải JSON (debug print, partial line) → bỏ qua,
  KHÔNG crash.
- Reader đọc được half-line do timeout cắt giữa → readline() trên
  pyserial sẽ trả phần đã đọc; lần sau ghép phần còn lại — JSON parse
  fail ở phần đầu → bỏ qua, phần sau parse OK. Chấp nhận mất 1 event
  nếu mất kết nối giữa chừng.
- on_event raise exception → log + tiếp tục đọc, không kill thread.


TEST ĐỘC LẬP (__main__ block — đề xuất thêm)
--------------------------------------------
- Kết nối, ping, gửi LIGHT ON / LIGHT OFF cách nhau 1s, in mọi event
  nhận được. Mục đích: smoke test phần cứng UART trước khi chạy full
  hệ thống.


LIÊN KẾT
--------
- Định nghĩa cmd/event: xem [[CLAUDE]] mục "Giao thức truyền thông".
- Mã waste_type: dùng hằng số từ pi_config (KHÔNG hardcode 1/2/3/4
  trong file này — import nếu cần validate).
- Bên ESP32 nhận/gửi tương ứng: [[task_comms]] (Core 0).
"""

import json
import logging
import threading
import time

import serial

from pi_config import (
    ESP32_PORT,
    ESP32_BAUDRATE,
    ESP32_TIMEOUT,
    WASTE_PLASTIC,
    WASTE_GLASS,
    WASTE_PAPER,
    WASTE_METAL,
)

log = logging.getLogger(__name__)

_VALID_WASTE_TYPES = {WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL}
_PING_TIMEOUT = 3.0  # giây chờ ALIVE sau PING


class ESP32Comm:
    """Giao tiếp UART JSON 2 chiều với ESP32. Tạo đúng 1 instance."""

    def __init__(self, port: str = ESP32_PORT, baudrate: int = ESP32_BAUDRATE):
        self._port = port
        self._baudrate = baudrate
        self._ser: serial.Serial | None = None
        self._running = False
        self._send_lock = threading.Lock()
        self._alive_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self.on_event = None          # callback(dict) — set bởi main_controller
        self.reconnect_needed = False  # True nếu reader thoát do lỗi

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Mở serial, drain buffer, start reader thread, ping ESP32.

        Trả False CHỈ khi không mở được cổng serial.
        Ping fail → log warning nhưng vẫn trả True (chế độ hạn chế).
        """
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=ESP32_TIMEOUT,
                write_timeout=2,
            )
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except serial.SerialException as e:
            log.error("[ESP32] Không mở được serial '%s': %s", self._port, e)
            log.error("[ESP32] Kiểm tra: ls -l /dev/ttyS0  và  sudo usermod -aG dialout $USER")
            self._ser = None
            return False

        self._running = True
        self.reconnect_needed = False
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="esp32-reader", daemon=True
        )
        self._reader_thread.start()

        if not self.ping():
            log.warning(
                "[ESP32] Ping không nhận ALIVE trong %.1fs — chạy chế độ hạn chế",
                _PING_TIMEOUT,
            )

        return True

    def disconnect(self):
        """Dừng reader thread và đóng serial."""
        self._running = False
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def ping(self) -> bool:
        """Gửi PING, chờ ALIVE tối đa _PING_TIMEOUT giây. Trả True nếu OK."""
        self._alive_event.clear()
        self._send({"cmd": "PING"})
        return self._alive_event.wait(timeout=_PING_TIMEOUT)

    def send_knock(self, count: int):
        """Ra lệnh gõ count lần (clamp [1, 10])."""
        count = max(1, min(10, int(count)))
        self._send({"cmd": "KNOCK", "count": count})

    def send_rotate(self, waste_type: int):
        """Ra lệnh xoay ống đến ngăn waste_type (1=Nhựa..4=Kim loại).

        Bỏ qua và log error nếu waste_type không hợp lệ — không gửi gì
        để tránh ESP32 xoay sang ngăn sai.
        """
        if waste_type not in _VALID_WASTE_TYPES:
            log.error(
                "[ESP32] send_rotate: waste_type=%r không hợp lệ — bỏ qua "
                "(hợp lệ: %s)",
                waste_type,
                _VALID_WASTE_TYPES,
            )
            return
        self._send({"cmd": "ROTATE", "target": waste_type})

    def send_discharge(self):
        """Ra lệnh mở cửa đáy xả vật thể."""
        self._send({"cmd": "DISCHARGE"})

    def send_light(self, state: bool):
        """Bật (True) hoặc tắt (False) đèn chiếu sáng qua relay."""
        self._send({"cmd": "LIGHT", "state": "ON" if state else "OFF"})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, payload: dict):
        """Ghi JSON + newline ra serial dưới lock. No-op nếu port không sẵn sàng."""
        if self._ser is None or not self._ser.is_open:
            log.debug("[ESP32] _send: serial không sẵn sàng, bỏ qua %r", payload)
            return
        try:
            line = json.dumps(payload, ensure_ascii=False) + '\n'
            with self._send_lock:
                self._ser.write(line.encode('utf-8'))
                self._ser.flush()
        except serial.SerialException as e:
            log.error("[ESP32] Lỗi serial khi gửi %r: %s", payload, e)

    def _reader_loop(self):
        """Daemon thread: đọc và dispatch event JSON từ ESP32."""
        line = ""
        while self._running:
            try:
                raw = self._ser.readline()
                if not raw:
                    continue  # readline timeout — quay lại kiểm tra _running
                # Làm sạch byte null và khoảng trắng ẩn
                line = raw.decode('utf-8', errors='replace').replace('\x00', '').strip()
                if not line:
                    continue

                event = None
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Bẫy dự phòng 1: Trích xuất đoạn JSON {...} nếu bị dính log debug
                    import re
                    match = re.search(r'\{.*?\}', line)
                    if match:
                        try:
                            event = json.loads(match.group(0))
                        except json.JSONDecodeError:
                            pass

                    # Bẫy dự phòng 2: Kiểm tra trực tiếp chuỗi ALIVE phòng trường hợp JSON bị lệch
                    if "ALIVE" in line.upper():
                        self._alive_event.set()

                if event and isinstance(event, dict):
                    name = event.get("event")
                    if name == "ALIVE":
                        self._alive_event.set()
                    if self.on_event:
                        try:
                            self.on_event(event)
                        except Exception as e:
                            log.error("[ESP32] on_event raised: %s", e)
            except serial.SerialException as e:
                log.error("[ESP32] Lỗi serial trong reader: %s", e)
                break  # main_controller phát hiện qua reconnect_needed
            except Exception as e:
                log.error("[ESP32] Lỗi không mong đợi trong reader: %s", e)

        if self._running:
            # Thoát do lỗi, không phải do disconnect() chủ động
            self.reconnect_needed = True
            log.warning("[ESP32] Reader thread thoát bất thường — reconnect_needed=True")


# ----------------------------------------------------------------------
# Smoke test độc lập
# ----------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    def _print_event(ev: dict):
        print(f"[EVENT] {ev}")

    comm = ESP32Comm()
    comm.on_event = _print_event

    print(f"Kết nối tới {comm._port} @ {comm._baudrate} baud …")
    if not comm.connect():
        print("Không kết nối được serial. Kiểm tra port và quyền.")
        raise SystemExit(1)

    print("Gửi LIGHT ON …")
    comm.send_light(True)
    time.sleep(1.0)

    print("Gửi LIGHT OFF …")
    comm.send_light(False)
    time.sleep(1.0)

    print("Lắng nghe event trong 5 giây …")
    time.sleep(5.0)

    comm.disconnect()
    print("Done.")
