from pathlib import Path

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

    # Vite dist directory for same-origin UI (Docker/Fly). Empty = auto /app/static.
    static_dir: str = ""

    # Live routing (optional — static GTA table when key missing)
    here_api_key: str = ""
    routing_enabled: bool = True

    # LLM summaries for optimize rationale (optional)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def here_live(self) -> bool:
        return bool(self.routing_enabled and self.here_api_key.strip())

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def resolved_static_dir(self) -> Path | None:
        if self.static_dir.strip():
            path = Path(self.static_dir.strip())
        else:
            path = Path(__file__).resolve().parent.parent / "static"
        if path.is_dir() and (path / "index.html").is_file():
            return path
        return None


settings = Settings()
