import asyncio
import logging

from fastapi import APIRouter, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from utils.rate_limiter import limiter

from configs.database import init_db
from configs.rabbitmq import close_rabbitmq
from configs.redis_config import close_redis
from configs.settings import (
    API_PREFIX,
    ENABLE_EMBEDDED_ATTENDANCE_WORKER,
    ENABLE_EMBEDDED_SYNC_WORKER,
)
from middleware.cors import register_cors
from routers.attendance import router as attendance_router
from worker.attendance_worker import run_worker as run_attendance_worker
from worker.sync_worker import run_sync_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


app = FastAPI(
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
    title="QR Attendance Service"
)

# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

register_cors(app)

api_router = APIRouter(prefix=API_PREFIX)
api_router.include_router(attendance_router)

app.include_router(api_router)


@app.on_event("startup")
async def on_startup():
    await init_db()
    if ENABLE_EMBEDDED_SYNC_WORKER:
        asyncio.create_task(run_sync_worker())
    if ENABLE_EMBEDDED_ATTENDANCE_WORKER:
        asyncio.create_task(run_attendance_worker())


@app.on_event("shutdown")
async def on_shutdown():
    await close_rabbitmq()
    await close_redis()


@app.get(f"{API_PREFIX}/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "qr_attendance"}
