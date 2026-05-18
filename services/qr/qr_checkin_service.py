import json
import logging
import uuid
from typing import Any

from beanie import PydanticObjectId
from pydantic import ValidationError

from configs.rabbitmq import publish_checkin_message
from configs.redis_config import get_redis
from configs.settings import QR_DUPLICATE_PENDING_TTL_SECONDS
from exceptions import ErrorCode, app_exception
from schemas.attendance import (
    AttendanceCodeRequest,
    CheckInMessage,
    QRPayloadData,
    QRScanQueuedResponse,
    QRScanRequest,
)
from services.qr.qr_utils import QRUtils

logger = logging.getLogger("qr_service.attendance.checkin")

class QRCheckinService:
    @staticmethod
    async def _load_active_payload(
        payload: QRPayloadData,
        *,
        invalid_error: ErrorCode,
        expired_error: ErrorCode,
    ) -> tuple[Any, dict[str, Any], str, str, QRPayloadData]:
        """Kiểm tra tính hợp lệ của QR/Mã nhập tay so với dữ liệu đang lưu trong Redis (check secret, check thời gian)."""
        redis = get_redis()
        session_key = QRUtils.session_key(payload.sessionId)
        session_raw = await redis.get(session_key)
        if not session_raw:
            app_exception(ErrorCode.QR_SESSION_NOT_FOUND)

        session_meta = json.loads(session_raw)
        if session_meta.get("status") != "open":
            app_exception(ErrorCode.QR_SESSION_CLOSED)

        if session_meta.get("event_id") != payload.eventId:
            app_exception(invalid_error)

        payload_key = QRUtils.payload_key(payload.sessionId, payload.sequence)
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

        now = QRUtils.utc_now()
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
        """Kiểm tra quyền tham gia, khoảng cách GPS, chống spam, và cuối cùng là đẩy yêu cầu vào RabbitMQ."""
        redis = get_redis()

        # 1. Chuyển đổi Event ID sang object ID hợp lệ
        try:
            event_id = PydanticObjectId(payload.eventId)
        except (TypeError, ValueError):
            app_exception(invalid_error)

        # 2. KIỂM TRA QUYỀN THAM GIA: Quét trong danh sách participants lưu trên Redis (Set)
        participant_key = QRUtils.participant_key(payload.sessionId)
        is_allowed = await redis.sismember(participant_key, str(current_user_id))
        if not is_allowed:
            app_exception(ErrorCode.USER_NOT_ALLOWED_FOR_EVENT)

        # 3. KIỂM TRA VỊ TRÍ (GPS): Nếu sự kiện yêu cầu phải có tọa độ
        distance_meters: float | None = None
        if session_meta.get("location_required"):
            if latitude is None or longitude is None:
                app_exception(ErrorCode.LOCATION_REQUIRED)

            # Tính khoảng cách giữa tọa độ sinh viên và tọa độ đã cấu hình cho sự kiện
            distance_meters = QRUtils.calculate_distance_meters(
                origin_lat=float(session_meta["latitude"]),
                origin_lng=float(session_meta["longitude"]),
                target_lat=latitude,
                target_lng=longitude,
            )
            # Nếu vượt quá bán kính cho phép (ví dụ > 300m)
            if distance_meters > float(session_meta["radius_meters"]):
                app_exception(ErrorCode.LOCATION_OUT_OF_RANGE)

        # 4. CHỐNG DUPLICATE (SPAM CLICK): Ngăn chặn việc bấm nút gửi liên tục hoặc quét 2 máy cùng lúc
        duplicate_key = QRUtils.duplicate_key(
            session_meta["event_type"],
            current_user_id,
            event_id,
        )
        request_id = uuid.uuid4().hex
        # Sử dụng NX (Not Exist) để đảm bảo chỉ có 1 request đầu tiên được chấp nhận trong thời gian TTL
        duplicate_marker = await redis.set(
            duplicate_key,
            f"pending:{request_id}",
            ex=QR_DUPLICATE_PENDING_TTL_SECONDS,
            nx=True,
        )
        if not duplicate_marker:
            app_exception(ErrorCode.DUPLICATE_CHECKIN)

        # 5. ĐÓNG GÓI TIN NHẮN (MESSAGE PAYLOAD): Chuẩn bị dữ liệu để ném vào Queue xử lý ngầm
        queued_at = QRUtils.utc_now()
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

        # 6. ĐẨY VÀO RABBITMQ: Giai đoạn 1 hoàn tất tại đây
        try:
            await publish_checkin_message(
                message.model_dump(mode="json"),
                message_id=request_id,
            )
        except Exception:
            # Nếu RabbitMQ sập, phải xóa cờ duplicate để sinh viên có thể thử lại ngay lập tức
            await redis.delete(duplicate_key)
            app_exception(ErrorCode.CHECKIN_QUEUE_UNAVAILABLE)

        logger.info(
            "[QR-API] Pushed to RabbitMQ | request_id=%s | user=%s | event=%s",
            request_id,
            current_user_id,
            event_id,
        )

        # Trả về mã 202 Accepted cho Frontend ngay lập tức
        return QRScanQueuedResponse(
            request_id=request_id,
            session_id=payload.sessionId,
            event_id=event_id,
            queued_at=queued_at,
        )

    @staticmethod
    async def submit_scan(
        current_user_id: PydanticObjectId,
        request: QRScanRequest,
        source_ip: str | None = None,
    ) -> QRScanQueuedResponse:
        """Xử lý yêu cầu check-in từ việc quét mã QR."""
        try:
            payload_json = QRUtils.decode_qr_value(request.qr_value)
            raw_payload: dict[str, Any] = json.loads(payload_json)
            payload = QRPayloadData.model_validate(raw_payload)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, UnicodeDecodeError):
            app_exception(ErrorCode.QR_PAYLOAD_INVALID)
            
        _redis, session_meta, session_key, payload_key, stored_payload = await QRCheckinService._load_active_payload(
            payload,
            invalid_error=ErrorCode.QR_PAYLOAD_INVALID,
            expired_error=ErrorCode.QR_PAYLOAD_EXPIRED,
        )
        return await QRCheckinService._queue_checkin(
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
        """Xử lý yêu cầu check-in từ việc nhập mã số thủ công."""
        redis = get_redis()
        manual_code_raw = await redis.get(QRUtils.manual_code_key(request.code))
        if not manual_code_raw:
            app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)

        try:
            manual_code_meta = json.loads(manual_code_raw)
            payload_key = QRUtils.payload_key(
                manual_code_meta["session_id"],
                int(manual_code_meta["sequence"]),
            )
            stored_payload_raw = await redis.get(payload_key)
            if not stored_payload_raw:
                app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)
            payload = QRPayloadData.model_validate(json.loads(stored_payload_raw))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, KeyError):
            app_exception(ErrorCode.ATTENDANCE_CODE_INVALID)

        _redis, session_meta, session_key, payload_key, stored_payload = await QRCheckinService._load_active_payload(
            payload,
            invalid_error=ErrorCode.ATTENDANCE_CODE_INVALID,
            expired_error=ErrorCode.ATTENDANCE_CODE_INVALID,
        )
        return await QRCheckinService._queue_checkin(
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
