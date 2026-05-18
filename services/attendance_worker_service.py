import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId

from configs.rabbitmq import publish_checkin_sync_message
from configs.redis_config import get_redis
from configs.settings import (
    QR_CHECKIN_LOCK_TTL_SECONDS,
    QR_DUPLICATE_COMPLETED_TTL_SECONDS,
)
from models.attendance import Attendance
from models.audit_log import AuditLog
from repositories.attendance_repo import AttendanceRepository
from repositories.audit_log_repo import AuditLogRepository
from repositories.participant_repo import ParticipantRepository
from schemas.attendance import CheckInMessage

logger = logging.getLogger("qr_service.attendance_worker")


class AttendanceWorkerService:
    @staticmethod
    def _utc_now() -> datetime:
        """Lấy thời gian hiện tại theo chuẩn UTC."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _ensure_utc(value: datetime | None) -> datetime | None:
        """Đảm bảo một đối tượng datetime luôn có timezone là UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    async def _acquire_lock(lock_key: str, token: str) -> bool:
        """Chiếm distributed lock trên Redis để đảm bảo tại một thời điểm chỉ có 1 worker xử lý 1 cặp (User, Event)."""
        redis = get_redis()
        acquired = await redis.set(
            lock_key,
            token,
            ex=QR_CHECKIN_LOCK_TTL_SECONDS,
            nx=True,
        )
        return bool(acquired)

    @staticmethod
    async def _release_lock(lock_key: str, token: str) -> None:
        """Giải phóng distributed lock sau khi xử lý xong hoặc gặp lỗi."""
        redis = get_redis()
        current_token = await redis.get(lock_key)
        if current_token == token:
            await redis.delete(lock_key)

    @staticmethod
    async def _set_completed_duplicate_marker(
        duplicate_key: str,
        event_end: datetime | None,
        request_id: str,
    ) -> None:
        """Đánh dấu yêu cầu này đã được xử lý xong hoàn toàn để chống việc sinh viên dùng lại mã cũ."""
        redis = get_redis()
        now = AttendanceWorkerService._utc_now()
        ttl_seconds = QR_DUPLICATE_COMPLETED_TTL_SECONDS
        normalized_event_end = AttendanceWorkerService._ensure_utc(event_end)
        
        # Đảm bảo marker tồn tại ít nhất cho đến khi sự kiện kết thúc
        if normalized_event_end is not None:
            ttl_seconds = max(
                ttl_seconds,
                int((normalized_event_end - now).total_seconds())
                + QR_DUPLICATE_COMPLETED_TTL_SECONDS,
            )
        await redis.set(
            duplicate_key,
            f"processed:{request_id}",
            ex=max(1, ttl_seconds),
        )

    @staticmethod
    async def _publish_checkin_sync(
        *,
        attendance: Attendance,
        event_type: str,
        event_id: PydanticObjectId,
        user_id: PydanticObjectId,
        request_id: str,
    ) -> None:
        """Gửi thông báo điểm danh thành công sang Backend chính để đồng bộ dữ liệu (Giai đoạn 2)."""
        sync_payload = {
            "user_id": str(user_id),
            "event_id": str(event_id),
            "event_type": event_type,
            "request_id": request_id,
            "checked_in_at": attendance.scanned_at.isoformat(),
        }
        await publish_checkin_sync_message(
            payload=sync_payload,
            message_id=request_id,
        )
        logger.info(
            "[qr: Thành công] Đã publish message đồng bộ check-in sang BE | request_id=%s | event_type=%s | event=%s | user=%s",
            request_id,
            event_type,
            event_id,
            user_id,
        )

    @staticmethod
    async def process_checkin(message: CheckInMessage) -> None:
        """Hàm nghiệp vụ chính để xử lý một yêu cầu điểm danh lấy từ hàng đợi."""
        event_id = PydanticObjectId(message.event_id)
        user_id = PydanticObjectId(message.user_id)
        event_type = message.event_type
        lock_key = f"checkin_lock:{event_type}:{user_id}:{event_id}"
        lock_token = message.request_id
        duplicate_key = message.duplicate_key

        # 1. Chiếm Lock để tránh Race Condition (nhiều worker xử lý cùng lúc)
        if not await AttendanceWorkerService._acquire_lock(lock_key, lock_token):
            return

        redis = get_redis()
        try:
            # 2. KIỂM TRA TRÙNG LẶP TRONG DB: Đề phòng trường hợp sinh viên đã điểm danh thành công trước đó
            existing_attendance = await AttendanceRepository.get_by_event_and_user(
                event_id,
                user_id,
                event_type=event_type,
            )
            if existing_attendance is not None:
                # Nếu đã có trong DB nhưng marker Redis bị mất, hãy đồng bộ lại sang BE cho chắc
                duplicate_marker = await redis.get(duplicate_key)
                if duplicate_marker in (None, f"pending:{message.request_id}"):
                    await AttendanceWorkerService._publish_checkin_sync(
                        attendance=existing_attendance,
                        event_type=event_type,
                        event_id=event_id,
                        user_id=user_id,
                        request_id=message.request_id,
                    )
                await AttendanceWorkerService._set_completed_duplicate_marker(
                    duplicate_key=duplicate_key,
                    event_end=None,
                    request_id=message.request_id,
                )
                return

            if event_type not in {"public", "unit"}:
                await redis.delete(duplicate_key)
                return

            # 3. KIỂM TRA QUYỀN (Double Check): Xác nhận sinh viên có trong danh sách tham gia
            participant_exists = await ParticipantRepository.exists_by_event_and_user(
                str(event_id),
                str(user_id),
                event_type=event_type,
            )
            if not participant_exists:
                await redis.delete(duplicate_key)
                logger.warning(
                    "[qr: Cảnh báo] Không tìm thấy participant, hủy check-in | event_type=%s | event=%s | user=%s | request_id=%s",
                    event_type,
                    event_id,
                    user_id,
                    message.request_id,
                )
                return

            # 4. LƯU BẢN GHI ĐIỂM DANH: Ghi vào MongoDB của dịch vụ QR
            attendance = Attendance(
                event_id=event_id,
                event_type=event_type,
                user_id=user_id,
                session_id=message.session_id,
                sequence=message.sequence,
                request_id=message.request_id,
                valid_from=message.valid_from,
                valid_until=message.valid_until,
                scanned_at=message.scanned_at,
                processed_at=AttendanceWorkerService._utc_now(),
                checkin_latitude=message.latitude,
                checkin_longitude=message.longitude,
                distance_meters=message.distance_meters,
                source=message.source,
            )
            await AttendanceRepository.create(attendance)

            # 5. GHI AUDIT LOG: Lưu vết để phục vụ hậu kiểm sau này
            await AuditLogRepository.create(
                AuditLog(
                    action="attendance.checkin.completed",
                    actor_id=user_id,
                    event_id=event_id,
                    user_id=user_id,
                    target_type="attendance",
                    target_id=str(attendance.id),
                    request_id=message.request_id,
                    metadata={
                        "session_id": message.session_id,
                        "sequence": message.sequence,
                        "distance_meters": message.distance_meters,
                        "source_ip": message.source_ip,
                        "source": message.source,
                    },
                )
            )

            # 6. ĐỒNG BỘ SANG BACKEND CHÍNH: Báo cho BE chính để cập nhật UI/Dashboard
            await AttendanceWorkerService._publish_checkin_sync(
                attendance=attendance,
                event_type=event_type,
                event_id=event_id,
                user_id=user_id,
                request_id=message.request_id,
            )

            # 7. HOÀN TẤT: Cập nhật marker trên Redis để chặn các yêu cầu quét mã này lần nữa
            await AttendanceWorkerService._set_completed_duplicate_marker(
                duplicate_key=duplicate_key,
                event_end=None,
                request_id=message.request_id,
            )
            logger.info(
                "[qr: Thành công] Check-in completed | request_id=%s | event_type=%s | event=%s | user=%s",
                message.request_id,
                event_type,
                event_id,
                user_id,
            )
        except Exception:
            # Nếu có bất kỳ lỗi gì trong quá trình lưu DB, xóa marker để có thể thử lại
            await redis.delete(duplicate_key)
            raise
        finally:
            # 8. GIẢI PHÓNG LOCK: Cho phép các yêu cầu khác (nếu có) được xử lý
            await AttendanceWorkerService._release_lock(lock_key, lock_token)
