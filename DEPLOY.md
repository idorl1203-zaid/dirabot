# 🚀 פריסת DiraBot ל-Railway (always-on 24/7)

DiraBot דורש תהליך שרץ תמידית עם דפדפן Playwright — לכן **לא מתאים ל-Vercel/serverless**.
Railway מריץ קונטיינר Docker תמידי עם דיסק קבוע — מתאים בול.

הכל כבר מוכן בפרויקט: `Dockerfile`, `.dockerignore`, `railway.json`.

---

## שלבים (מריצים מתוך תיקיית הפרויקט)

```bash
cd ~/Desktop/DiraBot
```

### 1. התקנת Railway CLI
```bash
npm i -g @railway/cli
# או: brew install railway
```

### 2. התחברות (נפתח בדפדפן)
```bash
railway login
```

### 3. יצירת פרויקט
```bash
railway init          # בחר שם, למשל: dirabot
```

### 4. דיסק קבוע ל-DB וה-config (חשוב — אחרת הנתונים נמחקים בכל דיפלוי!)
צור volume וחבר אותו לנתיב **`/data`**:
```bash
railway volume add --mount-path /data
```
(או דרך הדשבורד: Service → Settings → Volumes → Mount path `/data`)

### 5. משתני סביבה (המפתחות מ-`.env`)
```bash
railway variables --set "TELEGRAM_BOT_TOKEN=<הטוקן מ-.env>" \
                  --set "GEMINI_API_KEY=<המפתח מ-.env>"
```
> `telegram_chat_id` כבר נמצא ב-`config.yaml` (נזרע ל-volume אוטומטית).

### 6. דיפלוי!
```bash
railway up
```
Railway יבנה את ה-Dockerfile (כמה דקות — מוריד Chromium), יעלה, ויריץ.

### 7. כתובת ציבורית לדשבורד
```bash
railway domain
```
תקבל URL כמו `https://dirabot-production.up.railway.app`.

---

## מה קורה אחרי הדיפלוי
- הבוט סורק כל 2.5 שעות ושולח התראות Telegram — **גם כשהמק כבוי**.
- הדשבורד נגיש מה-URL הציבורי.
- ה-DB (מצב הדדופ) נשמר ב-volume ולא נמחק בין דיפלויים.
- שינויים בפרופילים דרך הדשבורד נשמרים ל-volume.

## עלות
Railway: ~$5/חודש usage-based (יש קרדיט חינם להתחלה). Chromium + התהליך התמידי צורכים RAM צנוע.

## פתרון תקלות
- **build נכשל על ה-image:** אם `v1.62.0-jammy` לא קיים, עדכן ב-Dockerfile לגרסת playwright הקרובה (ראה https://mcr.microsoft.com/en-us/product/playwright/python/tags).
- **הבוט לא שולח:** ודא ש-`TELEGRAM_BOT_TOKEN` ו-`GEMINI_API_KEY` הוגדרו (`railway variables`).
- **נתונים נמחקים בין דיפלויים:** ה-volume לא מחובר ל-`/data` — חזור לשלב 4.
