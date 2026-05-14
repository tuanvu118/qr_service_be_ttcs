from datetime import datetime, timezone
from typing import Any, Optional

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if not isinstance(value, datetime):
        raise ValueError("Invalid datetime value")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class QRSessionOpenRequest(BaseModel):
    session_start: Optional[datetime] = None
    session_end: Optional[datetime] = None
    window_seconds: int = Field(default=30, ge=5, le=300)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_meters: Optional[float] = Field(default=None, gt=0, le=1000)

    @field_validator("session_start", "session_end", mode="before")
    @classmethod
    def normalize_optional_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_utc(value)


class QRPayloadData(BaseModel):
    sessionId: str
    eventId: str
    sequence: int
    validFrom: datetime
    validUntil: datetime
    secret: str

    @field_validator("validFrom", "validUntil", mode="before")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class QRWindowResponse(BaseModel):
    sequence: int
    valid_from: datetime
    valid_until: datetime
    qr_value: str
    manual_code: str

    @field_validator("valid_from", "valid_until", mode="before")
    @classmethod
    def normalize_window_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class QRSessionOpenResponse(BaseModel):
    session_id: str
    event_id: PydanticObjectId
    event_type: str
    session_start: datetime
    session_end: datetime
    window_seconds: int
    participant_count: int
    location_required: bool
    windows: list[QRWindowResponse]

    @field_validator("session_start", "session_end", mode="before")
    @classmethod
    def normalize_session_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class QRSessionRead(BaseModel):
    session_id: str
    event_id: PydanticObjectId
    event_type: str
    session_start: datetime
    session_end: datetime
    window_seconds: int
    participant_count: int
    location_required: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_meters: Optional[float] = None
    status: str

    @field_validator("session_start", "session_end", mode="before")
    @classmethod
    def normalize_read_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class QRScanRequest(BaseModel):
    qr_value: str = Field(min_length=10)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class AttendanceCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class QRScanQueuedResponse(BaseModel):
    request_id: str
    session_id: str
    event_id: PydanticObjectId
    status: str = "queued"
    queued_at: datetime

    @field_validator("queued_at", mode="before")
    @classmethod
    def normalize_queue_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class AttendanceRead(BaseModel):
    id: PydanticObjectId
    event_id: PydanticObjectId
    event_type: str
    user_id: PydanticObjectId
    session_id: str
    sequence: int
    request_id: str
    valid_from: datetime
    valid_until: datetime
    scanned_at: datetime
    processed_at: datetime
    checkin_latitude: Optional[float] = None
    checkin_longitude: Optional[float] = None
    distance_meters: Optional[float] = None
    source: str

    @field_validator("valid_from", "valid_until", "scanned_at", "processed_at", mode="before")
    @classmethod
    def normalize_attendance_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    model_config = ConfigDict(from_attributes=True)


class CheckInMessage(BaseModel):
    request_id: str
    session_id: str
    event_id: str
    event_type: str = "public"
    user_id: str
    sequence: int
    valid_from: datetime
    valid_until: datetime
    scanned_at: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_meters: Optional[float] = None
    duplicate_key: str
    participant_key: str
    payload_key: str
    session_key: str
    source_ip: Optional[str] = None
    source: str = "qr"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_until", "scanned_at", mode="before")
    @classmethod
    def normalize_message_datetime(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class ManualAttendanceRequest(BaseModel):
    event_id: PydanticObjectId
    user_id: PydanticObjectId
    event_type: str = "public"
