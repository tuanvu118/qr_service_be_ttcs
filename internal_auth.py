from fastapi import Header
from typing import Optional
import json
from schemas.auth import TokenData, UnitRole

def get_current_user_from_gateway(
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    x_user_roles_json: Optional[str] = Header(None, alias="X-User-Roles"),
    x_unit_id: Optional[str] = Header(None, alias="X-Unit-Id"),
) -> TokenData:
    roles = []
    if x_user_roles_json:
        try:
            raw = json.loads(x_user_roles_json)
            roles = [UnitRole(**item) for item in raw]
        except json.JSONDecodeError:
            pass
    return TokenData(sub=x_user_id, email=x_user_email, roles=roles, unit_id=x_unit_id)
