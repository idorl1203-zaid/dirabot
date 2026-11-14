# 🏠 DiraBot — סוכן חיפוש דירות

סוכן Python אוטונומי שסורק יד2 ומדלן, מסנן לפי הקריטריונים שלך, ושולח התראות ל-Telegram — ללא כפילויות.

---

## ⚡ התקנה מהירה

### שלב 1 — התקן תלויות
```bash
cd ~/Desktop/DiraBot
pip install -r requirements.txt
```

### שלב 2 — הגדר מפתחות API
```bash
cp .env.example .env
# ערוך את .env והכנס את המפתחות
```

**Gemini API Key** (חינם):
👉 https://aistudio.google.com/app/api-keys

**Telegram Bot Token**:
1. פתח Telegram ועבור ל-@BotFather
2. שלח `/newbot`
3. בחר שם לבוט
4. קבל את ה-TOKEN
5. שלח `/start` לבוט שלך
6. עבור ל: `https://api.telegram.org/bot<TOKEN>/getUpdates`
7. העתק את ה-`chat_id` ל-`config.yaml` תחת `notifications.telegram_chat_id`

### שלב 3 — הגדר פרופיל (אינטראקטיבי!)
```bash
python agent.py --setup
```
הסוכן ישאל אתכם שאלות ויבנה את הקריטריונים אוטומטית ב-`config.yaml`.

### שלב 4 — הרץ!
```bash
python agent.py
```

---

## 📋 פקודות

| פקודה | מה עושה |
|---|---|
| `python agent.py` | הרצה מלאה עם טריגרים תקופתיים |
| `python agent.py --setup` | שיחת הגדרת פרופיל |
| `python agent.py --scan-now` | סריקה חד-פעמית מיידית |

---

## ⚙️ שינוי קריטריונים

העתק את `config.example.yaml` ל-`config.yaml` וערוך אותו — שינויים נכנסים לתוקף בסריקה הבאה, **ללא הפעלה מחדש!**

```yaml
search:
  locations:
    - "תל אביב יפו"
    - "הרצליה"
  price:
    min: 4000
    max: 8000
  rooms:
    min: 2
    max: 3.5
```

---

## 📁 מבנה הפרויקט

```
DiraBot/
├── agent.py              # הסוכן הראשי
├── config.yaml           # ← שנה כאן!
├── db.py                 # SQLite + deduplication
├── telegram_notifier.py  # שליחת הודעות
├── profile_builder.py    # הגדרת פרופיל
├── scraper/
│   ├── yad2.py           # יד2
│   ├── madlan.py         # מדלן
│   └── base.py           # לוגיקת ניקוד
├── .env                  # מפתחות (לא עולה ל-git!)
└── dirabot.db            # נוצר אוטומטית
```

---

## 📱 דוגמת הודעת Telegram

```
🏠 דירה חדשה נמצאה! ⭐⭐⭐
🟡 Yad2   •   📊 ציון: 87/100

📍 תל אביב, רמת אביב
🛏 3 חדרים  •  קומה 4
💰 6,200 ₪/חודש
📐 75 מ"ר
🌿 מרפסת  •  🛗 מעלית

📝 דירה מרווחת, שמשה, שיפוץ מלא...

🔗 לצפייה במודעה
```
