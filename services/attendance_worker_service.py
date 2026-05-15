from datetime import datetime, timezone

from beanie import PydanticObjectId

from configs.redis_config import get_redis
from configs.settings import (
    QR_CHECKIN_LOCK_TTL_SECONDS,
    QR_DUPLICATE_COMPLETED_TTL_SECONDS,
)
from models.attendance import Attendance
from models.audit_log import AuditLog
from repositories.attendance_repo import AttendanceRepository
from repositories.audit_log_repo import AuditLogRepository
from repositories.event_registration_repo import EventRegistrationRepository
from repositories.public_event_repo import PublicEventRepository
from repositories.unit_event_repo import UnitEventRepo
from repositories.unit_event_submission_members_repo import UnitEventSubmissionMembersRepo
from repositories.unit_event_submissions_repo import UnitEventSubmissionsRepo
from repositories.user_repo import UserRepo
from schemas.attendance import CheckInMessage


class AttendanceWorkerService:
    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _ensure_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    async def _acquire_lock(lock_key: str, token: str) -> bool:
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
        redis = get_redis()
        now = AttendanceWorkerService._utc_now()
        ttl_seconds = QR_DUPLICATE_COMPLETED_TTL_SECONDS
        normalized_event_end = AttendanceWorkerService._ensure_utc(event_end)
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
    async def process_checkin(message: CheckInMessage) -> None:
        event_id = PydanticObjectId(message.event_id)
        user_id = PydanticObjectId(message.user_id)
        event_type = message.event_type
        lock_key = f"checkin_lock:{event_type}:{user_id}:{event_id}"
        lock_token = message.request_id
        duplicate_key = message.duplicate_key

        if not await AttendanceWorkerService._acquire_lock(lock_key, lock_token):
            return

        redis = get_redis()
        try:
            if await AttendanceRepository.exists_by_event_and_user(
                event_id,
                user_id,
                event_type=event_type,
            ):
                event_end = await AttendanceWorkerService._resolve_event_end(
                    event_id,
                    event_type,
                )
                await AttendanceWorkerService._set_completed_duplicate_marker(
                    duplicate_key=duplicate_key,
                    event_end=event_end,
                    request_id=message.request_id,
                )
                return

            event_end = await AttendanceWorkerService._resolve_event_end(event_id, event_type)
            if event_type == "public":
                registration = await EventRegistrationRepository.get_by_event_and_user(
                    event_id,
                    user_id,
                )
                if not registration:
                    await redis.delete(duplicate_key)
                    return
            elif event_type == "unit":
                matched_submission_ids = await AttendanceWorkerService._get_unit_submission_ids_for_user(
                    event_id,
                    user_id,
                )
                if not matched_submission_ids:
                    await redis.delete(duplicate_key)
                    return
            else:
                await redis.delete(duplicate_key)
                return

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
            if event_type == "public":
                await EventRegistrationRepository.mark_checked_in(event_id, user_id)
            elif event_type == "unit":
                user = await UserRepo().get_by_id(user_id)
                student_id = user.student_id if user else None
                await UnitEventSubmissionMembersRepo().mark_checked_in_by_submission_ids_and_user(
                    matched_submission_ids,
                    user_id,
                    student_id=student_id,
                )
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
            await AttendanceWorkerService._set_completed_duplicate_marker(
                duplicate_key=duplicate_key,
                event_end=event_end,
                request_id=message.request_id,
            )
        except Exception:
            await redis.delete(duplicate_key)
            raise
        finally:
            await AttendanceWorkerService._release_lock(lock_key, lock_token)

    @staticmethod
    async def _resolve_event_end(
        event_id: PydanticObjectId,
        event_type: str,
    ) -> datetime | None:
        if event_type == "public":
            event = await PublicEventRepository.get_by_id(event_id)
            return event.event_end if event else None
        if event_type == "unit":
            event = await UnitEventRepo().get_by_id(event_id)
            return event.event_end if event else None
        return None

    @staticmethod
    async def _get_unit_submission_ids_for_user(
        event_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> list[PydanticObjectId]:
        approved_submissions = await UnitEventSubmissionsRepo().get_all_approved_by_unit_event_id(
            event_id
        )
        submission_ids = [submission.id for submission in approved_submissions]
        if not submission_ids:
            return []

        members = await UnitEventSubmissionMembersRepo().get_all_by_unit_event_submission_ids(
            submission_ids
        )
        user = await UserRepo().get_by_id(user_id)
        student_id = str(user.student_id).strip() if user and user.student_id else None

        matched_submission_ids: set[PydanticObjectId] = set()
        for member in members:
            matched_user = member.userId == user_id
            matched_student = (
                student_id is not None
                and member.studentId is not None
                and str(member.studentId).strip() == student_id
            )
            if matched_user or matched_student:
                matched_submission_ids.add(member.unitEventSubmissionId)

        return list(matched_submission_ids)
