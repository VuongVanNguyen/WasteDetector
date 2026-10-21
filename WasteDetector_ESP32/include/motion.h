#pragma once

// ============================================================
// motion — engine quay ống: motor DRV8871 + 4x TCRT5000, HOME = cảm biến Thủy tinh
// ============================================================
// Dùng CHUNG bởi test_motor_ir.cpp, test_full_cycle.cpp và task_realtime.cpp.
// Mô hình cung + hằng số: config.h. Cơ chế chi tiết: đầu motion.cpp.

#include "config.h"

#define MOTION_TWIST_UNKNOWN    (-999)

// Khởi tạo LEDC motor, ISR 4 chân IR, mở NVS và nạp trạng thái lần chạy trước.
// Gọi MỘT lần, trong task sẽ điều khiển motor (Core 1).
void motionBegin();

// Bắt buộc về HOME khi khởi động. Gọi MỘT lần ngay sau motionBegin(), TRƯỚC
// khi nhận lệnh. Chờ BOOT_HOME_GRACE_MS (có thể dừng khẩn trong lúc chờ), đọc
// IR xác định vị trí — đứng lưng chừng thì dò — rồi quay về Thủy tinh.
bool motionHomeOnBoot();

// Vị trí hiện tại: WASTE_PLASTIC..WASTE_METAL, hoặc WASTE_NONE (chưa biết).
int  motionPosition();

// true nếu vị trí hiện tại là ƯỚC LƯỢNG bằng canh giờ (cảm biến tại đó đã chết),
// không phải do chính cảm biến xác nhận.
bool motionPositionEstimated();

// true khi ống đang đậu tại HOME (Thủy tinh).
bool motionIsHome();

// Độ xoắn CÓ DẤU của station, gốc tại HOME. MOTION_TWIST_UNKNOWN nếu không rõ.
int  motionTwistDeg(int pos);

const char* motionPosName(int pos);

// Xác định vị trí: đọc IR; không cảm biến nào bị che thì dò (mặc định CW).
bool motionSeek();

// Quay tới một ngăn (WASTE_PLASTIC..WASTE_METAL). Chưa biết vị trí thì tự dò trước.
bool motionRotateTo(int target);

// Về HOME = motionRotateTo(HOME_POS).
bool motionGoHome();

// Chạy quét hiệu chuẩn: HOME → Kim loại → Nhựa → HOME. Đo lại thời gian quay
// mỗi chiều (dùng cho chế độ canh giờ khi IR hỏng) và xác nhận cả 4 IR đều nhận.
bool motionCalibrate();

// Thả trôi cầu H (Hi-Z).
void motionCoast();

// ------------------------------------------------------------ Cảm biến hỏng
// Bit i = station i (0=Kim loại,1=Giấy,2=Thủy tinh,3=Nhựa) đã bị đánh dấu chết.
// Lưu trong NVS — còn nhớ sau khi mất điện.
uint8_t motionDeadMask();
void    motionClearDeadMask();        // gọi sau khi đã SỬA cảm biến

// ------------------------------------------------------------ Bảo vệ
bool        motionFaulted();
const char* motionFaultReason();      // NULL nếu không có lỗi
// Mở khóa. Người vận hành xác nhận dây đã được tháo xoắn → bỏ gợi ý vị trí cũ
// trong NVS và dò lại. false nếu dò không ra.
bool        motionClearFault();

// Dừng khẩn: hàm được gọi mỗi ~2ms trong MỌI lúc motor chạy (quay, dò, hiệu
// chuẩn, chờ boot). Trả về true → phanh ngay, hủy cả chuỗi thao tác đang chạy.
void motionSetAbortPoll(bool (*fn)());

// ------------------------------------------------------------ Jog tháo xoắn
// Quay TỰ DO, không IR, không trần xoắn, không bị FAULT chặn — lối thoát khi
// dây đã cuốn. Caller tự gọi motionJogStop(). Sau jog vị trí = CHƯA BIẾT.
void motionJogStart(int dir);
void motionJogStop();

void motionPrintState();
void motionPrintIrDump();
