"""
מודול לשליפת נתוני רכב מ-API ממשלתי.
משתמש ב-data.gov.il לקבלת פרטי רכב לפי לוחית רישוי.
בודק במספר מאגרים לפי סדר עדיפות.
"""

import logging
import httpx
from typing import Optional, Tuple

from backend.config import config
from backend.models import GovData

logger = logging.getLogger("MoonGuard.GovAPI")


async def search_single_database(
    client: httpx.AsyncClient,
    lpr: str,
    resource_id: str,
    db_name: str
) -> Tuple[bool, Optional[dict]]:
    """
    חיפוש במאגר בודד.
    
    Args:
        client: לקוח HTTP
        lpr: מספר לוחית
        resource_id: מזהה המאגר
        db_name: שם המאגר ללוגים
        
    Returns:
        tuple של (נמצא, רשומה)
    """
    params = {
        "resource_id": resource_id,
        "q": lpr,
        "limit": 1
    }
    
    try:
        response = await client.get(config.GOV_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("success") and data.get("result", {}).get("records"):
            record = data["result"]["records"][0]
            logger.info(f"נמצא במאגר '{db_name}': {lpr}")
            return True, record
        
        return False, None
        
    except Exception as e:
        logger.warning(f"שגיאה בחיפוש במאגר '{db_name}': {e}")
        return False, None


def extract_vehicle_data(record: dict) -> dict:
    """
    חילוץ נתוני רכב מרשומה.
    שמות השדות יכולים להשתנות בין מאגרים.
    
    Args:
        record: רשומה מה-API
        
    Returns:
        מילון עם נתוני הרכב
    """
    # ניסיון לחלץ נתונים - שמות שדות שונים במאגרים שונים
    manufacturer = (
        record.get("tozeret_nm") or
        record.get("tozeret_cd") or
        record.get("tozeret") or
        "לא ידוע"
    )
    
    model = (
        record.get("kinuy_mishari") or
        record.get("degem_nm") or
        record.get("degem_cd") or
        "לא ידוע"
    )
    
    color = (
        record.get("tzeva_rechev") or
        record.get("tzeva_cd") or
        "לא ידוע"
    )
    
    year = str(
        record.get("shnat_yitzur") or
        record.get("shnat_yitsur") or
        "לא ידוע"
    )
    
    return {
        "manufacturer": manufacturer,
        "model": model,
        "color": color,
        "year": year
    }


async def search_all_databases(lpr: str) -> GovData:
    """
    חיפוש בכל המאגרים הממשלתיים לפי סדר.
    
    סדר הבדיקה:
    1. מאגר ראשי (רכבים פעילים)
    2. מאגר לא פעילים (ללא טסט) -> התראה
    3. מאגרי מורדים מכביש -> התראה
    4. מאגרים נוספים (ציבורי, דו גלגלי, כבד)
    5. אם לא נמצא בכלל -> לוחית מזויפת
    
    Args:
        lpr: מספר לוחית הרישוי
        
    Returns:
        אובייקט GovData עם כל המידע
    """
    async with httpx.AsyncClient(timeout=config.GOV_API_TIMEOUT) as client:
        
        # עוברים על כל המאגרים לפי הסדר
        for db_key in config.GOV_SEARCH_ORDER:
            db_info = config.GOV_DATABASES.get(db_key)
            if not db_info:
                continue
            
            found, record = await search_single_database(
                client=client,
                lpr=lpr,
                resource_id=db_info["resource_id"],
                db_name=db_info["name"]
            )
            
            if found and record:
                # חילוץ נתוני הרכב
                vehicle_data = extract_vehicle_data(record)
                
                # בניית התגובה
                gov_data = GovData(
                    found=True,
                    manufacturer=vehicle_data["manufacturer"],
                    model=vehicle_data["model"],
                    color=vehicle_data["color"],
                    year=vehicle_data["year"],
                    source_db=db_info["name"],
                    alert_type=db_info.get("alert_type"),
                    alert_message=db_info.get("alert_message")
                )
                
                # לוג מפורט
                if db_info.get("alert_type"):
                    logger.warning(
                        f"⚠️ רכב {lpr} נמצא במאגר בעייתי: "
                        f"{db_info['name']} - {db_info.get('alert_message')}"
                    )
                else:
                    logger.info(
                        f"✓ רכב {lpr}: {gov_data.manufacturer} {gov_data.model} "
                        f"({gov_data.color}) - מאגר: {db_info['name']}"
                    )
                
                return gov_data
        
        # לא נמצא באף מאגר - לוחית מזויפת!
        logger.error(f"🔴 לוחית מזויפת! {lpr} לא נמצא באף מאגר ממשלתי")
        
        return GovData(
            found=False,
            alert_type="FAKE_PLATE",
            alert_message="לוחית מזויפת - לא נמצא באף מאגר ממשלתי"
        )


async def get_vehicle_data(lpr: str) -> GovData:
    """
    שליפת נתוני רכב מכל המאגרים הממשלתיים.
    
    Args:
        lpr: מספר לוחית הרישוי (7-8 ספרות)
        
    Returns:
        אובייקט GovData עם פרטי הרכב
    """
    try:
        return await search_all_databases(lpr)
        
    except httpx.TimeoutException:
        logger.error(f"Timeout בשליפת נתוני רכב: {lpr}")
        return GovData(found=False, error="Timeout")
        
    except httpx.HTTPStatusError as e:
        logger.error(f"שגיאת HTTP: {e.response.status_code}")
        return GovData(found=False, error=f"HTTP {e.response.status_code}")
        
    except Exception as e:
        logger.error(f"שגיאה בשליפת נתוני רכב: {e}")
        return GovData(found=False, error=str(e))


def validate_lpr(lpr: str) -> bool:
    """
    בדיקת תקינות מספר לוחית רישוי.
    
    Args:
        lpr: מספר הלוחית לבדיקה
        
    Returns:
        True אם תקין, False אחרת
    """
    if not lpr:
        return False
    
    if not lpr.isdigit():
        return False
    
    if len(lpr) not in config.LPR_VALID_LENGTHS:
        return False
    
    return True
