"""Matching an invoice against the ERP (matching/invoice.py): supplier, IBAN, order, receipt."""

from decimal import Decimal

from claimpilot_worker.matching.invoice import MatchSettings, match

SUPPLIER = {
    "key": "bioflora",
    "ico": "98391267",
    "vat_id": "SK2995153513",
    "iban": "SK89 0200 0000 0076 9943 1836",
}
ORDER = {
    "number": "OB25000001",
    "supplier_ico": "98391267",
    "lines": [
        {"ean": "2904012073381", "supplier_code": "0001", "qty": "2", "unit_price": "2.656"},
        {"ean": "2904012074456", "supplier_code": "0002", "qty": "6", "unit_price": "4.00"},
    ],
}
RECEIPT = {"delivery_note": "PR-1", "order_number": "OB25000001", "lines": ORDER["lines"]}
HEADER = {
    "supplier_ico": "98391267",
    "supplier_vat_id": "SK2995153513",
    "supplier_iban": "SK89 0200 0000 0076 9943 1836",
    "order_number": "OB25000001",
}
LINES = [
    {"ean": "2904012073381", "quantity": "2", "line_net": "5,31"},
    {"ean": "2904012074456", "quantity": "6", "line_net": "24,00"},
]  # fmt: skip


class Erp:
    def __init__(
        self,
        suppliers=(SUPPLIER,),
        orders=(ORDER,),
        receipts=(RECEIPT,),
        invoices=(),
        invoiced=None,
    ):
        self.suppliers, self.orders, self.receipts = list(suppliers), list(orders), list(receipts)
        self.invoices = set(invoices)
        self.invoiced = invoiced or {}  # order line index -> quantity on earlier invoices

    def invoiced_before(self, number):
        return {j: Decimal(str(q)) for j, q in self.invoiced.items()}

    def supplier(self, ico, vat_id):
        return next((s for s in self.suppliers if s["vat_id"] == vat_id or s["ico"] == ico), None)

    def order(self, number):
        return next((o for o in self.orders if o["number"] == number), None)

    def receipts_for(self, number):
        return [r for r in self.receipts if r["order_number"] == number]

    def invoice_known(self, supplier_ico, number):
        return (supplier_ico, number) in self.invoices


def kinds(result) -> set[tuple[str, int | None]]:
    return {(f.kind, f.line) for f in result.findings}


def test_a_clean_invoice_matches():
    result = match(HEADER, LINES, Erp(), MatchSettings())
    assert result.findings == []
    assert [m.order_line for m in result.lines] == [0, 1]


def test_unknown_supplier_stops_matching():
    result = match(
        dict(HEADER, supplier_ico="99999999", supplier_vat_id="SK9999999999"),
        LINES,
        Erp(),
        MatchSettings(),
    )
    assert kinds(result) == {("unknown_supplier", None)}


def test_a_changed_iban_is_a_finding():
    result = match(
        dict(HEADER, supplier_iban="SK31 1200 0000 1987 4263 7541"), LINES, Erp(), MatchSettings()
    )
    assert kinds(result) == {("iban_changed", None)}


def test_price_above_the_tolerance():
    lines = [LINES[0], dict(LINES[1], line_net="24,48")]  # 4.08 a piece: +2 %
    assert kinds(match(HEADER, lines, Erp(), MatchSettings())) == {("price_diff", 1)}
    lines = [LINES[0], dict(LINES[1], line_net="24,10")]  # +0.42 %: inside the tolerance
    assert kinds(match(HEADER, lines, Erp(), MatchSettings())) == set()


def test_per_supplier_tolerance():
    lines = [LINES[0], dict(LINES[1], line_net="24,48")]
    settings = MatchSettings(per_supplier={"98391267": Decimal("3")})
    assert kinds(match(HEADER, lines, Erp(), settings)) == set()


def test_short_delivery_against_the_receipt():
    receipt = dict(RECEIPT, lines=[ORDER["lines"][0], dict(ORDER["lines"][1], qty="5")])
    result = match(HEADER, LINES, Erp(receipts=[receipt]), MatchSettings())
    assert kinds(result) == {("short_delivery", 1)}


def test_lines_match_by_supplier_code_when_there_is_no_ean():
    lines = [
        {"supplier_code": "0001", "quantity": "2", "line_net": "5,31"},
        {"supplier_code": "0002", "quantity": "6", "line_net": "24,00"},
    ]
    assert match(HEADER, lines, Erp(), MatchSettings()).findings == []


def test_an_eleven_digit_ean_matches_its_padded_code():
    order = dict(ORDER, lines=[dict(ORDER["lines"][0], ean="0074912305874"), ORDER["lines"][1]])
    lines = [dict(LINES[0], ean="74912305874"), LINES[1]]
    receipt = dict(RECEIPT, lines=order["lines"])
    assert (
        match(HEADER, lines, Erp(orders=[order], receipts=[receipt]), MatchSettings()).findings
        == []
    )


def test_the_same_product_on_two_lines_takes_two_order_lines():
    order = dict(ORDER, lines=[ORDER["lines"][0], dict(ORDER["lines"][0], qty="3")])
    lines = [LINES[0], dict(LINES[0], quantity="3", line_net="7,97")]
    receipt = dict(RECEIPT, lines=order["lines"])
    result = match(HEADER, lines, Erp(orders=[order], receipts=[receipt]), MatchSettings())
    assert result.findings == []
    assert [m.order_line for m in result.lines] == [0, 1]


def test_a_line_that_was_not_ordered():
    lines = [*LINES, {"ean": "2904012071349", "quantity": "1", "line_net": "1,00"}]
    assert kinds(match(HEADER, lines, Erp(), MatchSettings())) == {("not_ordered", 2)}


def test_an_unknown_order_number():
    assert kinds(match(dict(HEADER, order_number="OB99"), LINES, Erp(), MatchSettings())) == {
        ("unknown_order", None)
    }


def test_a_credit_note_needs_a_known_original():
    header = dict(HEADER, original_invoice_number="260104417")
    del header["order_number"]
    result = match(header, LINES, Erp(), MatchSettings(), kind="credit_note")
    assert kinds(result) == {("unknown_original", None)} and result.needs_info
    erp = Erp(invoices=[("98391267", "260104417")])
    assert match(header, LINES, erp, MatchSettings(), kind="credit_note").findings == []


def test_a_proforma_is_not_checked_against_a_receipt():
    result = match(HEADER, LINES, Erp(receipts=[]), MatchSettings(), kind="proforma")
    assert result.findings == []


def test_an_order_of_another_supplier_is_not_a_match():
    other = dict(ORDER, supplier_ico="97145289")
    result = match(HEADER, LINES, Erp(orders=(other,)), MatchSettings())
    assert ("order_mismatch", None) in kinds(result)
    assert result.lines == []  # its lines are not held against this invoice


def test_an_order_of_another_buyer_is_not_a_match():
    order = dict(ORDER, buyer_ico="93533446")
    header = dict(HEADER, buyer_ico="90882750")
    assert ("order_mismatch", None) in kinds(
        match(header, LINES, Erp(orders=(order,)), MatchSettings())
    )


# --- goods invoiced twice -------------------------------------------------------------------------


def test_a_second_invoice_for_the_same_receipt_is_flagged_on_every_line():
    erp = Erp(invoiced={0: 2, 1: 6})  # the first invoice took everything that was received
    result = match(HEADER, LINES, erp, MatchSettings())
    assert kinds(result) == {("already_invoiced", 0), ("already_invoiced", 1)}
    assert "2 on earlier invoices" in result.findings[0].detail


def test_the_rest_of_a_receipt_can_be_invoiced_once_more():
    # 6 received on line 2, 4 already invoiced: 2 are left.
    erp = Erp(invoiced={1: 4})
    two = [LINES[0], dict(LINES[1], quantity="2", line_net="8,00")]
    assert match(HEADER, two, erp, MatchSettings()).findings == []
    three = [LINES[0], dict(LINES[1], quantity="3", line_net="12,00")]
    assert ("already_invoiced", 1) in kinds(match(HEADER, three, erp, MatchSettings()))


def test_an_invoice_for_less_than_what_is_left_is_an_over_delivery_as_before():
    erp = Erp(invoiced={1: 1})  # 5 left, 3 invoiced
    three = [LINES[0], dict(LINES[1], quantity="3", line_net="12,00")]
    assert ("over_delivery", 1) in kinds(match(HEADER, three, erp, MatchSettings()))


def test_more_than_was_received_with_nothing_invoiced_before_is_a_short_delivery():
    more = [LINES[0], dict(LINES[1], quantity="7", line_net="28,00")]
    assert ("short_delivery", 1) in kinds(match(HEADER, more, Erp(), MatchSettings()))


def test_a_proforma_does_not_count_the_receipt():
    erp = Erp(invoiced={0: 2, 1: 6})
    assert match(HEADER, LINES, erp, MatchSettings(), kind="proforma").findings == []


def test_the_invoiced_quantity_is_kept_per_line_for_the_next_invoice():
    result = match(HEADER, LINES, Erp(), MatchSettings())
    assert [m.quantity for m in result.lines] == [Decimal(2), Decimal(6)]
