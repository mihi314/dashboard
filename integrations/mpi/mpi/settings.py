from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MPI_", env_file=".env")

    # Ingest API of the dashboard, e.g. https://example.com:4443/ingest/climate
    INGEST_URL: str
    INGEST_TOKEN: str

    # Bluetooth MAC address -> device name used in the dashboard, e.g. {"AA:BB:CC:DD:EE:FF": "living_room"}
    DEVICES: dict[str, str]

    # How long to listen for advertisements per run (the sensors advertise every few seconds)
    SCAN_SECONDS: float = 30
    INTERVAL_MINUTES: int = 5
    HTTP_TIMEOUT_SECONDS: float = 10


settings = Settings()  # pyright: ignore
