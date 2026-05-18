from typing import List, Optional

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


class UnitRole(BaseModel):
    unit_id: str
    roles: List[str]


class TokenData(BaseModel):
    sub: str
    email: Optional[str] = None
    is_active: bool = True
    roles: List[UnitRole]
    unit_id: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str
