from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: PostgresDsn

    # Price anomaly thresholds — listings outside this range are flagged
    # but still written to veld_2026_transformed with price_is_anomaly=True.
    price_min: float = 5.0
    price_max: float = 5000.0

    # DB write batch sizes
    stage1_batch_size: int = 100
    stage2_batch_size: int = 100


settings = Settings()
