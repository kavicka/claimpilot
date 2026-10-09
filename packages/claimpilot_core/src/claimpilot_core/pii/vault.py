"""Encrypted store for the values behind PII tokens (schema `pii`, table `vault`).

Only two code paths read it: the api (to show the handler real values) and the submission step
(to send real values to the core system). Nothing that calls a model imports this module.
"""

import uuid

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import VaultEntry
from claimpilot_core.logging import register_secret
from claimpilot_core.pii.tokens import next_token


class VaultKeyMissingError(RuntimeError):
    pass


class Vault:
    def __init__(self, key: str) -> None:
        if not key:
            raise VaultKeyMissingError("CLAIMPILOT_PII_VAULT_KEY is empty; run `make vault-key`")
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, blob: bytes) -> str:
        return self._fernet.decrypt(blob).decode("utf-8")

    async def store(
        self, session: AsyncSession, claim_id: uuid.UUID, mapping: dict[str, tuple[str, str]]
    ) -> None:
        await session.execute(delete(VaultEntry).where(VaultEntry.claim_id == claim_id))
        for token, (entity, value) in mapping.items():
            session.add(
                VaultEntry(
                    claim_id=claim_id,
                    token=token,
                    entity_type=entity,
                    value_encrypted=self.encrypt(value),
                )
            )

    async def add(self, session: AsyncSession, claim_id: uuid.UUID, entity: str, value: str) -> str:
        """A value the handler typed that the vault does not hold yet: give it the next token."""
        existing = (
            await session.scalars(select(VaultEntry.token).where(VaultEntry.claim_id == claim_id))
        ).all()
        token = next_token(entity, list(existing))
        session.add(
            VaultEntry(
                claim_id=claim_id,
                token=token,
                entity_type=entity,
                value_encrypted=self.encrypt(value),
            )
        )
        return token

    async def load(self, session: AsyncSession, claim_id: uuid.UUID) -> dict[str, str]:
        return {t: v for t, (_, v) in (await self.load_entries(session, claim_id)).items()}

    async def load_entries(
        self, session: AsyncSession, claim_id: uuid.UUID
    ) -> dict[str, tuple[str, str]]:
        """token -> (entity type, value)."""
        rows = await session.scalars(select(VaultEntry).where(VaultEntry.claim_id == claim_id))
        out = {}
        for row in rows:
            value = self.decrypt(row.value_encrypted)
            register_secret(value)
            out[row.token] = (row.entity_type, value)
        return out
