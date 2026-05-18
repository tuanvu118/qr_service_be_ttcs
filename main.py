from fastapi import APIRouter, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from utils.rate_limiter import limiter

from configs.database import init_db
from configs.rabbitmq import close_rabbitmq
from configs.redis_config import close_redis
from configs.settings import API_PREFIX
from middleware.cors import register_cors



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

app.include_router(api_router)


@app.on_event("startup")
async def on_startup():
    await init_db()


@app.on_event("shutdown")
async def on_shutdown():
    await close_rabbitmq()
    await close_redis()


@app.get(f"{API_PREFIX}/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "qr_attendance"}
