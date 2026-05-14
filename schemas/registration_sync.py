from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class RegistrationSyncMessage(BaseModel):
    user_id: str
    event_id: str
    event_type: str  # "public" or "unit"
    student_id: Optional[str] = None
    full_name: Optional[str] = None
    registered_at: Optional[datetime] = None
    action: str = "REGISTER"  # "REGISTER" hoặc "CANCEL"
