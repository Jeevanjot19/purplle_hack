import time, uuid, logging, structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError as SAOperationalError
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.redis_client import get_redis_pool

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup_begin")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("startup_db_ok")
    except Exception as exc:
        logger.error("startup_db_failed", error=str(exc))
    try:
        import redis.asyncio as aioredis
        pool = await get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        await r.ping()
        logger.info("startup_redis_ok")
    except Exception as exc:
        logger.error("startup_redis_failed", error=str(exc))
    logger.info("startup_complete")
    yield
    await engine.dispose()
    logger.info("shutdown_complete")

app = FastAPI(
    title="Store Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    start = time.perf_counter()
    response: Response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    parts = request.url.path.split("/")
    store_id = None
    if "stores" in parts:
        idx = parts.index("stores")
        if idx + 1 < len(parts):
            store_id = parts[idx + 1]

    logger.info("http_request",
                trace_id=trace_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=latency_ms,
                store_id=store_id)
    response.headers["X-Trace-ID"] = trace_id
    return response

# Import and include routers
from app.routers import health, ingestion, metrics, funnel, heatmap, anomalies, sse, pos

app.include_router(health.router)
app.include_router(ingestion.router)
app.include_router(metrics.router)
app.include_router(funnel.router)
app.include_router(heatmap.router)
app.include_router(anomalies.router)
app.include_router(sse.router)
app.include_router(pos.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
