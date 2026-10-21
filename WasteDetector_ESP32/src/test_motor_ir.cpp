// ============================================================================
// TEST MOTOR + IR — harness bàn phím cho engine motion (GA25-370 + 4x TCRT5000)
// ============================================================================
// Flash:    pio run -e test_motor_ir --target upload
// Monitor:  pio device monitor -e test_motor_ir
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │  SPACE = DỪNG KHẨN — phanh ngay, hủy cả chuỗi thao tác.      │
//   │  Có tác dụng MỌI lúc motor chạy: quay, dò, về HOME, hiệu     │
//   │  chuẩn, jog, và cả lúc đếm ngược tự về HOME khi boot.        │
//   │  Phím khác trong lúc motor chạy bị BỎ QUA.                   │
//   └──────────────────────────────────────────────────────────────┘
//
//   '1' Nhựa  '2' Thủy tinh  '3' Giấy  '4' Kim loại  → 1 CHU KỲ ĐẦY ĐỦ:
//        HOME → quay tới ngăn → chờ giả lập xả → BẮT BUỘC quay về HOME.
//        Nếu lúc bấm ống không ở HOME (chu kỳ trước bị ngắt), engine tự về
//        HOME trước rồi mới đi — không bao giờ đi tắt ngăn → ngăn.
//   '0' về HOME           'h' xác định lại vị trí     's' trạng thái
//   'i' đọc mức 4 IR
//   'c' HIỆU CHUẨN: HOME → Kim loại → Nhựa → HOME, đo thời gian quay mỗi chiều
//       (bắt buộc chạy 1 lần khi IR còn tốt — chế độ canh giờ cần số đo này)
//   'd' xóa đánh dấu IR chết (sau khi đã SỬA cảm biến)
//   'f' mở khóa FAULT (sau khi đã tháo xoắn, ống ở Thủy tinh)
//   '[' jog CCW   ']' jog CW — quay TỰ DO tháo xoắn, SPACE để dừng
//
//   Kim loại ─── Giấy ─── THỦY TINH ─── Nhựa     ╳ cấm khép vòng
//     +180°      +90°     0° (HOME)     −90°
//              <──── CW ────   ── CCW ──>
//
// Dò chiều motor: từ HOME bấm '3' (Giấy). Tới Giấy là đúng; đi về phía Nhựa →
// hệ dừng ở cạnh đầu tiên, đặt MOTOR_DIR_INVERTED = 1.

#include <Arduino.h>
#include "config.h"
#include "motion.h"

#define ESTOP_KEY           ' '
#define DISCHARGE_SIM_MS    (DOOR_HOLD_MS + DOOR_SETTLE_MS)   // = thời gian cửa MG90S mở + đóng

static void printMenu() {
    Serial.println("\n--- SPACE=DUNG KHAN | '1'..'4'=chu ky (toi ngan -> xa -> ve HOME) | '0'=HOME"
                   " 'h'=do vi tri 's'=trang thai 'i'=IR | 'c'=hieu chuan 'd'=xoa IR chet 'f'=mo khoa"
                   " | '['/']'=jog ---");
}

// motion.cpp gọi mỗi ~1-2ms khi motor chạy. Chỉ SPACE là dừng; phím khác bị
// nuốt để không xếp hàng thành lệnh chạy ngay sau khi thao tác hiện tại xong.
static bool estopPressed() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == ESTOP_KEY) return true;
        if (c != '\r' && c != '\n')
            Serial.printf("  (bo qua '%c' — dang chay. SPACE de dung khan)\n", c);
    }
    return false;
}

// Chờ có thể dừng khẩn. true = bị dừng.
static bool waitOrStop(uint32_t ms) {
    uint32_t t0 = millis();
    while (millis() - t0 < ms) {
        if (estopPressed()) return true;
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    return false;
}

static void doJog(int dir) {
    Serial.printf("\n[JOG] Quay TU DO %s — KHONG kiem tra IR/xoan/FAULT. SPACE de dung (tu dung sau %dms).\n",
                  dir == MOTOR_DIR_CW ? "CW" : "CCW", MOTOR_FREE_JOG_MAX_MS);
    motionJogStart(dir);
    bool byUser = waitOrStop(MOTOR_FREE_JOG_MAX_MS);
    motionJogStop();
    Serial.println(byUser ? "[JOG] Da dung." : "[JOG] DUNG TU DONG — het thoi gian an toan.");
    Serial.println("[JOG] Vi tri = CHUA BIET. Dua ong ve Thuy tinh roi bam 'h' (hoac 'f' neu dang khoa).");
}

// Một chu kỳ thật: tới ngăn → xả (chờ đúng thời gian cửa MG90S) → về HOME.
// Thủy tinh: ngăn xả chính là HOME nên không quay, chỉ xả tại chỗ.
//
// Chu kỳ chỉ dừng giữa chừng khi quay lỗi hoặc bấm SPACE. Khi đó ống nằm lại
// ở ngăn khác HOME — KHÔNG tự thử lại; chu kỳ kế tiếp (hoặc '0') sẽ tự về HOME
// trước khi làm gì khác.
static void doCycle(int target) {
    Serial.printf("\n[CYCLE] === Bat dau chu ky: %s ===\n", motionPosName(target));
    if (!motionRotateTo(target)) {
        Serial.println("[CYCLE] Dung giua chung (loi/dung khan). Chu ky sau se tu ve HOME truoc.");
        return;
    }
    Serial.printf("[CYCLE] Gia lap xa rac %dms... (SPACE de dung)\n", DISCHARGE_SIM_MS);
    if (waitOrStop(DISCHARGE_SIM_MS)) {
        Serial.println("[CYCLE] Dung khan luc dang xa — ong o yen tai ngan. Bam '0' (hoac chu ky sau) de ve HOME.");
        return;
    }
    Serial.println("[CYCLE] Xa xong — ve HOME.");
    if (motionGoHome()) Serial.println("[CYCLE] === Hoan tat: ong da o HOME, san sang vat tiep theo ===");
    else                Serial.println("[CYCLE] KHONG ve duoc HOME — xem loi phia tren.");
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== TEST MOTOR + IR (GA25-370 + DRV8871 + 4x TCRT5000) ===");
    Serial.printf("DRV8871: IN1=GPIO%d IN2=GPIO%d | speed=%d brake=%dms | dao chieu=%s\n",
                  PIN_MOTOR_IN1, PIN_MOTOR_IN2, MOTOR_SPEED, MOTOR_BRAKE_MS,
                  MOTOR_DIR_INVERTED ? "CO" : "KHONG");
    Serial.printf("IR: Kim loai=%d Giay=%d Thuy tinh=%d Nhua=%d\n",
                  PIN_IR_METAL, PIN_IR_PAPER, PIN_IR_GLASS, PIN_IR_PLASTIC);
    Serial.println("Cung: Kim loai(+180) - Giay(+90) - THUY TINH/HOME(0) - Nhua(-90)");
    Serial.println("!! SPACE = DUNG KHAN bat cu luc nao motor dang chay.");

    motionBegin();
    motionSetAbortPoll(estopPressed);
    motionHomeOnBoot();

    printMenu();
}

void loop() {
    if (!Serial.available()) { vTaskDelay(pdMS_TO_TICKS(5)); return; }

    char cmd = Serial.read();
    if (cmd == '\n' || cmd == '\r') return;

    switch (cmd) {
        case ESTOP_KEY:
            motionCoast();
            Serial.println("[DUNG KHAN] Motor dang dung yen.");
            return;

        case '1': doCycle(WASTE_PLASTIC); break;
        case '2': doCycle(WASTE_GLASS);   break;
        case '3': doCycle(WASTE_PAPER);   break;
        case '4': doCycle(WASTE_METAL);   break;

        case '0': motionGoHome();       break;
        case 'h': motionSeek();         break;
        case 's': motionPrintState();   break;
        case 'i': motionPrintIrDump();  break;
        case 'c': motionCalibrate();    break;
        case 'd': motionClearDeadMask(); break;
        case 'f': motionClearFault();   break;

        case '[': doJog(MOTOR_DIR_CCW); break;
        case ']': doJog(MOTOR_DIR_CW);  break;

        default:
            Serial.printf("[?] Lenh khong biet: '%c'.\n", cmd);
            break;
    }
    printMenu();
}
