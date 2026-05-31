from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://store:store123@db:5432/storedb"
    redis_url: str = "redis://cache:6379"
    log_level: str = "INFO"
    max_batch_size: int = 500
    stale_feed_threshold_seconds: int = 600

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
