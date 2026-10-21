from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'dastavez.db').as_posix()}"
    secret_key: str = "dev-only-secret"
    storage_dir: Path = BACKEND_DIR / "storage"
    token_ttl_seconds: int = 60 * 60 * 12

    llm_provider: str = "demo"
    llm_api_key: str = ""
    llm_model: str = ""
    stt_provider: str = "demo"
    stt_api_key: str = ""
    soffice_path: str = ""

    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = (".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt", ".csv", ".webm", ".wav", ".mp3", ".m4a")
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
