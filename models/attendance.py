from datetime import datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class Attendance(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    event_id: PydanticObjectId
    event_type: str = "public"
    user_id: PydanticObjectId
    session_id: str
    sequence: int
    request_id: str
    valid_from: datetime
    valid_until: datetime
    scanned_at: datetime
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checkin_latitude: Optional[float] = None
    checkin_longitude: Optional[float] = None
    distance_meters: Optional[float] = None
    source: str = "qr"

    class Settings:
        name = "attendances"
        indexes = [
            IndexModel(
                [("event_type", ASCENDING), ("event_id", ASCENDING), ("user_id", ASCENDING)],
                unique=True,
            ),
            IndexModel([("request_id", ASCENDING)], unique=True),
            IndexModel([("session_id", ASCENDING), ("sequence", ASCENDING)]),
        ]
