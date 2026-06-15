# 🌧 Rain Alert → LINE

แจ้งเตือนผ่าน LINE เมื่อโอกาสฝนเกิน 70% — รันอัตโนมัติทุกชั่วโมงผ่าน GitHub Actions

---

## ขั้นตอน Setup

### 1. Fork หรือสร้าง Repo ใหม่

อัปโหลดไฟล์ทั้งหมดขึ้น GitHub repo ของคุณ

---

### 2. สมัคร LINE Messaging API

1. ไปที่ [developers.line.biz](https://developers.line.biz)
2. สร้าง Provider → สร้าง Channel ประเภท **Messaging API**
3. เปิด **LINE Official Account Manager** → ปิด "Auto-reply" และ "Greeting message"
4. กลับมาที่ Developer Console → แท็บ **Messaging API**
5. กด **Issue** ที่ "Channel access token (long-lived)" → Copy เก็บไว้
6. หา **User ID** ของคุณได้ที่แท็บ **Basic settings** → "Your user ID"

---

### 3. ตั้งค่า GitHub Secrets

ไปที่ repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | ค่า |
|---|---|
| `LINE_CHANNEL_TOKEN` | Channel access token จากข้อ 2 |
| `LINE_USER_ID` | User ID จากข้อ 2 |

---

### 4. แก้ไขเมืองใน rain_alert.py

```python
CITIES = [
    {"name": "บ้าน",       "lat": 13.7563, "lon": 100.5018},
    {"name": "ที่ทำงาน",   "lat": 13.7308, "lon": 100.5212},
]
```

หา lat/lon ของเมืองได้จาก [Google Maps](https://maps.google.com) → คลิกขวาที่จุด → Copy좌표

---

### 5. ทดสอบ

ไปที่ repo → **Actions → Rain Alert → Run workflow** → กด Run

ถ้าทุกอย่างถูกต้อง LINE จะได้รับข้อความทันที (ถ้าโอกาสฝนเกิน 70%)

---

## ปรับแต่งเพิ่มเติม

| ต้องการ | แก้ที่ |
|---|---|
| เปลี่ยน threshold | `RAIN_THRESHOLD = 70` ใน rain_alert.py |
| เพิ่มเมือง | เพิ่ม dict ใน `CITIES` |
| แจ้งเฉพาะช่วงเวลา | แก้ cron ใน rain_alert.yml |
| แจ้ง Group LINE | ใช้ Group ID แทน User ID |

---

## โครงสร้างไฟล์

```
rain-alert/
├── rain_alert.py              # โค้ดหลัก
├── .github/
│   └── workflows/
│       └── rain_alert.yml     # GitHub Actions
└── README.md
```
