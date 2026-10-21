// ============================================================================
// motion — engine quay ống: GA25-370 qua DRV8871 + 4x TCRT5000
//          HOME = CẢM BIẾN THỦY TINH
// ============================================================================
//
//     Kim loại ─── Giấy ─── THỦY TINH ─── Nhựa  ░░ vùng cấm ░░
//       +180°      +90°     0° (HOME)     −90°
//       idx 0      idx 1       idx 2      idx 3
//                 <──── CW ────   ── CCW ──>
//
// (1) DỪNG TRÊN CẠNH IR. ISR chỉ ghi sự kiện (station, thời điểm) vào hàng đợi
//     vòng; task đọc mỗi 1ms và phanh. Cạnh lặp của cảm biến vừa rời bị bỏ qua
//     (LM393 không có hysteresis, rung tại rìa tấm phản quang).
//
// (2) THỨ TỰ. Mỗi cạnh phải là station SỐNG kế tiếp trên đường đi. Cạnh lạ →
//     phanh ngay (sai chiều / cảm biến lệch), ống chỉ kịp đi tối đa 90°.
//
// (3) IR HỎNG → CANH GIỜ. Engine luôn đo tFirst (khởi động → station kề) và
//     tMid (cạnh → cạnh) cho từng chiều, lưu NVS. Cảm biến bị đánh dấu chết:
//       - nằm giữa đường: bỏ qua, chờ cạnh station sau nó (cửa sổ 2 đoạn).
//       - là đích: phanh theo giờ, tính từ cạnh SỐNG ngay trước nó. Đích là
//         đầu mút (Kim loại/Nhựa) thì phanh sớm (MOTION_ENDPOINT_PCT).
//     Không bao giờ canh giờ hai đoạn liên tiếp. Tối đa MỘT cảm biến chết;
//     cái thứ hai → FAULT.
//
// (4) PHÁT HIỆN IR CHẾT — không có encoder nên "ống kẹt" và "IR chết" trông
//     giống nhau (cạnh không tới). Phân biệt bằng bằng chứng:
//       a. Lỡ cạnh giữa đường, nhưng cạnh station SAU nó tới đúng giờ → ống
//          vẫn quay, cảm biến kia chết.
//       b. Lỡ cạnh ĐÍCH → phanh, LÙI về cảm biến vừa đi qua và đo thời gian.
//          Lùi lâu (≥ MOTION_PROBE_MIN_PCT × t90) = ống đã đi quá chỗ đích
//          → đích chết, đánh dấu rồi quay lại bằng canh giờ. Lùi nhanh = ống
//          bị kẹt giữa đường → báo lỗi. Lùi luôn là chiều an toàn (về phía
//          đoạn vừa đi qua, không bao giờ sâu thêm vào vùng cấm).
//       c. Cảm biến xuất phát vẫn báo CÓ VẬT khi ống đã tới station kế → kẹt
//          ở mức thấp (chập / bụi) → đánh dấu chết.
//     Cảm biến đã đánh dấu chết mà lại lên cạnh đúng chỗ → tự gỡ đánh dấu.
//
// (5) NVS — gợi ý vị trí qua lần mất điện. Một cảm biến KHÔNG cho biết độ
//     xoắn: Nhựa ở −90° và Nhựa ở +270° (đã lố qua Kim loại, xuyên vùng cấm)
//     trông y hệt nhau. NVS nhớ "lần cuối ống đứng ở đâu / đang đi từ đâu tới
//     đâu" để phân xử:
//       - Dò mặc định theo CW. Ngoại lệ: NVS nói ống ở phía Kim loại (bị ngắt
//         khi đang đi TỚI Kim loại, hoặc lần cuối đứng ở Kim loại) → dò CCW.
//       - Dò CW mà gặp Nhựa trước tiên = ống đi ra từ vùng cấm. Chỉ chấp nhận
//         khi NVS nói ống đang ở phía Nhựa. Tương tự dò CCW gặp Kim loại.
//       - Boot thấy ngay Nhựa trong khi NVS nói phía Kim loại (hoặc ngược lại)
//         → FAULT, không đoán.
//     Thủy tinh luôn được chấp nhận: đó là lối khôi phục "quay tay về Thủy
//     tinh rồi reset".
//     Chỉ GHI NVS KHI MOTOR ĐỨNG YÊN: lúc ghi flash, cache tắt trên cả hai core,
//     ISR GPIO (không nằm trong IRAM) bị hoãn và task không phanh kịp.
//
// (6) DỪNG KHẨN. Hàm abortPoll được gọi mỗi 1-2ms ở MỌI vòng chờ có motor chạy.
//     Đã bấm thì cả chuỗi thao tác (vd. quay → về HOME) bị hủy tới hết lệnh
//     ngoài cùng.
//
// Bảng chân lý DRV8871: IN1=PWM/IN2=0 chiều A | IN1=0/IN2=PWM chiều B |
// cả hai max = PHANH | cả hai 0 = THẢ TRÔI.

#include <Arduino.h>
#include <Preferences.h>
#include "esp_timer.h"
#include "soc/gpio_reg.h"
#include "config.h"
#include "motion.h"

// TCRT5000 + LM393: DO xuống LOW khi gặp tấm phản quang.
static const bool IR_ACTIVE_LOW = true;

// ---------------------------------------------------------------- Hình học

#define IDX_NONE     (-1)
#define IDX_METAL    0
#define IDX_PAPER    1
#define IDX_GLASS    2
#define IDX_PLASTIC  3

// Thứ tự VẬT LÝ quanh ống — nguồn sự thật duy nhất. Đổi thứ tự lắp: sửa 3 mảng này.
static constexpr int STATION_POS[STATION_COUNT]       = { WASTE_METAL, WASTE_PAPER, WASTE_GLASS, WASTE_PLASTIC };
static constexpr int STATION_TWIST_DEG[STATION_COUNT] = { +180, +90, 0, -90 };
static constexpr int STATION_PIN[STATION_COUNT]       = { PIN_IR_METAL, PIN_IR_PAPER, PIN_IR_GLASS, PIN_IR_PLASTIC };

// ISR đọc mức chân qua GPIO_IN1_REG — chỉ đúng cho GPIO >= 32.
static_assert(PIN_IR_PLASTIC >= 32 && PIN_IR_GLASS >= 32 &&
              PIN_IR_PAPER   >= 32 && PIN_IR_METAL >= 32,
              "ISR doc GPIO_IN1_REG nen 4 chan IR phai >= GPIO32");
static_assert(STATION_COUNT == IR_POSITION_COUNT, "Moi station co dung 1 cam bien");
static_assert(STATION_POS[STATION_HOME_IDX] == HOME_POS && STATION_HOME_IDX == IDX_GLASS,
              "HOME phai la Thuy tinh");
static_assert(STATION_TWIST_DEG[STATION_HOME_IDX] == 0, "Goc xoan lay HOME lam goc 0");

// Bit của từng chân trong GPIO_IN1_REG — để trong DRAM cho ISR.
static DRAM_ATTR const uint32_t STATION_BIT[STATION_COUNT] = {
    1u << (PIN_IR_METAL - 32), 1u << (PIN_IR_PAPER - 32),
    1u << (PIN_IR_GLASS - 32), 1u << (PIN_IR_PLASTIC - 32),
};

// CW giảm chỉ số (về phía Kim loại), CCW tăng chỉ số (về phía Nhựa).
static int dirStep(int dir)  { return dir == MOTOR_DIR_CCW ? +1 : -1; }
static int dirSlot(int dir)  { return dir == MOTOR_DIR_CCW ? 1 : 0; }
static int dirOpp(int dir)   { return dir == MOTOR_DIR_CCW ? MOTOR_DIR_CW : MOTOR_DIR_CCW; }
static const char* dirName(int dir) { return dir == MOTOR_DIR_CW ? "CW" : "CCW"; }
static bool isEndpoint(int i) { return i == 0 || i == STATION_COUNT - 1; }

static int stationIdx(int pos) {
    for (int i = 0; i < STATION_COUNT; i++) if (STATION_POS[i] == pos) return i;
    return IDX_NONE;
}

const char* motionPosName(int pos) {
    switch (pos) {
        case WASTE_PLASTIC: return "Nhua";
        case WASTE_GLASS:   return "Thuy tinh(HOME)";
        case WASTE_PAPER:   return "Giay";
        case WASTE_METAL:   return "Kim loai";
        default:            return "chua xac dinh";
    }
}
static const char* stName(int idx) {
    return motionPosName(idx >= 0 ? STATION_POS[idx] : WASTE_NONE);
}

// ---------------------------------------------------------------- ISR

#define IR_EVT_LEN 32
static volatile uint32_t evtHead = 0;               // bộ đếm đơn điệu
static volatile int8_t   evtIdx[IR_EVT_LEN];        // station của sự kiện
static volatile uint32_t evtUs[IR_EVT_LEN];         // thời điểm (µs, cắt 32 bit)
static volatile uint32_t irRejected = 0;
static volatile uint32_t irLastUs[STATION_COUNT];

static inline uint32_t nowUs() { return (uint32_t)esp_timer_get_time(); }

static void IRAM_ATTR irIsr(void* arg) {
    const int i = (int)(intptr_t)arg;

    // Đọc lại mức chân — nhiễu tạo cạnh chứ không giữ được mức.
    const bool low = (REG_READ(GPIO_IN1_REG) & STATION_BIT[i]) == 0;
    if (low != IR_ACTIVE_LOW) { irRejected++; return; }

    const uint32_t t = (uint32_t)esp_timer_get_time();
    if (t - irLastUs[i] < IR_DEBOUNCE_US) { irRejected++; return; }
    irLastUs[i] = t;

    // Ghi dữ liệu TRƯỚC, tăng bộ đếm SAU — task thấy head nào thì ô đó đã đủ.
    const uint32_t s = evtHead % IR_EVT_LEN;
    evtIdx[s] = (int8_t)i;
    evtUs[s]  = t;
    evtHead   = evtHead + 1;
}

// ---------------------------------------------------------------- NVS

struct NvState {
    uint8_t  ver;
    int8_t   lastIdx;     // station lần cuối đứng yên (IDX_NONE = không rõ)
    uint8_t  moving;      // 1 = motor đang chạy lệnh from→to thì mất điện/dừng
    int8_t   fromIdx;
    int8_t   toIdx;
    uint8_t  deadMask;    // bit i = cảm biến station i đã chết
    uint16_t tFirst[2];   // ms, [0]=CW [1]=CCW, 0 = chưa đo
    uint16_t tMid[2];
};
#define NV_VER 1

static Preferences prefs;
static bool    nvOk = false;
static NvState nv, nvSaved;

static void nvDefaults(NvState& s) {
    memset(&s, 0, sizeof s);
    s.ver = NV_VER;
    s.lastIdx = s.fromIdx = s.toIdx = IDX_NONE;
}

// Chỉ gọi khi motor ĐỨNG YÊN (xem mục (5) đầu file). Không đổi thì không ghi.
static void nvCommit() {
    if (!nvOk || memcmp(&nv, &nvSaved, sizeof nv) == 0) return;
    prefs.putBytes("st", &nv, sizeof nv);
    nvSaved = nv;
}

static void nvMarkMoving(int from, int to) {
    nv.moving = 1; nv.fromIdx = from; nv.toIdx = to;
    nvCommit();
}

static void nvMarkStopped(int idx) {
    nv.moving = 0; nv.lastIdx = idx; nv.fromIdx = nv.toIdx = IDX_NONE;
    nvCommit();
}

// Phía của ống theo gợi ý NVS: +1 = phía Kim loại, −1 = phía Nhựa, 0 = không rõ.
static int hintSide() {
    int ref = nv.moving ? nv.toIdx : nv.lastIdx;
    if (ref == IDX_METAL)   return +1;
    if (ref == IDX_PLASTIC) return -1;
    return 0;
}

// Chiều dò khi không cảm biến nào bị che. Xem mục (5).
// Mặc định CW. Chỉ đổi sang CCW khi ống được biết là ở phía Kim loại (đang đi
// tới Kim loại thì bị ngắt, hoặc lần cuối đứng ở Kim loại): lố qua Kim loại là
// đã vào vùng cấm, dò CW tiếp sẽ ra Nhựa ở +270°. Mọi trường hợp khác — kể cả
// bị ngắt giữa lúc VỀ HOME — CW đều an toàn và gặp IR gần nhất.
static int seekDir() {
    return hintSide() == +1 ? MOTOR_DIR_CCW : MOTOR_DIR_CW;
}

static void printHint() {
    if (nv.moving)
        Serial.printf("[NVS] Lan truoc bi ngat GIUA lenh quay %s -> %s.\n",
                      stName(nv.fromIdx), stName(nv.toIdx));
    else if (nv.lastIdx >= 0)
        Serial.printf("[NVS] Lan truoc dung yen tai %s.\n", stName(nv.lastIdx));
    else
        Serial.println("[NVS] Khong co goi y vi tri (lan dau / da xoa).");
}

// ---------------------------------------------------------------- State

static int  curIdx       = IDX_NONE;
static bool curEstimated = false;     // vị trí do canh giờ, không do cảm biến xác nhận

static bool        faultLatched = false;
static const char* faultWhy     = NULL;
static int         consecFail   = 0;

bool        motionFaulted()           { return faultLatched; }
const char* motionFaultReason()       { return faultLatched ? faultWhy : NULL; }
int         motionPosition()          { return curIdx >= 0 ? STATION_POS[curIdx] : WASTE_NONE; }
bool        motionPositionEstimated() { return curIdx >= 0 && curEstimated; }
bool        motionIsHome()            { return curIdx == STATION_HOME_IDX; }
uint8_t     motionDeadMask()          { return nv.deadMask; }

int motionTwistDeg(int pos) {
    int i = stationIdx(pos);
    return i < 0 ? MOTION_TWIST_UNKNOWN : STATION_TWIST_DEG[i];
}

static bool isDead(int i) { return i >= 0 && (nv.deadMask & (1u << i)); }

// ---------------------------------------------------------------- Dừng khẩn

static bool (*abortPoll)() = NULL;
static bool estop   = false;
static int  opDepth = 0;

void motionSetAbortPoll(bool (*fn)()) { abortPoll = fn; }

// Mỗi hàm public bọc một Op. Cờ dừng khẩn chỉ xóa khi bắt đầu thao tác NGOÀI
// CÙNG — nhờ vậy GoHome → RotateTo lồng nhau vẫn thấy cờ của nhau.
struct Op {
    Op()  { if (opDepth++ == 0) estop = false; }
    ~Op() { opDepth--; }
};

static bool aborted() {
    if (!estop && abortPoll && abortPoll()) {
        estop = true;
        Serial.println("\n[DUNG KHAN] Da nhan lenh dung!");
    }
    return estop;
}

// Delay có kiểm tra dừng khẩn. true = bị dừng.
static bool waitMs(uint32_t ms) {
    uint32_t t0 = millis();
    while (millis() - t0 < ms) {
        if (aborted()) return true;
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return aborted();
}

// ---------------------------------------------------------------- Motor

static uint32_t lastStopMs = 0;
static bool     motorRan   = false;

static void motorGo(int dir) {
    bool a = (dir == MOTOR_DIR_CW) != (bool)MOTOR_DIR_INVERTED;   // XOR
    ledcWrite(MOTOR_LEDC_CH_IN1, a ? MOTOR_SPEED : 0);
    ledcWrite(MOTOR_LEDC_CH_IN2, a ? 0 : MOTOR_SPEED);
    motorRan = true;
}

void motionCoast() {
    ledcWrite(MOTOR_LEDC_CH_IN1, 0);
    ledcWrite(MOTOR_LEDC_CH_IN2, 0);
}

static void motorBrake() {
    ledcWrite(MOTOR_LEDC_CH_IN1, MOTOR_DUTY_MAX);
    ledcWrite(MOTOR_LEDC_CH_IN2, MOTOR_DUTY_MAX);
    vTaskDelay(pdMS_TO_TICKS(MOTOR_BRAKE_MS));
    motionCoast();
    lastStopMs = millis();
}

// Rotor phải đứng hẳn trước khi chạy lại — đảo chiều lúc còn quay thì back-EMF
// cộng vào 12V, sụt rail chung, ESP32 có thể brownout.
static void waitDeadtime() {
    if (!motorRan) return;
    uint32_t d = millis() - lastStopMs;
    if (d < MOTOR_DEADTIME_MS) vTaskDelay(pdMS_TO_TICKS(MOTOR_DEADTIME_MS - d));
}

// ---------------------------------------------------------------- IR đọc mức

static bool irRaw(int i) {
    bool low = digitalRead(STATION_PIN[i]) == LOW;
    return IR_ACTIVE_LOW ? low : !low;
}

// Đọc nhanh 3 lần liên tiếp, không delay — dùng được khi motor đang chạy.
static bool coveredNow(int i) { return irRaw(i) && irRaw(i) && irRaw(i); }

// Mặt nạ các cảm biến SỐNG đang bị che, gộp (OR) qua IR_STABLE_SAMPLES mẫu.
// Gộp OR vì ống đậu ngay rìa tấm phản quang thì DO rung — rung vẫn là "đang ở đó".
static uint8_t irMask() {
    uint8_t m = 0;
    for (int n = 0; n < IR_STABLE_SAMPLES; n++) {
        for (int i = 0; i < STATION_COUNT; i++)
            if (!isDead(i) && irRaw(i)) m |= (1u << i);
        vTaskDelay(pdMS_TO_TICKS(IR_STABLE_INTERVAL_MS));
    }
    return m;
}

#define MASK_MULTI (-2)
static int maskIdx(uint8_t m) {
    if (m == 0) return IDX_NONE;
    if (m & (m - 1)) return MASK_MULTI;
    for (int i = 0; i < STATION_COUNT; i++) if (m == (1u << i)) return i;
    return MASK_MULTI;
}

void motionPrintIrDump() {
    Serial.print("  [IR] ");
    for (int i = 0; i < STATION_COUNT; i++) {
        Serial.printf("%s(GPIO%d)=%d%s%s | ", stName(i), STATION_PIN[i],
                      digitalRead(STATION_PIN[i]), irRaw(i) ? "*" : " ",
                      isDead(i) ? "[CHET]" : "");
    }
    Serial.printf("su kien=%u  canh bi loai=%u\n", (unsigned)evtHead, (unsigned)irRejected);
}

// ---------------------------------------------------------------- Bảo vệ

static void latchFault(const char* why) {
    motorBrake();
#if !MOTION_FAULT_LATCH
    Serial.printf("[CANH BAO NANG] %s — KHONG khoa (MOTION_FAULT_LATCH=0). Kiem tra day cap!\n", why);
    return;
#endif
    faultLatched = true;
    faultWhy     = why;
    Serial.println("");
    Serial.println("############################################################");
    Serial.printf ("# [FAULT] HE THONG DA KHOA: %s\n", why);
    Serial.println("# Moi lenh quay/ve HOME se bi TU CHOI.");
    Serial.println("#   1. Kiem tra day cap — co bi xoan qua muc khong?");
    Serial.println("#   2. Jog ('[' / ']') hoac quay TAY ong ve ngan Thuy tinh,");
    Serial.println("#      day phai THANG hoan toan khi ong dung o do.");
    Serial.println("#   3. Bam 'f' de mo khoa (hoac reset nguon khi ong o Thuy tinh).");
    Serial.println("############################################################");
}

static void noteFailure(const char* why, bool severe) {
    if (severe) { latchFault(why); return; }
    if (faultLatched) return;
    Serial.printf("  [BAO VE] Loi: %s\n", why);
#if MOTION_FAULT_LATCH
    consecFail++;
    Serial.printf("  [BAO VE] Lan loi thu %d/%d lien tiep.\n", consecFail, MOTION_MAX_CONSEC_FAIL);
    if (consecFail >= MOTION_MAX_CONSEC_FAIL) latchFault(why);
#endif
}

static void noteSuccess() { consecFail = 0; }

// Đánh dấu cảm biến chết. KHÔNG ghi NVS ở đây — có thể đang chạy motor; điểm
// dừng kế tiếp sẽ ghi. Trả về false nếu đây là cái chết THỨ HAI (đã chốt FAULT).
static bool markDead(int i, const char* how) {
    if (isDead(i)) return true;
    Serial.println("");
    Serial.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
    Serial.printf ("!! [IR HONG] Cam bien %s (GPIO%d): %s\n", stName(i), STATION_PIN[i], how);
    if (nv.deadMask) {
        Serial.println("!! Da co mot cam bien chet khac — KHONG du moc de canh gio.");
        Serial.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        latchFault("hai cam bien IR hong — khong con du moc de dinh vi");
        return false;
    }
    nv.deadMask |= (1u << i);
    Serial.println("!! Chuyen sang CHE DO SUY GIAM: doan toi cam bien nay se CANH GIO");
    Serial.println("!! tu canh IR song gan nhat. Sua cam bien roi bam 'd' de xoa danh dau.");
    Serial.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
    return true;
}

static void reviveSensor(int i) {
    if (!isDead(i)) return;
    nv.deadMask &= ~(1u << i);
    Serial.printf("  [IR] Cam bien %s vua len canh dung cho — con song, go danh dau CHET.\n", stName(i));
}

// ---------------------------------------------------------------- Đo thời gian

static void learn(uint16_t& slot, uint32_t ms, const char* what) {
    if (ms < 50 || ms > 20000) return;
    if (slot == 0) { slot = (uint16_t)ms; return; }
    if (ms * 2 < slot || ms > 2u * slot) {
        Serial.printf("  [DO] Bo mau %s=%ums (lech xa gia tri %ums).\n", what, (unsigned)ms, slot);
        return;
    }
    slot = (uint16_t)((int32_t)slot + ((int32_t)ms - (int32_t)slot) / (1 << MOTION_EMA_SHIFT));
}

// ---------------------------------------------------------------- Chờ cạnh

#define W_TIMEOUT (-10)
#define W_ABORT   (-11)

// Chờ sự kiện IR kế tiếp (bỏ qua cạnh rung của `ignoreIdx`). Hết `limitUs`
// tính từ `refUs` → W_TIMEOUT. Có kiểm tra dừng khẩn mỗi 1ms.
static int waitEdge(uint32_t& seen, uint32_t refUs, uint32_t limitUs, int ignoreIdx, uint32_t& tE) {
    for (;;) {
        while (seen != evtHead) {
            const uint32_t s = seen % IR_EVT_LEN;
            const int e = evtIdx[s];
            const uint32_t t = evtUs[s];
            seen++;
            if (e == ignoreIdx) continue;
            tE = t;
            return e;
        }
        if (aborted()) return W_ABORT;
        if (nowUs() - refUs >= limitUs) return W_TIMEOUT;
        vTaskDelay(1);
    }
}

// ---------------------------------------------------------------- Dừng / đồng bộ lại

// Sau khi đã phanh vì lý do bất thường: đọc lại IR, đồng bộ vị trí, ghi NVS.
// Không thấy cảm biến nào → vị trí CHƯA BIẾT, NVS giữ nguyên gợi ý "đang đi".
static void resync() {
    vTaskDelay(pdMS_TO_TICKS(MOTOR_SETTLE_MS));
    int idx = maskIdx(irMask());
    curEstimated = false;
    if (idx >= 0) { curIdx = idx; nvMarkStopped(idx); }
    else          { curIdx = IDX_NONE; nvCommit(); }
}

static void abortStop() {
    motorBrake();
    resync();
    Serial.printf("[DUNG KHAN] Da phanh. Vi tri: %s\n", stName(curIdx));
}

// Có phải cặp "đi về đầu mút này mà lại thấy đầu mút kia" — tức đã vòng qua
// vùng cấm Kim loại↔Nhựa?
static bool wrapPair(int want, int got) {
    return (want == IDX_METAL && got == IDX_PLASTIC) || (want == IDX_PLASTIC && got == IDX_METAL);
}

// Đã phanh để dừng tại `to`. Đọc lại IR, xác nhận, ghi NVS.
static bool finishAt(int to, int dir, bool timed) {
    vTaskDelay(pdMS_TO_TICKS(MOTOR_SETTLE_MS));
    uint8_t m  = irMask();
    int    idx = maskIdx(m);

    if (idx == IDX_NONE || idx == to) {
        if (idx == IDX_NONE && !timed)
            Serial.println("  [CANH BAO] Da phanh tren canh IR nhung ong troi khoi tam phan quang —"
                           " tam qua hep hoac phanh yeu.");
        curIdx = to;
        curEstimated = timed;
        nvMarkStopped(to);
        return true;
    }
    if (idx == MASK_MULTI) {
        motionPrintIrDump();
        curIdx = IDX_NONE;
        nvCommit();
        noteFailure("nhieu cam bien cung bao CO VAT khi dung yen", true);
        return false;
    }
    curIdx = idx;
    curEstimated = false;
    nvMarkStopped(idx);
    if (wrapPair(to, idx)) {
        noteFailure("dung o dau mut ben kia — da vuot vung cam Kim loai<->Nhua", true);
        return false;
    }
    const bool ahead = (idx - to) * dirStep(dir) > 0;
    Serial.printf("  [TROI] Dung o %s thay vi %s (%s).\n", stName(idx), stName(to),
                  ahead ? "quan tinh vuot — giam MOTOR_SPEED / tang MOTOR_BRAKE_MS" : "nguoc huong di");
    noteFailure("dung sai ngan sau khi phanh", false);
    return false;
}

// Gặp cạnh của một cảm biến không phải station kế tiếp. Motor đã phanh.
static bool sequenceError(int got, int want, int dir) {
    Serial.printf("[ERROR] Sai thu tu: dang di %s, cho %s nhung gap %s.\n",
                  dirName(dir), stName(want), stName(got));
    Serial.println("        Ong quay NGUOC huong -> dat MOTOR_DIR_INVERTED = 1 (hoac dao 2 day motor).");
    Serial.println("        Ong quay DUNG huong  -> tam phan quang lech / bien tro LM393 sai nguong.");
    resync();
    if (curIdx == IDX_NONE) { curIdx = got; nvMarkStopped(got); }
    motionPrintIrDump();
    noteFailure("cam bien vuot qua khong dung thu tu", wrapPair(want, got));
    return false;
}

// ---------------------------------------------------------------- Quay

enum MoveResult { MV_OK, MV_FAIL, MV_RETRY };

// Lỡ cạnh ĐÍCH `k` (cảm biến được cho là sống). Motor đã phanh. `cur` là cảm
// biến sống vừa đi qua (hoặc xuất phát). Xem mục (4b).
static MoveResult recoverMissedTarget(int cur, int k, int dir) {
    const int ds = dirSlot(dir);
    vTaskDelay(pdMS_TO_TICKS(MOTOR_SETTLE_MS));
    int idx = maskIdx(irMask());

    if (idx == MASK_MULTI) {
        resync();
        noteFailure("nhieu cam bien cung bao CO VAT", true);
        return MV_FAIL;
    }
    if (idx >= 0) {
        curIdx = idx; curEstimated = false; nvMarkStopped(idx);
        if (idx == k) {
            Serial.printf("  [IR] Khong bat duoc canh %s nhung muc chan dang CO VAT — coi nhu da toi.\n", stName(k));
            return MV_OK;
        }
        if (idx == cur) {
            Serial.printf("[ERROR] Ong KHONG roi khoi %s — ket co khi hoac motor khong quay.\n", stName(cur));
            Serial.println("        1. 12V da vao terminal POWER cua DRV8871 chua? GND chung voi ESP32?");
            Serial.println("        2. MOTOR_SPEED du thang ma sat tinh khi da lap ong chua?");
            motionPrintIrDump();
            noteFailure("ong khong roi khoi vi tri xuat phat", false);
            return MV_FAIL;
        }
        noteFailure("dung o ngan khong mong doi sau khi lo canh", wrapPair(k, idx));
        return MV_FAIL;
    }

    // Không cảm biến nào bị che: ống ở đâu đó quanh `k`. Lùi về `cur` để phân xử.
    if (isDead(cur)) {
        curIdx = IDX_NONE; nvCommit();
        latchFault("lo canh dich khi moc xuat phat cung la cam bien chet — mat vi tri");
        return MV_FAIL;
    }
    const int      rev = dirOpp(dir);
    const uint16_t ref = nv.tFirst[dirSlot(rev)] ? nv.tFirst[dirSlot(rev)] : nv.tFirst[ds];
    const uint32_t limitMs = ref ? 2u * ref : (uint32_t)SEEK_BLIND_MS;

    Serial.printf("[KIEM CHUNG] Lo canh %s. Lui %s ve %s de phan biet KET hay IR CHET (toi da %ums)...\n",
                  stName(k), dirName(rev), stName(cur), (unsigned)limitMs);

    // KHÔNG ghi lại NVS: giữ gợi ý của lệnh gốc (cur → đích). Mất điện lúc
    // đang lùi sau khi đã lố qua Kim loại thì gợi ý "đang tới Kim loại" mới
    // khiến lần boot sau dò CCW — ghi đè thành "đang về Giấy" sẽ dò CW.
    waitDeadtime();
    uint32_t seen = evtHead;
    motorGo(rev);
    const uint32_t t0 = nowUs();
    uint32_t tE = t0;

    for (;;) {
        int e = waitEdge(seen, t0, limitMs * 1000u, IDX_NONE, tE);
        if (e == W_ABORT)   { abortStop(); return MV_FAIL; }
        if (e == W_TIMEOUT) {
            motorBrake(); resync();
            latchFault("lui kiem chung khong gap lai cam bien vua di qua — mat vi tri");
            return MV_FAIL;
        }
        if (isDead(e)) continue;
        if (e == cur) break;
        if (e == k) {
            // Đích lên cạnh khi tiếp cận từ phía bên kia → nó sống, và ống đang ở đích.
            motorBrake();
            Serial.printf("  [IR] %s chi bat canh khi di NGUOC chieu — kiem tra tam phan quang lech tam.\n", stName(k));
            return finishAt(k, rev, false) ? MV_OK : MV_FAIL;
        }
        motorBrake();
        return sequenceError(e, cur, rev) ? MV_OK : MV_FAIL;
    }
    motorBrake();
    const uint32_t backMs = (tE - t0) / 1000u;
    if (!finishAt(cur, rev, false)) return MV_FAIL;

    Serial.printf("  [KIEM CHUNG] Lui mat %ums (t90 tham chieu %ums).\n", (unsigned)backMs, ref);
    if (!ref) {
        noteFailure("chua co so do t90 — khong phan biet duoc KET hay IR CHET. Chay 'c' khi IR con tot", false);
        return MV_FAIL;
    }
    if (backMs * 100u >= (uint32_t)ref * MOTION_PROBE_MIN_PCT) {
        bool ok = markDead(k, "ong da quay QUA vi tri nay ma khong co canh IR");
        nvCommit();
        return ok ? MV_RETRY : MV_FAIL;
    }
    Serial.printf("[ERROR] Ong bi KET giua %s va %s (lui chi mat %ums).\n", stName(cur), stName(k), (unsigned)backMs);
    noteFailure("ong bi ket giua duong", false);
    return MV_FAIL;
}

// Quay từ station đã biết `from` tới `to`. Xem mục (1)-(4) đầu file.
static MoveResult runMove(int from, int to) {
    const int dir  = (to > from) ? MOTOR_DIR_CCW : MOTOR_DIR_CW;
    const int step = dirStep(dir);
    const int ds   = dirSlot(dir);

    Serial.printf("[ROTATE] %s (%+d do) -> %s (%+d do) | %s, %d doan%s\n",
                  stName(from), STATION_TWIST_DEG[from], stName(to), STATION_TWIST_DEG[to],
                  dirName(dir), abs(to - from), nv.deadMask ? " | CHE DO SUY GIAM" : "");

    nvMarkMoving(from, to);
    waitDeadtime();

    uint32_t seen = evtHead;
    const bool startCovered = !isDead(from) && !curEstimated;
    motorGo(dir);
    const uint32_t t0 = nowUs();

    int      cur        = from;
    uint32_t refUs      = t0;
    bool     refIsStart = true;
    bool     refReal    = startCovered;   // mốc đáng tin để đo thời gian?

    while (cur != to) {
        int nxt  = cur + step;
        int nSeg = 1;
        if (isDead(nxt) && nxt != to) { nxt += step; nSeg = 2; }   // bỏ qua IR chết giữa đường

        const uint16_t tA = refIsStart ? nv.tFirst[ds] : nv.tMid[ds];
        const uint16_t tB = nv.tMid[ds];

        // ---- Đích đã chết → phanh theo giờ, tính từ cạnh sống ngay trước nó.
        if (isDead(nxt)) {
            if (!tA) {
                motorBrake(); resync();
                noteFailure("IR dich da chet ma chua co so do thoi gian — khong canh gio duoc", false);
                return MV_FAIL;
            }
            const uint32_t runMs = isEndpoint(nxt) ? (uint32_t)tA * MOTION_ENDPOINT_PCT / 100u : tA;
            Serial.printf("  [CANH GIO] %s da chet — phanh sau %ums tinh tu %s.\n",
                          stName(nxt), (unsigned)runMs, refIsStart ? "luc khoi dong" : "canh truoc");
            for (;;) {
                uint32_t tE;
                int e = waitEdge(seen, refUs, runMs * 1000u, cur, tE);
                if (e == W_ABORT)   { abortStop(); return MV_FAIL; }
                if (e == W_TIMEOUT) break;
                if (e == nxt) {                      // IR "chết" lại lên cạnh đúng chỗ
                    motorBrake();
                    reviveSensor(nxt);
                    return finishAt(to, dir, false) ? MV_OK : MV_FAIL;
                }
                if (isDead(e)) continue;
                motorBrake();
                return sequenceError(e, nxt, dir) ? MV_OK : MV_FAIL;
            }
            motorBrake();
            return finishAt(to, dir, true) ? MV_OK : MV_FAIL;
        }

        // ---- Chờ cạnh của station SỐNG kế tiếp.
        uint32_t expMs   = (tA && (nSeg == 1 || tB)) ? (uint32_t)tA + (nSeg == 2 ? tB : 0) : 0;
        uint32_t limitMs = expMs ? expMs * MOTION_MISS_PCT / 100u : (uint32_t)SEEK_BLIND_MS * nSeg;
        int      skipCand = IDX_NONE;   // station nghi chết, đang cho chạy tiếp để kiểm chứng

        for (;;) {
            uint32_t tE;
            int e = waitEdge(seen, refUs, limitMs * 1000u, cur, tE);
            if (e == W_ABORT) { abortStop(); return MV_FAIL; }

            if (e == W_TIMEOUT) {
                // (4a) Lỡ cạnh GIỮA đường: cho chạy tiếp một đoạn, xem station sau có tới đúng giờ không.
                if (skipCand == IDX_NONE && nSeg == 1 && nxt != to && expMs && tB && !nv.deadMask) {
                    skipCand = nxt;
                    nxt     += step;
                    nSeg     = 2;
                    limitMs  = (expMs + tB) * MOTION_MISS_PCT / 100u;
                    Serial.printf("  [?] Lo canh %s — chay tiep toi %s de kiem chung...\n",
                                  stName(skipCand), stName(nxt));
                    continue;
                }
                motorBrake();
                if (skipCand != IDX_NONE) {
                    resync();
                    latchFault("lo 2 canh IR lien tiep — khong con biet vi tri");
                    return MV_FAIL;
                }
                if (nxt == to && nSeg == 1) return recoverMissedTarget(cur, nxt, dir);
                resync();
                noteFailure("het gio ma chua gap cam bien ke tiep", false);
                return MV_FAIL;
            }

            if (e == nxt) {
                if (skipCand != IDX_NONE) {
                    if (!markDead(skipCand, "ong van quay (station sau toi dung gio) nhung khong co canh IR")) {
                        resync(); return MV_FAIL;
                    }
                } else if (nSeg == 1 && refReal) {
                    const uint32_t ms = (tE - refUs) / 1000u;
                    if (refIsStart) learn(nv.tFirst[ds], ms, "tFirst");
                    else            learn(nv.tMid[ds],   ms, "tMid");
                }
                if (nxt == to) motorBrake();          // phanh TRƯỚC, kiểm tra sau
                // (4c) Cảm biến xuất phát vẫn báo CÓ VẬT khi đã tới station kế → kẹt mức thấp.
                if (refIsStart && startCovered && coveredNow(from)) {
                    if (!markDead(from, "van bao CO VAT khi ong da quay sang ngan ke (ket muc thap)")) {
                        if (nxt != to) motorBrake();
                        resync(); return MV_FAIL;
                    }
                }
                Serial.printf("  [IR] %s sau %ums\n", stName(nxt), (unsigned)((tE - refUs) / 1000u));
                cur = nxt; refUs = tE; refIsStart = false; refReal = true;
                if (cur == to) return finishAt(to, dir, false) ? MV_OK : MV_FAIL;
                break;
            }
            if (e == skipCand) {                     // cạnh trễ nhưng có thật: ống chỉ chạy chậm
                Serial.printf("  [IR] %s toi TRE (%ums) — ong chay cham, khong phai IR chet.\n",
                              stName(e), (unsigned)((tE - refUs) / 1000u));
                cur = e; refUs = tE; refIsStart = false; refReal = true;
                if (cur == to) { motorBrake(); return finishAt(to, dir, false) ? MV_OK : MV_FAIL; }
                break;
            }
            if (isDead(e)) {
                if (nSeg == 2 && skipCand == IDX_NONE && e == cur + step) {   // IR chết giữa đường sống lại
                    reviveSensor(e);
                    cur = e; refUs = tE; refIsStart = false; refReal = true;
                    break;
                }
                continue;
            }
            motorBrake();
            return sequenceError(e, nxt, dir) ? MV_OK : MV_FAIL;
        }
    }
    return MV_OK;
}

// ---------------------------------------------------------------- Định vị

// Vị trí vừa xác định có mâu thuẫn với gợi ý NVS không? `dir` = chiều đã dò,
// −1 nếu đọc được ngay (không dò). Trả về lý do nếu đáng ngờ. Xem mục (5).
static const char* landingSuspicious(int idx, int dir) {
    const int side = hintSide();
    if (dir == MOTOR_DIR_CW && idx == IDX_PLASTIC && side != -1)
        return "do CW gap Nhua truoc tien — ong di ra tu vung cam, co the dang xoan +270 do";
    if (dir == MOTOR_DIR_CCW && idx == IDX_METAL && side != +1)
        return "do CCW gap Kim loai truoc tien — ong di ra tu vung cam, co the dang xoan -180 do";
    if (dir < 0 && idx == IDX_PLASTIC && side == +1)
        return "dang o Nhua trong khi NVS ghi ong o phia Kim loai — co the dang xoan +270 do";
    if (dir < 0 && idx == IDX_METAL && side == -1)
        return "dang o Kim loai trong khi NVS ghi ong o phia Nhua — co the dang xoan -180 do";
    return NULL;
}

// Không cảm biến nào bị che: quay theo `dir` tới cảm biến sống đầu tiên.
static bool seekMove(int dir, bool useHint) {
    const int      ds = dirSlot(dir);
    const uint16_t tA = nv.tFirst[ds];
    uint32_t limitMs  = tA ? (uint32_t)tA * MOTION_MISS_PCT / 100u : (uint32_t)SEEK_BLIND_MS;
    if (nv.deadMask && tA) limitMs += nv.tMid[ds] ? nv.tMid[ds] : tA;   // có thể phải vượt 1 IR chết

    Serial.printf("[SEEK] Khong IR nao bi che — do theo %s, toi da %ums.\n", dirName(dir), (unsigned)limitMs);

    // KHÔNG ghi NVS ở đây: mất điện giữa lúc dò thì lần sau vẫn phải dò theo
    // đúng gợi ý cũ.
    waitDeadtime();
    uint32_t seen = evtHead;
    motorGo(dir);
    const uint32_t t0 = nowUs();
    int idx = IDX_NONE;

    for (;;) {
        uint32_t tE;
        int e = waitEdge(seen, t0, limitMs * 1000u, IDX_NONE, tE);
        if (e == W_ABORT) { abortStop(); return false; }
        if (e == W_TIMEOUT) break;
        if (isDead(e)) continue;
        idx = e;
        break;
    }
    motorBrake();
    vTaskDelay(pdMS_TO_TICKS(MOTOR_SETTLE_MS));

    int now = maskIdx(irMask());
    if (now == MASK_MULTI) {
        curIdx = IDX_NONE;
        noteFailure("nhieu cam bien cung bao CO VAT", true);
        return false;
    }
    if (now >= 0) idx = now;   // trôi sang station kế, hoặc cạnh bị lỡ nhưng mức có
    if (idx < 0) {
        curIdx = IDX_NONE;
        Serial.println("[SEEK] KHONG gap cam bien nao. Ong khong quay, hoac IR tren doan nay deu hong.");
        motionPrintIrDump();
        noteFailure("do vi tri khong gap cam bien nao", false);
        return false;
    }
    if (useHint) {
        if (const char* why = landingSuspicious(idx, dir)) {
            curIdx = IDX_NONE;
            Serial.printf("[SEEK] Dung o %s nhung vi tri MO HO.\n", stName(idx));
            latchFault(why);
            return false;
        }
    }
    curIdx = idx; curEstimated = false;
    nvMarkStopped(idx);
    Serial.printf("[SEEK] Tim thay %s.\n", stName(idx));
    return true;
}

// Xác định vị trí. useHint = false khi người vận hành đã xác nhận dây thẳng ('f').
static bool locate(bool useHint) {
    uint8_t m  = irMask();
    int    idx = maskIdx(m);

    if (idx == MASK_MULTI) {
        motionPrintIrDump();
        curIdx = IDX_NONE;
        noteFailure("nhieu cam bien cung bao CO VAT khi dung yen — chap/lech tam phan quang", true);
        return false;
    }
    if (idx >= 0) {
        if (useHint) {
            if (const char* why = landingSuspicious(idx, -1)) {
                curIdx = IDX_NONE;
                latchFault(why);
                return false;
            }
        }
        curIdx = idx; curEstimated = false;
        nvMarkStopped(idx);
        Serial.printf("[VI TRI] Dang o %s.\n", stName(idx));
        return true;
    }
    return seekMove(useHint ? seekDir() : MOTOR_DIR_CW, useHint);
}

// ---------------------------------------------------------------- API

static bool refuseIfFault() {
    if (!faultLatched) return false;
    Serial.printf("[TU CHOI] He dang KHOA (FAULT): %s. Thao xoan roi bam 'f'.\n", faultWhy);
    return true;
}

bool motionSeek() {
    Op op;
    if (refuseIfFault()) return false;
    curIdx = IDX_NONE;
    bool ok = locate(true);
    motionPrintState();
    return ok;
}

// Đưa ống từ vị trí đã biết tới station t (một chặng), kể cả lần thử lại bằng
// canh giờ khi vừa phát hiện IR hỏng. Vị trí phải đã biết (curIdx >= 0).
static bool moveTo(int t) {
    if (curIdx == t) {
        // Xác nhận lại bằng cảm biến nếu được — ống có thể đã bị đẩy khỏi chỗ đậu.
        if (!curEstimated && !isDead(t) && !(irMask() & (1u << t))) {
            Serial.printf("[CANH BAO] So sach ghi %s nhung IR khong con bi che — xac dinh lai.\n", stName(t));
            curIdx = IDX_NONE;
            if (!locate(true)) return false;
        }
        if (curIdx == t) return true;
    }
    MoveResult r = runMove(curIdx, t);
    if (r == MV_RETRY && !estop && !faultLatched && curIdx >= 0) {
        Serial.println("[ROTATE] Thu lai bang CANH GIO cho cam bien vua hong...");
        r = runMove(curIdx, t);
    }
    return r == MV_OK && curIdx == t;
}

// Mô hình vận hành: MỌI chu kỳ xuất phát từ HOME (quay tới ngăn → xả → về
// HOME). Ống đứng ở ngăn khác HOME lúc nhận lệnh chỉ có thể là vì chu kỳ trước
// bị ngắt giữa chừng (mất điện, dừng khẩn, lỗi) — khi đó về HOME TRƯỚC rồi mới
// quay tới ngăn đích, không bao giờ đi tắt ngăn→ngăn.
bool motionRotateTo(int target) {
    Op op;
    if (refuseIfFault()) return false;
    const int t = stationIdx(target);
    if (t < 0) { Serial.println("[ERROR] target khong hop le (1-4)"); return false; }

    if (curIdx == IDX_NONE) {
        Serial.println("[AUTO-SEEK] Chua biet vi tri — xac dinh truoc khi quay...");
        if (!locate(true)) return false;
    }

    if (curIdx != STATION_HOME_IDX && t != STATION_HOME_IDX) {
        Serial.printf("[ROTATE] Ong dang o %s, KHONG phai HOME — chu ky truoc bi ngat. Ve HOME truoc...\n",
                      stName(curIdx));
        if (!moveTo(STATION_HOME_IDX)) { motionPrintState(); return false; }
    }

    const bool ok = moveTo(t);
    if (ok) {
        noteSuccess();
        Serial.printf("[ROTATE_DONE] Da den %s%s.\n", stName(t), curEstimated ? " (uoc luong bang canh gio)" : "");
    }
    motionPrintState();
    return ok;
}

bool motionGoHome() {
    Op op;
    if (refuseIfFault()) return false;
    Serial.println("[HOME] Ve HOME (Thuy tinh)...");
    return motionRotateTo(HOME_POS);
}

bool motionHomeOnBoot() {
    Op op;
    printHint();
    if (nv.deadMask) {
        Serial.print("[NVS] Cam bien dang danh dau CHET:");
        for (int i = 0; i < STATION_COUNT; i++) if (isDead(i)) Serial.printf(" %s", stName(i));
        Serial.println(" — chay che do suy giam.");
    }
    Serial.printf("[BOOT] Tu ve HOME sau %dms — dung khan / rut nguon NGAY neu chua san sang...\n",
                  BOOT_HOME_GRACE_MS);
    if (waitMs(BOOT_HOME_GRACE_MS)) {
        Serial.println("[BOOT] Da HUY tu ve HOME theo lenh dung khan.");
        return false;
    }
    if (refuseIfFault()) return false;
    if (!locate(true)) {
        Serial.println("[BOOT] KHONG xac dinh duoc vi tri.");
        return false;
    }
    if (curIdx != STATION_HOME_IDX)
        Serial.printf("[BOOT] Dang o %s, khong phai HOME — chu ky truoc bi ngat giua chung.\n", stName(curIdx));
    bool ok = motionGoHome();
    if (!ok) Serial.println("[BOOT] KHONG ve duoc HOME. Kiem tra co cau/nguon TRUOC khi nhan vat that.");
    return ok;
}

bool motionCalibrate() {
    Op op;
    if (refuseIfFault()) return false;
    if (nv.deadMask) {
        Serial.println("[CALIB] Dang co IR bi danh dau CHET — sua roi bam 'd' truoc khi hieu chuan.");
        return false;
    }
    if (!motionGoHome()) return false;
    if (curEstimated) { Serial.println("[CALIB] Vi tri HOME dang la uoc luong — khong hieu chuan."); return false; }

    Serial.println("[CALIB] Quet: HOME -> Kim loai -> Nhua -> HOME. SPACE de dung.");
    const uint16_t oldF0 = nv.tFirst[0], oldF1 = nv.tFirst[1], oldM0 = nv.tMid[0], oldM1 = nv.tMid[1];
    nv.tFirst[0] = nv.tFirst[1] = nv.tMid[0] = nv.tMid[1] = 0;

    static const int legs[] = { IDX_METAL, IDX_PLASTIC, STATION_HOME_IDX };
    bool ok = true;
    for (int leg : legs) {
        if (runMove(curIdx, leg) != MV_OK || curIdx != leg) { ok = false; break; }
    }
    if (ok && (!nv.tFirst[0] || !nv.tFirst[1] || !nv.tMid[0] || !nv.tMid[1])) ok = false;

    if (!ok) {
        nv.tFirst[0] = oldF0; nv.tFirst[1] = oldF1; nv.tMid[0] = oldM0; nv.tMid[1] = oldM1;
        nvCommit();
        Serial.println("[CALIB] THAT BAI — giu so do cu.");
        motionPrintState();
        return false;
    }
    nvCommit();
    noteSuccess();
    Serial.printf("[CALIB] Xong. CW: tFirst=%ums tMid=%ums | CCW: tFirst=%ums tMid=%ums\n",
                  nv.tFirst[0], nv.tMid[0], nv.tFirst[1], nv.tMid[1]);
    Serial.printf("        Goi y SEEK_BLIND_MS trong khoang (%u, %u).\n",
                  (unsigned)max(nv.tFirst[0], nv.tFirst[1]),
                  (unsigned)(min(nv.tFirst[0], nv.tFirst[1]) + min(nv.tMid[0], nv.tMid[1])));
    return true;
}

void motionClearDeadMask() {
    nv.deadMask = 0;
    nvCommit();
    Serial.println("[IR] Da xoa danh dau cam bien chet. Nen chay 'c' de kiem tra lai ca 4.");
}

bool motionClearFault() {
    Op op;
    Serial.println("[FAULT] Mo khoa — bo goi y vi tri cu trong NVS, xac dinh lai tu dau...");
    faultLatched = false;
    faultWhy     = NULL;
    consecFail   = 0;
    curIdx       = IDX_NONE;
    nv.moving    = 0;
    nv.lastIdx   = nv.fromIdx = nv.toIdx = IDX_NONE;
    nvCommit();

    if (!locate(false)) {
        Serial.println("[FAULT] Van khong xac dinh duoc vi tri.");
        if (!estop) latchFault("khong xac dinh duoc vi tri sau khi mo khoa");
        return false;
    }
    Serial.println("[FAULT] Da mo khoa. Nen bam '0' ve HOME truoc khi chay chu ky.");
    return true;
}

// ------------------------------------------------------------ Jog

void motionJogStart(int dir) {
    waitDeadtime();
    curIdx = IDX_NONE;
    curEstimated = false;
    nv.moving = 0;
    nv.lastIdx = nv.fromIdx = nv.toIdx = IDX_NONE;   // quay tay: mọi gợi ý cũ vô nghĩa
    nvCommit();                                      // ghi TRƯỚC khi motor chạy
    motorGo(dir);
}

void motionJogStop() { motorBrake(); }

// ------------------------------------------------------------ In trạng thái

void motionPrintState() {
    Serial.printf("[STATE] vi tri=%s%s | xoan=", stName(curIdx), motionPositionEstimated() ? " (uoc luong)" : "");
    if (curIdx < 0) Serial.print("?");
    else            Serial.printf("%+d do", STATION_TWIST_DEG[curIdx]);
    Serial.printf(" | CW tFirst/tMid=%u/%ums  CCW=%u/%ums\n",
                  nv.tFirst[0], nv.tMid[0], nv.tFirst[1], nv.tMid[1]);
    if (nv.deadMask) {
        Serial.print("        IR CHET:");
        for (int i = 0; i < STATION_COUNT; i++) if (isDead(i)) Serial.printf(" %s", stName(i));
        Serial.println(" — che do suy giam");
    }
    if (faultLatched)
        Serial.printf("        !! DANG KHOA (FAULT): %s — bam 'f' de mo khoa.\n", faultWhy);
    else if (consecFail)
        Serial.printf("        canh bao: %d/%d lan loi lien tiep.\n", consecFail, MOTION_MAX_CONSEC_FAIL);
}

// ------------------------------------------------------------ Khởi tạo

void motionBegin() {
    // Không pinMode cho chân motor: LEDC chiếm quyền qua GPIO matrix.
    ledcSetup(MOTOR_LEDC_CH_IN1, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcSetup(MOTOR_LEDC_CH_IN2, MOTOR_LEDC_FREQ, MOTOR_LEDC_BITS);
    ledcAttachPin(PIN_MOTOR_IN1, MOTOR_LEDC_CH_IN1);
    ledcAttachPin(PIN_MOTOR_IN2, MOTOR_LEDC_CH_IN2);
    motionCoast();

    // GPIO 34/35 input-only, không có trở kéo nội. DO của LM393 là open-collector,
    // mức HIGH nhờ trở kéo trên module (xem CLAUDE.md về chia áp 10k+20k).
    for (int i = 0; i < STATION_COUNT; i++) {
        pinMode(STATION_PIN[i], INPUT);
        attachInterruptArg(digitalPinToInterrupt(STATION_PIN[i]), irIsr,
                           (void*)(intptr_t)i, IR_ACTIVE_LOW ? FALLING : RISING);
    }

    nvDefaults(nv);
    nvOk = prefs.begin("motion", false);
    if (!nvOk) {
        Serial.println("[NVS] KHONG mo duoc NVS — chay khong co goi y vi tri.");
    } else if (prefs.getBytesLength("st") == sizeof(NvState)) {
        NvState s;
        prefs.getBytes("st", &s, sizeof s);
        if (s.ver == NV_VER) nv = s;
    }
    nvSaved = nv;

    faultLatched = false;
    faultWhy     = NULL;
    consecFail   = 0;
    curIdx       = IDX_NONE;
    curEstimated = false;
}
