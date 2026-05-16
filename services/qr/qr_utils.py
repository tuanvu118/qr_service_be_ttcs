import base64
import math
from datetime import datetime, timezone

from beanie import PydanticObjectId

from exceptions import ErrorCode, app_exception
from schemas.attendance import QRSessionOpenRequest


class QRUtils:
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def iso(value: datetime) -> str:
        return QRUtils.ensure_utc(value).isoformat()

    @staticmethod
    def parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return QRUtils.ensure_utc(parsed)

    @staticmethod
    def encode_qr_value(payload_json: str) -> str:
        encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
        return encoded.rstrip("=")

    @staticmethod
    def decode_qr_value(qr_value: str) -> str:
        padding = "=" * (-len(qr_value) % 4)
        return base64.urlsafe_b64decode(f"{qr_value}{padding}").decode("utf-8")

    @staticmethod
    def session_key(session_id: str) -> str:
        return f"qr_session:{session_id}:meta"

    @staticmethod
    def participant_key(session_id: str) -> str:
        return f"qr_session:{session_id}:participants"

    @staticmethod
    def payload_key(session_id: str, sequence: int) -> str:
        return f"qr_session:{session_id}:payload:{sequence}"

    @staticmethod
    def manual_code_key(code: str) -> str:
        return f"attendance_code:{code}"

    @staticmethod
    def event_session_key(event_type: str, event_id: PydanticObjectId) -> str:
        return f"qr_event_active_session:{event_type}:{event_id}"

    @staticmethod
    def duplicate_key(event_type: str, user_id: PydanticObjectId, event_id: PydanticObjectId) -> str:
        return f"scan:{event_type}:{user_id}:{event_id}"

    @staticmethod
    def validate_location_configuration(request: QRSessionOpenRequest) -> None:
        location_fields = [request.latitude, request.longitude, request.radius_meters]
        any_location = any(value is not None for value in location_fields)
        all_location = all(value is not None for value in location_fields)
        if any_location and not all_location:
            app_exception(
                ErrorCode.QR_PAYLOAD_INVALID,
                extra_detail="latitude, longitude, radius_meters phai duoc cung cap day du",
            )

    @staticmethod
    def calculate_distance_meters(
        origin_lat: float,
        origin_lng: float,
        target_lat: float,
        target_lng: float,
    ) -> float:
        earth_radius_m = 6371000
        delta_lat = math.radians(target_lat - origin_lat)
        delta_lng = math.radians(target_lng - origin_lng)
        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(math.radians(origin_lat))
            * math.cos(math.radians(target_lat))
            * math.sin(delta_lng / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return earth_radius_m * c
