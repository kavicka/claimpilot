from pathlib import Path

from claimpilot_core.settings import get_settings


def storage_path(relative: str) -> Path:
    return get_settings().storage_dir / relative
