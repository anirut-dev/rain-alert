import requests
import json
import os
from datetime import datetime

# ===== CONFIG =====
CITIES = [
    {"name": "บ้าน",       "lat": 13.7563, "lon": 100.5018},
    {"name": "ที่ทำงาน",   "lat": 13.7308, "lon": 100.5212},
    # เพิ่มเมืองได้ที่นี่
]

RAIN_THRESHOLD = 10   # % โอกาสฝนที่จะแจ้งเตือน
LINE_TOKEN     = os.environ["LINE_CHANNEL_TOKEN"]
LINE_USER_ID   = os.environ["LINE_USER_ID"]
STATE_FILE     = "alert_state.json"
# ==================


def load_state():
    """โหลด state ว่าแจ้งเตือนไปแล้วหรือยังในรอบนี้"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_session_key():
    """คีย์รอบ = เมือง + วันที่ + ช่วง (am/pm)"""
    now = datetime.now()
    period = "am" if now.hour < 12 else "pm"
    return f"{now.strftime('%Y-%m-%d')}-{period}"


def get_rain_probability(lat, lon):
    """ดึงโอกาสฝนชั่วโมงนี้จาก Open-Meteo"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation_probability",
        "forecast_days": 1,
        "timezone": "Asia/Bangkok",
    }
    res = requests.get(url, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    current_hour = datetime.now().hour
    prob = data["hourly"]["precipitation_probability"][current_hour]
    return prob


def send_line_message(message):
    """ส่งข้อความผ่าน LINE Messaging API"""
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


def main():
    now = datetime.now()
    session_key = get_session_key()
    state = load_state()
    alerted_this_session = state.get(session_key, [])

    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] เริ่มเช็ค {len(CITIES)} เมือง (รอบ {session_key})")

    for city in CITIES:
        name = city["name"]
        city_key = f"{session_key}-{name}"

        if name in alerted_this_session:
            print(f"  ⏭ {name}: แจ้งไปแล้วในรอบนี้ ข้าม")
            continue

        try:
            prob = get_rain_probability(city["lat"], city["lon"])
            print(f"  🌦 {name}: โอกาสฝน {prob}%")

            if prob >= RAIN_THRESHOLD:
                period_label = "เช้า" if now.hour < 12 else "บ่าย/เย็น"
                message = (
                    f"🌧 แจ้งเตือนฝน — {name}\n"
                    f"⏰ {now.strftime('%H:%M')} น. (รอบ{period_label})\n"
                    f"💧 โอกาสฝน: {prob}%\n"
                    f"🌂 อย่าลืมพกร่มด้วยนะ!"
                )
                send_line_message(message)
                alerted_this_session.append(name)
                print(f"  ✅ {name}: ส่ง LINE แล้ว")

        except Exception as e:
            print(f"  ❌ {name}: error — {e}")

    # บันทึก state
    state[session_key] = alerted_this_session

    # เก็บแค่ 4 รอบล่าสุด (2 วัน) ไม่ให้ไฟล์บวม
    keys_sorted = sorted(state.keys(), reverse=True)
    state = {k: state[k] for k in keys_sorted[:4]}
    save_state(state)

    print("เสร็จแล้ว ✓")


if __name__ == "__main__":
    main()
