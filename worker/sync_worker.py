import asyncio
import json
from datetime import datetime, timezone

from pydantic import ValidationError

from configs.database import init_db
from configs.rabbitmq import close_rabbitmq, get_registration_sync_queue
from repositories.participant_repo import ParticipantRepository
from schemas.registration_sync import RegistrationSyncMessage


async def process_sync_message(message_body: bytes) -> None:
    """Xử lý tin nhắn đồng bộ đăng ký từ Backend chính."""
    try:
        payload = json.loads(message_body.decode("utf-8"))
        sync_msg = RegistrationSyncMessage.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"Invalid sync message received: {e}")
        return

    # Nếu hành động là CANCEL, xóa sinh viên khỏi danh sách được phép tham gia
    if sync_msg.action == "CANCEL":
        deleted = await ParticipantRepository.delete_by_event_and_user(sync_msg.event_id, sync_msg.user_id)
        if deleted:
            print(f"Successfully deleted participant: user {sync_msg.user_id} from event {sync_msg.event_id}")
        else:
            print(f"Participant not found for deletion: user {sync_msg.user_id}, event {sync_msg.event_id}")
        return

    # Mặc định là đồng bộ mới hoặc cập nhật thông tin sinh viên
    participant_data = {
        "user_id": sync_msg.user_id,
        "event_id": sync_msg.event_id,
        "event_type": sync_msg.event_type,
        "student_id": sync_msg.student_id,
        "full_name": sync_msg.full_name,
        "registered_at": sync_msg.registered_at,
        "synced_at": datetime.now(timezone.utc),
    }

    # Lưu vào qr_db để phục vụ việc kiểm tra quyền quét QR nhanh chóng
    await ParticipantRepository.create_or_ignore(participant_data)
    print(f"Successfully synced participant: user {sync_msg.user_id} for event {sync_msg.event_id}")


async def run_sync_worker() -> None:
    """Khởi tạo và chạy worker lắng nghe tin nhắn đồng bộ đăng ký."""
    await init_db()
    queue = await get_registration_sync_queue()
    print("Started Registration Sync Worker. Listening for messages...")

    async with queue.iterator() as queue_iterator:
        async for message in queue_iterator:
            async with message.process(requeue=True):
                await process_sync_message(message.body)


async def main() -> None:
    """Điểm khởi đầu của script đồng bộ."""
    try:
        await run_sync_worker()
    finally:
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
