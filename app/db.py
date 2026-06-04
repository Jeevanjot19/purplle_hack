from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


try:
    engine = create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )

    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
except ModuleNotFoundError as exc:
    # Allows unit tests that mock DB sessions to import routers on hosts where
    # asyncpg is not installed. Docker/API runtime installs requirements.api.txt.
    engine = None
    AsyncSessionLocal = None
    _engine_import_error = exc
else:
    _engine_import_error = None


async def get_db() -> AsyncSession:
    if AsyncSessionLocal is None:
        raise RuntimeError(f"Database driver unavailable: {_engine_import_error}")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
