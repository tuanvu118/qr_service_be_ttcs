from datetime import datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class Participant(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    user_id: str
    event_id: str
    event_type: str  # "public" or "unit"
    student_id: Optional[str] = None
    full_name: Optional[str] = None
    registered_at: datetime
    synced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "participants"
        indexes = [
            IndexModel(
                [("event_id", ASCENDING), ("user_id", ASCENDING)],
                unique=True,
                name="unique_participant_event",
            ),
        ]
