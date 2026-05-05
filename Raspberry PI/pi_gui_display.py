"""
============================================
KHỐI 1 — Raspberry Pi — Module Giao Diện
Chức năng: Hiển thị kết quả phân loại rác trên màn hình HDMI
Framework: Tkinter (có sẵn trên Pi, không cần cài thêm)
============================================

Kết nối:
  - Pi HDMI → Màn hình
"""

import tkinter as tk
from tkinter import font as tkfont
import time
from threading import Thread

class WasteSorterGUI:
    """
    Giao diện hiển thị kết quả phân loại rác.
    Hiển thị toàn màn hình trên HDMI.
    """
    
    # Màu sắc cho từng loại rác
    COLORS = {
        0x00: ("#333333", "#AAAAAA", "?"),       # Không xác định
        0x01: ("#1a1a2e", "#FFD700", "⚙"),       # Kim loại - Vàng
        0x02: ("#1a1a2e", "#00CED1", "◆"),       # Thủy tinh - Xanh ngọc
        0x03: ("#1a1a2e", "#FF6347", "♻"),       # Nhựa - Đỏ cam
        0x04: ("#1a1a2e", "#8B4513", "📦"),      # Giấy - Nâu
    }
    
    WASTE_NAMES = {
        0x00: "Chờ phân loại...",
        0x01: "KIM LOẠI",
        0x02: "THỦY TINH",
        0x03: "NHỰA",
        0x04: "GIẤY / CARTON"
    }
    
    WASTE_INSTRUCTIONS = {
        0x00: "Vui lòng bỏ rác vào ống",
        0x01: "→ Bỏ vào thùng KIM LOẠI (Vàng)",
        0x02: "→ Bỏ vào thùng THỦY TINH (Xanh)",
        0x03: "→ Bỏ vào thùng NHỰA (Đỏ)",
        0x04: "→ Bỏ vào thùng GIẤY (Nâu)"
    }
    
    def __init__(self, fullscreen=True):
        self.root = tk.Tk()
        self.root.title("Máy Phân Loại Rác Thông Minh")
        
        if fullscreen:
            self.root.attributes('-fullscreen', True)
            self.root.bind('<Escape>', lambda e: self.root.attributes('-fullscreen', False))
        else:
            self.root.geometry("800x480")  # Kích thước màn hình 7 inch
        
        self.root.configure(bg="#1a1a2e")
        
        # Fonts
        self.title_font = tkfont.Font(family="Helvetica", size=28, weight="bold")
        self.result_font = tkfont.Font(family="Helvetica", size=72, weight="bold")
        self.icon_font = tkfont.Font(family="Helvetica", size=100)
        self.info_font = tkfont.Font(family="Helvetica", size=20)
        self.status_font = tkfont.Font(family="Helvetica", size=14)
        self.stats_font = tkfont.Font(family="Helvetica", size=16)
        
        # Thống kê
        self.total_count = 0
        self.type_counts = {0x01: 0, 0x02: 0, 0x03: 0, 0x04: 0}
        
        self._build_ui()
        
    def _build_ui(self):
        """Xây dựng giao diện"""
        # === HEADER ===
        header_frame = tk.Frame(self.root, bg="#16213e", pady=10)
        header_frame.pack(fill=tk.X)
        
        self.title_label = tk.Label(
            header_frame,
            text="🗑 MÁY PHÂN LOẠI RÁC THÔNG MINH",
            font=self.title_font,
            fg="#FFFFFF",
            bg="#16213e"
        )
        self.title_label.pack()
        
        # === MAIN CONTENT ===
        main_frame = tk.Frame(self.root, bg="#1a1a2e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # Icon loại rác
        self.icon_label = tk.Label(
            main_frame,
            text="?",
            font=self.icon_font,
            fg="#AAAAAA",
            bg="#1a1a2e"
        )
        self.icon_label.pack(pady=(20, 10))
        
        # Tên loại rác
        self.result_label = tk.Label(
            main_frame,
            text="Chờ phân loại...",
            font=self.result_font,
            fg="#AAAAAA",
            bg="#1a1a2e"
        )
        self.result_label.pack(pady=(0, 10))
        
        # Hướng dẫn
        self.instruction_label = tk.Label(
            main_frame,
            text="Vui lòng bỏ rác vào ống",
            font=self.info_font,
            fg="#888888",
            bg="#1a1a2e"
        )
        self.instruction_label.pack(pady=(0, 10))
        
        # Độ tin cậy
        self.confidence_label = tk.Label(
            main_frame,
            text="",
            font=self.info_font,
            fg="#666666",
            bg="#1a1a2e"
        )
        self.confidence_label.pack()
        
        # === THỐNG KÊ ===
        stats_frame = tk.Frame(self.root, bg="#16213e", pady=15)
        stats_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Tổng số
        self.total_label = tk.Label(
            stats_frame,
            text="Tổng: 0 vật thể",
            font=self.stats_font,
            fg="#FFFFFF",
            bg="#16213e"
        )
        self.total_label.pack()
        
        # Chi tiết từng loại
        detail_frame = tk.Frame(stats_frame, bg="#16213e")
        detail_frame.pack(pady=5)
        
        self.stats_labels = {}
        stats_items = [
            (0x01, "Kim loại", "#FFD700"),
            (0x02, "Thủy tinh", "#00CED1"),
            (0x03, "Nhựa", "#FF6347"),
            (0x04, "Giấy", "#8B4513"),
        ]
        
        for wtype, name, color in stats_items:
            lbl = tk.Label(
                detail_frame,
                text=f"{name}: 0",
                font=self.stats_font,
                fg=color,
                bg="#16213e",
                padx=20
            )
            lbl.pack(side=tk.LEFT)
            self.stats_labels[wtype] = lbl
        
        # === STATUS BAR ===
        self.status_label = tk.Label(
            self.root,
            text="Trạng thái: Sẵn sàng",
            font=self.status_font,
            fg="#00FF00",
            bg="#0f0f23",
            pady=5
        )
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)
    
    def update_result(self, waste_type, confidence=0.0):
        """
        Cập nhật kết quả phân loại lên màn hình.
        
        Args:
            waste_type: Mã loại rác (0x01-0x04)
            confidence: Độ tin cậy (0.0-1.0)
        """
        bg_color, fg_color, icon = self.COLORS.get(waste_type, self.COLORS[0x00])
        name = self.WASTE_NAMES.get(waste_type, "???")
        instruction = self.WASTE_INSTRUCTIONS.get(waste_type, "")
        
        # Cập nhật UI (thread-safe)
        def _update():
            self.icon_label.configure(text=icon, fg=fg_color)
            self.result_label.configure(text=name, fg=fg_color)
            self.instruction_label.configure(text=instruction, fg="#CCCCCC")
            
            if confidence > 0:
                self.confidence_label.configure(
                    text=f"Độ tin cậy: {confidence:.1%}",
                    fg=fg_color
                )
            else:
                self.confidence_label.configure(text="")
            
            # Cập nhật thống kê
            if waste_type in self.type_counts:
                self.type_counts[waste_type] += 1
                self.total_count += 1
                
                self.total_label.configure(text=f"Tổng: {self.total_count} vật thể")
                
                stats_names = {0x01: "Kim loại", 0x02: "Thủy tinh",
                              0x03: "Nhựa", 0x04: "Giấy"}
                for wt, lbl in self.stats_labels.items():
                    lbl.configure(text=f"{stats_names[wt]}: {self.type_counts[wt]}")
        
        self.root.after(0, _update)
    
    def update_status(self, message, color="#00FF00"):
        """Cập nhật thanh trạng thái"""
        def _update():
            self.status_label.configure(text=f"Trạng thái: {message}", fg=color)
        self.root.after(0, _update)
    
    def reset_display(self):
        """Reset về trạng thái chờ"""
        self.update_result(0x00)
        self.update_status("Sẵn sàng", "#00FF00")
    
    def run(self):
        """Chạy GUI (blocking)"""
        self.root.mainloop()
    
    def close(self):
        """Đóng GUI"""
        self.root.quit()
        self.root.destroy()


# ============ TEST ĐỘC LẬP ============
if __name__ == "__main__":
    gui = WasteSorterGUI(fullscreen=False)
    
    # Simulate phân loại
    def simulate():
        import random
        time.sleep(2)
        
        waste_types = [0x01, 0x02, 0x03, 0x04]
        
        for i in range(10):
            wtype = random.choice(waste_types)
            confidence = random.uniform(0.6, 0.99)
            
            gui.update_status("Đang phân loại...", "#FFFF00")
            time.sleep(1)
            
            gui.update_result(wtype, confidence)
            gui.update_status("Hoàn thành!", "#00FF00")
            time.sleep(3)
            
            gui.reset_display()
            time.sleep(1)
    
    sim_thread = Thread(target=simulate, daemon=True)
    sim_thread.start()
    
    gui.run()

