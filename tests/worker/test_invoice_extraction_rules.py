"""Rules around the invoice model calls: who is a person, how unlabelled batch rows read."""

import pytest

from claimpilot_worker.extraction.invoice import company_aware_ner


def no_model(text):
    return []


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Vystavil: Belo Kríž", "Belo Kríž"),
        ("Vybavuje: Ľubica Šťastná  E-mail: x@y.sk", "Ľubica Šťastná"),
        ("Faktúru vyhotovil: Ondrej Malý", "Ondrej Malý"),
        ("Contact person: Jan Dvořák, tel. / fax: +420 601 000 000", "Jan Dvořák"),
    ],
)
def test_a_name_after_an_issuer_label_is_a_person(text, name, monkeypatch):
    monkeypatch.setattr("claimpilot_core.pii.guard.transformer_ner", no_model)
    spans = company_aware_ner(text)
    assert [(s.entity, s.text) for s in spans] == [("PERSON", name)]


def test_a_blank_signature_line_is_no_person(monkeypatch):
    monkeypatch.setattr("claimpilot_core.pii.guard.transformer_ner", no_model)
    assert company_aware_ner("Prevzal: ____________  Vystavil: Lekárne Sever s.r.o.") == []


def test_lowercase_words_after_the_label_are_no_name(monkeypatch):
    monkeypatch.setattr("claimpilot_core.pii.guard.transformer_ner", no_model)
    assert company_aware_ner("Vystavil: elektronicky systém") == []


# --- batches printed without a label ----------------------------------------------------------

from claimpilot_core.schemas.invoices import CellValue, ItemValues  # noqa: E402
from claimpilot_core.schemas.parsing import FracBox, TableCell  # noqa: E402
from claimpilot_worker.extraction.invoice import Item, _line_result  # noqa: E402


def cell(line, text, col=0, header="popis"):
    box = FracBox(x0=0.1, y0=0.3 + line / 100, x1=0.4, y1=0.31 + line / 100)
    return TableCell(
        page=1, table=0, item=0, line=line, col=col, header=header, text=text, bbox=box
    )


def wholesale_item(*extra):
    return Item(1, 1, [cell(0, "Nutrilek čaj 20x2g"), cell(0, "27,80", 5, "Spolu"), *extra])


def values(result):
    return {k: f.value_raw for k, f in result.fields.items()}


def test_an_unlabelled_batch_and_expiry_are_read_by_rule():
    item = wholesale_item(cell(1, "2L58861 11/28"), cell(2, "EAN: 8599085545930"))
    # The model shifted the pair: the expiry landed in batch.
    answer = ItemValues(
        item=1,
        values=[
            CellValue(field="batch", value="11/28"),
            CellValue(field="sukl_code", value="2L58861"),  # filed under the column it sits in
        ],
    )
    got = values(_line_result(answer, item, {}))
    assert got == {"batches[0].batch": "2L58861", "batches[0].expiry": "11/28"}


def test_two_batch_rows_keep_the_quantities_the_model_read():
    item = wholesale_item(cell(1, "5L63585 12/29"), cell(2, "5L63168 12/29"))
    answer = ItemValues(
        item=1,
        values=[
            CellValue(field="batch", value="5L63585"),
            CellValue(field="batch_quantity", value="93"),
            CellValue(field="batch", value="5L63168"),
            CellValue(field="batch_quantity", value="3"),
        ],
    )
    got = values(_line_result(answer, item, {}))
    assert got["batches[1].batch"] == "5L63168" and got["batches[1].expiry"] == "12/29"
    assert (got["batches[0].quantity"], got["batches[1].quantity"]) == ("93", "3")


def test_an_item_without_such_a_line_keeps_the_model_values():
    item = wholesale_item(cell(1, "Šarža: AB123, Exp. 2027-03"))
    answer = ItemValues(item=1, values=[CellValue(field="batch", value="AB123")])
    assert values(_line_result(answer, item, {})) == {"batches[0].batch": "AB123"}
