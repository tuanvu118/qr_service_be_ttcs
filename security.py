from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from configs.settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    API_PREFIX,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from exceptions import ErrorCode, app_exception
from schemas.auth import TokenData, UnitRole


ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_PREFIX}/auth/login")


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            app_exception(ErrorCode.INVALID_TOKEN)
        roles_payload = payload.get("roles", [])
        roles: List[UnitRole] = [UnitRole(**item) for item in roles_payload]
        token_data = TokenData(
            sub=str(payload.get("sub")),
            email=payload.get("email"),
            is_active=payload.get("is_active", True),
            roles=roles,
        )
    except (JWTError, ValueError, TypeError):
        app_exception(ErrorCode.INVALID_TOKEN)
    return token_data


def _has_role_in_unit(
    current_user: TokenData,
    required_roles: List[str],
    unit_id: str,
) -> bool:
    for unit_role in current_user.roles:
        if unit_role.unit_id == unit_id and any(
            role in unit_role.roles for role in required_roles
        ):
            return True
    return False


def require_admin(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    has_admin_role = any("ADMIN" in unit_role.roles for unit_role in current_user.roles)
    if not has_admin_role:
        app_exception(
            ErrorCode.INSUFFICIENT_PERMISSION,
            extra_detail="ADMIN role required",
        )
    return current_user


def require_manager(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    has_manager_role = any(
        "ADMIN" in unit_role.roles or "MANAGER" in unit_role.roles
        for unit_role in current_user.roles
    )
    if not has_manager_role:
        app_exception(
            ErrorCode.INSUFFICIENT_PERMISSION,
            extra_detail="MANAGER or higher required",
        )
    return current_user


def require_admin_or_manager_global(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    has_role = any(
        "ADMIN" in unit_role.roles or "MANAGER" in unit_role.roles
        for unit_role in current_user.roles
    )
    if not has_role:
        app_exception(
            ErrorCode.INSUFFICIENT_PERMISSION,
            extra_detail="ADMIN or MANAGER role required",
        )
    return current_user


def require_staff(
    current_user: TokenData = Depends(get_current_user),
    x_unit_id: str | None = Header(default=None, alias="X-Unit-Id"),
) -> TokenData:
    if x_unit_id is None:
        app_exception(ErrorCode.HEADER_UNIT_REQUIRED)
    if not _has_role_in_unit(
        current_user, ["ADMIN", "MANAGER", "STAFF"], x_unit_id
    ):
        app_exception(
            ErrorCode.INSUFFICIENT_PERMISSION,
            extra_detail="STAFF or higher required",
        )
    return current_user


def require_user(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    return current_user


def require_global_admin(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    has_admin_role = any("ADMIN" in unit_role.roles for unit_role in current_user.roles)
    if not has_admin_role:
        app_exception(
            ErrorCode.INSUFFICIENT_PERMISSION,
            extra_detail="Global ADMIN role required",
        )
    return current_user
