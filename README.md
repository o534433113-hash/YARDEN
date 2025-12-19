# MoonGuard - מערכת חמ"ל לאימות רכבים

מערכת לזיהוי ואימות רכבים באמצעות LPR (זיהוי לוחיות רישוי) בשילוב AI.

## התקנה

```bash
# יצירת סביבה וירטואלית
python -m venv venv
venv\Scripts\activate  # Windows

# התקנת תלויות
pip install -r requirements.txt
```

## הרצה

```bash
# הפעלת השרת
python backend/main.py
```

## שימוש

1. פתח את הדפדפן בכתובת: `http://localhost:8000`
2. בחר תיקייה לניטור דרך הממשק
3. המערכת תתחיל לעקוב אחר תמונות חדשות בתיקייה

## פורמט שם קובץ

```
9908_01_20251211121434974_7072996_1_P1.jpg
|____|  |_______________|  |_____|
  |            |             |
מיקום      תאריך+שעה     לוחית רישוי
```

## API Endpoints

- `POST /api/watch/start` - התחלת ניטור תיקייה
- `POST /api/watch/stop` - עצירת ניטור
- `GET /api/watch/status` - סטטוס הניטור
- `GET /api/events` - רשימת אירועים
- `WS /ws` - WebSocket לעדכונים בזמן אמת

