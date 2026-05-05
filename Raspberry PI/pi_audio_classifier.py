"""
============================================
KHỐI 1 — Raspberry Pi — Module Âm Thanh
Chức năng: Thu âm thanh gõ vật thể → Phân tích FFT
           → Phân loại vật liệu (kim loại, thủy tinh, nhựa, giấy)
============================================

Kết nối:
  - Micro MAX9814 → USB Sound Card → USB port trên Pi
  - Hoặc dùng USB Microphone trực tiếp

Cài đặt thư viện:
  pip install numpy scipy sounddevice matplotlib

Nguyên lý phân loại:
  Mỗi vật liệu khi bị gõ sẽ phát ra âm thanh có đặc trưng tần số khác nhau:
  - Kim loại:   Tần số cao (2000-6000 Hz), sustain dài, sắc nét
  - Thủy tinh:  Tần số cao (1500-4000 Hz), sustain trung bình, trong trẻo
  - Nhựa:       Tần số trung bình (500-2000 Hz), sustain ngắn, đục
  - Giấy/Carton: Tần số thấp (100-800 Hz), sustain rất ngắn, bùm bục
"""

import numpy as np
from scipy.fft import fft, fftfreq
from scipy.signal import butter, filtfilt, find_peaks
import sounddevice as sd
import time
import json
import os

class AudioClassifier:
    """
    Thu và phân tích âm thanh gõ vật thể để phân loại vật liệu.
    """
    
    # Mã loại rác (đồng bộ với Arduino Nano #2)
    WASTE_NONE    = 0x00
    WASTE_METAL   = 0x01
    WASTE_GLASS   = 0x02
    WASTE_PLASTIC = 0x03
    WASTE_PAPER   = 0x04
    
    WASTE_NAMES = {
        WASTE_NONE:    "Không xác định",
        WASTE_METAL:   "Kim loại",
        WASTE_GLASS:   "Thủy tinh",
        WASTE_PLASTIC: "Nhựa",
        WASTE_PAPER:   "Giấy/Carton"
    }
    
    def __init__(self, device_id=None):
        """
        Args:
            device_id: ID thiết bị âm thanh (None = mặc định)
        """
        self.device_id = device_id
        
        # Cấu hình thu âm
        self.sample_rate = 44100     # Hz
        self.record_duration = 0.5   # Giây thu âm sau khi gõ
        self.channels = 1            # Mono
        
        # Cấu hình phân tích
        self.noise_threshold = 0.01  # Ngưỡng nhiễu nền
        
        # Ngưỡng phân loại (cần calibrate theo máy thực tế)
        # Mỗi loại vật liệu có dải tần số đặc trưng (dominant frequency)
        self.freq_ranges = {
            self.WASTE_METAL:   (2000, 6000),   # Hz
            self.WASTE_GLASS:   (1500, 4000),   # Hz
            self.WASTE_PLASTIC: (500, 2000),    # Hz
            self.WASTE_PAPER:   (100, 800),     # Hz
        }
        
        # File lưu dữ liệu calibration
        self.calibration_file = "audio_calibration.json"
        self.calibration_data = {}
        self.load_calibration()
        
    def list_devices(self):
        """Liệt kê các thiết bị âm thanh có sẵn"""
        print("\n=== THIẾT BỊ ÂM THANH ===")
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f"  [{i}] {dev['name']} (Input channels: {dev['max_input_channels']})")
        print()
        
    def record_knock(self):
        """
        Thu âm thanh gõ.
        
        Returns:
            numpy.ndarray: Dữ liệu âm thanh
        """
        print(f"[Audio] Thu âm {self.record_duration}s...")
        
        audio_data = sd.rec(
            int(self.sample_rate * self.record_duration),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype='float32',
            device=self.device_id
        )
        sd.wait()  # Chờ thu xong
        
        # Chuyển về 1D array
        audio_data = audio_data.flatten()
        
        print(f"[Audio] Thu xong. Max amplitude: {np.max(np.abs(audio_data)):.4f}")
        return audio_data
    
    def analyze_fft(self, audio_data):
        """
        Phân tích FFT để tìm tần số đặc trưng.
        
        Args:
            audio_data: Dữ liệu âm thanh (1D numpy array)
            
        Returns:
            dict: Kết quả phân tích
                - dominant_freq: Tần số chủ đạo (Hz)
                - freq_spectrum: Phổ tần số
                - energy_bands: Năng lượng trong từng dải tần
        """
        # Lọc nhiễu bằng bandpass filter (100 Hz - 8000 Hz)
        nyquist = self.sample_rate / 2
        low = 100 / nyquist
        high = 8000 / nyquist
        b, a = butter(4, [low, high], btype='band')
        filtered = filtfilt(b, a, audio_data)
        
        # FFT
        N = len(filtered)
        yf = fft(filtered)
        xf = fftfreq(N, 1 / self.sample_rate)
        
        # Chỉ lấy nửa dương
        positive_mask = xf > 0
        xf = xf[positive_mask]
        magnitude = 2.0 / N * np.abs(yf[positive_mask])
        
        # Tìm tần số chủ đạo
        dominant_idx = np.argmax(magnitude)
        dominant_freq = xf[dominant_idx]
        
        # Tính năng lượng trong từng dải tần
        energy_bands = {}
        for waste_type, (f_low, f_high) in self.freq_ranges.items():
            band_mask = (xf >= f_low) & (xf <= f_high)
            energy = np.sum(magnitude[band_mask] ** 2)
            energy_bands[waste_type] = energy
        
        # Tính thêm đặc trưng phụ
        # Sustain: đo thời gian tín hiệu trên ngưỡng
        envelope = np.abs(filtered)
        above_threshold = envelope > (np.max(envelope) * 0.1)
        sustain_samples = np.sum(above_threshold)
        sustain_time = sustain_samples / self.sample_rate
        
        result = {
            'dominant_freq': dominant_freq,
            'magnitude': magnitude,
            'frequencies': xf,
            'energy_bands': energy_bands,
            'sustain_time': sustain_time,
            'max_amplitude': np.max(np.abs(audio_data))
        }
        
        return result
    
    def classify(self, audio_data):
        """
        Phân loại vật liệu dựa trên âm thanh.
        
        Args:
            audio_data: Dữ liệu âm thanh
            
        Returns:
            tuple: (waste_type, confidence, analysis_result)
        """
        # Kiểm tra có âm thanh không
        if np.max(np.abs(audio_data)) < self.noise_threshold:
            print("[Audio] Không phát hiện âm thanh gõ!")
            return self.WASTE_NONE, 0.0, None
        
        # Phân tích FFT
        analysis = self.analyze_fft(audio_data)
        
        # Phân loại dựa trên năng lượng dải tần
        energy_bands = analysis['energy_bands']
        total_energy = sum(energy_bands.values())
        
        if total_energy == 0:
            return self.WASTE_NONE, 0.0, analysis
        
        # Tính tỷ lệ năng lượng mỗi dải
        energy_ratios = {}
        for waste_type, energy in energy_bands.items():
            energy_ratios[waste_type] = energy / total_energy
        
        # Loại có năng lượng cao nhất = kết quả phân loại
        best_type = max(energy_ratios, key=energy_ratios.get)
        confidence = energy_ratios[best_type]
        
        # Kết hợp thêm đặc trưng sustain để tăng độ chính xác
        sustain = analysis['sustain_time']
        dominant_freq = analysis['dominant_freq']
        
        print(f"[Audio] Tần số chủ đạo: {dominant_freq:.1f} Hz")
        print(f"[Audio] Sustain: {sustain:.3f}s")
        print(f"[Audio] Năng lượng dải tần:")
        for wt, ratio in energy_ratios.items():
            name = self.WASTE_NAMES[wt]
            bar = "█" * int(ratio * 30)
            print(f"  {name:12s}: {ratio:.2%} {bar}")
        
        print(f"[Audio] >> Kết quả: {self.WASTE_NAMES[best_type]} "
              f"(Confidence: {confidence:.1%})")
        
        return best_type, confidence, analysis
    
    def calibrate(self, waste_type, num_samples=10):
        """
        Thu thập mẫu âm thanh để calibrate cho 1 loại vật liệu.
        
        Args:
            waste_type: Loại rác (WASTE_METAL, WASTE_GLASS, ...)
            num_samples: Số mẫu cần thu
        """
        name = self.WASTE_NAMES[waste_type]
        print(f"\n=== CALIBRATE: {name} ===")
        print(f"Chuẩn bị gõ {num_samples} lần vào vật liệu {name}")
        
        samples = []
        
        for i in range(num_samples):
            input(f"\nMẫu {i+1}/{num_samples} - Nhấn Enter rồi gõ...")
            time.sleep(0.1)  # Delay nhỏ
            
            audio = self.record_knock()
            analysis = self.analyze_fft(audio)
            
            samples.append({
                'dominant_freq': float(analysis['dominant_freq']),
                'sustain_time': float(analysis['sustain_time']),
                'energy_bands': {str(k): float(v) for k, v in analysis['energy_bands'].items()}
            })
            
            print(f"  Tần số: {analysis['dominant_freq']:.1f} Hz, "
                  f"Sustain: {analysis['sustain_time']:.3f}s")
        
        # Tính trung bình
        avg_freq = np.mean([s['dominant_freq'] for s in samples])
        std_freq = np.std([s['dominant_freq'] for s in samples])
        
        print(f"\n>> Trung bình tần số: {avg_freq:.1f} ± {std_freq:.1f} Hz")
        
        # Lưu calibration
        self.calibration_data[str(waste_type)] = {
            'name': name,
            'avg_freq': avg_freq,
            'std_freq': std_freq,
            'freq_range': (avg_freq - 2*std_freq, avg_freq + 2*std_freq),
            'samples': samples
        }
        self.save_calibration()
        
    def save_calibration(self):
        """Lưu dữ liệu calibration ra file"""
        with open(self.calibration_file, 'w') as f:
            json.dump(self.calibration_data, f, indent=2)
        print(f"[Audio] Đã lưu calibration vào {self.calibration_file}")
        
    def load_calibration(self):
        """Đọc dữ liệu calibration từ file"""
        if os.path.exists(self.calibration_file):
            with open(self.calibration_file, 'r') as f:
                self.calibration_data = json.load(f)
            print(f"[Audio] Đã load calibration từ {self.calibration_file}")
            
            # Cập nhật freq_ranges từ calibration
            for waste_type_str, data in self.calibration_data.items():
                waste_type = int(waste_type_str)
                if 'freq_range' in data:
                    self.freq_ranges[waste_type] = tuple(data['freq_range'])
        else:
            print("[Audio] Chưa có calibration. Dùng ngưỡng mặc định.")


# ============ TEST ĐỘC LẬP ============
if __name__ == "__main__":
    classifier = AudioClassifier()
    classifier.list_devices()
    
    print("=== CHỌN CHẾ ĐỘ ===")
    print("1. Test phân loại (gõ và nhận diện)")
    print("2. Calibrate từng loại vật liệu")
    
    choice = input("Chọn (1/2): ").strip()
    
    if choice == '2':
        # Calibrate
        print("\nCalibrate từng loại:")
        for wtype in [AudioClassifier.WASTE_METAL, AudioClassifier.WASTE_GLASS,
                       AudioClassifier.WASTE_PLASTIC, AudioClassifier.WASTE_PAPER]:
            name = AudioClassifier.WASTE_NAMES[wtype]
            do_cal = input(f"\nCalibrate {name}? (y/n): ").strip().lower()
            if do_cal == 'y':
                num = int(input("Số mẫu (khuyến nghị 10): ") or "10")
                classifier.calibrate(wtype, num)
    else:
        # Test phân loại
        print("\nNhấn Enter để gõ và phân loại. Ctrl+C để dừng.\n")
        try:
            while True:
                input(">> Nhấn Enter, sau đó gõ vào vật thể...")
                time.sleep(0.1)
                audio = classifier.record_knock()
                waste_type, confidence, _ = classifier.classify(audio)
                print(f"\n{'='*40}")
                print(f"KẾT QUẢ: {classifier.WASTE_NAMES[waste_type]}")
                print(f"Độ tin cậy: {confidence:.1%}")
                print(f"{'='*40}\n")
        except KeyboardInterrupt:
            print("\nDừng.")
