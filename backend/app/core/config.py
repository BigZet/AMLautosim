from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://aml:aml@localhost:5432/aml_simulator"
    api_base_url: str = "http://localhost:8000"
    secret_key: str = "change-me-for-production"
    access_token_expire_minutes: int = 240

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

