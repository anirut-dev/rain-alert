import requests
import json
import os
from datetime import datetime, timezone, timedelta

TZ_BANGKOK = timezone(timedelta(hours=7))

# ===== CONFIG =====
CITIES = [
    {"name": "บ้าน",       "lat": 14.2089, "lon": 100.7367},  # ลำไทร วังน้อย อยุธยา
    {"name": "ที่ทำงาน",   "lat": 14.0384, "lon": 100.6166},  # คลองหนึ่ง คลองหลวง ปทุมธานี
]

RAIN_THRESHOLD       = 70   # % แจ้งเตือนฝน
PM25_THRESHOLD       = 50   # µg/m³
MORNING_HOUR         = 7    # รายงานเช้า
EVENING_HOUR         = 17   # รายงานขากลับ
ACTIVE_START         = 6    # แจ้งเตือนรายชั่วโมงตั้งแต่ 06:00
ACTIVE_END           = 21   # ถึง 21:00 (กันเด้งกลางดึก)
LINE_TOKEN           = os.environ["LINE_CHANNEL_TOKEN"]
LINE_USER_ID         = os.environ["LINE_USER_ID"]
STATE_FILE           = "alert_state.json"
# ==================

PM25_LEVELS = [
    (0,   15,  "ดีมาก 😊",         ""),
    (15,  25,  "ดี 🟢",             ""),
    (25,  50,  "ปานกลาง 🟡",       ""),
    (50,  75,  "เริ่มมีผล 🟠",      "⚠️ ควรลดกิจกรรมกลางแจ้ง"),
    (75,  150, "มีผลต่อสุขภาพ 🔴", "🚨 หลีกเลี่ยงกิจกรรมกลางแจ้ง"),
    (150, 999, "อันตราย ☠️",        "🚨 อยู่ในอาคาร สวมหน้ากาก N95"),
]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_session_key():
    now = datetime.now(TZ_BANGKOK)
    period = "am" if now.hour < 12 else "pm"
    return f"{now.strftime('%Y-%m-%d')}-{period}"


def get_weather(lat, lon):
    """ดึงโอกาสฝน (ชั่วโมงนี้ + ถัดไป) และ PM2.5"""
    rain_res = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "precipitation_probability",
            "forecast_days": 1, "timezone": "Asia/Bangkok",
        },
        timeout=10,
    )
    rain_res.raise_for_status()
    hourly_rain = rain_res.json()["hourly"]["precipitation_probability"]
    current_hour = datetime.now(TZ_BANGKOK).hour
    rain_now  = hourly_rain[current_hour]
    rain_next = hourly_rain[current_hour + 1] if current_hour < 23 else rain_now

    aqi_res = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "pm2_5",
            "forecast_days": 1, "timezone": "Asia/Bangkok",
        },
        timeout=10,
    )
    aqi_res.raise_for_status()
    pm25 = aqi_res.json()["hourly"]["pm2_5"][current_hour]

    return rain_now, rain_next, round(pm25, 1)


def pm25_label(pm25):
    for lo, hi, label, advice in PM25_LEVELS:
        if lo <= pm25 < hi:
            return label, advice
    return "ไม่ทราบ", ""


def send_line_message(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    res = requests.post(url, headers=headers, json=body, timeout=10)
    res.raise_for_status()


def get_gold_prices():
    """ดึงราคาทองคำไทย 96.5% จาก thaigold.info (มีราคาเปลี่ยนแปลงวันนี้ในตัว)"""
    try:
        res = requests.get("https://www.thaigold.info/RealTimeDataV2/gtdata_.txt", timeout=10)
        res.raise_for_status()
        rows = {r.get("name"): r for r in res.json()}
        bar = rows.get("สมาคมฯ", {})   # ทองคำแท่ง 96.5% (ราคาสมาคมค้าทองคำ)
        return {
            "bar_buy":  str(bar.get("bid", "-")),   # รับซื้อ
            "bar_sell": str(bar.get("ask", "-")),   # ขายออก
            "diff":     bar.get("diff", ""),         # เปลี่ยนแปลงจากเมื่อวาน
        }
    except Exception as e:
        print(f"  ⚠️ ดึงราคาทองไม่ได้: {e}")
        return {}


def gold_change_label(diff):
    """แปลงค่า diff ของ thaigold.info เป็นข้อความขึ้น/ลง"""
    try:
        d = float(str(diff).replace(",", "").replace("+", ""))
        if d > 0:
            return f"▲ +{d:,.0f}"
        elif d < 0:
            return f"▼ {d:,.0f}"
        else:
            return "— ไม่เปลี่ยน"
    except Exception:
        return ""


def gold_price_lines(prices):
    change = gold_change_label(prices.get("diff", ""))
    # ทองรูปพรรณขายออก = ทองแท่งขายออก + 500 (มาตรฐานราคาไทย)
    try:
        shape_sell = f"{float(prices.get('bar_sell','0').replace(',','')) + 500:,.0f}"
    except Exception:
        shape_sell = "-"
    return [
        "🥇 ราคาทองคำ 96.5% วันนี้ (บาท)",
        f"  • ทองแท่ง    รับซื้อ {prices.get('bar_buy', '-')} | ขายออก {prices.get('bar_sell', '-')}  {change}",
        f"  • ทองรูปพรรณ ขายออก {shape_sell}",
    ]


def get_fuel_prices():
    """ดึงราคาน้ำมัน PTT: E20, ดีเซล (B7), ดีเซล B20"""
    try:
        res = requests.get("https://api.chnwt.dev/thai-oil-api/latest", timeout=10)
        res.raise_for_status()
        data = res.json()
        ptt = data.get("response", {}).get("stations", {}).get("ptt", {})
        return {
            "E20":    ptt.get("gasohol_e20",  {}).get("price", "-"),
            "B7":     ptt.get("diesel",        {}).get("price", "-"),
            "diesel_b20": ptt.get("diesel_b20", {}).get("price", "-"),
        }
    except Exception as e:
        print(f"  ⚠️ ดึงราคาน้ำมันไม่ได้: {e}")
        return {}


def fuel_price_lines(prices):
    return [
        "⛽ ราคาน้ำมัน PTT วันนี้",
        f"  • แก๊สโซฮอล์ E20 : {prices.get('E20', '-')} บ./ลิตร",
        f"  • ดีเซล B7        : {prices.get('B7', '-')} บ./ลิตร",
        f"  • ดีเซล B20       : {prices.get('diesel_b20', '-')} บ./ลิตร",
    ]


def build_morning_report(name, rain_now, rain_next, pm25, level_label, advice, now, fuel_prices, gold_prices):
    rain_line = f"🌧 โอกาสฝน: {rain_now}% — {'ควรพกร่ม!' if rain_now >= RAIN_THRESHOLD else 'ไม่น่ามีฝน'}"
    next_line = f"⏭ ชั่วโมงถัดไป: {rain_next}%{' ⚠️' if rain_next >= RAIN_THRESHOLD else ''}"
    lines = [
        f"🌅 สวัสดีตอนเช้า! สรุปอากาศวันนี้",
        f"📍 {name} — {now.strftime('%d/%m/%Y %H:%M')} น.",
        f"{'─' * 25}",
        rain_line,
        next_line,
        f"💨 PM2.5: {pm25} µg/m³ — {level_label}",
    ]
    if advice:
        lines.append(advice)
    if fuel_prices:
        lines.append(f"{'─' * 25}")
        lines.extend(fuel_price_lines(fuel_prices))
    if gold_prices:
        lines.append(f"{'─' * 25}")
        lines.extend(gold_price_lines(gold_prices))
    return "\n".join(lines)


def build_evening_report(name, rain_now, rain_next, pm25, level_label, advice, now):
    rain_line = f"🌧 โอกาสฝน: {rain_now}% — {'ระวังฝนขากลับ! 🌂' if rain_now >= RAIN_THRESHOLD else 'น่าจะกลับได้สบาย ✅'}"
    next_line = f"⏭ ชั่วโมงถัดไป: {rain_next}%{' ⚠️' if rain_next >= RAIN_THRESHOLD else ''}"
    lines = [
        f"🌆 อัปเดตอากาศช่วงเย็น — ขากลับบ้าน",
        f"📍 {name} — {now.strftime('%H:%M')} น.",
        f"{'─' * 25}",
        rain_line,
        next_line,
        f"💨 PM2.5: {pm25} µg/m³ — {level_label}",
    ]
    if advice:
        lines.append(advice)
    return "\n".join(lines)


def build_alert_message(name, rain_now, rain_next, pm25, level_label, advice, now):
    period_label = "เช้า" if now.hour < 12 else "บ่าย/เย็น"
    lines = [f"⚠️ แจ้งเตือน — {name}",
             f"⏰ {now.strftime('%H:%M')} น. (รอบ{period_label})"]
    if rain_now >= RAIN_THRESHOLD:
        lines.append(f"🌧 โอกาสฝน: {rain_now}% → อย่าลืมพกร่ม!")
    if rain_next >= RAIN_THRESHOLD:
        lines.append(f"⏭ ชั่วโมงถัดไปยังมีฝน: {rain_next}%")
    if pm25 >= PM25_THRESHOLD:
        lines.append(f"💨 PM2.5: {pm25} µg/m³ — {level_label}")
        if advice:
            lines.append(advice)
    return "\n".join(lines)


def build_incoming_rain_message(name, rain_next, now):
    """แจ้งล่วงหน้าว่าอีก 1 ชั่วโมงจะมีฝน"""
    return (
        f"🌂 แจ้งเตือนล่วงหน้า — {name}\n"
        f"⏰ {now.strftime('%H:%M')} น.\n"
        f"⛈ อีก 1 ชั่วโมงโอกาสฝน: {rain_next}%\n"
        f"กรุณาเตรียมร่มไว้ล่วงหน้า!"
    )


def main():
    now = datetime.now(TZ_BANGKOK)
    today_str   = now.strftime("%Y-%m-%d")
    session_key = get_session_key()
    state = load_state()
    alerted_this_session = state.get(session_key, [])

    # GitHub Actions มักข้ามรอบ cron ต้นชั่วโมง จึงไม่เช็คชั่วโมงเป๊ะ
    # แต่ยิงรายงานในรอบแรกที่เจอภายในช่วงเวลา แล้วกันส่งซ้ำด้วย morning_done/evening_done
    in_morning_window = MORNING_HOUR <= now.hour < 12
    in_evening_window = EVENING_HOUR <= now.hour < 22
    do_morning = in_morning_window and state.get("morning_done") != today_str
    do_evening = in_evening_window and state.get("evening_done") != today_str

    do_morning = True  # TEMP TEST: บังคับส่งรายงานเช้าเพื่อทดสอบ — ลบบรรทัดนี้หลังเทสต์

    fuel_prices = get_fuel_prices() if do_morning else {}
    gold_prices = get_gold_prices() if do_morning else {}

    morning_sent = False
    evening_sent = False

    mode = "รายงานเช้า" if do_morning else ("รายงานเย็น" if do_evening else f"รอบ {session_key}")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] เริ่มเช็ค {len(CITIES)} เมือง ({mode})")

    for city in CITIES:
        name = city["name"]

        if not do_morning and not do_evening and name in alerted_this_session:
            print(f"  ⏭ {name}: แจ้งไปแล้วในรอบนี้ ข้าม")
            continue

        try:
            rain_now, rain_next, pm25 = get_weather(city["lat"], city["lon"])
            level_label, advice = pm25_label(pm25)
            print(f"  🌦 {name}: ฝนตอนนี้ {rain_now}% | ชั่วโมงหน้า {rain_next}% | PM2.5 {pm25} µg/m³")

            # --- รายงานเช้า ---
            if do_morning:
                msg = build_morning_report(name, rain_now, rain_next, pm25, level_label, advice, now, fuel_prices, gold_prices)
                send_line_message(msg)
                morning_sent = True
                print(f"  ✅ {name}: ส่งรายงานเช้าแล้ว")

            # --- รายงานเย็น 17:00 ---
            elif do_evening:
                msg = build_evening_report(name, rain_now, rain_next, pm25, level_label, advice, now)
                send_line_message(msg)
                evening_sent = True
                print(f"  ✅ {name}: ส่งรายงานเย็นแล้ว")

            # แจ้งเตือนรายชั่วโมงเฉพาะช่วงกลางวัน (state ฝนยังอัปเดตตลอด)
            elif not (ACTIVE_START <= now.hour <= ACTIVE_END):
                print(f"  💤 {name}: นอกเวลาแจ้งเตือน ({now.strftime('%H:%M')}) ข้าม")

            else:
                # แจ้งเตือนฉุกเฉิน (ฝนหรือ PM2.5 เกิน threshold)
                if rain_now >= RAIN_THRESHOLD or pm25 >= PM25_THRESHOLD:
                    msg = build_alert_message(name, rain_now, rain_next, pm25, level_label, advice, now)
                    send_line_message(msg)
                    alerted_this_session.append(name)
                    print(f"  ✅ {name}: ส่งแจ้งเตือนฉุกเฉินแล้ว")

                # แจ้งล่วงหน้า: ตอนนี้ยังไม่มีฝน แต่ชั่วโมงหน้าจะมี
                elif rain_next >= RAIN_THRESHOLD and rain_now < RAIN_THRESHOLD:
                    msg = build_incoming_rain_message(name, rain_next, now)
                    send_line_message(msg)
                    alerted_this_session.append(name)
                    print(f"  ✅ {name}: ส่งแจ้งเตือนล่วงหน้าแล้ว")

        except Exception as e:
            print(f"  ❌ {name}: error — {e}")

    # อัปเดต state
    state[session_key] = alerted_this_session

    # ตัดเหลือ 4 รอบล่าสุด (กันไฟล์บวม) — คีย์พิเศษเก็บไว้เสมอ
    SPECIAL = ("morning_done", "evening_done")
    session_keys = sorted((k for k in state if k not in SPECIAL), reverse=True)
    keep = set(session_keys[:4])
    state = {k: v for k, v in state.items() if k in keep or k in SPECIAL}

    # บันทึกว่าวันนี้ส่งรายงานเช้า/เย็นแล้ว (กันรอบสำรองส่งซ้ำ)
    if do_morning and morning_sent:
        state["morning_done"] = today_str
    if do_evening and evening_sent:
        state["evening_done"] = today_str

    save_state(state)

    print("เสร็จแล้ว ✓")


if __name__ == "__main__":
    main()
