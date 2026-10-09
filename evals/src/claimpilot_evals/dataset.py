"""The synthetic dataset as the evals see it: claims, documents and ground truth per split."""

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from claimpilot_core.settings import repo_root


@dataclass
class GtDoc:
    claim_id: str
    data: dict
    path: Path

    @property
    def doc_id(self) -> str:
        return self.data["doc_id"]

    @property
    def item_id(self) -> str:
        return f"{self.claim_id}/{self.doc_id}"

    @property
    def doc_type(self) -> str:
        return self.data["doc_type"]


@dataclass
class GtClaim:
    data: dict
    folder: Path

    @property
    def claim_id(self) -> str:
        return self.data["scenario_id"]

    @cached_property
    def docs(self) -> list[GtDoc]:
        return [GtDoc(self.claim_id, d, self.folder / d["file"]) for d in self.data["documents"]]

    def pii_values(self) -> list[tuple[str, str]]:
        """(entity type, value) for every PII value printed anywhere in this claim, deduplicated."""
        seen = {(p["type"], p["value"]) for d in self.data["documents"] for p in d["pii"]}
        return sorted(seen)


class Dataset:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or repo_root() / "data" / "synthetic"

    def manifest(self, split: str) -> dict:
        return json.loads((self.root / f"manifest-{split}.json").read_text("utf-8"))

    def claims(self, split: str, limit: int | None = None) -> list[GtClaim]:
        rows = self.manifest(split)["claims"]
        if limit:
            rows = rows[:limit]
        out = []
        for row in rows:
            folder = self.root / "claims" / row["scenario_id"]
            out.append(
                GtClaim(json.loads((folder / "ground_truth.json").read_text("utf-8")), folder)
            )
        return out

    def version(self, split: str) -> str:
        import hashlib

        raw = (self.root / f"manifest-{split}.json").read_bytes()
        return hashlib.sha256(raw).hexdigest()[:12]
