import logging

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Request, status

from exceptions import ErrorCode, app_exception
from schemas.attendance import (
    AttendanceCodeRequest,
    QRScanQueuedResponse,
    QRScanRequest,
    QRSessionOpenRequest,
    QRSessionOpenResponse,
)
from schemas.auth import TokenData
from security import require_admin_or_manager_global, require_user
from services.qr_attendance_service import QRAttendanceService
from utils.rate_limiter import limiter

logger = logging.getLogger("qr_service.router")

router = APIRouter(prefix="/attendance", tags=["QR Attendance"])


def _to_object_id(value: str) -> PydanticObjectId:
    try:
        return PydanticObjectId(value)
    except (InvalidId, TypeError, ValueError):
        app_exception(ErrorCode.INVALID_ID_FORMAT)


@router.post(
    "/events/{event_id}/sessions",
    response_model=QRSessionOpenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_public_session(
    event_id: PydanticObjectId,
    request_body: QRSessionOpenRequest,
    current_user: TokenData = Depends(require_admin_or_manager_global),
) -> QRSessionOpenResponse:
    logger.info(
        "[QR-API] open_public_session | user_id=%s | event_id=%s",
        current_user.sub,
        event_id,
    )
    return await QRAttendanceService.open_public_session(
        event_id=event_id,
        actor_id=_to_object_id(current_user.sub),
        request=request_body,
    )


@router.post(
    "/unit-events/{event_id}/sessions",
    response_model=QRSessionOpenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_unit_event_session(
    event_id: PydanticObjectId,
    request_body: QRSessionOpenRequest,
    current_user: TokenData = Depends(require_admin_or_manager_global),
) -> QRSessionOpenResponse:
    logger.info(
        "[QR-API] open_unit_event_session | user_id=%s | event_id=%s",
        current_user.sub,
        event_id,
    )
    return await QRAttendanceService.open_unit_event_session(
        event_id=event_id,
        actor_id=_to_object_id(current_user.sub),
        request=request_body,
    )


@router.post(
    "/scan",
    response_model=QRScanQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def scan_qr_code(
    request: Request,
    request_body: QRScanRequest,
    current_user: TokenData = Depends(require_user),
) -> QRScanQueuedResponse:
    source_ip = request.client.host if request.client else None
    logger.info("[QR-API] scan_qr_code | user_id=%s", current_user.sub)
    return await QRAttendanceService.submit_scan(
        current_user_id=_to_object_id(current_user.sub),
        request=request_body,
        source_ip=source_ip,
    )


@router.post(
    "/code",
    response_model=QRScanQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("30/minute")
async def submit_attendance_code(
    request: Request,
    request_body: AttendanceCodeRequest,
    current_user: TokenData = Depends(require_user),
) -> QRScanQueuedResponse:
    source_ip = request.client.host if request.client else None
    logger.info("[QR-API] submit_attendance_code | user_id=%s", current_user.sub)
    return await QRAttendanceService.submit_manual_code(
        current_user_id=_to_object_id(current_user.sub),
        request=request_body,
        source_ip=source_ip,
    )
