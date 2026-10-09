from pathlib import Path

import pytest

from claimpilot_core.settings import Settings

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointing at the real config and prompts but a throwaway cassette and storage dir."""
    return Settings(
        config_dir=REPO / "config",
        prompts_dir=REPO / "prompts",
        cassettes_dir=tmp_path / "cassettes",
        storage_dir=tmp_path / "storage",
        ollama_url="http://ollama.test",
    )


@pytest.fixture(autouse=True)
def _no_tracing(monkeypatch):
    """Unit tests never export traces, whatever .env says."""
    from claimpilot_core.observability import get_tracer
    from claimpilot_core.settings import get_settings

    monkeypatch.setenv("CLAIMPILOT_LANGFUSE_HOST", "")
    get_settings.cache_clear()
    get_tracer.cache_clear()
    yield
    get_settings.cache_clear()
    get_tracer.cache_clear()
