"""Invoice steps against the compose Postgres: ingest, redaction and extraction of a rendered
synthetic invoice, with a fake model. Run with `make test-db`."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Case, DocCell, Document, ExtractedField, Invoice, VaultEntry
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.schemas.invoices import CellValue, InvoiceHeader, InvoiceLines, ItemValues
from claimpilot_core.settings import get_settings
from claimpilot_worker import pipeline
from claimpilot_worker.extraction.schema import grounded_schema

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


class FakeGateway:
    """Answers the header with the invoice number and the lines with each item's line total,
    copied from the item cells it was given."""

    def __init__(self) -> None:
        self.payloads: list[str] = []
        self.number = f"INV-{uuid.uuid4().hex[:8]}"  # unique per run: the test db keeps rows

    async def generate_json(self, step, prompt_id, output, variables, **kw):
        self.payloads.append(str(variables))
        spec = SimpleNamespace(key=f"fake:{step}")
        if output is InvoiceLines:
            items = []
            for block in variables["items"].split("\n#")[0:]:
                head, *rest = block.lstrip("#").split("\n")
                n = int(head)
                total = None
                for line in rest:
                    for part in line.split(" | "):
                        if part.strip().startswith("[Spolu bez DPH]"):
                            total = part.split("]", 1)[1].strip()
                values = [CellValue(field="line_net", value=total)] if total else []
                items.append(ItemValues(item=n, values=values))
            value = InvoiceLines(items=items)
        else:
            model = grounded_schema(InvoiceHeader)
            value = model.model_validate(
                {
                    name: (
                        []
                        if name in ("recap", "fees")
                        else {"value": None, "quote": None, "page": None}
                    )
                    for name in InvoiceHeader.model_fields
                }
                | {"invoice_number": {"value": self.number, "quote": None, "page": 1}}
                | {"supplier_ico": {"value": "98391267", "quote": None, "page": 1}}
            )
        return SimpleNamespace(value=value, prompt_tag=f"{prompt_id}@1+abc", spec=spec, attempts=1)


@pytest.fixture(autouse=True)
def test_database(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    monkeypatch.setenv("CLAIMPILOT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    import claimpilot_worker.steps  # noqa: F401  registers the steps

    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


@pytest.fixture(scope="module")
def wholesale_pdf():
    from claimpilot_datagen.invoices.model import Layout
    from claimpilot_datagen.invoices.render import render
    from claimpilot_datagen.invoices.sampler import build_invoice_set

    iset = build_invoice_set(42)
    inv = next(
        i
        for i in iset.invoices
        if i.split == "dev" and i.layout is Layout.WHOLESALE and not i.edge_cases
    )
    data, _ext, v = render(inv, 42)
    return data, v


async def new_invoice(data: bytes, tmp_path) -> uuid.UUID:
    rel = f"invoices/{uuid.uuid4().hex}/invoice.pdf"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(data)
    async with db_session.session_scope() as s:
        inv = Invoice(reference=f"F-{uuid.uuid4().hex[:10]}", status=S.RECEIVED.value)
        s.add(inv)
        await s.flush()
        s.add(
            Document(
                case_id=inv.id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_path=rel,
            )
        )
        return inv.id


async def test_an_invoice_goes_from_received_to_validated(wholesale_pdf, tmp_path):
    data, v = wholesale_pdf
    iid = await new_invoice(data, tmp_path)
    gateway = FakeGateway()
    ctx = {"job_try": 1, "settings": get_settings(), "gateway": gateway}
    assert await pipeline.advance(ctx, str(iid)) == "PARSED"
    assert await pipeline.advance(ctx, str(iid)) == "REDACTED"
    assert await pipeline.advance(ctx, str(iid)) == "EXTRACTED"

    expected = [ln["cells"]["line_net"]["printed"] for ln in v["lines"]]
    async with db_session.session_scope() as s:
        doc = (await s.scalars(select(Document).where(Document.case_id == iid))).one()
        assert doc.doc_type == "invoice"
        cells = (await s.scalars(select(DocCell).where(DocCell.document_id == doc.id))).all()
        assert cells and all(c.text_redacted is not None for c in cells)
        vault = (await s.scalars(select(VaultEntry).where(VaultEntry.case_id == iid))).all()
        assert {e.entity_type for e in vault} <= {"PERSON", "EMAIL_ADDRESS", "PHONE"}
        fields = {
            f.field: f
            for f in (
                await s.scalars(select(ExtractedField).where(ExtractedField.case_id == iid))
            ).all()
        }
    assert fields["invoice_number"].value_raw == gateway.number
    got = [fields[f"lines[{n}].line_net"] for n in range(1, len(expected) + 1)]
    assert [f.value_raw for f in got] == expected
    assert all(f.grounded and f.bbox for f in got), "each line value is grounded to its cell"
    # The supplier's contact person is in the vault, never in a model payload.
    contact = v["inv"].supplier.contact
    assert not any(contact in p for p in gateway.payloads)

    assert await pipeline.advance(ctx, str(iid)) == "VALIDATED"
    async with db_session.session_scope() as s:
        inv = await s.get(Invoice, iid)
        assert (inv.invoice_number, inv.supplier_ico, inv.doc_kind) == (
            gateway.number,
            "98391267",
            "invoice",
        )
        names = {c["name"] for c in inv.validation}
        assert "duplicate" not in names
        row = (
            await s.scalars(
                select(ExtractedField).where(
                    ExtractedField.case_id == iid, ExtractedField.field == "lines[1].line_net"
                )
            )
        ).one()
        assert "line_math" in row.checks  # the check is written onto the field it concerns

    # The same supplier and number again: validation marks it, it still reaches review.
    second = await new_invoice(data, tmp_path)
    for expected in ("PARSED", "REDACTED", "EXTRACTED", "VALIDATED"):
        assert await pipeline.advance(ctx, str(second)) == expected
    async with db_session.session_scope() as s:
        dup = next(c for c in (await s.get(Invoice, second)).validation if c["name"] == "duplicate")
        assert not dup["ok"]


class GtGateway:
    """A perfect extraction: answers with the ground truth of the invoice."""

    def __init__(self, gt: dict) -> None:
        self.gt = gt

    async def generate_json(self, step, prompt_id, output, variables, **kw):
        spec = SimpleNamespace(key=f"gt:{step}")
        if output is InvoiceLines:
            present = [ln for ln in self.gt["lines"] if ln["page"] is not None]
            asked = [int(x.split("\n")[0]) for x in variables["items"].split("#")[1:]]
            items = []
            for n in asked:
                cells = present[n - 1]["cells"]
                values = [CellValue(field=k, value=v["printed"]) for k, v in cells.items()]
                items.append(ItemValues(item=n, values=values))
            value = InvoiceLines(items=items)
        else:
            empty = {"value": None, "quote": None, "page": None}
            data = {k: [] if k in ("recap", "fees") else empty for k in InvoiceHeader.model_fields}
            for k, v in self.gt["header"].items():
                if k in InvoiceHeader.model_fields and v.get("page"):
                    data[k] = {"value": v["printed"], "quote": v["printed"], "page": v["page"]}
            data["recap"] = [
                {**{k: r[k]["printed"] for k in ("rate", "base", "vat")}, "quote": None, "page": 1}
                for r in self.gt["recap"]
                if r.get("page")
            ]
            value = grounded_schema(InvoiceHeader).model_validate(data)
        return SimpleNamespace(value=value, prompt_tag=f"{prompt_id}@1+gt", spec=spec, attempts=1)


async def test_a_planted_price_difference_is_found_on_its_line(tmp_path, monkeypatch):
    import json

    import httpx

    from claimpilot_core.settings import repo_root
    from claimpilot_core_mock import erp

    root = repo_root() / "data" / "synthetic" / "invoices"
    monkeypatch.setenv("ERP_MOCK_DATA", str(root))
    erp.records.cache_clear()
    gt = None
    for path in sorted((root / "dev").glob("*/ground_truth.json")):
        data = json.loads(path.read_text("utf-8"))
        kinds = {f["kind"] for f in data["findings"]}
        if kinds == {"price_diff"} and data["layout"] != "scan_en" and data["kind"] == "invoice":
            gt = data
            break
    assert gt is not None
    from claimpilot_datagen.invoices.render import render
    from claimpilot_datagen.invoices.sampler import build_invoice_set

    inv = next(i for i in build_invoice_set(42).invoices if i.invoice_id == gt["invoice_id"])
    data, _ext, _v = render(inv, 42)
    # The test db keeps rows: an earlier run's copy of this invoice would read as a duplicate.
    async with db_session.session_scope() as s:
        number = gt["header"]["invoice_number"]["value"]
        await s.execute(
            delete(Case).where(
                Case.id.in_(select(Invoice.id).where(Invoice.invoice_number == number))
            )
        )
    iid = await new_invoice(data, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=erp.app), base_url="http://erp"
    ) as client:
        ctx = {
            "job_try": 1,
            "settings": get_settings(),
            "gateway": GtGateway(gt),
            "erp_client": client,
        }
        for expected in ("PARSED", "REDACTED", "EXTRACTED", "VALIDATED", "MATCHED", "ROUTED"):
            assert await pipeline.advance(ctx, str(iid)) == expected
        assert await pipeline.advance(ctx, str(iid)) == "IN_REVIEW"
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        failed = [c["name"] for c in invoice.validation if not c["ok"]]
        assert failed == [], failed  # a perfect extraction of a correct invoice passes validation
        planted = next(f for f in gt["findings"] if f["kind"] == "price_diff")
        got = [(f["kind"], f["line"]) for f in invoice.matching["findings"]]
        assert got == [("price_diff", planted["line"])]
        assert invoice.queue == "standard"
        assert [h["rule"] for h in invoice.routing] == ["I7"]
        invoice.status = "APPROVED"  # what the handler's approval does (api)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=erp.app), base_url="http://erp"
    ) as client:
        ctx = {
            "job_try": 1,
            "settings": get_settings(),
            "gateway": GtGateway(gt),
            "erp_client": client,
        }
        assert await pipeline.advance(ctx, str(iid)) == "EXPORTED"
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        assert invoice.erp_id and invoice.export["errors"] == []
        assert (tmp_path / "invoices" / str(iid) / "export.xml").exists()
    erp.records.cache_clear()
