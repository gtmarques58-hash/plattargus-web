from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str

    API_KEY: str | None = None
    CACHE_TTL_SECONDS: int = 43200

    STREAM_HI: str = "detalhar:hi"
    STREAM_LO: str = "detalhar:lo"
    CONSUMER_GROUP: str = "detalhar-workers"
    CONSUMER_NAME: str = "worker-1"

    LOCK_MINUTES: int = 25

    # ========== Pipeline ARGUS ==========
    USAR_LLM: bool = False  # False = só determinístico (rápido, sem custo)
    ARGUS_API_KEY: str | None = None  # API key para LLM (Anthropic ou OpenAI)

settings = Settings()
