"""Settings loaded from environment variables."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Medidor de Espectaculares - KYC Platform"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 2

    # Postgres - set DATABASE_URL env var in production
    database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Security
    secret_key: str = "change-me-in-production-32-chars-min!"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # CORS
    cors_origins: list[str] = ["*"]

    # KYC config
    kyc_min_age: int = 18
    kyc_max_age: int = 75
    kyc_required_docs: list[str] = ["ine", "curp", "proof_of_address", "selfie"]

    # Biometric thresholds
    biometric_min_face_quality: float = 0.65
    biometric_liveness_required: bool = True
    biometric_match_threshold: float = 0.85

    # ML Risk thresholds
    risk_auto_approve_min: float = 0.85
    risk_auto_reject_max: float = 0.30
    risk_review_between: bool = True

    # Redis - set REDIS_URL env var in production
    redis_url: str = ""

    # External APIs
    curp_api_url: str = ""
    sat_api_url: str = ""
    bureau_api_url: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
