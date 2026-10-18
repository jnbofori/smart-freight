from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "dev-secret-change-me-in-production"
    database_url: str = "sqlite:///./smart_freight.db"
    access_token_expire_minutes: int = 60 * 24
    cookie_name: str = "access_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Live routing (optional — static GTA table when key missing)
    here_api_key: str = ""
    routing_enabled: bool = True

    @property
    def here_live(self) -> bool:
        return bool(self.routing_enabled and self.here_api_key.strip())


settings = Settings()
