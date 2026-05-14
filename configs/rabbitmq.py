from __future__ import annotations

import asyncio
import json
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractQueue,
    AbstractRobustConnection,
)

from configs.settings import (
    RABBITMQ_CHECKIN_DEAD_LETTER_EXCHANGE,
    RABBITMQ_CHECKIN_DEAD_LETTER_QUEUE,
    RABBITMQ_CHECKIN_DEAD_LETTER_ROUTING_KEY,
    RABBITMQ_CHECKIN_EXCHANGE,
    RABBITMQ_CHECKIN_RETRY_DELAY_MS,
    RABBITMQ_CHECKIN_RETRY_EXCHANGE,
    RABBITMQ_CHECKIN_RETRY_QUEUE,
    RABBITMQ_CHECKIN_RETRY_ROUTING_KEY,
    RABBITMQ_CHECKIN_QUEUE,
    RABBITMQ_CHECKIN_ROUTING_KEY,
    RABBITMQ_PREFETCH_COUNT,
    RABBITMQ_URL,
    RABBITMQ_REGISTRATION_SYNC_EXCHANGE,
    RABBITMQ_REGISTRATION_SYNC_QUEUE,
    RABBITMQ_REGISTRATION_SYNC_ROUTING_KEY,
)

_connection: AbstractRobustConnection | None = None
_channel: AbstractChannel | None = None
_exchange: AbstractExchange | None = None
_queue: AbstractQueue | None = None
_retry_exchange: AbstractExchange | None = None
_retry_queue: AbstractQueue | None = None
_dead_letter_exchange: AbstractExchange | None = None
_dead_letter_queue: AbstractQueue | None = None
_sync_exchange: AbstractExchange | None = None
_sync_queue: AbstractQueue | None = None
_lock = asyncio.Lock()


async def _ensure_rabbitmq() -> tuple[AbstractChannel, AbstractExchange, AbstractQueue]:
    global _connection, _channel, _exchange, _queue
    global _retry_exchange, _retry_queue, _dead_letter_exchange, _dead_letter_queue
    global _sync_exchange, _sync_queue

    if _connection and not _connection.is_closed and _channel and not _channel.is_closed:
        if (
            _exchange is not None
            and _queue is not None
            and _retry_exchange is not None
            and _retry_queue is not None
            and _dead_letter_exchange is not None
            and _dead_letter_queue is not None
            and _sync_exchange is not None
            and _sync_queue is not None
        ):
            return _channel, _exchange, _queue

    async with _lock:
        if _connection is None or _connection.is_closed:
            _connection = await aio_pika.connect_robust(RABBITMQ_URL)

        if _channel is None or _channel.is_closed:
            _channel = await _connection.channel()
            await _channel.set_qos(prefetch_count=RABBITMQ_PREFETCH_COUNT)

        if _exchange is None:
            _exchange = await _channel.declare_exchange(
                RABBITMQ_CHECKIN_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )

        if _retry_exchange is None:
            _retry_exchange = await _channel.declare_exchange(
                RABBITMQ_CHECKIN_RETRY_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )

        if _dead_letter_exchange is None:
            _dead_letter_exchange = await _channel.declare_exchange(
                RABBITMQ_CHECKIN_DEAD_LETTER_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )

        if _queue is None:
            _queue = await _channel.declare_queue(
                RABBITMQ_CHECKIN_QUEUE,
                durable=True,
            )
            await _queue.bind(_exchange, routing_key=RABBITMQ_CHECKIN_ROUTING_KEY)

        if _retry_queue is None:
            _retry_queue = await _channel.declare_queue(
                RABBITMQ_CHECKIN_RETRY_QUEUE,
                durable=True,
                arguments={
                    "x-message-ttl": RABBITMQ_CHECKIN_RETRY_DELAY_MS,
                    "x-dead-letter-exchange": RABBITMQ_CHECKIN_EXCHANGE,
                    "x-dead-letter-routing-key": RABBITMQ_CHECKIN_ROUTING_KEY,
                },
            )
            await _retry_queue.bind(
                _retry_exchange,
                routing_key=RABBITMQ_CHECKIN_RETRY_ROUTING_KEY,
            )

        if _dead_letter_queue is None:
            _dead_letter_queue = await _channel.declare_queue(
                RABBITMQ_CHECKIN_DEAD_LETTER_QUEUE,
                durable=True,
            )
            await _dead_letter_queue.bind(
                _dead_letter_exchange,
                routing_key=RABBITMQ_CHECKIN_DEAD_LETTER_ROUTING_KEY,
            )

        if _sync_exchange is None:
            _sync_exchange = await _channel.declare_exchange(
                RABBITMQ_REGISTRATION_SYNC_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )

        if _sync_queue is None:
            _sync_queue = await _channel.declare_queue(
                RABBITMQ_REGISTRATION_SYNC_QUEUE,
                durable=True,
            )
            await _sync_queue.bind(_sync_exchange, routing_key=RABBITMQ_REGISTRATION_SYNC_ROUTING_KEY)

    return _channel, _exchange, _queue


async def _publish_json_message(
    exchange: AbstractExchange,
    routing_key: str,
    payload: dict[str, Any],
    message_id: str,
    headers: dict[str, Any] | None = None,
) -> None:
    message = Message(
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
        message_id=message_id,
        headers=headers,
    )
    await exchange.publish(message, routing_key=routing_key)


async def publish_checkin_message(payload: dict[str, Any], message_id: str) -> None:
    _, exchange, _ = await _ensure_rabbitmq()
    await _publish_json_message(
        exchange=exchange,
        routing_key=RABBITMQ_CHECKIN_ROUTING_KEY,
        payload=payload,
        message_id=message_id,
    )


async def publish_checkin_retry_message(
    payload: dict[str, Any],
    message_id: str,
    headers: dict[str, Any] | None = None,
) -> None:
    await _ensure_rabbitmq()
    if _retry_exchange is None:
        raise RuntimeError("RabbitMQ retry exchange is not initialized")

    await _publish_json_message(
        exchange=_retry_exchange,
        routing_key=RABBITMQ_CHECKIN_RETRY_ROUTING_KEY,
        payload=payload,
        message_id=message_id,
        headers=headers,
    )


async def publish_checkin_dead_letter_message(
    payload: dict[str, Any],
    message_id: str,
    headers: dict[str, Any] | None = None,
) -> None:
    await _ensure_rabbitmq()
    if _dead_letter_exchange is None:
        raise RuntimeError("RabbitMQ dead-letter exchange is not initialized")

    await _publish_json_message(
        exchange=_dead_letter_exchange,
        routing_key=RABBITMQ_CHECKIN_DEAD_LETTER_ROUTING_KEY,
        payload=payload,
        message_id=message_id,
        headers=headers,
    )


async def get_checkin_queue() -> AbstractQueue:
    _, _, queue = await _ensure_rabbitmq()
    return queue


async def close_rabbitmq() -> None:
    global _connection, _channel, _exchange, _queue
    global _retry_exchange, _retry_queue, _dead_letter_exchange, _dead_letter_queue

    if _channel is not None and not _channel.is_closed:
        await _channel.close()
    if _connection is not None and not _connection.is_closed:
        await _connection.close()

    _connection = None
    _channel = None
    _exchange = None
    _queue = None
    _retry_exchange = None
    _retry_queue = None
    _dead_letter_exchange = None
    _dead_letter_queue = None
    
    global _sync_exchange, _sync_queue
    _sync_exchange = None
    _sync_queue = None

async def get_registration_sync_queue() -> AbstractQueue:
    await _ensure_rabbitmq()
    global _sync_queue
    if _sync_queue is None:
        raise RuntimeError("Sync queue not initialized")
    return _sync_queue
