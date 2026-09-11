#!/usr/bin/env python3
"""
test_uart.py (Root wrapper) — Chạy test_uart từ thư mục gốc
"""
import os
import sys

# Thêm thư mục 'Raspberry PI' vào sys.path
pi_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Raspberry PI")
if pi_dir not in sys.path:
    sys.path.insert(0, pi_dir)

from test_uart import main

if __name__ == "__main__":
    main()
