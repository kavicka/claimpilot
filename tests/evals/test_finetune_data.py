"""Training examples for the invoice adapter: the prompts as served, the right answers, and no
personal data (ADR-014)."""

import json

import pytest

from claimpilot_datagen.invoices.model import Layout
from claimpilot_datagen.invoices.render import render
from claimpilot_datagen.invoices.sampler import build_invoice_set
from claimpilot_evals.finetune import examples_for


@pytest.fixture(scope="module")
def examples(tmp_path_factory):
    from claimpilot_worker.ingest.parser import parse

    iset = build_invoice_set(42)
    out = []
    for layout in (Layout.WHOLESALE, Layout.POHODA):
        inv = next(i for i in iset.invoices if i.split == "train" and i.layout is layout)
        data, _ext, v = render(inv, 42)
        path = tmp_path_factory.mktemp("inv") / "invoice.pdf"
        path.write_bytes(data)
        gt = {"header": v["header"], "recap": v["recap"], "fees": v["fees"], "lines": v["lines"]}
        out.append((inv, examples_for(gt, parse(path, tables=True))))
    return out


def test_one_header_call_and_the_line_calls(examples):
    for inv, ex in examples:
        prompts = [e["prompt"].split("@")[0] for e in ex]
        assert prompts[0] == "invoice_extraction/header"
        assert set(prompts[1:]) == {"invoice_extraction/lines"}
        answers = [json.loads(e["messages"][-1]["content"]) for e in ex[1:]]
        items = [it["item"] for a in answers for it in a["items"]]
        assert items == list(range(1, len(inv.lines) + 1))


def test_the_contact_person_never_appears(examples):
    for inv, ex in examples:
        text = json.dumps([e["messages"] for e in ex], ensure_ascii=False)
        assert inv.supplier.contact not in text
        assert inv.supplier.phone not in text


# --- handler corrections as training answers ---------------------------------------------------

from claimpilot_evals.finetune import header_from_fields, lines_from_fields  # noqa: E402


def test_stored_header_fields_become_the_header_answer():
    fields = {
        "invoice_number": ("260104417", "Faktúra č. 260104417", 1),
        "buyer_name": ("<PERSON_1>", "Odberateľ: <PERSON_1>", 1),  # a sole trader
        "recap[0].rate": ("23%", None, 1),
        "recap[0].base": ("29,31", None, 1),
        "recap[0].vat": ("6,74", None, 1),
        "total": (None, None, None),
        "page_note": ("strana 1 z 1", None, 1),  # read by rule, never asked of the model
    }
    answer = header_from_fields(fields)
    assert answer["invoice_number"] == {
        "value": "260104417",
        "quote": "Faktúra č. 260104417",
        "page": 1,
    }
    assert answer["buyer_name"]["value"] == "<PERSON_1>"
    assert answer["total"] == {"value": None, "quote": None, "page": None}
    assert answer["recap"] == [
        {"rate": "23%", "base": "29,31", "vat": "6,74", "quote": None, "page": 1}
    ]
    assert "page_note" not in answer and answer["fees"] == []


def test_stored_line_fields_become_the_line_answers():
    values = {
        "lines[1].quantity": "2",
        "lines[1].line_net": "5,31",
        "lines[1].batches[0].batch": "2L58861",
        "lines[1].batches[0].expiry": "11/28",
        "lines[2].quantity": "96",
        "lines[2].batches[0].batch": "5L63585",
        "lines[2].batches[0].quantity": "93",
        "lines[2].batches[1].batch": "5L63168",
        "lines[2].batches[1].quantity": "3",
        "lines[3].line_net": None,  # an empty field nobody filled
    }
    out = lines_from_fields(values)
    assert out[1] == [
        {"field": "quantity", "value": "2"},
        {"field": "line_net", "value": "5,31"},
        {"field": "batch", "value": "2L58861"},
        {"field": "expiry", "value": "11/28"},
    ]
    assert [v["field"] for v in out[2]] == [
        "quantity",
        "batch",
        "batch_quantity",
        "batch",
        "batch_quantity",
    ]
    assert out[3] == []
