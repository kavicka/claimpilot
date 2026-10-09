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
