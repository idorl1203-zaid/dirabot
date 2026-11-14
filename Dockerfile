# DiraBot — קונטיינר לפריסה always-on (Railway / Render / Fly.io)
# בסיס: image רשמי של Playwright — כולל Chromium + כל תלויות המערכת
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

# תלויות פייתון (playwright 1.62 כבר מותקן ב-image → לא ישודרג)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# קוד האפליקציה
COPY . .

# ה-DB וה-config נשמרים ב-volume קבוע (מוגדר ב-Railway על /data)
ENV DIRABOT_DB_PATH=/data/dirabot.db \
    DIRABOT_CONFIG_PATH=/data/config.yaml \
    PORT=6008

EXPOSE 6008

# shell form כדי ש-$PORT יורחב (הפלטפורמה מזריקה PORT דינמי)
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-6008}
