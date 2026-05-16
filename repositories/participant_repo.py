from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

from models.participant import Participant


class ParticipantRepository:
    @staticmethod
    async def create_or_ignore(participant_data: dict) -> Participant | None:
        try:
            participant = Participant(**participant_data)
            return await participant.insert()
        except DuplicateKeyError:
            # If already exists, ignore
            return None

    @staticmethod
    async def exists_by_event_and_user(
        event_id: str,
        user_id: str,
        event_type: str | None = None,
    ) -> bool:
        filters = [
            Participant.event_id == event_id,
            Participant.user_id == user_id,
        ]
        if event_type is not None:
            filters.append(Participant.event_type == event_type)
        count = await Participant.find(*filters).count()
        return count > 0

    @staticmethod
    async def get_by_event_and_user(event_id: str, user_id: str) -> Participant | None:
        return await Participant.find_one(
            Participant.event_id == event_id, Participant.user_id == user_id
        )

    @staticmethod
    async def list_user_ids_by_event(event_id: str, event_type: str) -> list[str]:
        participants = await Participant.find(
            Participant.event_id == event_id,
            Participant.event_type == event_type,
        ).to_list()
        return [participant.user_id for participant in participants]

    @staticmethod
    async def delete_by_event_and_user(event_id: str, user_id: str) -> bool:
        participant = await Participant.find_one(
            Participant.event_id == event_id, Participant.user_id == user_id
        )
        if participant:
            await participant.delete()
            return True
        return False
