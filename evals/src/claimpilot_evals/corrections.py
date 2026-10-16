"""Export handler corrections as a growing third dataset next to dev and test.

    uv run claimpilot-eval export-corrections

Each line: claim reference, scenario id (synthetic claims), document type, field, the value the
pipeline produced and the handler's value. Personal data stays tokenized where the vault had it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from claimpilot_core.db.models import Claim, Correction, Document, ExtractedField
from claimpilot_core.db.session import session_scope
from claimpilot_core.settings import repo_root


async def export(target_dir: Path | None = None) -> Path:
    target_dir = target_dir or repo_root() / "data" / "corrections"
    target_dir.mkdir(parents=True, exist_ok=True)
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Correction, ExtractedField, Document, Claim)
                .join(ExtractedField, Correction.field_id == ExtractedField.id)
                .join(Document, ExtractedField.document_id == Document.id)
                .join(Claim, ExtractedField.case_id == Claim.id)
                .order_by(Correction.id)
            )
        ).all()
    path = target_dir / f"corrections-{datetime.now(UTC):%Y%m%d}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for corr, field, doc, claim in rows:
            fh.write(
                json.dumps(
                    {
                        "claim": claim.reference,
                        "scenario_id": claim.scenario_id,
                        "document_type": doc.doc_type,
                        "field": field.field,
                        "pipeline_value": corr.old_value,
                        "handler_value": corr.new_value,
                        "model": field.model,
                        "prompt_version": field.prompt_version,
                        "corrected_at": corr.created_at.isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path
