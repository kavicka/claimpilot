"""Write masked page renders for claims extracted before the extract step wrote them.

    uv run claimpilot-mask-backfill

Reads the parsed blocks and the claim's vault entries, writes `m<n>.png` and `mask.json` next to
each document's renders. Erased claims (no vault entries) are skipped. Nothing reaches a model.
"""

import asyncio

from sqlalchemy import select

from claimpilot_core.db.models import Claim, DocBlock, Document
from claimpilot_core.db.session import get_sessionmaker
from claimpilot_core.pii.guard import ClaimRedactor
from claimpilot_core.pii.vault import Vault
from claimpilot_core.settings import get_settings
from claimpilot_worker.ingest.mask import has_personal_data
from claimpilot_worker.ingest.mask_preview import write_masked_renders
from claimpilot_worker.steps.extract import _parsed


async def backfill() -> None:
    settings = get_settings()
    vault = Vault(settings.pii_vault_key.get_secret_value())
    async with get_sessionmaker()() as session:
        claims = (await session.scalars(select(Claim).order_by(Claim.reference))).all()
        for claim in claims:
            entries = await vault.load_entries(session, claim.id)
            if not entries:
                continue
            detect = has_personal_data(ClaimRedactor.from_mapping(entries))
            docs = (
                await session.scalars(select(Document).where(Document.case_id == claim.id))
            ).all()
            for doc in docs:
                rows = (
                    await session.scalars(
                        select(DocBlock)
                        .where(DocBlock.document_id == doc.id)
                        .order_by(DocBlock.seq)
                    )
                ).all()
                if not rows:
                    continue
                try:
                    parsed, _ = _parsed(doc, list(rows))
                except RuntimeError:
                    continue  # not redacted yet; the extract step writes it later
                render_dir = settings.storage_dir / "renders" / str(doc.id)
                report = await asyncio.to_thread(write_masked_renders, render_dir, parsed, detect)
                if report is None:
                    print(f"{claim.reference} {doc.filename}: no renders")
                elif report.refused:
                    print(f"{claim.reference} {doc.filename}: refused ({report.refused})")
                else:
                    print(
                        f"{claim.reference} {doc.filename}: {report.masked_blocks} blocks, "
                        f"{report.unread_lines} unread lines masked"
                    )


def main() -> None:
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
