"""
Shared SlowAPI Limiter instance.
Import từ file này thay vì import từ main để tránh circular import.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
