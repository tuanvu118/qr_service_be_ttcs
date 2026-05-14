from datetime import datetime, timezone
from typing import Any, Dict, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class AuditLog(Document):
    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    action: str
    actor_id: Optional[PydanticObjectId] = None
    event_id: Optional[PydanticObjectId] = None
    user_id: Optional[PydanticObjectId] = None
    target_type: str
    target_id: str
    status: str = "success"
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "audit_logs"
        indexes = [
            IndexModel([("request_id", ASCENDING)]),
            IndexModel([("event_id", ASCENDING), ("created_at", ASCENDING)]),
        ]
