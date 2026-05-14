from typing import TypeVar, Generic, Optional
from pydantic import BaseModel

T = TypeVar("T")

class BaseResponse(BaseModel, Generic[T]):
    message: str = ""
    status: str = "success"
    data: Optional[T] = None
