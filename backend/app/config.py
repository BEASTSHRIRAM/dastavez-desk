from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


def normalize_db_url(url: str) -> str:
    """Accept the URL forms people actually paste (Supabase gives postgresql:// or postgres://) and
    return a SQLAlchemy psycopg3 URL. Supabase requires SSL, so sslmode=require is added when absent."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgresql") and "supabase" in url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'dastavez.db').as_posix()}"
    secret_key: str = "dev-only-secret"
    storage_dir: Path = BACKEND_DIR / "storage"
    token_ttl_seconds: int = 60 * 60 * 12

    seed_demo: bool = True  # fictional demo businesses and logins; set false for a real deployment
    llm_provider: str = "demo"
    llm_api_key: str = ""
    llm_model: str = ""
    stt_provider: str = "demo"
    stt_api_key: str = ""
    groq_api_key: str = ""  # one key serves both LLM_PROVIDER=groq and STT_PROVIDER=groq
    groq_llm_model: str = "llama-3.3-70b-versatile"
    groq_stt_model: str = "whisper-large-v3-turbo"
    soffice_path: str = ""

    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = (".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt", ".csv", ".webm", ".wav", ".mp3", ".m4a")
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    @property
    def db_url(self) -> str:
        return normalize_db_url(self.database_url)

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def is_pooled(self) -> bool:
        """Supabase's transaction pooler (port 6543) cannot use server-side prepared statements."""
        return ":6543" in self.database_url or "pooler.supabase" in self.database_url and ":5432" not in self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
