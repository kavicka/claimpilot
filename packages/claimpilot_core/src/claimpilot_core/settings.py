"""Runtime settings, read from the environment and `.env`."""

from functools import lru_cache
from pathlib import Path

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
    core_mock_url: str = "http://127.0.0.1:4401"
    erp_url: str = "http://127.0.0.1:4403"

    storage_dir: Path = Field(default_factory=lambda: repo_root() / "data" / "storage")
    config_dir: Path = Field(default_factory=lambda: repo_root() / "config")
    prompts_dir: Path = Field(default_factory=lambda: repo_root() / "prompts")
    cassettes_dir: Path = Field(default_factory=lambda: repo_root() / "evals" / "cassettes")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
