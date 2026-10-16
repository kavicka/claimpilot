"""Handler corrections as training data (ADR-014), against the compose Postgres: the corrected
value is the answer, the prompt is the redacted text, and nothing personal gets in."""

import json
import uuid

import pytest

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    Correction,
    DocBlock,
    DocCell,
    Document,
    ExtractedField,
    Invoice,
    User,
)
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"
BOX = {"x0": 0.1, "y0": 0.5, "x1": 0.4, "y1": 0.52}  # the item table
TOP = {"x0": 0.1, "y0": 0.1, "x1": 0.6, "y1": 0.12}  # the header, above it


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


async def corrected_invoice(status: str) -> str:
    number = f"FT{uuid.uuid4().hex[:8]}"
    async with db_session.session_scope() as s:
        user = User(
            username=f"h-{uuid.uuid4().hex[:6]}", display_name="Handler", role="handler",
            password_hash="x",  # never logs in
        )  # fmt: skip
        inv = Invoice(reference=f"T-{uuid.uuid4().hex[:8]}", status=status, doc_kind="invoice")
        s.add_all([user, inv])
        await s.flush()
        doc = Document(
            case_id=inv.id, filename="f.pdf", mime_type="application/pdf", sha256="c" * 64,
            storage_path="x", doc_type="invoice", page_count=1,
        )  # fmt: skip
        s.add(doc)
        await s.flush()
        header = f"Faktúra č. {number} | Vystavil: Belo Kríž"
        s.add(
            DocBlock(
                document_id=doc.id, page=1, seq=0, kind="text", text=header,
                text_redacted=f"Faktúra č. {number} | Vystavil: <PERSON_1>", bbox=TOP,
            )
        )  # fmt: skip
        for col, (head, text) in enumerate([("popis", "Šampón 200 ml"), ("Spolu", "5,41")]):
            s.add(
                DocCell(
                    document_id=doc.id, page=1, tbl=0, item=0, line=0, col=col, header=head,
                    text=text, text_redacted=text, bbox=BOX,
                )
            )  # fmt: skip
        fields = {
            "invoice_number": number,
            "supplier_name": "Belo Kríž",  # a handler typed a person's name in: never trained on
            "lines[1].name": "Šampón 200 ml",
            "lines[1].line_net": "5,41",
        }
        rows = {}
        for name, value in fields.items():
            rows[name] = ExtractedField(
                case_id=inv.id, document_id=doc.id, field=name, value_raw=value,
                value_norm=value, page=1, method="llm_text",
            )  # fmt: skip
            s.add(rows[name])
        await s.flush()
        s.add(
            Correction(
                field_id=rows["lines[1].line_net"].id,
                old_value="5,14",
                new_value="5,41",
                user_id=user.id,
            )
        )
    return number


async def test_a_corrected_approved_invoice_trains_on_its_corrected_values():
    from claimpilot_evals.finetune import corrections_examples

    number = await corrected_invoice("APPROVED")
    pending = await corrected_invoice("IN_REVIEW")
    examples = [json.dumps(e["messages"], ensure_ascii=False) for e in corrections_examples_of(
        await corrections_examples(), number
    )]  # fmt: skip
    assert len(examples) == 2  # the header call and one chunk of lines
    header, lines = (json.loads(e) for e in examples)
    answer = json.loads(header[-1]["content"])
    assert answer["invoice_number"]["value"] == number
    assert answer["supplier_name"]["value"] is None  # not on the page as typed
    assert {"field": "line_net", "value": "5,41"} in json.loads(lines[-1]["content"])["items"][0][
        "values"
    ]
    everything = json.dumps(await corrections_examples(), ensure_ascii=False)
    assert "Kríž" not in everything
    assert pending not in everything  # not approved: not trained on


def corrections_examples_of(examples: list[dict], number: str) -> list[dict]:
    """The examples of one invoice: its header call names the number, its line call follows."""
    for i, e in enumerate(examples):
        if number in e["messages"][-1]["content"]:
            return examples[i : i + 2]
    return []
