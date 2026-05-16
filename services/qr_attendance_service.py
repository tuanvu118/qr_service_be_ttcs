import base64
import json
import logging
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from beanie import PydanticObjectId
from pydantic import ValidationError

from configs.rabbitmq import publish_checkin_message
from configs.redis_config import get_redis
from configs.settings import (
    ATTENDANCE_MANUAL_CODE_LENGTH,
    QR_DEFAULT_WINDOW_SECONDS,
    QR_DUPLICATE_PENDING_TTL_SECONDS,
    QR_MAX_WINDOWS_PER_SESSION,
    QR_SESSION_TTL_BUFFER_SECONDS,
)
from exceptions import ErrorCode, app_exception
from models.audit_log import AuditLog
from repositories.audit_log_repo import AuditLogRepository
from repositories.participant_repo import ParticipantRepository
from schemas.attendance import (
    AttendanceCodeRequest,
    CheckInMessage,
    QRPayloadData,
    QRScanQueuedResponse,
    QRScanRequest,
    QRSessionOpenRequest,
    QRSessionOpenResponse,
    QRWindowResponse,
)

logger = logging.getLogger("qr_service.attendance")


class QRAttendanceService:
    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return QRAttendanceService._ensure_utc(value).isoformat()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return QRAttendanceService._ensure_utc(parsed)

    @staticmethod
    def _encode_qr_value(payload_json: str) -> str:
        encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
        return encoded.rstrip("=")

    @staticmethod
    def _decode_qr_value(qr_value: str) -> str:
        padding = "=" * (-len(qr_value) % 4)
        return base64.urlsafe_b64decode(f"{qr_value}{padding}").decode("utf-8")

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"qr_session:{session_id}:meta"

    @staticmethod
    def _participant_key(session_id: str) -> str:
        return f"qr_session:{session_id}:participants"

    @staticmethod
    def _payload_key(session_id: str, sequence: int) -> str:
        return f"qr_session:{session_id}:payload:{sequence}"

    @staticmethod
    def _manual_code_key(code: str) -> str:
        return f"attendance_code:{code}"

    @staticmethod
    def _event_session_key(event_type: str, event_id: PydanticObjectId) -> str:
        return f"qr_event_active_session:{event_type}:{event_id}"

    @staticmethod
    def _duplicate_key(event_type: str, user_id: PydanticObjectId, event_id: PydanticObjectId) -> str:
        return f"scan:{event_type}:{user_id}:{event_id}"

    @staticmethod
    def _validate_location_configuration(request: QRSessionOpenRequest) -> None:
        location_fields = [request.latitude, request.longitude, request.radius_meters]
        any_location = any(value is not None for value in location_fields)
        all_location = all(value is not None for value in location_fields)
        if any_location and not all_location:
            app_exception(
                ErrorCode.QR_PAYLOAD_INVALID,
                extra_detail="latitude, longitude, radius_meters phai duoc cung cap day du",
            )

    @staticmethod
    def _build_windows(
        session_id: str,
        event_id: PydanticObjectId,
        session_start: datetime,
        session_end: datetime,
        window_seconds: int,
    ) -> list[QRWindowResponse]:
        windows: list[QRWindowResponse] = []
        cursor = session_start
        sequence = 1

        while cursor < session_end:
            if len(windows) >= QR_MAX_WINDOWS_PER_SESSION:
                app_exception(ErrorCode.QR_SESSION_TOO_LARGE)

            valid_until = min(cursor + timedelta(seconds=window_seconds), session_end)
            payload = QRPayloadData(
                sessionId=session_id,
                eventId=str(event_id),
                sequence=sequence,
                validFrom=cursor,
                validUntil=valid_until,
                secret=secrets.token_urlsafe(24),
            )
            payload_json = payload.model_dump_json()
            qr_value = QRAttendanceService._encode_qr_value(payload_json)
            windows.append(
                QRWindowResponse(
                    sequence=sequence,
                    valid_from=cursor,
                    valid_until=valid_until,
                    qr_value=qr_value,
                    manual_code="",
                )
            )
            cursor = valid_until
            sequence += 1

        return windows

    @staticmethod
    async def _generate_manual_code(
        redis,
        session_id: str,
        sequence: int,
        ttl_seconds: int,
    ) -> str:
        if ATTENDANCE_MANUAL_CODE_LENGTH <= 0:
            app_exception(
                ErrorCode.CHECKIN_QUEUE_UNAVAILABLE,
                extra_detail="ATTENDANCE_MANUAL_CODE_LENGTH phai lon hon 0",
            )

        lower_bound = 0 if ATTENDANCE_MANUAL_CODE_LENGTH == 1 else 10 ** (ATTENDANCE_MANUAL_CODE_LENGTH - 1)
        upper_bound = 10 ** ATTENDANCE_MANUAL_CODE_LENGTH

        for _ in range(20):
            random_value = secrets.randbelow(upper_bound - lower_bound) + lower_bound
            manual_code = f"{random_value:0{ATTENDANCE_MANUAL_CODE_LENGTH}d}"
            stored = await redis.set(
                QRAttendanceService._manual_code_key(manual_code),
                json.dumps(
                    {
                        "session_id": session_id,
                        "sequence": sequence,
                    }
                ),
                ex=ttl_seconds,
                nx=True,
            )
            if stored:
                return manual_code

        app_exception(
            ErrorCode.CHECKIN_QUEUE_UNAVAILABLE,
            extra_detail="Khong the tao ma diem danh duy nhat cho window",
        )

    @staticmethod
    async def _load_active_payload(
        payload: QRPayloadData,
        *,
        invalid_error: ErrorCode,
        expired_error: ErrorCode,
    ) -> tuple[Any, dict[str, Any], str, str, QRPayloadData]:
        redis = get_redis()
        session_key = QRAttendanceService._session_key(payload.sessionId)
        session_raw = await redis.get(session_key)
        if not session_raw:
            app_exception(ErrorCode.QR_SESSION_NOT_FOUND)

        session_meta = json.loads(session_raw)
        if session_meta.get("status") != "open":
            app_exception(ErrorCode.QR_SESSION_CLOSED)

        if session_meta.get("event_id") != payload.eventId:
            app_exception(invalid_error)

        payload_key = QRAttendanceService._payload_key(payload.sessionId, payload.sequence)
        stored_payload_raw = await redis.get(payload_key)
        if not stored_payload_raw:
            app_exception(expired_error)

        try:
            stored_payload = QRPayloadData.model_validate(json.loads(stored_payload_raw))
        except (json.JSONDecodeError, ValidationError, TypeError):
            app_exception(invalid_error)

        if (
            stored_payload.secret != payload.secret
            or stored_payload.sessionId != payload.sessionId
            or stored_payload.eventId != payload.eventId
            or stored_payload.sequence != payload.sequence
        ):
            app_exception(invalid_error)

        now = QRAttendanceService._utc_now()
        if now < stored_payload.validFrom or now > stored_payload.validUntil:
            app_exception(expired_error)

        return redis, session_meta, session_key, payload_key, stored_payload

    @staticmethod
    async def _queue_checkin(
        *,
        current_user_id: PydanticObjectId,
        payload: QRPayloadData,
        stored_payload: QRPayloadData,
        session_meta: dict[str, Any],
        session_key: str,
        payload_key: str,
        latitude: float | None,
        longitude: float | None,
        source: str,
        source_ip: str | None = None,
        invalid_error: ErrorCode = ErrorCode.QR_PAYLOAD_INVALID,
    ) -> QRScanQueuedResponse:
        redis = get_redis()

        try:
            event_id = PydanticObjectId(payload.eventId)
        except (TypeError, ValueError):
            app_exception(invalid_error)

        participant_key = QRAttendanceService._participant_key(payload.sessionId)
        is_allowed = await redis.sismember(participant_key, str(current_user_id))
        if not is_allowed:
            app_exception(ErrorCode.USER_NOT_ALLOWED_FOR_EVENT)

        distance_meters: float | None = None
        if session_meta.get("location_required"):
            if latitude is None or longitude is None:
                app_exception(ErrorCode.LOCATION_REQUIRED)

            distance_meters = QRAttendanceService._calculate_distance_meters(
                origin_lat=float(session_meta["latitude"]),
                origin_lng=float(session_meta["longitude"]),
                target_lat=latitude,
                target_lng=longitude,
            )
            if distance_meters > float(session_meta["radius_meters"]):
                app_exception(ErrorCode.LOCATION_OUT_OF_RANGE)

        duplicate_key = QRAttendanceService._duplicate_key(
            session_meta["event_type"],
            current_user_id,
            event_id,
        )
        request_id = uuid.uuid4().hex
        duplicate_marker = await redis.set(
            duplicate_key,
            f"pending:{request_id}",
            ex=QR_DUPLICATE_PENDING_TTL_SECONDS,
            nx=True,
        )
        if not duplicate_marker:
            app_exception(ErrorCode.DUPLICATE_CHECKIN)

        queued_at = QRAttendanceService._utc_now()
        message = CheckInMessage(
            request_id=request_id,
            session_id=payload.sessionId,
            event_id=str(event_id),
            event_type=session_meta["event_type"],
            user_id=str(current_user_id),
            sequence=payload.sequence,
            valid_from=stored_payload.validFrom,
            valid_until=stored_payload.validUntil,
            scanned_at=queued_at,
            latitude=latitude,
            longitude=longitude,
            distance_meters=distance_meters,
            duplicate_key=duplicate_key,
            participant_key=participant_key,
            payload_key=payload_key,
            session_key=session_key,
            source_ip=source_ip,
            source=source,
            metadata={
                "location_required": session_meta.get("location_required", False),
            },
        )

        try:
            await publish_checkin_message(
                message.model_dump(mode="json"),
                message_id=request_id,
            )
        except Exception:
            await redis.delete(duplicate_key)
            app_exception(ErrorCode.CHECKIN_QUEUE_UNAVAILABLE)

        logger.info(
            "[QR-API] Pushed to RabbitMQ | request_id=%s | user=%s | event=%s",
            request_id,
            current_user_id,
            event_id,
        )

        return QRScanQueuedResponse(
            request_id=request_id,
            session_id=payload.sessionId,
            event_id=event_id,
            queued_at=queued_at,
        )

    @staticmethod
    async def _create_session(
        *,
        event_id: PydanticObjectId,
        event_type: str,
        actor_id: PydanticObjectId,
        request: QRSessionOpenRequest,
        session_start: datetime,
        session_end: datetime,
        participant_ids: list[PydanticObjectId],
    ) -> QRSessionOpenResponse:
        now = QRAttendanceService._utc_now()
        window_seconds = request.window_seconds or QR_DEFAULT_WINDOW_SECONDS
        session_id = uuid.uuid4().hex
        windows = QRAttendanceService._build_windows(
            session_id=session_id,
            event_id=event_id,
            session_start=session_start,
            session_end=session_end,
            window_seconds=window_seconds,
        )

        session_ttl = max(
            1,
            int((session_end - now).total_seconds()) + QR_SESSION_TTL_BUFFER_SECONDS,
        )
        redis = get_redis()
        session_key = QRAttendanceService._session_key(session_id)
        participant_key = QRAttendanceService._participant_key(session_id)

        session_meta = {
            "session_id": session_id,
            "event_id": str(event_id),
            "event_type": event_type,
            "session_start": QRAttendanceService._iso(session_start),
            "session_end": QRAttendanceService._iso(session_end),
            "window_seconds": window_seconds,
            "participant_count": len(participant_ids),
            "latitude": request.latitude,
            "longitude": request.longitude,
            "radius_meters": request.radius_meters,
            "location_required": request.radius_meters is not None,
            "status": "open",
            "created_by": str(actor_id),
            "created_at": QRAttendanceService._iso(now),
            "window_count": len(windows),
        }

        await redis.set(session_key, json.dumps(session_meta), ex=session_ttl)
        await redis.set(
            QRAttendanceService._event_session_key(event_type, event_id),
            session_id,
            ex=session_ttl,
        )

        if participant_ids:
            await redis.sadd(participant_key, *[str(participant_id) for participant_id in participant_ids])
        await redis.expire(participant_key, session_ttl)

        for window in windows:
            payload_ttl = max(
                1,
                int((window.valid_until - now).total_seconds()) + QR_SESSION_TTL_BUFFER_SECONDS,
            )
            stored_payload_json = QRAttendanceService._decode_qr_value(window.qr_value)
            manual_code = await QRAttendanceService._generate_manual_code(
                redis=redis,
                session_id=session_id,
                sequence=window.sequence,
                ttl_seconds=payload_ttl,
            )
            await redis.set(
                QRAttendanceService._payload_key(session_id, window.sequence),
                stored_payload_json,
                ex=payload_ttl,
            )
            window.manual_code = manual_code

        await AuditLogRepository.create(
            AuditLog(
                action="qr_session.created",
                actor_id=actor_id,
                event_id=event_id,
                target_type="qr_session",
                target_id=session_id,
                metadata={
                    "event_type": event_type,
                    "participant_count": len(participant_ids),
                    "window_seconds": window_seconds,
                    "window_count": len(windows),
                },
            )
        )

        logger.info(
            "[QR-API] Session created | session_id=%s | event=%s | windows=%s | participants=%s",
            session_id,
            event_id,
            len(windows),
            len(participant_ids),
        )

        return QRSessionOpenResponse(
            session_id=session_id,
            event_id=event_id,
            event_type=event_type,
            session_start=session_start,
            session_end=session_end,
            window_seconds=window_seconds,
            participant_count=len(participant_ids),
            location_required=request.radius_meters is not None,
            windows=windows,
        )

    @staticmethod
    async def open_public_session(
        event_id: PydanticObjectId,
        actor_id: PydanticObjectId,
        request: QRSessionOpenRequest,
    ) -> QRSessionOpenResponse:
        QRAttendanceService._validate_location_configuration(request)

        now = QRAttendanceService._utc_now()
        session_start = QRAttendanceService._ensure_utc(request.session_start or now)
        session_end = request.session_end
        if session_end is None:
            app_exception(
                ErrorCode.INVALID_QR_SESSION_TIME,
                extra_detail="session_end la bat buoc",
            )
        session_end = QRAttendanceService._ensure_utc(session_end)
        if session_start >= session_end:
            app_exception(ErrorCode.INVALID_QR_SESSION_TIME)

        participant_id_strs = await ParticipantRepository.list_user_ids_by_event(
            str(event_id),
            "public",
        )
        participant_ids = [PydanticObjectId(participant_id) for participant_id in participant_id_strs]

        logger.info(
            "[QR-API] open_public_session | event_id=%s | actor=%s | participants=%s",
            event_id,
            actor_id,
            len(participant_ids),
        )

        return await QRAttendanceService._create_session(
            event_id=event_id,
            event_type="public",
            actor_id=actor_id,
            request=request,
            session_start=session_start,
            session_end=session_end,
            participant_ids=participant_ids,
        )

    @staticmethod
    async def open_unit_event_session(
        event_id: PydanticObjectId,
        actor_id: PydanticObjectId,
        request: QRSessionOpenRequest,
    ) -> QRSessionOpenResponse:
        QRAttendanceService._validate_location_configuration(request)

        now = QRAttendanceService._utc_now()
        session_start = QRAttendanceService._ensure_utc(request.session_start or now)
        session_end = request.session_end
        if session_end is None:
            app_exception(
                ErrorCode.INVALID_QR_SESSION_TIME,
                extra_detail="session_end la bat buoc",
            )
        session_end = QRAttendanceService._ensure_utc(session_end)
        if session_start >= session_end:
            app_exception(ErrorCode.INVALID_QR_SESSION_TIME)

        participant_id_strs = await ParticipantRepository.list_user_ids_by_event(
            str(event_id),
            "unit",
        )
        participant_ids = [PydanticObjectId(participant_id) for participant_id in participant_id_strs]

        logger.info(
            "[QR-API] open_unit_event_session | event_id=%s | actor=%s | participants=%s",
            event_id,
            actor_id,
            len(participant_ids),
        )

        return await QRAttendanceService._create_session(
            event_id=event_id,
            event_type="unit",
            actor_id=actor_id,
            request=request,
            session_start=session_start,
            session_end=session_end,
            participant_ids=participant_ids,
        )

    @staticmethod
    def _calculate_distance_meters(
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

    @staticmethod
    async def submit_scan(
        current_user_id: PydanticObjectId,
        request: QRScanRequest,
        source_ip: str | None = None,
    ) -> QRScanQueuedResponse:
        try:
            payload_json = QRAttendanceService._decode_qr_value(request.qr_value)
            raw_payload: dict[str, Any] = json.loads(payload_json)
            payload = QRPayloadData.model_validate(raw_payload)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, UnicodeDecodeError):
            app_exception(ErrorCode.QR_PAYLOAD_INVALID)
        _redis, session_meta, session_key, payload_key, stored_payload = await QRAttendanceService._load_active_payload(
            payload,
            invalid_error=ErrorCode.QR_PAYLOAD_INVALID,
            expired_error=ErrorCode.QR_PAYLOAD_EXPIRED,
        )
        return await QRAttendanceService._queue_checkin(
            current_user_id=current_user_id,
            payload=payload,
            stored_payload=stored_payload,
            session_meta=session_meta,
            session_key=session_key,
            payload_key=payload_key,
            latitude=request.latitude,
            longitude=request.longitude,
            source="qr",
            source_ip=source_ip,
            invalid_error=ErrorCode.QR_PAYLOAD_INVALID,
        )

    @staticmethod
    async def submit_manual_code(
        current_user_id: PydanticObjectId,
        request: AttendanceCodeRequest,
        source_ip: str | None = None,
    ) -> QRScanQueuedResponse:
        redis = get_redis()
        manual_code_raw = await redis.get(QRAttendanceService._manual_code_key(request.code))
        if not manual_code_raw:
            app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)

        try:
            manual_code_meta = json.loads(manual_code_raw)
            payload_key = QRAttendanceService._payload_key(
                manual_code_meta["session_id"],
                int(manual_code_meta["sequence"]),
            )
            stored_payload_raw = await redis.get(payload_key)
            if not stored_payload_raw:
                app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)
            payload = QRPayloadData.model_validate(json.loads(stored_payload_raw))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, KeyError):
            app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)

        _redis, session_meta, session_key, payload_key, stored_payload = await QRAttendanceService._load_active_payload(
            payload,
            invalid_error=ErrorCode.ATTENDANCE_CODE_INVALID,
            expired_error=ErrorCode.ATTENDANCE_CODE_INVALID,
        )
        return await QRAttendanceService._queue_checkin(
            current_user_id=current_user_id,
            payload=payload,
            stored_payload=stored_payload,
            session_meta=session_meta,
            session_key=session_key,
            payload_key=payload_key,
            latitude=request.latitude,
            longitude=request.longitude,
            source="manual_code",
            source_ip=source_ip,
            invalid_error=ErrorCode.ATTENDANCE_CODE_INVALID,
        )
