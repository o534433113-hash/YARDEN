"""
מודול לניטור תיקיות דינמי.
מאזין לקבצים חדשים בתיקייה שנבחרה על ידי המשתמש.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from backend.config import config

logger = logging.getLogger("MoonGuard.Watcher")


class NewFileHandler(FileSystemEventHandler):
    """מטפל באירועי יצירת קבצים חדשים."""
    
    def __init__(
        self,
        start_time: datetime,
        callback: Callable[[Path], None],
        loop: asyncio.AbstractEventLoop
    ):
        """
        אתחול המטפל.
        
        Args:
            start_time: זמן התחלת הניטור (מתעלם מקבצים ישנים יותר)
            callback: פונקציה לקריאה כשמזוהה קובץ חדש
            loop: לולאת האירועים של asyncio
        """
        super().__init__()
        self.start_time = start_time
        self.callback = callback
        self.loop = loop
        self.processed_files: set[str] = set()
    
    def on_created(self, event: FileCreatedEvent) -> None:
        """
        מטפל באירוע יצירת קובץ.
        
        Args:
            event: אירוע יצירת הקובץ
        """
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # בדיקת סיומת קובץ
        if file_path.suffix.lower() not in config.VALID_EXTENSIONS:
            return
        
        # מניעת עיבוד כפול
        if str(file_path) in self.processed_files:
            return
        
        # בדיקת זמן יצירת הקובץ
        try:
            file_stat = file_path.stat()
            file_ctime = datetime.fromtimestamp(file_stat.st_ctime)
            
            if file_ctime < self.start_time:
                logger.debug(f"מתעלם מקובץ ישן: {file_path.name}")
                return
            
        except OSError as e:
            logger.error(f"שגיאה בקריאת מידע על קובץ: {e}")
            return
        
        self.processed_files.add(str(file_path))
        logger.info(f"קובץ חדש זוהה: {file_path.name}")
        
        # קריאה ל-callback באופן אסינכרוני
        asyncio.run_coroutine_threadsafe(
            self._delayed_callback(file_path),
            self.loop
        )
    
    async def _delayed_callback(self, file_path: Path) -> None:
        """
        קריאה מושהית ל-callback לוודא שהקובץ נכתב במלואו.
        
        Args:
            file_path: נתיב הקובץ
        """
        # המתנה קצרה לוודא שהקובץ נכתב במלואו
        await asyncio.sleep(0.5)
        await self.callback(file_path)


class DynamicWatcher:
    """מנהל ניטור תיקיות דינמי."""
    
    def __init__(self):
        """אתחול המנהל."""
        self._observer: Optional[Observer] = None
        self._watched_folder: Optional[Path] = None
        self._start_time: Optional[datetime] = None
        self._files_processed: int = 0
        self._callback: Optional[Callable] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    @property
    def is_active(self) -> bool:
        """בודק האם הניטור פעיל."""
        return self._observer is not None and self._observer.is_alive()
    
    @property
    def watched_folder(self) -> Optional[str]:
        """מחזיר את התיקייה המנוטרת."""
        return str(self._watched_folder) if self._watched_folder else None
    
    @property
    def start_time(self) -> Optional[datetime]:
        """מחזיר את זמן תחילת הניטור."""
        return self._start_time
    
    @property
    def files_processed(self) -> int:
        """מחזיר את מספר הקבצים שעובדו."""
        return self._files_processed
    
    def increment_processed(self) -> None:
        """מגדיל את מונה הקבצים המעובדים."""
        self._files_processed += 1
    
    def set_callback(self, callback: Callable[[Path], None]) -> None:
        """
        הגדרת פונקציית callback לעיבוד קבצים.
        
        Args:
            callback: פונקציה אסינכרונית שתיקרא עבור כל קובץ חדש
        """
        self._callback = callback
    
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        הגדרת לולאת אירועים.
        
        Args:
            loop: לולאת האירועים של asyncio
        """
        self._loop = loop
    
    def start(self, folder_path: str) -> tuple[bool, str]:
        """
        התחלת ניטור תיקייה.
        
        Args:
            folder_path: נתיב לתיקייה לניטור
            
        Returns:
            tuple של (הצלחה, הודעה)
        """
        # עצירת ניטור קודם אם קיים
        self.stop()
        
        # בדיקת תקינות הנתיב
        folder = Path(folder_path)
        if not folder.exists():
            return False, f"תיקייה לא קיימת: {folder_path}"
        
        if not folder.is_dir():
            return False, f"הנתיב אינו תיקייה: {folder_path}"
        
        if not self._callback:
            return False, "לא הוגדרה פונקציית callback"
        
        if not self._loop:
            return False, "לא הוגדרה לולאת אירועים"
        
        try:
            # שמירת זמן ההתחלה
            self._start_time = datetime.now()
            self._watched_folder = folder
            self._files_processed = 0
            
            # יצירת מטפל ו-observer
            handler = NewFileHandler(
                start_time=self._start_time,
                callback=self._callback,
                loop=self._loop
            )
            
            self._observer = Observer()
            self._observer.schedule(handler, str(folder), recursive=False)
            self._observer.start()
            
            logger.info(f"התחיל ניטור תיקייה: {folder}")
            return True, f"מנטר תיקייה: {folder}"
            
        except Exception as e:
            logger.error(f"שגיאה בהפעלת ניטור: {e}")
            return False, f"שגיאה: {str(e)}"
    
    def stop(self) -> tuple[bool, str]:
        """
        עצירת הניטור.
        
        Returns:
            tuple של (הצלחה, הודעה)
        """
        if not self._observer:
            return True, "הניטור כבר מופסק"
        
        try:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            
            old_folder = self._watched_folder
            self._watched_folder = None
            self._start_time = None
            
            logger.info(f"הניטור הופסק: {old_folder}")
            return True, "הניטור הופסק בהצלחה"
            
        except Exception as e:
            logger.error(f"שגיאה בעצירת ניטור: {e}")
            return False, f"שגיאה: {str(e)}"
    
    def get_status(self) -> dict:
        """
        קבלת סטטוס הניטור.
        
        Returns:
            מילון עם פרטי הסטטוס
        """
        return {
            "is_active": self.is_active,
            "watched_folder": self.watched_folder,
            "started_at": self._start_time.isoformat() if self._start_time else None,
            "files_processed": self._files_processed
        }


def parse_filename(filename: str) -> dict:
    """
    פרסור שם קובץ לחילוץ מידע.
    
    פורמט צפוי: 9908_01_20251211121434974_7072996_1_P1.jpg
    
    Args:
        filename: שם הקובץ
        
    Returns:
        מילון עם המידע המחולץ
    """
    try:
        base_name = Path(filename).stem
        parts = base_name.split("_")
        
        if len(parts) < 4:
            return {"valid": False, "error": "פורמט שם קובץ לא תקין"}
        
        # חילוץ מיקום
        location_id = f"{parts[0]}_{parts[1]}"
        
        # חילוץ זמן
        timestamp_full = parts[2]
        if len(timestamp_full) < 14:
            return {"valid": False, "error": "פורמט זמן לא תקין"}
        
        date_str = timestamp_full[:8]
        time_str = timestamp_full[8:14]
        
        # פורמט תצוגה
        formatted_time = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
        formatted_date = f"{date_str[6:]}/{date_str[4:6]}/{date_str[:4]}"
        
        # לוחית רישוי
        lpr = parts[3]
        
        return {
            "valid": True,
            "location_id": location_id,
            "raw_date": date_str,
            "display_time": formatted_time,
            "display_date": formatted_date,
            "lpr": lpr
        }
        
    except Exception as e:
        logger.error(f"שגיאה בפרסור שם קובץ: {e}")
        return {"valid": False, "error": str(e)}


# אובייקט watcher גלובלי
watcher = DynamicWatcher()

