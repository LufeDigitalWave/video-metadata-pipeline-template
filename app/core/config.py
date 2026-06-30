from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://media:CHANGE_ME@localhost:5432/media_pipeline"
    REDIS_URL: str = "redis://localhost:6379"

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "CHANGE_ME"
    MINIO_SECRET_KEY: str = "CHANGE_ME"
    MINIO_BUCKET: str = "media-pipeline"
    MINIO_SECURE: bool = False

    MAX_FILE_SIZE_MB: int = 500

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


settings = Settings()
