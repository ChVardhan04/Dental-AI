"""Central configuration. Every value can be overridden through environment variables or a .env file."""
from functools import cached_property

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "local-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Application -------------------------------------------------------
    app_env: str = "development"  # development | test | staging | production
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    auto_create_tables: bool = True  # production should run `alembic upgrade head` instead
    seed_reference_data: bool = True  # models registry, knowledge documents, emergency rules

    # --- Database / storage ------------------------------------------------
    database_url: str = "sqlite:///./dentedge.db"
    storage_backend: str = "local"  # local | s3
    upload_dir: str = "./uploads"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_prefix: str = "dentedge"
    # Fernet key (base64, 32 bytes). Encrypts every stored image/audio/report at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    storage_encryption_key: str = ""
    max_upload_mb: int = 12
    max_audio_mb: int = 25

    # --- Security ----------------------------------------------------------
    jwt_secret_key: str = INSECURE_DEFAULT_SECRET
    jwt_access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080"
    rate_limit_per_minute: int = 300
    auth_rate_limit_per_minute: int = 10
    upload_rate_limit_per_minute: int = 20
    redis_url: str = ""  # enables shared rate limiting across API replicas
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    data_retention_days: int = 3650

    # --- AI ----------------------------------------------------------------
    llm_provider: str = "template"  # template | openai | anthropic | local
    llm_model: str = ""
    llm_timeout_seconds: int = 30
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    local_llm_base_url: str = "http://localhost:11434/v1"  # any OpenAI-compatible server (Ollama, vLLM, ...)
    vision_provider: str = "research"  # research | llm | none
    speech_provider: str = "none"  # none | openai | local
    local_speech_base_url: str = ""
    # Which model deployment statuses the orchestrator may run. Research models are clearly labelled.
    allowed_model_statuses: str = "production,staging,research"
    confidence_threshold: float = 0.60
    quality_min_width: int = 320
    quality_min_height: int = 240

    # --- Integrations --------------------------------------------------------
    appointment_booking_url: str = "https://www.dentedge.com/book-appointment"

    @model_validator(mode="after")
    def _production_guards(self):
        if self.app_env == "production":
            problems = []
            if self.jwt_secret_key == INSECURE_DEFAULT_SECRET or len(self.jwt_secret_key) < 32:
                problems.append("JWT_SECRET_KEY must be set to a random value of at least 32 characters")
            if not self.storage_encryption_key:
                problems.append("STORAGE_ENCRYPTION_KEY must be set so files are encrypted at rest")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must point to PostgreSQL in production")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @cached_property
    def model_statuses(self) -> set[str]:
        return {s.strip() for s in self.allowed_model_statuses.split(",") if s.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
