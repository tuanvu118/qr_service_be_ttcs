import json
import logging
import secrets
import uuid
from datetime import datetime

from beanie import PydanticObjectId

from configs.redis_config import get_redis
from configs.settings import (
    ATTENDANCE_MANUAL_CODE_LENGTH,
    QR_DEFAULT_WINDOW_SECONDS,
    QR_MAX_WINDOWS_PER_SESSION,
    QR_SESSION_TTL_BUFFER_SECONDS,
)
from exceptions import ErrorCode, app_exception
from models.audit_log import AuditLog
from repositories.audit_log_repo import AuditLogRepository
from repositories.participant_repo import ParticipantRepository
from schemas.attendance import (
    QRPayloadData,
    QRSessionOpenRequest,
    QRSessionOpenResponse,
    QRWindowResponse,
)
from services.qr.qr_utils import QRUtils

logger = logging.getLogger("qr_service.attendance.session")

class QRSessionService:
    @staticmethod
    def _build_windows(
        session_id: str,
        event_id: PydanticObjectId,
        session_start: datetime,
        session_end: datetime,
        window_seconds: int,
    ) -> list[QRWindowResponse]:
        """Chia nhỏ thời gian sự kiện thành các 'cửa sổ' (ví dụ 60s/mã) và tạo QR payload cho từng cửa sổ."""
        from datetime import timedelta
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
            qr_value = QRUtils.encode_qr_value(payload_json)
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
        """Tạo mã số ngẫu nhiên (6 chữ số) duy nhất trong phiên để sinh viên nhập tay nếu không quét được QR."""
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
                QRUtils.manual_code_key(manual_code),
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
        """Logic tổng hợp để khởi tạo một phiên điểm danh: lưu meta, lưu danh sách sinh viên, tạo các cửa sổ và mã QR."""
        now = QRUtils.utc_now()
        window_seconds = request.window_seconds or QR_DEFAULT_WINDOW_SECONDS
        session_id = uuid.uuid4().hex
        windows = QRSessionService._build_windows(
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
        session_key = QRUtils.session_key(session_id)
        participant_key = QRUtils.participant_key(session_id)

        session_meta = {
            "session_id": session_id,
            "event_id": str(event_id),
            "event_type": event_type,
            "session_start": QRUtils.iso(session_start),
            "session_end": QRUtils.iso(session_end),
            "window_seconds": window_seconds,
            "participant_count": len(participant_ids),
            "latitude": request.latitude,
            "longitude": request.longitude,
            "radius_meters": request.radius_meters,
            "location_required": request.radius_meters is not None,
            "status": "open",
            "created_by": str(actor_id),
            "created_at": QRUtils.iso(now),
            "window_count": len(windows),
        }

        await redis.set(session_key, json.dumps(session_meta), ex=session_ttl)
        await redis.set(
            QRUtils.event_session_key(event_type, event_id),
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
            stored_payload_json = QRUtils.decode_qr_value(window.qr_value)
            manual_code = await QRSessionService._generate_manual_code(
                redis=redis,
                session_id=session_id,
                sequence=window.sequence,
                ttl_seconds=payload_ttl,
            )
            await redis.set(
                QRUtils.payload_key(session_id, window.sequence),
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
        """API dành cho Admin mở phiên điểm danh cho sự kiện Công khai."""
        QRUtils.validate_location_configuration(request)

        now = QRUtils.utc_now()
        session_start = QRUtils.ensure_utc(request.session_start or now)
        session_end = request.session_end
        if session_end is None:
            app_exception(
                ErrorCode.INVALID_QR_SESSION_TIME,
                extra_detail="session_end la bat buoc",
            )
        session_end = QRUtils.ensure_utc(session_end)
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

        return await QRSessionService._create_session(
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
        """API dành cho Admin mở phiên điểm danh cho sự kiện cấp Đơn vị."""
        QRUtils.validate_location_configuration(request)

        now = QRUtils.utc_now()
        session_start = QRUtils.ensure_utc(request.session_start or now)
        session_end = request.session_end
        if session_end is None:
            app_exception(
                ErrorCode.INVALID_QR_SESSION_TIME,
                extra_detail="session_end la bat buoc",
            )
        session_end = QRUtils.ensure_utc(session_end)
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

        return await QRSessionService._create_session(
            event_id=event_id,
            event_type="unit",
            actor_id=actor_id,
            request=request,
            session_start=session_start,
            session_end=session_end,
            participant_ids=participant_ids,
        )
