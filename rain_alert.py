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
RAIN_CLEAR_THRESHOLD = 30   # % ถือว่าฝนหยุดแล้ว
PM25_THRESHOLD       = 50   # µg/m³
MORNING_HOUR         = 7    # รายงานเช้า
EVENING_HOUR         = 17   # รายงานขากลับ
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
    """ดึงราคาทองคำไทย (ทองแท่ง + ทองรูปพรรณ)"""
    try:
        res = requests.get("https://api.chnwt.dev/thai-gold-api/latest", timeout=10)
        res.raise_for_status()
        price = res.json().get("response", {}).get("price", {})
        return {
            "bar_buy":    price.get("gold_bar", {}).get("buy",  "-"),
            "bar_sell":   price.get("gold_bar", {}).get("sell", "-"),
            "shape_buy":  price.get("gold",     {}).get("buy",  "-"),
            "shape_sell": price.get("gold",     {}).get("sell", "-"),
        }
    except Exception as e:
        print(f"  ⚠️ ดึงราคาทองไม่ได้: {e}")
        return {}


def gold_change_label(today_str, yesterday_str):
    """คำนวณส่วนต่างราคาทองเทียบเมื่อวาน"""
    try:
        diff = float(today_str.replace(",", "")) - float(yesterday_str.replace(",", ""))
        if diff > 0:
            return f"▲ +{diff:,.0f}"
        elif diff < 0:
            return f"▼ {diff:,.0f}"
        else:
            return "— ไม่เปลี่ยน"
    except Exception:
        return ""


def gold_price_lines(prices, prev_gold):
    bar_change   = gold_change_label(prices.get("bar_sell", "0"),   prev_gold.get("bar_sell",   "0")) if prev_gold else ""
    shape_change = gold_change_label(prices.get("shape_sell", "0"), prev_gold.get("shape_sell", "0")) if prev_gold else ""
    return [
        "🥇 ราคาทองคำวันนี้ (บาท/บาททอง)",
        f"  • ทองแท่ง    ซื้อ {prices.get('bar_buy', '-')} | ขาย {prices.get('bar_sell', '-')} {bar_change}",
        f"  • ทองรูปพรรณ ซื้อ {prices.get('shape_buy', '-')} | ขาย {prices.get('shape_sell', '-')} {shape_change}",
    ]


def get_fuel_prices():
    """ดึงราคาน้ำมัน PTT: E20, ดีเซล (B7), ดีเซล B20"""
    try:
        res = requests.get("https://api.chnwt.dev/thai-oil-api/latest", timeout=10)
        res.raise_for_status()
        data = res.json()
        ptt = data.get("data", {}).get("ptt", {})
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


def build_morning_report(name, rain_now, rain_next, pm25, level_label, advice, now, fuel_prices, gold_prices, prev_gold):
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
        lines.extend(gold_price_lines(gold_prices, prev_gold))
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


def build_rain_cleared_message(name, rain_now, now):
    """แจ้งเมื่อฝนหยุดแล้ว"""
    return (
        f"☀️ ฝนหยุดแล้ว — {name}\n"
        f"⏰ {now.strftime('%H:%M')} น.\n"
        f"💧 โอกาสฝนลดเหลือ: {rain_now}%\n"
        f"ออกไปข้างนอกได้แล้วครับ!"
    )


def main():
    now = datetime.now(TZ_BANGKOK)
    is_morning  = (now.hour == MORNING_HOUR)
    is_evening  = (now.hour == EVENING_HOUR)
    session_key = get_session_key()
    state = load_state()
    alerted_this_session = state.get(session_key, [])

    # เก็บ state ฝนรอบก่อนสำหรับตรวจสอบ "ฝนหยุด"
    prev_rain_state = state.get("prev_rain", {})
    new_rain_state  = {}

    fuel_prices = get_fuel_prices() if is_morning else {}
    gold_prices = get_gold_prices() if is_morning else {}
    prev_gold   = state.get("prev_gold", {})
    today_str   = now.strftime("%Y-%m-%d")

    mode = "รายงานเช้า" if is_morning else ("รายงานเย็น" if is_evening else f"รอบ {session_key}")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] เริ่มเช็ค {len(CITIES)} เมือง ({mode})")

    for city in CITIES:
        name = city["name"]

        if not is_morning and not is_evening and name in alerted_this_session:
            print(f"  ⏭ {name}: แจ้งไปแล้วในรอบนี้ ข้าม")
            continue

        try:
            rain_now, rain_next, pm25 = get_weather(city["lat"], city["lon"])
            level_label, advice = pm25_label(pm25)
            new_rain_state[name] = rain_now
            print(f"  🌦 {name}: ฝนตอนนี้ {rain_now}% | ชั่วโมงหน้า {rain_next}% | PM2.5 {pm25} µg/m³")

            # --- รายงานเช้า 07:00 ---
            if is_morning:
                msg = build_morning_report(name, rain_now, rain_next, pm25, level_label, advice, now, fuel_prices, gold_prices, prev_gold)
                send_line_message(msg)
                print(f"  ✅ {name}: ส่งรายงานเช้าแล้ว")

            # --- รายงานเย็น 17:00 ---
            elif is_evening:
                msg = build_evening_report(name, rain_now, rain_next, pm25, level_label, advice, now)
                send_line_message(msg)
                print(f"  ✅ {name}: ส่งรายงานเย็นแล้ว")

            else:
                sent = False

                # แจ้งเตือนฉุกเฉิน (ฝนหรือ PM2.5 เกิน threshold)
                if rain_now >= RAIN_THRESHOLD or pm25 >= PM25_THRESHOLD:
                    msg = build_alert_message(name, rain_now, rain_next, pm25, level_label, advice, now)
                    send_line_message(msg)
                    alerted_this_session.append(name)
                    sent = True
                    print(f"  ✅ {name}: ส่งแจ้งเตือนฉุกเฉินแล้ว")

                # แจ้งล่วงหน้า: ตอนนี้ยังไม่มีฝน แต่ชั่วโมงหน้าจะมี
                elif rain_next >= RAIN_THRESHOLD and rain_now < RAIN_THRESHOLD and not sent:
                    msg = build_incoming_rain_message(name, rain_next, now)
                    send_line_message(msg)
                    alerted_this_session.append(name)
                    sent = True
                    print(f"  ✅ {name}: ส่งแจ้งเตือนล่วงหน้าแล้ว")

                # แจ้งฝนหยุด: รอบก่อนฝน > 70% แต่ตอนนี้ลดลงต่ำกว่า 30%
                prev_rain = prev_rain_state.get(name, 0)
                if prev_rain >= RAIN_THRESHOLD and rain_now < RAIN_CLEAR_THRESHOLD and not sent:
                    msg = build_rain_cleared_message(name, rain_now, now)
                    send_line_message(msg)
                    print(f"  ✅ {name}: ส่งแจ้งฝนหยุดแล้ว")

        except Exception as e:
            print(f"  ❌ {name}: error — {e}")

    state[session_key] = alerted_this_session
    state["prev_rain"] = {**prev_rain_state, **new_rain_state}

    # บันทึกราคาทองวันนี้ไว้เปรียบเทียบพรุ่งนี้
    if is_morning and gold_prices:
        state["prev_gold"] = {**gold_prices, "date": today_str}

    keys_sorted = [k for k in sorted(state.keys(), reverse=True) if k not in ("prev_rain", "prev_gold")]
    state = {k: state[k] for k in keys_sorted[:4]}
    state["prev_rain"] = {**prev_rain_state, **new_rain_state}
    if is_morning and gold_prices:
        state["prev_gold"] = {**gold_prices, "date": today_str}
    save_state(state)

    print("เสร็จแล้ว ✓")


if __name__ == "__main__":
    main()
