"""Versioned prompt files.

A prompt lives in `prompts/<step>/<name>.md`: YAML front-matter with a `version`, then a
`## system` section and a `## user` section rendered with Jinja2. The hash of the whole file is
logged on every call, so a report always says which exact prompt produced a number.
"""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from claimpilot_core.llm.types import ChatMessage
from claimpilot_core.settings import get_settings

_ENV = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)  # noqa: S701


class PromptFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    version: str
    sha: str
    system: str
    user: str
    meta: dict[str, Any]

    @property
    def tag(self) -> str:
        """`<id>@<version>+<short hash>`: what goes into extracted_fields.prompt_version."""
        return f"{self.prompt_id}@{self.version}+{self.sha[:8]}"

    def render(self, **variables: Any) -> list[ChatMessage]:
        messages = []
        if self.system:
            messages.append(
                ChatMessage(
                    role="system", content=_ENV.from_string(self.system).render(**variables)
                )
            )
        messages.append(
            ChatMessage(role="user", content=_ENV.from_string(self.user).render(**variables))
        )
        return messages


def parse_prompt(prompt_id: str, raw: str) -> Prompt:
    if not raw.startswith("---\n"):
        raise PromptFormatError(f"{prompt_id}: missing front-matter")
    _, front, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    if "version" not in meta:
        raise PromptFormatError(f"{prompt_id}: front-matter needs a version")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.strip().lower() in ("## system", "## user"):
            current = line.strip()[3:].lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    if "user" not in sections:
        raise PromptFormatError(f"{prompt_id}: needs a '## user' section")
    return Prompt(
        prompt_id=prompt_id,
        version=str(meta["version"]),
        sha=hashlib.sha256(raw.encode()).hexdigest(),
        system="\n".join(sections.get("system", [])).strip(),
        user="\n".join(sections["user"]).strip(),
        meta=meta,
    )


@lru_cache(maxsize=256)
def _load(path: Path, mtime: float) -> Prompt:
    prompt_id = f"{path.parent.name}/{path.stem}"
    return parse_prompt(prompt_id, path.read_text(encoding="utf-8"))


def load_prompt(prompt_id: str, prompts_dir: Path | None = None) -> Prompt:
    """Load `prompts/<step>/<name>.md` by id `<step>/<name>`."""
    path = (prompts_dir or get_settings().prompts_dir) / f"{prompt_id}.md"
    return _load(path, path.stat().st_mtime)
