import requests
import json
import os
from datetime import datetime

# ===== CONFIG =====
CITIES = [
    {"name": "บ้าน",       "lat": 14.2089, "lon": 100.7367},  # ลำไทร วังน้อย อยุธยา
    {"name": "ที่ทำงาน",   "lat": 14.0384, "lon": 100.6166},  # คลองหนึ่ง คลองหลวง ปทุมธานี
    # เพิ่มเมืองได้ที่นี่
]

RAIN_THRESHOLD  = 70  # % โอกาสฝนที่จะแจ้งเตือน
PM25_THRESHOLD  = 50  # µg/m³ ระดับที่จะแจ้งเตือน
MORNING_REPORT_HOUR = 7  # ส่งสรุปอากาศประจำวันเวลา 07:00
LINE_TOKEN      = os.environ["LINE_CHANNEL_TOKEN"]
LINE_USER_ID    = os.environ["LINE_USER_ID"]
STATE_FILE      = "alert_state.json"
# ==================

PM25_LEVELS = [
    (0,   15,  "ดีมาก 😊",            ""),
    (15,  25,  "ดี 🟢",                ""),
    (25,  50,  "ปานกลาง 🟡",          ""),
    (50,  75,  "เริ่มมีผล 🟠",         "⚠️ ควรลดกิจกรรมกลางแจ้ง"),
    (75,  150, "มีผลต่อสุขภาพ 🔴",    "🚨 หลีกเลี่ยงกิจกรรมกลางแจ้ง"),
    (150, 999, "อันตราย ☠️",           "🚨 อยู่ในอาคาร สวมหน้ากาก N95"),
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
    now = datetime.now()
    period = "am" if now.hour < 12 else "pm"
    return f"{now.strftime('%Y-%m-%d')}-{period}"


def get_weather(lat, lon):
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
    current_hour = datetime.now().hour
    rain_prob = rain_res.json()["hourly"]["precipitation_probability"][current_hour]

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

    return rain_prob, round(pm25, 1)


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


def build_morning_report(name, rain_prob, pm25, level_label, advice, now):
    """สร้างข้อความสรุปอากาศประจำเช้า"""
    rain_line = f"🌧 โอกาสฝน: {rain_prob}% — {'ควรพกร่ม!' if rain_prob >= RAIN_THRESHOLD else 'ไม่น่ามีฝน'}"
    lines = [
        f"🌅 สวัสดีตอนเช้า! สรุปอากาศวันนี้",
        f"📍 {name} — {now.strftime('%d/%m/%Y %H:%M')} น.",
        f"{'─' * 25}",
        rain_line,
        f"💨 PM2.5: {pm25} µg/m³ — {level_label}",
    ]
    if advice:
        lines.append(advice)
    return "\n".join(lines)


def build_alert_message(name, rain_prob, pm25, level_label, advice, now):
    """สร้างข้อความแจ้งเตือนฉุกเฉิน"""
    period_label = "เช้า" if now.hour < 12 else "บ่าย/เย็น"
    lines = [f"⚠️ แจ้งเตือน — {name}",
             f"⏰ {now.strftime('%H:%M')} น. (รอบ{period_label})"]
    if rain_prob >= RAIN_THRESHOLD:
        lines.append(f"🌧 โอกาสฝน: {rain_prob}% → อย่าลืมพกร่ม!")
    if pm25 >= PM25_THRESHOLD:
        lines.append(f"💨 PM2.5: {pm25} µg/m³ — {level_label}")
        if advice:
            lines.append(advice)
    return "\n".join(lines)


def main():
    now = datetime.now()
    is_morning_report = (now.hour == MORNING_REPORT_HOUR)
    session_key = get_session_key()
    state = load_state()
    alerted_this_session = state.get(session_key, [])

    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] เริ่มเช็ค {len(CITIES)} เมือง "
          f"({'รายงานเช้า' if is_morning_report else f'รอบ {session_key}'})")

    for city in CITIES:
        name = city["name"]

        # รอบปกติ: ถ้าแจ้งไปแล้วในรอบนี้ให้ข้าม (ยกเว้นรอบเช้า 7 โมงจะส่งเสมอ)
        if not is_morning_report and name in alerted_this_session:
            print(f"  ⏭ {name}: แจ้งไปแล้วในรอบนี้ ข้าม")
            continue

        try:
            rain_prob, pm25 = get_weather(city["lat"], city["lon"])
            level_label, advice = pm25_label(pm25)
            print(f"  🌦 {name}: ฝน {rain_prob}% | PM2.5 {pm25} µg/m³ ({level_label})")

            if is_morning_report:
                msg = build_morning_report(name, rain_prob, pm25, level_label, advice, now)
                send_line_message(msg)
                print(f"  ✅ {name}: ส่งรายงานเช้าแล้ว")
            else:
                rain_alert = rain_prob >= RAIN_THRESHOLD
                pm25_alert = pm25 >= PM25_THRESHOLD
                if rain_alert or pm25_alert:
                    msg = build_alert_message(name, rain_prob, pm25, level_label, advice, now)
                    send_line_message(msg)
                    alerted_this_session.append(name)
                    print(f"  ✅ {name}: ส่งแจ้งเตือนแล้ว")

        except Exception as e:
            print(f"  ❌ {name}: error — {e}")

    state[session_key] = alerted_this_session
    keys_sorted = sorted(state.keys(), reverse=True)
    state = {k: state[k] for k in keys_sorted[:4]}
    save_state(state)

    print("เสร็จแล้ว ✓")


if __name__ == "__main__":
    main()
