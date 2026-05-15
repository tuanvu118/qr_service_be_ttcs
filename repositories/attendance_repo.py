from beanie import PydanticObjectId

from models.attendance import Attendance


class AttendanceRepository:
    @staticmethod
    async def create(attendance: Attendance) -> Attendance:
        return await attendance.insert()

    @staticmethod
    async def get_by_event_and_user(
        event_id: PydanticObjectId,
        user_id: PydanticObjectId,
        event_type: str | None = None,
    ) -> Attendance | None:
        filters = [
            Attendance.event_id == event_id,
            Attendance.user_id == user_id,
        ]
        if event_type is not None:
            filters.append(Attendance.event_type == event_type)
        return await Attendance.find_one(*filters)

    @staticmethod
    async def exists_by_event_and_user(
        event_id: PydanticObjectId,
        user_id: PydanticObjectId,
        event_type: str | None = None,
    ) -> bool:
        filters = [
            Attendance.event_id == event_id,
            Attendance.user_id == user_id,
        ]
        if event_type is not None:
            filters.append(Attendance.event_type == event_type)
        return await Attendance.find(*filters).count() > 0

    @staticmethod
    async def list_by_event(
        event_id: PydanticObjectId,
        event_type: str | None = None,
    ) -> list[Attendance]:
        filters = [Attendance.event_id == event_id]
        if event_type is not None:
            filters.append(Attendance.event_type == event_type)
        return await Attendance.find(*filters).sort("-processed_at").to_list()
