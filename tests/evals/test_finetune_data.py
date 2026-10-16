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
