"""Runtime settings, read from the environment and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Walk up from this file to the directory holding the workspace pyproject."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "config").is_dir() and (parent / "prompts").is_dir():
            return parent
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="CLAIMPILOT_", extra="ignore", env_nested_delimiter="__"
    )

    database_url: str = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot"
    # On AWS the URL carries no password; RDS keeps it in Secrets Manager and ECS hands it over in
    # this variable. It is put into the URL once, here.
    database_password: SecretStr = SecretStr("")
    redis_url: str = "redis://127.0.0.1:6389/0"
    ollama_url: str = "http://127.0.0.1:11434"
    # Which model map to load from config/: providers.yaml (local Ollama) or providers.cloud.yaml
    # (Claude on Bedrock). The cloud deployment sets CLAIMPILOT_PROVIDERS_FILE.
    providers_file: str = "providers.yaml"
    aws_region: str = "eu-central-1"
    api_url: str = "http://127.0.0.1:4400"
    intake_token: str = ""
    # dev: demo users and a random session secret are allowed. production: the api and the worker
    # refuse to start with a missing secret, a default database password or a demo password
    # (check_production).
    environment: Literal["dev", "production"] = "dev"
    # Signs the login cookie. Empty in dev means a random key per process (sessions end on restart).
    session_secret: SecretStr = SecretStr("")
    # Creates the demo users handler.demo and senior.demo on startup. Dev only.
    demo_password: SecretStr = SecretStr("")
    # Behind a load balancer the client address is the last X-Forwarded-For entry the balancer
    # appended; off, the address of the TCP peer is used.
    trust_forwarded_for: bool = False
    core_mock_url: str = "http://127.0.0.1:4401"
    erp_url: str = "http://127.0.0.1:4403"
    # Bearer token for every call to the ERP (the ERP checks it when it has one configured).
    erp_token: SecretStr = SecretStr("")
    # mlx_lm.server with the base model of the invoice adapters (ADR-014), `make mlx-serve`.
    mlx_url: str = "http://127.0.0.1:4430"

    storage_dir: Path = Field(default_factory=lambda: repo_root() / "data" / "storage")
    config_dir: Path = Field(default_factory=lambda: repo_root() / "config")
    prompts_dir: Path = Field(default_factory=lambda: repo_root() / "prompts")
    cassettes_dir: Path = Field(default_factory=lambda: repo_root() / "evals" / "cassettes")
    adapters_dir: Path = Field(default_factory=lambda: repo_root() / "models" / "adapters")

    # Fernet key for the PII vault. Generate with `make vault-key`.
    pii_vault_key: SecretStr = SecretStr("")

    # record: call the model and write a cassette; replay: read cassettes only, fail if
    # missing; off: call the model, write nothing.
    llm_cassette_mode: str = "off"

    # Finished claims older than this are erased by the worker's daily purge job.
    retention_days: int = 3650
    # OCR for scans and photos: "docling" (RapidOCR or Apple Vision, inside the worker) or
    # "textract" (Amazon Textract; only with the AWS AI services opt-out policy, docs/deploy.md).
    ocr_engine: str = "docling"
    # Scans and photos: "vision" reads page images with the local vision model (critical fields
    # 97.6 % vs 81.1 % through OCR text on the dev scans, 2026-10-09); "text" uses the OCR text.
    scan_path: str = "vision"

    # OTLP/HTTP endpoint of the ADOT sidecar in AWS (http://127.0.0.1:4318); Langfuse wins when
    # both are set. Spans carry no prompt text (claimpilot_core.otel).
    otel_endpoint: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _password_into_url(self) -> "Settings":
        password = self.database_password.get_secret_value()
        if password:
            from sqlalchemy.engine import make_url

            url = make_url(self.database_url).set(password=password)
            self.database_url = url.render_as_string(hide_password=False)
        return self


DEFAULT_DATABASE_PASSWORD = "claimpilot"  # noqa: S105 - the dev default we refuse in production


class InsecureConfigError(RuntimeError):
    """The settings are not fit for production; the process must not start."""


def check_production(settings: Settings, role: str = "api") -> None:
    """Refuse to start in production with dev leftovers. `role` is "api" or "worker": the worker
    holds no login or intake secrets (docs/deploy.md), so it is not asked for them."""
    if settings.environment != "production":
        return
    from sqlalchemy.engine import make_url

    problems = []
    if settings.demo_password.get_secret_value():
        problems.append("CLAIMPILOT_DEMO_PASSWORD is set; production has no demo users")
    if not settings.pii_vault_key.get_secret_value():
        problems.append("CLAIMPILOT_PII_VAULT_KEY is empty")
    db_password = make_url(settings.database_url).password
    if not db_password or db_password == DEFAULT_DATABASE_PASSWORD:
        problems.append("the database password is empty or the development default")
    if role == "api":
        if not settings.session_secret.get_secret_value():
            problems.append("CLAIMPILOT_SESSION_SECRET is empty")
        if not settings.intake_token:
            problems.append("CLAIMPILOT_INTAKE_TOKEN is empty")
    if problems:
        raise InsecureConfigError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
