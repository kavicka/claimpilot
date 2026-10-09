"""PII tokens and re-hydration, without the detection stack (the api imports only this)."""

import re

TOKEN_PREFIX = {
    "PERSON": "PERSON",
    "BIRTH_NUMBER": "RC",
    "IBAN": "IBAN",
    "PHONE": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "ADDRESS": "ADDRESS",
    "ID_CARD": "ID",
    "LICENCE_PLATE": "PLATE",
}
ENTITY_FOR_PREFIX = {v: k for k, v in TOKEN_PREFIX.items()}
TOKEN_RE = re.compile(r"<(PERSON|RC|IBAN|PHONE|EMAIL|ADDRESS|ID|PLATE)_\d+>")


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    return TOKEN_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def next_token(entity: str, existing: list[str]) -> str:
    prefix = TOKEN_PREFIX[entity]
    used = [int(t[len(prefix) + 2 : -1]) for t in existing if t.startswith(f"<{prefix}_")]
    return f"<{prefix}_{max(used, default=0) + 1}>"
