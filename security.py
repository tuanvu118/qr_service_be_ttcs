from fastapi import Depends

from exceptions import ErrorCode, app_exception
from internal_auth import get_current_user_from_gateway
from schemas.auth import TokenData


def require_user(
    current_user: TokenData = Depends(get_current_user_from_gateway),
) -> TokenData:
    return current_user


def require_admin_or_manager_global(
    current_user: TokenData = Depends(get_current_user_from_gateway),
) -> TokenData:
    has_role = any(
        "ADMIN" in unit_role.roles or "MANAGER" in unit_role.roles
        for unit_role in current_user.roles
    )
    if not has_role:
        app_exception(ErrorCode.INSUFFICIENT_PERMISSION)
    return current_user
