from typing import Literal, Optional
from pydantic import AliasChoices, Field, FilePath
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres
    DASH_PGHOST: str = "localhost"
    DASH_PGPORT: int = 5432
    DASH_PGDATABASE: str = "dashboard"
    DASH_PGUSER: str = "dashboard"
    DASH_PGPASSWORD: str

    # Tells sqlalchemy to log all sql statements
    ECHO_SQL: bool = Field(False, validation_alias=AliasChoices("ECHO_SQL", "LOG_SQL"))

    # Enable request caching (in some cases) for development
    CACHE_REQUESTS: bool = False

    AGSI_API_KEY: str
    WORKFLOWY_SESSION_ID: str

    # Bearer token required by the ingest API
    DASH_INGEST_TOKEN: str


settings = Settings()  # pyright: ignore
