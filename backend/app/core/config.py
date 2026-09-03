"""
Pydantic Settings — single source of app configuration, read from environment variables.
Never hardcode a secret, endpoint, or credential outside this module.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str
    database_url_sync: str
    # See ADR-011: `database_url`/`database_url_sync` above are the migration/admin connection
    # (used only by alembic/env.py, which needs DDL rights). The running application NEVER
    # connects with those credentials - db/session.py builds its engine from this instead, using
    # the least-privilege procureiq_app role that migration 0004 creates.
    database_url_app: str

    redis_url: str = "redis://localhost:6379/0"

    secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    jwt_algorithm: str = "HS256"

    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "procureiq-uploads"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""

    llm_provider: str = "anthropic"
    llm_api_key: str = ""

    frontend_url: str = "http://localhost:3000"

    branding_app_name: str = "ProcureIQ"

    # D-01 demo hardening: both default True - production behaviour is unchanged unless a
    # deployment deliberately sets either to false. Neither is tied to `environment`/
    # `is_production` implicitly - explicit opt-out per deployment, not inferred.
    allow_self_registration: bool = True
    enable_api_docs: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
