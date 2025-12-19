"""
שרת MoonGuard - מערכת אימות רכבים.
FastAPI עם WebSocket לעדכונים בזמן אמת.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# הוספת הנתיב הראשי ל-path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import config
from backend.database import db
from backend.models import (
    VehicleEvent, EventStatus, WatcherStatus,
    WatchStartRequest, WatchStartResponse,
    EventsResponse, StatsResponse, WebSocketMessage,
    GovData, AIAnalysis
)
from backend.file_watcher import watcher, parse_filename
from backend.gov_api import get_vehicle_data, validate_lpr
from backend.ai_analyzer import analyze_vehicle_image, detect_yellow_plate, pre_screen_image

# הגדרת לוגים
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MoonGuard")


# ניהול חיבורי WebSocket
class ConnectionManager:
    """מנהל חיבורי WebSocket פעילים."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket) -> None:
        """חיבור לקוח חדש."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"לקוח WebSocket התחבר. סה\"כ: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket) -> None:
        """ניתוק לקוח."""
        self.active_connections.discard(websocket)
        logger.info(f"לקוח WebSocket התנתק. סה\"כ: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict) -> None:
        """שליחת הודעה לכל הלקוחות המחוברים."""
        if not self.active_connections:
            return
        
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # הסרת חיבורים מנותקים
        for conn in disconnected:
            self.active_connections.discard(conn)


manager = ConnectionManager()


async def process_new_file(file_path: Path) -> None:
    """
    עיבוד קובץ תמונה חדש.
    
    Args:
        file_path: נתיב לקובץ התמונה
    """
    filename = file_path.name
    logger.info(f"מעבד קובץ: {filename}")
    
    # פרסור שם הקובץ
    meta = parse_filename(filename)
    if not meta.get("valid"):
        logger.warning(f"שם קובץ לא תקין: {filename}")
        return
    
    lpr = meta["lpr"]
    
    # התעלמות מלוחיות שמכילות אותיות (לא מספרים בלבד)
    if not lpr.isdigit():
        logger.info(f"התעלמות מלוחית עם אותיות: {lpr}")
        try:
            file_path.unlink()
        except Exception:
            pass
        return
    
    # בדיקת תקינות לוחית
    if not validate_lpr(lpr):
        logger.warning(f"לוחית לא תקינה: {lpr}")
        try:
            file_path.unlink()
            logger.info("קובץ נמחק")
        except Exception as e:
            logger.error(f"שגיאה במחיקת קובץ: {e}")
        return
    
    location_id = meta["location_id"]
    
    # התעלמות מלוחיות בנות 7 ספרות המסתיימות ב-90 עד 99
    if len(lpr) == 7:
        last_two_digits = lpr[-2:]
        if 90 <= int(last_two_digits) <= 99:
            logger.info(f"התעלמות מלוחית 7 ספרות עם סיומת 90-99: {lpr}")
            try:
                file_path.unlink()
            except Exception:
                pass
            return
    
    logger.info(f"מעבד לוחית: {lpr} | מיקום: {location_id}")
    
    # סינון מקדים - בדיקה אם יש לדלג על התמונה
    pre_screen = await pre_screen_image(file_path)
    if pre_screen.get("skip"):
        reason = pre_screen.get("reason", "unknown")
        reason_map = {
            "person": "זוהה אדם בתמונה",
            "taxi": "זוהתה מונית",
            "yellow_vehicle": "זוהה רכב צהוב לחלוטין"
        }
        logger.info(f"דילוג על תמונה: {reason_map.get(reason, reason)}")
        try:
            file_path.unlink()
        except Exception:
            pass
        return
    
    # יצירת אירוע ראשוני
    event = VehicleEvent(
        timestamp=datetime.now(),
        display_time=meta["display_time"],
        display_date=meta["display_date"],
        location_id=meta["location_id"],
        lpr=lpr,
        image_filename=filename,
        image_path=str(file_path),
        status=EventStatus.PROCESSING
    )
    
    # שליפת נתונים ממשלתיים (בודק בכל המאגרים)
    gov_data = await get_vehicle_data(lpr)
    event.gov_data = gov_data
    
    # בדיקה אם יש התראה מיוחדת מהמאגרים
    if gov_data.alert_type:
        # רכב נמצא במאגר בעייתי או לא נמצא בכלל
        if gov_data.alert_type == "FAKE_PLATE":
            # לפני התראת לוחית מזויפת - בדיקה האם יש לוחית צהובה בתמונה
            has_yellow_plate = await detect_yellow_plate(file_path)
            
            if not has_yellow_plate:
                # אין לוחית צהובה בתמונה - התעלמות
                logger.info(f"לא זוהתה לוחית צהובה בתמונה, מתעלם: {filename}")
                try:
                    file_path.unlink()
                    logger.info("קובץ נמחק - אין לוחית צהובה")
                except Exception as e:
                    logger.error(f"שגיאה במחיקת קובץ: {e}")
                return
            
            # יש לוחית צהובה - התראת לוחית מזויפת
            event.status = EventStatus.FAKE_PLATE
            event.ai_analysis = AIAnalysis(
                scene_description="🔴 לוחית מזויפת! הרכב לא קיים באף מאגר ממשלתי",
                target_found=False,
                confidence=0
            )
            logger.error(f"🔴 לוחית מזויפת: {lpr}")
            
        elif gov_data.alert_type == "NO_LICENSE":
            event.status = EventStatus.NO_LICENSE
            event.ai_analysis = AIAnalysis(
                scene_description=f"⚠️ {gov_data.alert_message}",
                target_found=True,
                confidence=100
            )
            logger.warning(f"⚠️ רכב ללא טסט: {lpr}")
            
        elif gov_data.alert_type == "OFF_ROAD":
            event.status = EventStatus.OFF_ROAD
            event.ai_analysis = AIAnalysis(
                scene_description=f"⚠️ {gov_data.alert_message}",
                target_found=True,
                confidence=100
            )
            logger.warning(f"⚠️ רכב מורד מהכביש: {lpr}")
            
    elif not gov_data.found:
        # שגיאה בשליפה (לא אמור לקרות עם הלוגיקה החדשה)
        logger.info(f"רכב לא נמצא במאגר: {lpr}")
        event.status = EventStatus.UNKNOWN
        event.ai_analysis = AIAnalysis(
            scene_description="שגיאה בשליפת נתונים",
            target_found=False,
            confidence=0
        )
    else:
        # רכב נמצא במאגר רגיל - ממשיכים לאימות AI
        logger.info(
            f"נמצא: {gov_data.manufacturer} {gov_data.model} ({gov_data.color}) - מאגר: {gov_data.source_db}"
        )
        
        # ניתוח AI
        ai_result = await analyze_vehicle_image(file_path, gov_data, lpr)
        event.ai_analysis = ai_result
        
        # קבלת החלטה
        if ai_result.target_found and ai_result.confidence >= config.AI_CONFIDENCE_THRESHOLD:
            event.status = EventStatus.VERIFIED
            logger.info("✅ אומת בהצלחה")
        else:
            event.status = EventStatus.ALERT
            logger.warning("🔴 התראה: אי התאמה")
    
    # שמירה לבסיס הנתונים
    event_id = await db.save_event(event)
    event.id = event_id
    
    # עדכון מונה הקבצים
    watcher.increment_processed()
    
    # שליחת עדכון ב-WebSocket
    await manager.broadcast({
        "type": "new_event",
        "data": event.model_dump(mode="json")
    })
    
    # שליחת עדכון סטטיסטיקות
    stats = await db.get_stats()
    await manager.broadcast({
        "type": "stats_update",
        "data": stats.model_dump()
    })
    
    # העברה לתיקיית מעובדים
    try:
        dest = config.PROCESSED_FOLDER / filename
        file_path.rename(dest)
        logger.info(f"קובץ הועבר ל: {dest}")
    except Exception as e:
        logger.error(f"שגיאה בהעברת קובץ: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """מנהל מחזור חיי האפליקציה."""
    # התחלה
    logger.info("=" * 50)
    logger.info("MoonGuard Server Starting...")
    logger.info("=" * 50)
    
    # וידוא תיקיות
    config.ensure_folders()
    
    # התחברות לבסיס נתונים
    await db.connect()
    
    # הגדרת callback ו-loop ל-watcher
    watcher.set_callback(process_new_file)
    watcher.set_loop(asyncio.get_event_loop())
    
    logger.info(f"שרת מוכן על פורט {config.SERVER_PORT}")
    
    yield
    
    # סגירה
    logger.info("Server shutting down...")
    watcher.stop()
    await db.disconnect()


# יצירת אפליקציית FastAPI
app = FastAPI(
    title="MoonGuard",
    description="מערכת חמ\"ל לאימות רכבים",
    version="1.0.0",
    lifespan=lifespan
)

# הגדרת CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# --- API Endpoints ---

@app.get("/")
async def root():
    """דף הבית - מחזיר את ה-frontend."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return {"message": "MoonGuard API", "status": "running"}


@app.get("/api/images/{filename}")
async def get_image(filename: str):
    """הגשת תמונה מתיקיית processed."""
    image_path = config.PROCESSED_FOLDER / filename
    if image_path.exists():
        return FileResponse(image_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Image not found")


@app.post("/api/watch/start", response_model=WatchStartResponse)
async def start_watching(request: WatchStartRequest):
    """התחלת ניטור תיקייה."""
    success, message = watcher.start(request.folder_path)
    
    status = WatcherStatus(
        is_active=watcher.is_active,
        watched_folder=watcher.watched_folder,
        started_at=watcher.start_time,
        files_processed=watcher.files_processed
    )
    
    # שליחת עדכון סטטוס ללקוחות
    await manager.broadcast({
        "type": "status_update",
        "data": status.model_dump(mode="json")
    })
    
    return WatchStartResponse(
        success=success,
        message=message,
        status=status
    )


@app.post("/api/watch/stop")
async def stop_watching():
    """עצירת הניטור."""
    success, message = watcher.stop()
    
    status = WatcherStatus(
        is_active=False,
        watched_folder=None,
        started_at=None,
        files_processed=watcher.files_processed
    )
    
    # שליחת עדכון סטטוס ללקוחות
    await manager.broadcast({
        "type": "status_update",
        "data": status.model_dump(mode="json")
    })
    
    return {"success": success, "message": message}


@app.get("/api/watch/status", response_model=WatcherStatus)
async def get_watch_status():
    """קבלת סטטוס הניטור."""
    return WatcherStatus(
        is_active=watcher.is_active,
        watched_folder=watcher.watched_folder,
        started_at=watcher.start_time,
        files_processed=watcher.files_processed
    )


@app.get("/api/events", response_model=EventsResponse)
async def get_events(limit: int = 50, offset: int = 0, status: str = None):
    """שליפת אירועים."""
    event_status = EventStatus(status) if status else None
    events = await db.get_events(limit=limit, offset=offset, status=event_status)
    
    return EventsResponse(
        total=len(events),
        events=events
    )


@app.get("/api/events/{event_id}", response_model=VehicleEvent)
async def get_event(event_id: int):
    """שליפת אירוע בודד."""
    event = await db.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="אירוע לא נמצא")
    return event


@app.delete("/api/events/{event_id}")
async def delete_event(event_id: int):
    """מחיקת אירוע לצמיתות."""
    deleted = await db.delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="אירוע לא נמצא")
    
    # שליחת עדכון סטטיסטיקות
    stats = await db.get_stats()
    await manager.broadcast({
        "type": "stats_update",
        "data": stats.model_dump()
    })
    
    return {"success": True, "message": "אירוע נמחק בהצלחה"}


@app.delete("/api/events/clear/non-alerts")
async def clear_non_alert_events():
    """מחיקת כל האירועים שאינם התראות."""
    deleted_count = await db.delete_non_alert_events()
    
    # שליחת עדכון סטטיסטיקות
    stats = await db.get_stats()
    await manager.broadcast({
        "type": "stats_update",
        "data": stats.model_dump()
    })
    
    # שליחת אירועים נותרים (רק התראות)
    remaining_events = await db.get_events(limit=100)
    await manager.broadcast({
        "type": "events_cleared",
        "data": {"remaining": [e.model_dump() for e in remaining_events]}
    })
    
    return {"success": True, "deleted_count": deleted_count}


@app.get("/api/alerts", response_model=EventsResponse)
async def get_alerts(limit: int = 20):
    """שליפת התראות אחרונות."""
    alerts = await db.get_alerts(limit=limit)
    return EventsResponse(
        total=len(alerts),
        events=alerts
    )


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """שליפת סטטיסטיקות."""
    return await db.get_stats()


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """נקודת חיבור WebSocket."""
    await manager.connect(websocket)
    
    try:
        # שליחת סטטוס ראשוני
        status = WatcherStatus(
            is_active=watcher.is_active,
            watched_folder=watcher.watched_folder,
            started_at=watcher.start_time,
            files_processed=watcher.files_processed
        )
        await websocket.send_json({
            "type": "status_update",
            "data": status.model_dump(mode="json")
        })
        
        # שליחת סטטיסטיקות ראשוניות
        stats = await db.get_stats()
        await websocket.send_json({
            "type": "stats_update",
            "data": stats.model_dump()
        })
        
        # שליחת אירועים אחרונים
        events = await db.get_events(limit=20)
        for event in reversed(events):
            await websocket.send_json({
                "type": "new_event",
                "data": event.model_dump(mode="json")
            })
        
        # המתנה להודעות (שמירה על החיבור פתוח)
        while True:
            try:
                data = await websocket.receive_text()
                # ניתן להוסיף טיפול בהודעות נכנסות כאן
            except WebSocketDisconnect:
                break
                
    except Exception as e:
        logger.error(f"שגיאת WebSocket: {e}")
    finally:
        manager.disconnect(websocket)


# הגשת קבצים סטטיים
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=True
    )

