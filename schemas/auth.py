from typing import List

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
    email: str
    is_active: bool
    roles: List[UnitRole]


class RefreshTokenRequest(BaseModel):
    refresh_token: str
