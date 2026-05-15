import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from configs.database import init_db
from configs.rabbitmq import (
    close_rabbitmq,
    get_checkin_queue,
    publish_checkin_dead_letter_message,
    publish_checkin_retry_message,
)
from configs.redis_config import close_redis
from configs.settings import RABBITMQ_CHECKIN_MAX_RETRIES
from schemas.attendance import CheckInMessage
from services.attendance_worker_service import AttendanceWorkerService

RETRY_COUNT_HEADER = "x-checkin-retry-count"
FAILED_AT_HEADER = "x-checkin-last-failed-at"
ERROR_TYPE_HEADER = "x-checkin-error-type"
ERROR_MESSAGE_HEADER = "x-checkin-error-message"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_id(message, payload: dict[str, Any] | None = None) -> str:
    if message.message_id:
        return message.message_id
    if payload and payload.get("request_id"):
        return str(payload["request_id"])
    return uuid.uuid4().hex


def _retry_count(message) -> int:
    headers = message.headers or {}
    raw_value = headers.get(RETRY_COUNT_HEADER, 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _failure_headers(message, exc: Exception, retry_count: int) -> dict[str, Any]:
    return {
        RETRY_COUNT_HEADER: retry_count,
        FAILED_AT_HEADER: _utc_now_iso(),
        ERROR_TYPE_HEADER: exc.__class__.__name__,
        ERROR_MESSAGE_HEADER: str(exc)[:500],
    }


async def _send_invalid_message_to_dlq(message, exc: Exception) -> None:
    raw_body = message.body.decode("utf-8", errors="replace")
    headers = _failure_headers(message, exc, _retry_count(message))
    headers["x-checkin-failure-kind"] = "invalid-message"

    await publish_checkin_dead_letter_message(
        payload={
            "raw_body": raw_body,
            "failed_at": _utc_now_iso(),
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        },
        message_id=_message_id(message),
        headers=headers,
    )


async def _handle_processing_failure(
    message,
    payload: dict[str, Any],
    exc: Exception,
) -> None:
    current_retry_count = _retry_count(message)
    next_retry_count = current_retry_count + 1
    message_id = _message_id(message, payload)

    if current_retry_count < RABBITMQ_CHECKIN_MAX_RETRIES:
        headers = _failure_headers(message, exc, next_retry_count)
        await publish_checkin_retry_message(
            payload=payload,
            message_id=message_id,
            headers=headers,
        )
        print(
            "Check-in message failed; sent to retry queue. "
            f"message_id={message_id}, retry={next_retry_count}/"
            f"{RABBITMQ_CHECKIN_MAX_RETRIES}, error={exc}"
        )
        return

    headers = _failure_headers(message, exc, current_retry_count)
    headers["x-checkin-failure-kind"] = "max-retries-exceeded"
    await publish_checkin_dead_letter_message(
        payload={
            "original_payload": payload,
            "failed_at": _utc_now_iso(),
            "retry_count": current_retry_count,
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        },
        message_id=message_id,
        headers=headers,
    )
    print(
        "Check-in message exceeded retry limit; sent to DLQ. "
        f"message_id={message_id}, retry={current_retry_count}, error={exc}"
    )


async def run_worker() -> None:
    await init_db()
    queue = await get_checkin_queue()

    async with queue.iterator() as queue_iterator:
        async for message in queue_iterator:
            async with message.process(requeue=True):
                payload: dict[str, Any] | None = None
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    checkin_message = CheckInMessage.model_validate(payload)
                except (
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                    ValidationError,
                    ValueError,
                    TypeError,
                    AttributeError,
                ) as exc:
                    await _send_invalid_message_to_dlq(message, exc)
                    print(
                        "Invalid check-in message; sent to DLQ. "
                        f"message_id={message.message_id}, error={exc}"
                    )
                    continue

                try:
                    await AttendanceWorkerService.process_checkin(checkin_message)
                except Exception as exc:
                    await _handle_processing_failure(message, payload, exc)


async def _main() -> None:
    try:
        await run_worker()
    finally:
        await close_rabbitmq()
        await close_redis()


if __name__ == "__main__":
    asyncio.run(_main())
