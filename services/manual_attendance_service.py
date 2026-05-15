import uuid
from datetime import datetime, timezone
from beanie import PydanticObjectId
from exceptions import ErrorCode, app_exception
from models.attendance import Attendance
from models.audit_log import AuditLog
from repositories.attendance_repo import AttendanceRepository
from repositories.audit_log_repo import AuditLogRepository
from repositories.event_registration_repo import EventRegistrationRepository
from repositories.unit_event_submissions_repo import UnitEventSubmissionsRepo
from repositories.unit_event_submission_members_repo import UnitEventSubmissionMembersRepo
from repositories.user_repo import UserRepo
from schemas.attendance import AttendanceRead, ManualAttendanceRequest

class ManualAttendanceService:
    @staticmethod
    async def mark_manual_attendance(
        actor_id: PydanticObjectId,
        request: ManualAttendanceRequest,
    ) -> AttendanceRead:
        event_id = request.event_id
        user_id = request.user_id
        event_type = request.event_type

        # 1. Check if user is registered/member
        if event_type == "public":
            registration = await EventRegistrationRepository.get_by_event_and_user(event_id, user_id)
            if not registration:
                app_exception(ErrorCode.USER_NOT_ALLOWED_FOR_EVENT, extra_detail="Người dùng chưa đăng ký tham gia sự kiện này")
        elif event_type == "unit":
            approved_submissions = await UnitEventSubmissionsRepo().get_all_approved_by_unit_event_id(event_id)
            submission_ids = [submission.id for submission in approved_submissions]
            if not submission_ids:
                app_exception(ErrorCode.USER_NOT_ALLOWED_FOR_EVENT, extra_detail="Sự kiện không có đơn vị nào được duyệt tham gia")
            
            members = await UnitEventSubmissionMembersRepo().get_all_by_unit_event_submission_ids(submission_ids)
            user = await UserRepo().get_by_id(user_id)
            student_id = str(user.student_id).strip() if user and user.student_id else None
            
            matched_submission_ids = []
            for member in members:
                matched_user = member.userId == user_id
                matched_student = (
                    student_id is not None
                    and member.studentId is not None
                    and str(member.studentId).strip() == student_id
                )
                if matched_user or matched_student:
                    matched_submission_ids.append(member.unitEventSubmissionId)
            
            if not matched_submission_ids:
                app_exception(ErrorCode.USER_NOT_ALLOWED_FOR_EVENT, extra_detail="Người dùng không thuộc danh sách tham gia sự kiện này")
        else:
            app_exception(ErrorCode.INVALID_OPTION, extra_detail="event_type không hợp lệ")

        # 2. Check if attendance already exists
        if await AttendanceRepository.exists_by_event_and_user(event_id, user_id, event_type=event_type):
            app_exception(ErrorCode.DUPLICATE_CHECKIN, extra_detail="Người dùng đã được điểm danh trước đó")

        # 3. Create Attendance record
        now = datetime.now(timezone.utc)
        attendance = Attendance(
            event_id=event_id,
            event_type=event_type,
            user_id=user_id,
            session_id="manual",
            sequence=0,
            request_id=f"manual_{uuid.uuid4().hex}",
            valid_from=now,
            valid_until=now,
            scanned_at=now,
            processed_at=now,
            source="manual",
        )
        await AttendanceRepository.create(attendance)

        # 4. Mark as checked-in in registration/member record
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

        # 5. Audit Log
        await AuditLogRepository.create(
            AuditLog(
                action="attendance.manual_checkin.completed",
                actor_id=actor_id,
                event_id=event_id,
                user_id=user_id,
                target_type="attendance",
                target_id=str(attendance.id),
                metadata={
                    "source": "manual",
                },
            )
        )

        return AttendanceRead.model_validate(attendance)
