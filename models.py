"""
מודלים של Pydantic עבור מערכת MoonGuard.
מגדיר את מבני הנתונים לאירועים, התראות ותגובות API.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    """סטטוס אירוע אימות רכב."""
    VERIFIED = "VERIFIED"
    ALERT = "ALERT"
    UNKNOWN = "UNKNOWN"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    # סטטוסי התראות מיוחדות
    NO_LICENSE = "NO_LICENSE"      # רכב ללא טסט/רשיון
    OFF_ROAD = "OFF_ROAD"          # רכב מורד מהכביש
    FAKE_PLATE = "FAKE_PLATE"      # לוחית מזויפת


class GovData(BaseModel):
    """נתוני רכב מ-API ממשלתי."""
    found: bool = False
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    year: Optional[str] = None
    error: Optional[str] = None
    # מידע נוסף על המאגר
    source_db: Optional[str] = None          # מאיזה מאגר נמצא
    alert_type: Optional[str] = None         # סוג ההתראה (אם יש)
    alert_message: Optional[str] = None      # הודעת ההתראה


class AIAnalysis(BaseModel):
    """תוצאות ניתוח AI."""
    scene_description: str = ""
    detected_manufacturer: Optional[str] = None
    target_found: bool = False
    confidence: int = 0
    best_match_details: Optional[str] = None
    reasoning: Optional[str] = None


class VehicleEvent(BaseModel):
    """אירוע זיהוי רכב מלא."""
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    display_time: str = ""
    display_date: str = ""
    location_id: str = ""
    lpr: str = ""
    gov_data: GovData = Field(default_factory=GovData)
    ai_analysis: AIAnalysis = Field(default_factory=AIAnalysis)
    status: EventStatus = EventStatus.PROCESSING
    image_filename: str = ""
    image_path: Optional[str] = None
    
    class Config:
        from_attributes = True


class WatcherStatus(BaseModel):
    """סטטוס ה-File Watcher."""
    is_active: bool = False
    watched_folder: Optional[str] = None
    started_at: Optional[datetime] = None
    files_processed: int = 0


class WatchStartRequest(BaseModel):
    """בקשה להפעלת ניטור תיקייה."""
    folder_path: str


class WatchStartResponse(BaseModel):
    """תגובה להפעלת ניטור."""
    success: bool
    message: str
    status: WatcherStatus


class EventsResponse(BaseModel):
    """תגובה לשליפת אירועים."""
    total: int
    events: list[VehicleEvent]


class StatsResponse(BaseModel):
    """סטטיסטיקות מערכת."""
    total_events: int = 0
    verified_count: int = 0
    alert_count: int = 0
    unknown_count: int = 0


class WebSocketMessage(BaseModel):
    """הודעה ב-WebSocket."""
    type: str  # "new_event", "status_update", "stats_update"
    data: dict

