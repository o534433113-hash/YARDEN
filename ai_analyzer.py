"""
מודול לניתוח תמונות באמצעות OpenAI Vision.
שולח תמונות ל-GPT-4o לאימות רכב מול נתונים ממשלתיים.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from backend.config import config
from backend.models import GovData, AIAnalysis

logger = logging.getLogger("MoonGuard.AI")

# יצירת לקוח OpenAI
client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


def encode_image_to_base64(image_path: Path) -> str:
    """
    קידוד תמונה ל-Base64.
    
    Args:
        image_path: נתיב לקובץ התמונה
        
    Returns:
        מחרוזת Base64 של התמונה
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def get_image_media_type(image_path: Path) -> str:
    """
    קבלת סוג המדיה של התמונה.
    
    Args:
        image_path: נתיב לקובץ התמונה
        
    Returns:
        סוג המדיה (MIME type)
    """
    suffix = image_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png"
    }
    return media_types.get(suffix, "image/jpeg")


async def analyze_vehicle_image(
    image_path: Path,
    gov_data: GovData,
    lpr: str
) -> AIAnalysis:
    """
    ניתוח תמונת רכב באמצעות OpenAI Vision.
    
    Args:
        image_path: נתיב לתמונה
        gov_data: נתוני הרכב מה-API הממשלתי
        lpr: מספר לוחית הרישוי
        
    Returns:
        אובייקט AIAnalysis עם תוצאות הניתוח
    """
    if not image_path.exists():
        logger.error(f"קובץ תמונה לא נמצא: {image_path}")
        return AIAnalysis(
            scene_description="שגיאה: קובץ לא נמצא",
            target_found=False,
            confidence=0
        )
    
    # בניית תיאור הרכב הצפוי
    expected_desc = f"צבע: {gov_data.color}, יצרן: {gov_data.manufacturer}, דגם: {gov_data.model}"
    
    system_prompt = """אתה מערכת אימות חזותי לרכבים.
תפקידך לנתח תמונות ולאמת האם הרכב בתמונה תואם לנתונים הרשומים.

הנחיות חשובות:
1. התמקד בזיהוי היצרן - זהו הקריטריון המרכזי לאימות
2. אם היצרן בתמונה תואם ליצרן הרשום - זה אימות מוצלח (target_found=true)
3. התעלם מהבדלי צבע קלים או גוונים שונים
4. התעלם מהבדלים בדגם ספציפי כל עוד היצרן תואם
5. הייה סובלני - דווח על אי-התאמה רק אם יש הבדל ברור וחד משמעי ביצרן

דוגמאות לאימות מוצלח:
- רכב מרצדס בתמונה + יצרן רשום מרצדס = VERIFIED
- רכב טויוטה בתמונה + יצרן רשום טויוטה = VERIFIED (גם אם הדגם שונה)

דוגמאות לחשד (דרוש הבדל חד וברור):
- רכב הונדה בתמונה + יצרן רשום טויוטה = חשד

פורמט התשובה (JSON בלבד):
{
    "scene_description": "תיאור קצר של הסצנה והרכב",
    "detected_manufacturer": "היצרן שזוהה בתמונה",
    "target_found": true/false,
    "confidence": 0-100,
    "best_match_details": "תיאור הרכב שזוהה",
    "reasoning": "הסבר קצר"
}"""

    user_prompt = f"""מספר לוחית רישוי: {lpr}
נתונים רשומים: {expected_desc}

זהה את היצרן של הרכב בתמונה.
אם היצרן תואם ל-"{gov_data.manufacturer}" - זהו אימות מוצלח.
החזר JSON בלבד."""

    try:
        # קידוד התמונה
        image_base64 = encode_image_to_base64(image_path)
        media_type = get_image_media_type(image_path)
        
        logger.info(f"שולח תמונה לניתוח AI: {image_path.name}")
        
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_base64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.1
        )
        
        # פרסור התשובה
        content = response.choices[0].message.content
        
        # ניסיון לחלץ JSON מהתשובה
        try:
            # מחפש JSON בתוך הטקסט
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
            else:
                raise ValueError("לא נמצא JSON בתשובה")
            
            analysis = AIAnalysis(
                scene_description=result.get("scene_description", ""),
                detected_manufacturer=result.get("detected_manufacturer"),
                target_found=result.get("target_found", False),
                confidence=int(result.get("confidence", 0)),
                best_match_details=result.get("best_match_details"),
                reasoning=result.get("reasoning")
            )
            
            logger.info(
                f"תוצאת ניתוח: found={analysis.target_found}, "
                f"confidence={analysis.confidence}%"
            )
            
            return analysis
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"שגיאה בפרסור תשובת AI: {e}")
            return AIAnalysis(
                scene_description=content[:200],
                target_found=False,
                confidence=0,
                reasoning="שגיאה בפרסור התשובה"
            )
            
    except Exception as e:
        logger.error(f"שגיאה בניתוח AI: {e}")
        return AIAnalysis(
            scene_description=f"שגיאה: {str(e)}",
            target_found=False,
            confidence=0
        )


async def pre_screen_image(image_path: Path) -> dict:
    """
    סינון מקדים של תמונה - בדיקה אם יש לדלג על הניתוח.
    
    בדיקות:
    - אדם בתמונה
    - מונית או רכב צהוב לחלוטין
    
    Args:
        image_path: נתיב לקובץ התמונה
        
    Returns:
        מילון עם: skip (bool), reason (str)
    """
    if not image_path.exists():
        return {"skip": False, "reason": ""}
    
    system_prompt = """אתה מערכת סינון מקדים לתמונות.
בדוק האם התמונה מכילה אחד מהמקרים הבאים שיש להתעלם מהם:

1. אדם (לא רכב) - תמונה שבה אדם הוא הנושא המרכזי
2. מונית - רכב עם שלט מונית על הגג או סימני מונית ברורים
3. רכב צהוב לחלוטין - רכב שכל גופו צהוב (לא רק לוחית)

החזר תשובה בפורמט JSON בלבד:
{
    "skip": true/false,
    "reason": "person" / "taxi" / "yellow_vehicle" / "none"
}"""

    try:
        image_base64 = encode_image_to_base64(image_path)
        media_type = get_image_media_type(image_path)
        
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "בדוק את התמונה וקבע אם יש לדלג עליה."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_base64}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ],
            max_tokens=100,
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(content[json_start:json_end])
                skip = result.get("skip", False)
                reason = result.get("reason", "none")
                if skip:
                    logger.info(f"סינון מקדים: דילוג על תמונה - סיבה: {reason}")
                return {"skip": skip, "reason": reason}
        except:
            pass
            
        return {"skip": False, "reason": "none"}
        
    except Exception as e:
        logger.error(f"שגיאה בסינון מקדים: {e}")
        return {"skip": False, "reason": "error"}


async def detect_yellow_plate(image_path: Path) -> bool:
    """
    בדיקה האם קיימת לוחית רישוי צהובה בתמונה.
    
    לוחיות רישוי ישראליות הן צהובות עם מספרים שחורים.
    פונקציה זו בודקת האם יש לפחות לוחית אחת כזו בתמונה.
    
    Args:
        image_path: נתיב לקובץ התמונה
        
    Returns:
        True אם נמצאה לוחית צהובה, False אחרת
    """
    if not image_path.exists():
        logger.error(f"קובץ תמונה לא נמצא: {image_path}")
        return False
    
    system_prompt = """אתה מערכת זיהוי לוחיות רישוי.
תפקידך לזהות האם יש לוחית רישוי ישראלית צהובה בתמונה.

לוחיות רישוי ישראליות:
- צבע רקע צהוב בהיר
- מספרים ואותיות בשחור
- לרוב פס כחול בצד עם אותיות IL

החזר תשובה בפורמט JSON בלבד:
{
    "yellow_plate_found": true/false,
    "confidence": 0-100,
    "description": "תיאור קצר של מה שנמצא"
}"""

    user_prompt = """בדוק את התמונה וקבע האם יש בה לוחית רישוי ישראלית צהובה.
אם אתה רואה לוחית מלבנית צהובה עם מספרים - זו לוחית רישוי.
החזר תשובה בפורמט JSON בלבד."""

    try:
        image_base64 = encode_image_to_base64(image_path)
        media_type = get_image_media_type(image_path)
        
        logger.info(f"בודק לוחית צהובה בתמונה: {image_path.name}")
        
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_base64}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ],
            max_tokens=200,
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
            else:
                raise ValueError("לא נמצא JSON בתשובה")
            
            found = result.get("yellow_plate_found", False)
            confidence = result.get("confidence", 0)
            
            logger.info(f"תוצאת זיהוי לוחית צהובה: found={found}, confidence={confidence}%")
            
            return found and confidence >= 50
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"שגיאה בפרסור תשובת זיהוי לוחית: {e}")
            return False
            
    except Exception as e:
        logger.error(f"שגיאה בזיהוי לוחית צהובה: {e}")
        return False

