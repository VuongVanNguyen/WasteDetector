"""
pi_communication.py — Giao tiếp UART JSON với ESP32

Giao thức: JSON over UART, 115200 baud, newline-terminated
  Pi → ESP32: {"cmd": "...", ...}\n
  ESP32 → Pi: {"event": "...", ...}\n

Kết nối vật lý:
  Pi GPIO 14 (TX) → ESP32 GPIO 16 (RX2)
  Pi GPIO 15 (RX) → ESP32 GPIO 17 (TX2)
  GND chung
  (Cả 2 đều 3.3V logic — không cần level shifter)
"""

import json
import serial
import threading
import time
from typing import Callable, Optional

from pi_config import ESP32_PORT, ESP32_BAUDRATE, ESP32_TIMEOUT


class ESP32Controller:
    """
    Giao tiếp UART JSON với ESP32.
    Chạy 1 background thread đọc liên tục từ serial,
    gọi callback khi nhận được event từ ESP32.
    """

    def __init__(
        self,
        port: str = ESP32_PORT,
        baudrate: int = ESP32_BAUDRATE,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.on_event = on_event   # callback(event_dict) gọi khi nhận event

        self._ser: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    # ----------------------------------------------------------
    # Connection
    # ----------------------------------------------------------

    def connect(self) -> bool:
        # TODO: implement
        raise NotImplementedError

    def disconnect(self):
        # TODO: implement
        raise NotImplementedError

    def ping(self) -> bool:
        """Gửi PING, chờ ALIVE. Trả về True nếu ESP32 phản hồi."""
        # TODO: implement
        raise NotImplementedError

    # ----------------------------------------------------------
    # Commands (Pi → ESP32)
    # ----------------------------------------------------------

    def send_knock(self, count: int = 3):
        """Lệnh gõ vật thể count lần."""
        # TODO: implement
        raise NotImplementedError

    def send_rotate(self, waste_type: int):
        """Lệnh xoay ống đến ngăn waste_type (1-4)."""
        # TODO: implement
        raise NotImplementedError

    def send_discharge(self):
        """Lệnh mở cửa trượt đáy thả rác."""
        # TODO: implement
        raise NotImplementedError

    def send_light(self, state: bool):
        """Bật/tắt đèn chiếu sáng."""
        # TODO: implement
        raise NotImplementedError

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _send(self, payload: dict):
        """Serialize payload thành JSON và gửi qua serial."""
        # TODO: implement
        raise NotImplementedError

    def _reader_loop(self):
        """Background thread: đọc từng dòng JSON từ ESP32, gọi on_event."""
        # TODO: implement
        raise NotImplementedError
