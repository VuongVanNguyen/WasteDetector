from __future__ import annotations

import json
import logging
import os
import time

import sounddevice as sd
import numpy as np
import scipy.signal as signal
import scipy.fft as fft

from pi_config import (
    WASTE_NONE,
    WASTE_PLASTIC,
    WASTE_GLASS,
    WASTE_PAPER,
    WASTE_METAL,
    WASTE_NAMES,
    KNOCK_COUNT,
    KNOCK_INTERVAL_S,
    AUDIO_WINDOW_S,
    AUDIO_SEQUENCE_MARGIN_S,
    AUDIO_DEVICE_ID,
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_FILTER_LOW,
    AUDIO_FILTER_HIGH
)

AUDIO_OK = "OK"
AUDIO_SILENT = "SILENT"
AUDIO_CLIPPED = "CLIPPED"

# Cùng thư mục với file này (giống camera_roi.json) — không phụ thuộc cwd
# khi autostart từ rc.local.
CALIBRATION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "audio_calibration.json"
)
_CALIBRATION_VERSION = 1

# Thứ tự cố định để log/hiển thị — KHÔNG mang nghĩa ưu tiên.
_AUDIO_TYPES = (WASTE_PLASTIC, WASTE_GLASS, WASTE_PAPER, WASTE_METAL)

log = logging.getLogger(__name__)

class ESP32AudioClassifier:

    def __init__(self, device_id = AUDIO_DEVICE_ID):
        self.device_id = device_id
        self.sample_rate = AUDIO_SAMPLE_RATE
        self.record_duration = AUDIO_WINDOW_S
        self.channels = AUDIO_CHANNELS
        self.filter_low = AUDIO_FILTER_LOW
        self.filter_high = AUDIO_FILTER_HIGH

        self.freq_ranges = {
            WASTE_METAL: (2000, 6000),
            WASTE_GLASS: (1500, 4000),
            WASTE_PLASTIC: (500, 2000),
            WASTE_PAPER: (100, 800),
        }

        self.noise_min_threshold = 0.01
        self.noise_max_threshold = 0.99

        # Trích đặc trưng / phân loại — cần tinh chỉnh trên vật liệu thật
        self.envelope_ratio = 0.10        # sustain: envelope > 10% peak
        self.impact_pre_roll_s = 0.005    # giữ 5ms trước đỉnh — không cắt mất sườn lên
        self.sustain_metal_ratio = 0.67   # sustain > 67% độ dài đoạn → boost METAL
        self.sustain_metal_boost = 1.2
        self.clip_penalty = 0.7           # nhân confidence khi tín hiệu bị clip
        self.min_band_width_hz = 200.0    # dải calibrate hẹp nhất cho phép
        self.manual_window_s = 1.0        # cửa sổ thu khi gõ TAY (Mode 1/2) — người không bấm kịp AUDIO_WINDOW_S
        self.knock_min_gap_ratio = 0.5    # 2 va đập cách nhau ≥ 0.5 × KNOCK_INTERVAL_S
        self.knock_rel_height = 0.3       # đỉnh < 30% đỉnh mạnh nhất chuỗi → không phải va đập

        # Trạng thái chuỗi thu liên tục — chỉ worker thread chạm vào, trừ
        # _seq_frames/_seq_overflow do callback PortAudio ghi (đọc lại SAU
        # khi stream đã dừng nên không cần lock).
        self._seq_stream = None
        self._seq_buffer = None
        self._seq_frames = 0
        self._seq_overflow = False
        self._seq_count = 0

        self.calibration_file = CALIBRATION_FILE
        self.calibration_data = {}        # {str(waste_type): {...}} — đúng mã WASTE_* của pi_config
        self.noise_floor = None           # {"rms", "peak", "threshold"} sau Mode 3
        self.load_calibration()

    def list_devices(self):
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            print(f"{i}: {dev['name']} (input: {dev['max_input_channels']}, output: {dev['max_output_channels']})")

    def record_knock(self, duration=None):
        if duration is None:
            duration = self.record_duration
        window_samples = int(self.sample_rate * duration)
        try:
            audio_data = sd.rec(
                window_samples, samplerate=self.sample_rate, channels=self.channels, dtype='float32', device=self.device_id
                )
            sd.wait()
            return audio_data.flatten()
        # ValueError: device theo tên không khớp / khớp nhiều thiết bị, hoặc
        # tham số không hợp lệ với thiết bị.
        except (sd.PortAudioError, ValueError) as e:
            log.error(f"Error recording audio (device={self.device_id!r}): {e}")
            return np.array([], dtype=np.float32)

    def remove_dc_offset(self, audio_data):
        return audio_data - np.mean(audio_data)

    def check_audio_confidence(self, audio_data):
        if audio_data.size == 0:
            log.warning("No audio data (recording failed).")
            return AUDIO_SILENT
        # Clip xảy ra tại ADC → xét trên tín hiệu THÔ.
        if np.max(np.abs(audio_data)) > self.noise_max_threshold:
            log.warning("Audio clipping detected! Confidence may be reduced.")
            return AUDIO_CLIPPED
        # Im lặng xét SAU khi bỏ DC — offset DC không được tính là âm thanh.
        elif np.max(np.abs(self.remove_dc_offset(audio_data))) < self.noise_min_threshold:
            log.info("Audio below noise threshold. Likely no valid knock detected.")
            return AUDIO_SILENT
        else:
            log.info("Audio signal is within acceptable range.")
            return AUDIO_OK

    def filter_audio(self, audio_data):
        # butter() cũng có thể raise (filter_high >= Nyquist) → bọc chung try.
        try:
            sos = signal.butter(
                4, [self.filter_low, self.filter_high], btype='bandpass', output='sos', fs = self.sample_rate
                )
            filtered_audio = signal.sosfiltfilt(sos, audio_data)
            return filtered_audio
        except ValueError as e:
            log.error(f"Error filtering audio: {e}. Bypassing filter.")
            return audio_data

    def _extract_impact(self, audio_data):
        """Cắt đoạn bắt đầu ngay trước đỉnh va đập, dài tối đa record_duration.

        Va đập không nằm cố định ở đầu cửa sổ thu (Mode 1/2 thu 1s gõ tay;
        đoạn từ split_knocks đã căn sẵn nên bước này gần như không cắt gì).
        Căn theo đỉnh giúp sustain đo từ lúc va đập và đặc trưng giữa
        calibrate/vận hành cùng độ dài, so sánh được với nhau.
        """
        if audio_data.size == 0:
            return audio_data
        peak_idx = int(np.argmax(np.abs(audio_data)))
        start = max(0, peak_idx - int(self.impact_pre_roll_s * self.sample_rate))
        max_len = int(self.record_duration * self.sample_rate)
        return audio_data[start:start + max_len]

    def analyze_fft(self, audio_data):
        """Trích đặc trưng phổ từ tín hiệu THÔ (chưa bỏ DC, chưa lọc).

        Raise ValueError nếu audio_data rỗng — gọi check_audio_confidence trước.
        """
        audio_data = np.asarray(audio_data).ravel()
        if audio_data.size == 0:
            raise ValueError("analyze_fft: audio_data rỗng")

        x = self.remove_dc_offset(audio_data.astype(np.float64))
        x = self.filter_audio(x)
        x = self._extract_impact(x)
        n = len(x)
        if n < 2:
            raise ValueError("analyze_fft: đoạn va đập quá ngắn")

        # Không nhân cửa sổ Hann: đoạn bắt đầu ngay tại va đập, Hann = 0 ở mép
        # sẽ xóa đúng phần năng lượng mạnh nhất. Tín hiệu tự phân rã về ~0.
        yf = fft.rfft(x)
        xf = fft.rfftfreq(n, 1.0 / self.sample_rate)
        xf, yf = xf[1:], yf[1:]                     # bỏ bin DC
        magnitude = 2.0 / n * np.abs(yf)

        dominant_freq = float(xf[np.argmax(magnitude)])

        energy_bands = {}
        for waste_type, (f_low, f_high) in self.freq_ranges.items():
            band_mask = (xf >= f_low) & (xf <= f_high)
            energy_bands[waste_type] = float(np.sum(magnitude[band_mask] ** 2))

        # Envelope Hilbert thay vì |x|: |x| chạm 0 mỗi nửa chu kỳ nên đếm
        # thiếu mẫu. Ngưỡng không thấp hơn noise_min_threshold — tránh gõ nhẹ
        # khiến 10% peak chìm dưới nhiễu nền và sustain phình ra hết cửa sổ.
        envelope = np.abs(signal.hilbert(x))
        env_threshold = max(self.envelope_ratio * float(np.max(envelope)),
                            self.noise_min_threshold)
        sustain_time = float(np.count_nonzero(envelope > env_threshold)) / self.sample_rate

        return {
            'dominant_freq': dominant_freq,
            'magnitude': magnitude,
            'frequencies': xf,
            'energy_bands': energy_bands,
            'sustain_time': sustain_time,
            'max_amplitude': float(np.max(np.abs(audio_data))),
            'segment_s': n / self.sample_rate,
        }

    def classify(self, audio_data):
        """Trả (waste_type, confidence ∈ [0,1], analysis | None)."""
        audio_data = np.asarray(audio_data).ravel()

        status = self.check_audio_confidence(audio_data)
        if status == AUDIO_SILENT:
            return WASTE_NONE, 0.0, None

        analysis = self.analyze_fft(audio_data)
        analysis['status'] = status

        energy_bands = analysis['energy_bands']
        total_energy = sum(energy_bands.values())
        if total_energy <= 0:
            log.info("[Audio] Không có năng lượng trong các dải đặc trưng.")
            return WASTE_NONE, 0.0, analysis

        energy_ratios = {wt: e / total_energy for wt, e in energy_bands.items()}

        # Tinh chỉnh theo sustain rồi chuẩn hóa lại → tổng vẫn = 1, confidence
        # vẫn cùng thang tỷ lệ với khi không boost.
        scores = dict(energy_ratios)
        sustain = analysis['sustain_time']
        if sustain > self.sustain_metal_ratio * analysis['segment_s']:
            scores[WASTE_METAL] *= self.sustain_metal_boost
            score_sum = sum(scores.values())
            scores = {wt: s / score_sum for wt, s in scores.items()}

        best_type = max(scores, key=scores.get)
        confidence = scores[best_type]
        if status == AUDIO_CLIPPED:
            confidence *= self.clip_penalty
        confidence = float(np.clip(confidence, 0.0, 1.0))

        analysis['energy_ratios'] = energy_ratios
        analysis['scores'] = scores

        log.info("[Audio] Tần số chủ đạo: %.1f Hz", analysis['dominant_freq'])
        log.info("[Audio] Sustain: %.3fs (đoạn %.3fs)", sustain, analysis['segment_s'])
        log.info("[Audio] Năng lượng dải tần:")
        for wt in _AUDIO_TYPES:
            ratio = energy_ratios[wt]
            log.info("  %-12s: %6.2f%% %s", WASTE_NAMES[wt], ratio * 100, "█" * int(ratio * 30))
        log.info("[Audio] >> Kết quả: %s (conf=%.2f%s)", WASTE_NAMES[best_type], confidence,
                 ", CLIPPED" if status == AUDIO_CLIPPED else "")

        return best_type, confidence, analysis

    def _seq_callback(self, indata, frames, time_info, status):
        """Callback PortAudio — chạy trên thread audio, chỉ chép dữ liệu."""
        if status.input_overflow:
            self._seq_overflow = True
        n = min(frames, self._seq_buffer.size - self._seq_frames)
        self._seq_buffer[self._seq_frames:self._seq_frames + n] = indata[:n, 0]
        self._seq_frames += n
        if self._seq_frames >= self._seq_buffer.size:
            raise sd.CallbackStop

    def start_sequence(self, knock_count=KNOCK_COUNT) -> bool:
        """Bắt đầu thu nền cho cả chuỗi knock_count lần gõ. KHÔNG chặn.

        Gọi TRƯỚC khi gửi lệnh KNOCK. Trả False nếu không mở được thiết bị.
        """
        if self._seq_stream is not None:
            log.warning("[Audio] start_sequence khi chuỗi cũ chưa finish — hủy chuỗi cũ.")
            self.abort_sequence()

        knock_count = max(1, int(knock_count))
        duration = knock_count * KNOCK_INTERVAL_S + AUDIO_SEQUENCE_MARGIN_S
        self._seq_buffer = np.zeros(int(duration * self.sample_rate), dtype=np.float32)
        self._seq_frames = 0
        self._seq_overflow = False
        self._seq_count = knock_count
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate, channels=self.channels, dtype='float32',
                device=self.device_id, callback=self._seq_callback,
            )
            stream.start()
        except (sd.PortAudioError, ValueError) as e:
            log.error("[Audio] Không mở được luồng thu (device=%r): %s", self.device_id, e)
            self._seq_buffer = None
            return False
        self._seq_stream = stream
        log.debug("[Audio] Bắt đầu thu chuỗi %d lần gõ (%.2fs)", knock_count, duration)
        return True

    def _stop_stream(self):
        """Dừng + đóng stream hiện tại. Sau hàm này callback không còn chạy."""
        stream, self._seq_stream = self._seq_stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except sd.PortAudioError as e:
            log.error("[Audio] Lỗi dừng luồng thu: %s", e)
        try:
            stream.close()
        except sd.PortAudioError as e:
            log.error("[Audio] Lỗi đóng luồng thu: %s", e)

    def abort_sequence(self):
        """Hủy chuỗi đang thu, bỏ dữ liệu. An toàn khi không có chuỗi nào."""
        self._stop_stream()
        self._seq_buffer = None
        self._seq_frames = 0

    def finish_sequence(self) -> list[tuple[int, float]]:
        """Dừng thu, tách va đập, phân loại từng lần gõ → [(type, conf), ...].

        Gọi sau KNOCK_DONE cuối (hoặc khi chờ nó timeout). Không bao giờ
        raise — lỗi trả [] để fusion tự bù bằng camera.
        """
        if self._seq_stream is None or self._seq_buffer is None:
            log.error("[Audio] finish_sequence khi chưa start_sequence thành công.")
            return []

        t0 = time.monotonic()
        self._stop_stream()
        audio = self._seq_buffer[:self._seq_frames]
        count = self._seq_count
        self._seq_buffer = None

        if self._seq_overflow:
            log.warning("[Audio] Buffer overflow khi thu — có thể đã mất mẫu.")

        try:
            segments = self.split_knocks(audio, count)
            results = []
            for seg in segments:
                waste_type, confidence, _ = self.classify(seg)
                results.append((waste_type, confidence))
        except Exception as e:
            log.error("[Audio] finish_sequence lỗi: %s", e)
            return []

        log.info("[Audio] Chuỗi: %d/%d lần gõ phân tích được, %s (xử lý %.0f ms)",
                 len(results), count,
                 [(WASTE_NAMES[t], round(c, 2)) for t, c in results],
                 (time.monotonic() - t0) * 1000)
        return results

    def split_knocks(self, audio_data, count):
        """Tìm tối đa count va đập trong bản ghi dài → list đoạn THÔ, theo thời gian."""
        audio_data = np.asarray(audio_data).ravel()
        if audio_data.size == 0 or count < 1:
            return []

        x = self.filter_audio(self.remove_dc_offset(audio_data.astype(np.float64)))
        envelope = np.abs(signal.hilbert(x))

        min_gap = max(1, int(self.knock_min_gap_ratio * KNOCK_INTERVAL_S * self.sample_rate))
        peaks, props = signal.find_peaks(envelope, height=self.noise_min_threshold,
                                         distance=min_gap)
        if peaks.size == 0:
            log.info("[Audio] Không tìm thấy va đập nào vượt ngưỡng nhiễu.")
            return []

        # Cùng vật, cùng servo → các va đập mạnh ngang nhau; đỉnh yếu hẳn là
        # tiếng servo / tiếng vọng, không được lấp vào chỗ lần gõ bị trượt.
        heights = props['peak_heights']
        keep = heights >= self.knock_rel_height * float(np.max(heights))
        peaks, heights = peaks[keep], heights[keep]

        strongest = np.argsort(heights)[::-1][:count]
        peaks = np.sort(peaks[strongest])
        if peaks.size < count:
            log.warning("[Audio] Chỉ tìm thấy %d/%d va đập (gõ trượt / vật quá nhẹ?).",
                        peaks.size, count)

        pre_roll = int(self.impact_pre_roll_s * self.sample_rate)
        seg_len = int(self.record_duration * self.sample_rate)
        starts = [max(0, int(p) - pre_roll) for p in peaks]
        segments = []
        for i, start in enumerate(starts):
            end = start + seg_len
            if i + 1 < len(starts):
                end = min(end, starts[i + 1])     # không lấn sang va đập kế tiếp
            segments.append(audio_data[start:end])
        return segments

    def _make_band(self, center, std):
        """Dải center ± 2σ, rộng tối thiểu min_band_width_hz, nằm trong dải lọc."""
        width = self.min_band_width_hz
        lo, hi = center - 2 * std, center + 2 * std
        if hi - lo < width:
            lo, hi = center - width / 2, center + width / 2
        lo = max(lo, float(self.filter_low))
        hi = min(hi, float(self.filter_high))
        if hi - lo < width:                    # bị kẹp ở mép dải lọc
            if lo <= self.filter_low:
                hi = lo + width
            else:
                lo = hi - width
        return (float(lo), float(hi))

    def calibrate(self, waste_type, num_samples=10):
        """Gõ TAY num_samples lần vào 1 loại vật liệu → cập nhật dải tần + lưu file.

        Trả True nếu calibrate xong, False nếu thiết bị thu âm lỗi.
        """
        if waste_type not in _AUDIO_TYPES:
            raise ValueError(f"waste_type không hợp lệ: {waste_type!r}")
        num_samples = max(1, int(num_samples))

        name = WASTE_NAMES[waste_type]
        print(f"\n=== CALIBRATE: {name} ===")
        print(f"Chuẩn bị gõ {num_samples} lần vào vật liệu {name}")

        samples = []
        while len(samples) < num_samples:
            input(f"\nMẫu {len(samples) + 1}/{num_samples} - Nhấn Enter rồi gõ "
                  f"(trong {self.manual_window_s:.1f}s)...")
            audio = self.record_knock(self.manual_window_s)
            if audio.size == 0:
                print("  Lỗi thiết bị thu âm — dừng calibrate.")
                return False

            # Mẫu im lặng / bị clip làm lệch trung bình → bỏ, thu lại.
            status = self.check_audio_confidence(audio)
            if status == AUDIO_SILENT:
                print("  Không thu được tiếng gõ — thử lại.")
                continue
            if status == AUDIO_CLIPPED:
                print("  Tín hiệu bị clip — gõ nhẹ hơn hoặc giảm gain mic, thử lại.")
                continue

            analysis = self.analyze_fft(audio)
            samples.append({
                'dominant_freq': analysis['dominant_freq'],
                'sustain_time': analysis['sustain_time'],
                'energy_bands': {str(k): v for k, v in analysis['energy_bands'].items()},
            })
            print(f"  Tần số: {analysis['dominant_freq']:.1f} Hz, "
                  f"Sustain: {analysis['sustain_time']:.3f}s")

        freqs = np.array([s['dominant_freq'] for s in samples])
        avg_freq = float(np.mean(freqs))
        std_freq = float(np.std(freqs))
        freq_range = self._make_band(avg_freq, std_freq)
        avg_sustain = float(np.mean([s['sustain_time'] for s in samples]))

        print(f"\n>> Trung bình tần số: {avg_freq:.1f} ± {std_freq:.1f} Hz")
        print(f">> Dải áp dụng:       {freq_range[0]:.0f} – {freq_range[1]:.0f} Hz")
        print(f">> Sustain trung bình: {avg_sustain:.3f}s")

        self.calibration_data[str(waste_type)] = {
            'name': name,
            'avg_freq': avg_freq,
            'std_freq': std_freq,
            'freq_range': list(freq_range),
            'avg_sustain': avg_sustain,
            'samples': samples,
        }
        self.freq_ranges[waste_type] = freq_range   # áp dụng ngay, không chờ load lại
        self.save_calibration()
        return True

    def measure_noise_floor(self, duration_s=5.0):
        """Thu duration_s giây nhiễu nền (KHÔNG gõ) → {"rms", "peak", "threshold"}.

        Đo trên tín hiệu đã bỏ DC, chưa lọc — đúng thứ check_audio_confidence
        so với noise_min_threshold. Ngưỡng đề xuất = max(3×RMS, 1.5×peak):
        phép kiểm tra im lặng so ĐỈNH của cửa sổ với ngưỡng, mà đỉnh nhiễu
        Gauss đã ~4×RMS → chỉ 3×RMS thì nhiễu thuần cũng lọt qua.
        Trả None nếu thu âm lỗi.
        """
        audio = self.record_knock(duration_s)
        if audio.size == 0:
            return None
        x = self.remove_dc_offset(audio.astype(np.float64))
        rms = float(np.sqrt(np.mean(x ** 2)))
        peak = float(np.max(np.abs(x)))
        return {'rms': rms, 'peak': peak, 'threshold': max(3 * rms, 1.5 * peak)}

    def apply_noise_floor(self, result):
        """Áp dụng ngưỡng từ measure_noise_floor() và lưu file. Trả True nếu OK."""
        threshold = result['threshold']
        if not 0 < threshold < self.noise_max_threshold:
            log.error("[Audio] Ngưỡng nhiễu %.4f ngoài (0, %.2f) — môi trường quá ồn "
                      "hoặc gain mic quá cao, không áp dụng.", threshold, self.noise_max_threshold)
            return False
        self.noise_floor = {k: float(result[k]) for k in ('rms', 'peak', 'threshold')}
        self.noise_min_threshold = self.noise_floor['threshold']
        return self.save_calibration()

    def save_calibration(self):
        data = {
            'version': _CALIBRATION_VERSION,
            'sample_rate': self.sample_rate,
            'materials': self.calibration_data,
        }
        if self.noise_floor is not None:
            data['noise_floor'] = self.noise_floor

        # Ghi file tạm rồi thay thế — mất điện giữa chừng không làm hỏng file cũ.
        tmp_path = self.calibration_file + ".tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.calibration_file)
        except OSError as e:
            log.error("[Audio] Không lưu được calibration %s: %s", self.calibration_file, e)
            return False
        log.info("[Audio] Đã lưu calibration vào %s", self.calibration_file)
        return True

    def load_calibration(self):
        """Đọc file calibration, cập nhật freq_ranges + noise threshold.

        Mục hỏng/không hợp lệ bị bỏ qua (giữ mặc định) — không bao giờ raise.
        """
        if not os.path.exists(self.calibration_file):
            log.info("[Audio] Chưa có calibration. Dùng ngưỡng mặc định.")
            return False
        try:
            with open(self.calibration_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.error("[Audio] Không đọc được %s: %s — dùng mặc định.", self.calibration_file, e)
            return False
        if not isinstance(data, dict) or not isinstance(data.get('materials'), dict):
            log.error("[Audio] %s sai định dạng — dùng mặc định.", self.calibration_file)
            return False

        if data.get('sample_rate') != self.sample_rate:
            log.warning("[Audio] Calibration đo ở %s Hz, hiện chạy %s Hz — nên calibrate lại.",
                        data.get('sample_rate'), self.sample_rate)

        for key, entry in data['materials'].items():
            try:
                waste_type = int(key)
                lo, hi = (float(v) for v in entry['freq_range'])
            except (ValueError, TypeError, KeyError):
                log.warning("[Audio] Bỏ qua mục calibration hỏng: %r", key)
                continue
            if waste_type not in _AUDIO_TYPES or not 0 <= lo < hi:
                log.warning("[Audio] Bỏ qua mục calibration không hợp lệ: %r", key)
                continue
            self.freq_ranges[waste_type] = (lo, hi)
            self.calibration_data[str(waste_type)] = entry

        noise_floor = data.get('noise_floor')
        if noise_floor is not None:
            try:
                threshold = float(noise_floor['threshold'])
            except (ValueError, TypeError, KeyError):
                threshold = None
            if threshold is not None and 0 < threshold < self.noise_max_threshold:
                self.noise_floor = noise_floor
                self.noise_min_threshold = threshold
            else:
                log.warning("[Audio] noise_floor trong file không hợp lệ — giữ %.4f",
                            self.noise_min_threshold)

        log.info("[Audio] Đã load calibration từ %s", self.calibration_file)
        return True


# ----------------------------------------------------------------------
# Test độc lập
# ----------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    classifier = ESP32AudioClassifier()
    classifier.list_devices()
    print(f"\nThiết bị đang dùng: {classifier.device_id!r} (None = mặc định)")
    print(f"noise_min_threshold hiện tại: {classifier.noise_min_threshold:.4f}")

    print("\n=== CHỌN CHẾ ĐỘ ===")
    print("1. Test phân loại (gõ và nhận diện)")
    print("2. Calibrate từng loại vật liệu")
    print("3. Đo nhiễu nền, đề xuất noise_threshold")
    print(f"4. Thử chuỗi {KNOCK_COUNT} lần gõ (thu liên tục như vận hành thật)")
    choice = input("Chọn (1/2/3/4): ").strip()

    try:
        if choice == '2':
            print("\nCalibrate từng loại:")
            for wtype in (WASTE_METAL, WASTE_GLASS, WASTE_PLASTIC, WASTE_PAPER):
                name = WASTE_NAMES[wtype]
                if input(f"\nCalibrate {name}? (y/n): ").strip().lower() != 'y':
                    continue
                try:
                    num = int(input("Số mẫu (khuyến nghị 10): ").strip() or "10")
                except ValueError:
                    num = 10
                if not classifier.calibrate(wtype, num):
                    break

        elif choice == '3':
            input("\nGiữ môi trường như lúc vận hành (đèn, quạt...), KHÔNG gõ. "
                  "Nhấn Enter để đo 5s...")
            result = classifier.measure_noise_floor(5.0)
            if result is None:
                print("Lỗi thiết bị thu âm.")
            else:
                print(f"\nRMS nhiễu nền:  {result['rms']:.5f}")
                print(f"Đỉnh nhiễu nền: {result['peak']:.5f}")
                print(f"Đề xuất noise_threshold = {result['threshold']:.5f} "
                      f"(hiện tại {classifier.noise_min_threshold:.5f})")
                if input("Áp dụng và lưu? (y/n): ").strip().lower() == 'y':
                    if classifier.apply_noise_floor(result):
                        print("Đã lưu.")

        elif choice == '4':
            duration = KNOCK_COUNT * KNOCK_INTERVAL_S + AUDIO_SEQUENCE_MARGIN_S
            min_gap = classifier.knock_min_gap_ratio * KNOCK_INTERVAL_S
            print("\nNhấn Enter để bắt đầu, Ctrl+C để dừng.")
            while True:
                input(f"\n>> Enter, rồi gõ {KNOCK_COUNT} lần trong {duration:.1f}s "
                      f"(cách nhau > {min_gap:.2f}s)...")
                if not classifier.start_sequence(KNOCK_COUNT):
                    print("Lỗi thiết bị thu âm.")
                    break
                try:
                    time.sleep(duration)
                except KeyboardInterrupt:
                    classifier.abort_sequence()
                    raise
                results = classifier.finish_sequence()
                print(f"\n{'=' * 40}")
                for i, (wt, conf) in enumerate(results, 1):
                    print(f"Lần {i}: {WASTE_NAMES[wt]:12s} conf={conf:.1%}")
                if len(results) < KNOCK_COUNT:
                    print(f"(chỉ tách được {len(results)}/{KNOCK_COUNT} va đập)")
                print(f"{'=' * 40}")

        else:
            print("\nNhấn Enter để gõ và phân loại. Ctrl+C để dừng.\n")
            while True:
                input(f">> Nhấn Enter, sau đó gõ vào vật thể (trong "
                      f"{classifier.manual_window_s:.1f}s)...")
                audio = classifier.record_knock(classifier.manual_window_s)
                waste_type, confidence, _ = classifier.classify(audio)
                print(f"\n{'=' * 40}")
                print(f"KẾT QUẢ: {WASTE_NAMES[waste_type]}")
                print(f"Độ tin cậy: {confidence:.1%}")
                print(f"{'=' * 40}\n")

    except KeyboardInterrupt:
        print("\nDừng.")
