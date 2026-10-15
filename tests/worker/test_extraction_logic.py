from claimpilot_core.domain import DocType
from claimpilot_core.fields import kind_of, normalize
from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument
from claimpilot_worker.extraction.crossdoc import cross_document_checks
from claimpilot_worker.extraction.extract import (
    Extraction,
    Field,
    check_as_printed,
    flatten,
    ground,
    run_checks,
    score_confidence,
)
from claimpilot_worker.extraction.schema import grounded_model

BOX = FracBox(x0=0.1, y0=0.1, x1=0.5, y1=0.12)


def parsed(*texts, page=1):
    blocks = [Block(page=page, seq=i, kind="text", text=t, bbox=BOX) for i, t in enumerate(texts)]
    return ParsedDocument(
        sha256="x",
        mime_type="application/pdf",
        pages=[PageInfo(page=page, width=595, height=842)],
        blocks=blocks,
    )


def test_grounded_schema_wraps_every_field():
    schema = grounded_model(DocType.MEDICAL_INVOICE).model_json_schema()
    assert set(schema["required"]) >= {"invoice_number", "total", "line_items"}
    item = schema["$defs"]["GroundedLineItem"]["properties"]
    assert {"description", "amount", "quote", "page"} <= set(item)


def test_flatten_rows_and_scalars():
    raw = {
        "total": {"value": "279,50", "quote": "Gesamtbetrag 279,50 EUR", "page": 1},
        "line_items": [
            {"description": "Röntgen", "amount": "95,50", "quote": "2 | Röntgen | 95,50", "page": 1}
        ],
        "claim_types": {"values": ["Úraz"], "quote": "X Úraz", "page": 1},
    }
    names = {f.name: f for f in flatten(raw)}
    assert names["line_items[0].amount"].value_raw == "95,50"
    assert names["line_items[0].amount"].quote == "2 | Röntgen | 95,50"
    assert names["claim_types"].value_raw == '["Úraz"]'


def test_grounding_finds_the_block_and_rejects_invented_quotes():
    doc = parsed("Rechnung Nr. RE-2026-04417", "Gesamtbetrag 279,50 EUR")
    redacted = {b.seq: b.text for b in doc.blocks}
    ok, box = ground("Gesamtbetrag 279,50 EUR", "279,50", 1, doc, redacted)
    assert ok and box == BOX
    ok, box = ground("Total due 999,99", "999,99", 1, doc, redacted)
    assert not ok and box is None


def test_grounding_ignores_diacritics_lost_in_ocr():
    doc = parsed("Patient: Jana Kovacova")
    ok, _ = ground("Patient: Jana Kováčová", None, 1, doc, {0: doc.blocks[0].text})
    assert ok


def test_total_must_match_line_sum():
    fields = [
        Field("total", "279,50", None, 1, value_norm="279.50"),
        Field("line_items[0].amount", "120,00", None, 1, value_norm="120.00"),
        Field("line_items[1].amount", "159,50", None, 1, value_norm="159.50"),
    ]
    run_checks(DocType.MEDICAL_INVOICE, fields, {})
    assert fields[0].checks["total_matches_lines"] is True
    fields[2].value_norm = "150.00"
    run_checks(DocType.MEDICAL_INVOICE, fields, {})
    assert fields[0].checks["total_matches_lines"] is False


def test_iban_is_checked_on_the_rehydrated_value():
    f = Field("iban", "<IBAN_1>", None, 1)
    run_checks(DocType.CLAIM_FORM, [f], {"<IBAN_1>": "SK3112000000198742637541"})
    assert f.checks["iban_checksum"] is True
    run_checks(DocType.CLAIM_FORM, [f], {"<IBAN_1>": "SK3112000000198742637542"})
    assert f.checks["iban_checksum"] is False


def test_confidence_caps_ungrounded_values():
    grounded = Field("total", "1", "q", 1, grounded=True, checks={"parses": True})
    ungrounded = Field("total", "1", "q", 1, grounded=False, checks={"parses": True})
    failing = Field("total", "1", "q", 1, grounded=True, checks={"total_matches_lines": False})
    assert score_confidence(grounded) >= 0.9
    assert score_confidence(ungrounded) <= 0.45
    assert score_confidence(failing) < score_confidence(grounded)
    assert score_confidence(Field("total", None, None, None)) == 0.0


def test_field_kinds_and_normalization():
    assert kind_of("line_items[3].amount") == "amount"
    assert kind_of("trip_start") == "date"
    assert normalize("issue_date", "02/14/2026", country="US") == "2026-02-14"
    assert normalize("currency", "Kč") == "CZK"
    assert normalize("total", "1.279,50") == "1279.50"
    assert normalize("provider_country", "Österreich") == "AT"


def _ex(doc_type, **values):
    return Extraction(
        doc_type, [Field(k, v, None, 1, value_norm=v) for k, v in values.items()], {}, None, "m"
    )


def test_cross_document_checks():
    form = _ex(
        DocType.CLAIM_FORM,
        insured_name="<PERSON_1>",
        event_date="2026-02-14",
        trip_start="2026-02-10",
        trip_end="2026-02-20",
    )
    form.get("insured_name").value_norm = "<PERSON_1>"
    invoice = _ex(DocType.MEDICAL_INVOICE, patient_name="<PERSON_2>")
    report = _ex(DocType.MEDICAL_REPORT, patient_name="<PERSON_1>", visit_date="2026-02-19")
    results = cross_document_checks([form, invoice, report])
    assert results["event_in_trip"] is True
    assert results["same_person"] is False
    assert invoice.get("patient_name").checks["same_person"] is False
    assert results["dates_consistent"] is False  # five days apart


def test_a_value_that_lost_a_character_is_not_trusted_although_its_line_was_found():
    doc = parsed("Račun br. R-2026-36818", "Datum: 16.6.2026.", "Pacijent: <PERSON_1>")
    redacted = {b.seq: b.text for b in doc.blocks}
    fields = [
        Field("invoice_number", "R-2026 36818", "Račun br. R-2026-36818", 1),
        Field("issue_date", "16. 6. 2026.", "Datum: 16. 6. 2026.", 1),  # OCR lost the spaces
        Field("patient_name", "<PERSON_1>", "Pacijent: <PERSON_1>", 1),
    ]
    for f in fields:
        f.grounded, f.bbox = ground(f.quote, f.value_raw, f.page, doc, redacted)
        f.value_norm = normalize(f.name, f.value_raw)
    assert all(f.grounded for f in fields)  # the fuzzy match finds every line
    check_as_printed(fields, doc, redacted)
    assert [f.checks["as_printed"] for f in fields] == [False, True, True]
    run_checks(DocType.MEDICAL_INVOICE, fields, {})
    assert score_confidence(fields[0]) < 0.9 <= score_confidence(fields[1])
