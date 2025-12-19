"""
מודול בסיס נתונים SQLite עבור MoonGuard.
מנהל שמירה ושליפה של אירועי אימות רכבים.
"""

import aiosqlite
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import config
from backend.models import VehicleEvent, GovData, AIAnalysis, EventStatus, StatsResponse

logger = logging.getLogger("MoonGuard.Database")


class Database:
    """מחלקה לניהול בסיס הנתונים."""
    
    def __init__(self, db_path: Path = config.DATABASE_PATH):
        """
        אתחול מחלקת בסיס הנתונים.
        
        Args:
            db_path: נתיב לקובץ בסיס הנתונים
        """
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self) -> None:
        """התחברות לבסיס הנתונים ויצירת טבלאות."""
        self._connection = await aiosqlite.connect(str(self.db_path))
        self._connection.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"מחובר לבסיס נתונים: {self.db_path}")
    
    async def disconnect(self) -> None:
        """ניתוק מבסיס הנתונים."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("מנותק מבסיס הנתונים")
    
    async def _create_tables(self) -> None:
        """יצירת טבלאות בסיס הנתונים."""
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                display_time TEXT,
                display_date TEXT,
                location_id TEXT,
                lpr TEXT,
                gov_data TEXT,
                ai_analysis TEXT,
                status TEXT,
                image_filename TEXT,
                image_path TEXT
            )
        """)
        
        # אינדקסים לשיפור ביצועים
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp 
            ON events(timestamp DESC)
        """)
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_status 
            ON events(status)
        """)
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_lpr 
            ON events(lpr)
        """)
        
        await self._connection.commit()
    
    async def save_event(self, event: VehicleEvent) -> int:
        """
        שמירת אירוע חדש לבסיס הנתונים.
        
        Args:
            event: אובייקט האירוע לשמירה
            
        Returns:
            מזהה האירוע שנשמר
        """
        cursor = await self._connection.execute("""
            INSERT INTO events (
                timestamp, display_time, display_date, location_id,
                lpr, gov_data, ai_analysis, status, image_filename, image_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.timestamp.isoformat(),
            event.display_time,
            event.display_date,
            event.location_id,
            event.lpr,
            event.gov_data.model_dump_json(),
            event.ai_analysis.model_dump_json(),
            event.status.value,
            event.image_filename,
            event.image_path
        ))
        await self._connection.commit()
        
        event_id = cursor.lastrowid
        logger.info(f"אירוע נשמר: ID={event_id}, LPR={event.lpr}")
        return event_id
    
    async def get_events(
        self, 
        limit: int = 50, 
        offset: int = 0,
        status: Optional[EventStatus] = None
    ) -> list[VehicleEvent]:
        """
        שליפת אירועים מבסיס הנתונים.
        
        Args:
            limit: מספר אירועים מקסימלי
            offset: נקודת התחלה
            status: סינון לפי סטטוס
            
        Returns:
            רשימת אירועים
        """
        query = "SELECT * FROM events"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = await self._connection.execute(query, params)
        rows = await cursor.fetchall()
        
        events = []
        for row in rows:
            event = VehicleEvent(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                display_time=row["display_time"],
                display_date=row["display_date"],
                location_id=row["location_id"],
                lpr=row["lpr"],
                gov_data=GovData.model_validate_json(row["gov_data"]),
                ai_analysis=AIAnalysis.model_validate_json(row["ai_analysis"]),
                status=EventStatus(row["status"]),
                image_filename=row["image_filename"],
                image_path=row["image_path"]
            )
            events.append(event)
        
        return events
    
    async def get_event_by_id(self, event_id: int) -> Optional[VehicleEvent]:
        """
        שליפת אירוע לפי מזהה.
        
        Args:
            event_id: מזהה האירוע
            
        Returns:
            אובייקט האירוע או None
        """
        cursor = await self._connection.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return VehicleEvent(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            display_time=row["display_time"],
            display_date=row["display_date"],
            location_id=row["location_id"],
            lpr=row["lpr"],
            gov_data=GovData.model_validate_json(row["gov_data"]),
            ai_analysis=AIAnalysis.model_validate_json(row["ai_analysis"]),
            status=EventStatus(row["status"]),
            image_filename=row["image_filename"],
            image_path=row["image_path"]
        )
    
    async def get_stats(self) -> StatsResponse:
        """
        שליפת סטטיסטיקות מערכת.
        
        Returns:
            אובייקט סטטיסטיקות
        """
        cursor = await self._connection.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'VERIFIED' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN status = 'ALERT' THEN 1 ELSE 0 END) as alerts,
                SUM(CASE WHEN status = 'UNKNOWN' THEN 1 ELSE 0 END) as unknown
            FROM events
        """)
        row = await cursor.fetchone()
        
        return StatsResponse(
            total_events=row["total"] or 0,
            verified_count=row["verified"] or 0,
            alert_count=row["alerts"] or 0,
            unknown_count=row["unknown"] or 0
        )
    
    async def get_alerts(self, limit: int = 20) -> list[VehicleEvent]:
        """
        שליפת התראות אחרונות.
        
        Args:
            limit: מספר התראות מקסימלי
            
        Returns:
            רשימת התראות
        """
        return await self.get_events(limit=limit, status=EventStatus.ALERT)
    
    async def delete_event(self, event_id: int) -> bool:
        """
        מחיקת אירוע מבסיס הנתונים.
        
        Args:
            event_id: מזהה האירוע למחיקה
            
        Returns:
            True אם האירוע נמחק, False אם לא נמצא
        """
        cursor = await self._connection.execute(
            "DELETE FROM events WHERE id = ?",
            (event_id,)
        )
        await self._connection.commit()
        
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"אירוע נמחק: ID={event_id}")
        else:
            logger.warning(f"אירוע לא נמצא למחיקה: ID={event_id}")
        
        return deleted
    
    async def delete_non_alert_events(self) -> int:
        """
        מחיקת כל האירועים שאינם התראות מבסיס הנתונים.
        
        Returns:
            מספר האירועים שנמחקו
        """
        alert_statuses = ['ALERT', 'FAKE_PLATE', 'NO_LICENSE', 'OFF_ROAD']
        placeholders = ','.join(['?' for _ in alert_statuses])
        
        cursor = await self._connection.execute(
            f"DELETE FROM events WHERE status NOT IN ({placeholders})",
            alert_statuses
        )
        await self._connection.commit()
        
        deleted_count = cursor.rowcount
        logger.info(f"נמחקו {deleted_count} אירועים שאינם התראות")
        return deleted_count


# אובייקט בסיס נתונים גלובלי
db = Database()

