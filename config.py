"""
קונפיגורציה מרכזית למערכת MoonGuard.
טוען משתני סביבה ומגדיר הגדרות גלובליות.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# טעינת משתני סביבה
load_dotenv()


class Config:
    """הגדרות מערכת MoonGuard."""
    
    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = "gpt-4o"
    
    # Server
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8090"))
    
    # Database
    DATABASE_PATH: Path = Path(os.getenv("DATABASE_PATH", "./moonguard.db"))
    
    # Folders
    PROCESSED_FOLDER: Path = Path(os.getenv("PROCESSED_FOLDER", "./processed"))
    ERRORS_FOLDER: Path = Path(os.getenv("ERRORS_FOLDER", "./errors"))
    
    # Government API
    GOV_API_URL: str = "https://data.gov.il/api/3/action/datastore_search"
    GOV_API_TIMEOUT: int = 10
    
    # מאגרי רכבים ממשלתיים
    GOV_DATABASES: dict = {
        # מאגר ראשי - רכבים פעילים
        "main": {
            "resource_id": "053cea08-09bc-40ec-8f7a-156f0677aff3",
            "name": "מאגר ראשי",
            "alert_type": None
        },
        # רכבים לא פעילים - ללא טסט מעל 13 חודשים
        "inactive": {
            "resource_id": "f6efe89a-fb3d-43a4-bb61-9bf12a9b9099",
            "name": "רכבים לא פעילים",
            "alert_type": "NO_LICENSE",
            "alert_message": "רכב ללא טסט/רשיון מעל שנה"
        },
        # רכבים שהורדו מהכביש - 3 מאגרים
        "off_road_1": {
            "resource_id": "851ecab1-0622-4dbe-a6c7-f950cf82abf9",
            "name": "מורדים מכביש #1",
            "alert_type": "OFF_ROAD",
            "alert_message": "רכב מורד מהכביש"
        },
        "off_road_2": {
            "resource_id": "4e6b9724-4c1e-43f0-909a-154d4cc4e046",
            "name": "מורדים מכביש #2",
            "alert_type": "OFF_ROAD",
            "alert_message": "רכב מורד מהכביש"
        },
        "off_road_3": {
            "resource_id": "ec8cbc34-72e1-4b69-9c48-22821ba0bd6c",
            "name": "מורדים מכביש #3",
            "alert_type": "OFF_ROAD",
            "alert_message": "רכב מורד מהכביש"
        },
        # רכבים ציבוריים
        "public": {
            "resource_id": "cf29862d-ca25-4691-84f6-1be60dcb4a1e",
            "name": "רכבים ציבוריים",
            "alert_type": None
        },
        # דו גלגליים
        "motorcycle": {
            "resource_id": "bf9df4e2-d90d-4c0a-a400-19e15af8e95f",
            "name": "דו גלגליים",
            "alert_type": None
        },
        # רכבים מעל 3.5 טון
        "heavy": {
            "resource_id": "cd3acc5c-03c3-4c89-9c54-d40f93c0d790",
            "name": "רכבים כבדים (מעל 3.5 טון)",
            "alert_type": None
        },
        # רכבים כבדים - מאגר נוסף
        "heavy_2": {
            "resource_id": "03adc637-b6fe-402b-9937-7c3d3afc9140",
            "name": "רכבים כבדים #2",
            "alert_type": None
        },
        # פרטיים ומסחריים - מידע מורחב
        "private_extended": {
            "resource_id": "0866573c-40cd-4ca8-91d2-9dd2d7a492e5",
            "name": "פרטיים ומסחריים - מורחב",
            "alert_type": None
        }
    }
    
    # סדר בדיקת המאגרים
    GOV_SEARCH_ORDER: list = [
        "main",
        "private_extended",
        "inactive",
        "off_road_1", "off_road_2", "off_road_3",
        "public",
        "motorcycle",
        "heavy", "heavy_2"
    ]
    
    # File Processing
    VALID_EXTENSIONS: tuple = (".jpg", ".jpeg", ".png")
    LPR_VALID_LENGTHS: tuple = (7, 8)
    
    # AI Analysis
    AI_CONFIDENCE_THRESHOLD: int = 75
    
    @classmethod
    def ensure_folders(cls) -> None:
        """יצירת תיקיות נדרשות אם לא קיימות."""
        cls.PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
        cls.ERRORS_FOLDER.mkdir(parents=True, exist_ok=True)


# אובייקט קונפיגורציה גלובלי
config = Config()

