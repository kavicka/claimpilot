"""Runtime settings, read from the environment and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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
    redis_url: str = "redis://127.0.0.1:6389/0"
    ollama_url: str = "http://127.0.0.1:11434"
    api_url: str = "http://127.0.0.1:4400"
    core_mock_url: str = "http://127.0.0.1:4401"

    storage_dir: Path = Field(default_factory=lambda: repo_root() / "data" / "storage")
    config_dir: Path = Field(default_factory=lambda: repo_root() / "config")
    prompts_dir: Path = Field(default_factory=lambda: repo_root() / "prompts")
    cassettes_dir: Path = Field(default_factory=lambda: repo_root() / "evals" / "cassettes")

    # Fernet key for the PII vault. Generate with `make vault-key`.
    pii_vault_key: SecretStr = SecretStr("")

    # record: call the model and write a cassette; replay: read cassettes only, fail if
    # missing; off: call the model, write nothing.
    llm_cassette_mode: str = "off"

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
