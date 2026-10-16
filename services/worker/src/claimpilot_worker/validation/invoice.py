"""Invoice validation in code: arithmetic, identifiers, VAT regime, dates, completeness.

Input is what extraction stored: header values and line values as printed, keyed by field name
("total", "recap[0].base"; per line "line_net", "batches[0].expiry"). Every rule writes one
named check with the fields it concerns, so a failure points at the cells on the page. Nothing
here calls a model (ADR-002); this module is written apart from the generator's own arithmetic,
so a bug cannot hide in both.

A VAT recap may be computed two ways and both are lawful: VAT per rate (base of the rate x rate,
rounded once) or VAT per line (each line rounded, then summed). A recap that matches either
passes.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from claimpilot_core.identifiers import is_valid_iban
from claimpilot_core.invoice_values import parse_number, parse_percent, parse_vat_rate
from claimpilot_core.normalize import parse_date
from claimpilot_core.trade_ids import is_valid_ico, is_valid_vat_id, normalize_gtin

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Ours:
    """The buyer group's own entities: an invoice must be addressed to one of them."""

    icos: set[str]
    vat_ids: set[str]


@dataclass(frozen=True)
class Tolerance:
    line: Decimal = CENT  # a line total against quantity x price
    sum: Decimal = CENT  # a sum against its parts, per part rounded


@dataclass
class Check:
    name: str
    ok: bool
    fields: list[str]
    detail: str = ""


@dataclass
class ValidationResult:
    checks: list[Check] = field(default_factory=list)
    needs_info: bool = False  # pages are missing: ask the supplier, do not guess

    def add(self, name: str, ok: bool, fields: list[str], detail: str = "") -> None:
        self.checks.append(Check(name, ok, fields, detail))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _num(values: dict[str, str], name: str) -> Decimal | None:
    return parse_number(values.get(name))


def _pct(values: dict[str, str], name: str) -> Decimal:
    return parse_percent(values.get(name)) or Decimal(0)


def _rows(header: dict[str, str], prefix: str) -> list[dict[str, str]]:
    rows: dict[int, dict[str, str]] = defaultdict(dict)
    for name, value in header.items():
        m = re.fullmatch(rf"{prefix}\[(\d+)\]\.(\w+)", name)
        if m:
            rows[int(m[1])][m[2]] = value
    return [rows[i] for i in sorted(rows)]


# --- lines ------------------------------------------------------------------------------------


def expected_line_net(line: dict[str, str]) -> Decimal | None:
    """Quantity x the price after discounts, in the form the line prints."""
    qty = _num(line, "quantity")
    if qty is None:
        return None
    if (net := _num(line, "net_unit_price")) is not None:
        return r2(qty * net)
    unit = _num(line, "unit_price")
    if unit is None:
        return None
    if "struct_discount_pct" in line or "promo_discount_pct" in line:
        net = r2(
            unit
            * (1 - _pct(line, "struct_discount_pct") / HUNDRED)
            * (1 - _pct(line, "promo_discount_pct") / HUNDRED)
        )
        return r2(qty * net)
    return r2(qty * unit * (1 - _pct(line, "discount_pct") / HUNDRED))


def check_line(result: ValidationResult, i: int, line: dict[str, str], tol: Tolerance) -> None:
    ref = f"lines[{i}]"
    # A line the export cannot do without; extraction leaves an empty field to fill in.
    missing = [f"{ref}.{k}" for k in ("quantity", "line_net") if _num(line, k) is None]
    result.add("line_complete", not missing, missing or [f"{ref}.quantity", f"{ref}.line_net"])
    line_net = _num(line, "line_net")
    expected = expected_line_net(line)
    if "line_net" in line:
        ok = line_net is not None and expected is not None and abs(line_net - expected) <= tol.line
        result.add(
            "line_math",
            ok,
            [f"{ref}.{k}" for k in ("quantity", "unit_price", "line_net") if k in line],
            f"expected {expected}" if not ok else "",
        )
    rate = parse_vat_rate(line.get("vat_rate"))
    vat = _num(line, "vat_amount")
    if "vat_amount" in line and line_net is not None and rate is not None:
        ok = vat is not None and abs(vat - r2(line_net * rate / HUNDRED)) <= tol.line
        result.add("line_vat", ok, [f"{ref}.vat_amount", f"{ref}.vat_rate"])
    gross = _num(line, "line_gross")
    if "line_gross" in line and line_net is not None and vat is not None:
        ok = gross is not None and abs(gross - (line_net + vat)) <= tol.line
        result.add("line_gross", ok, [f"{ref}.line_gross"])
    if line.get("ean"):
        g = normalize_gtin(line["ean"])
        result.add("ean", g.gtin is not None, [f"{ref}.ean"], ",".join(sorted(g.flags)))


# --- the whole invoice ------------------------------------------------------------------------


def validate(
    header: dict[str, str],
    lines: list[dict[str, str]],
    ours: Ours,
    *,
    pages_present: int,
    kind: str = "invoice",
    tolerance: Tolerance | None = None,
    today: date | None = None,
) -> ValidationResult:
    """`lines` in reading order; check fields name them "lines[N]" with N counted from 1."""
    tol = tolerance or Tolerance()
    result = ValidationResult()
    for i, line in enumerate(lines, start=1):
        check_line(result, i, line, tol)
    _pages(result, header, pages_present)  # first: missing pages explain a missing total
    _recap(result, header, lines, tol)
    _lines_total(result, header, lines, tol)
    _totals(result, header, tol)
    _identity(result, header, ours)
    _regime(result, header, lines)
    _dates(result, header)
    _second_currency(result, header, tol)
    if kind == "credit_note":
        _credit_note(result, header)
    return result


def _recap(
    result: ValidationResult, header: dict[str, str], lines: list[dict[str, str]], tol: Tolerance
) -> None:
    recap = _rows(header, "recap")
    if not recap or not lines:
        return
    bases: dict[int, Decimal] = defaultdict(Decimal)
    line_vat: dict[int, Decimal] = defaultdict(Decimal)
    counts: dict[int, int] = defaultdict(int)
    for line in lines:
        rate, net = parse_vat_rate(line.get("vat_rate")), _num(line, "line_net")
        if rate is None or net is None:
            continue
        bases[rate] += net
        counts[rate] += 1
        line_vat[rate] += r2(net * rate / HUNDRED)
    for fee in _rows(header, "fees"):
        net = parse_number(fee.get("net"))
        if net is not None and bases:
            rate = max(bases, key=lambda r: r)  # a fee outside the items takes the standard rate
            bases[rate] += net
            line_vat[rate] += r2(net * rate / HUNDRED)
            counts[rate] += 1
    for k, row in enumerate(recap):
        rate, base, vat = (
            parse_vat_rate(row.get("rate")),
            parse_number(row.get("base")),
            parse_number(row.get("vat")),
        )
        ref = f"recap[{k}]"
        if rate is None or base is None:
            result.add("recap_base", False, [f"{ref}.rate", f"{ref}.base"], "unreadable")
            continue
        lines_sum = bases.get(rate, Decimal(0))
        ok = abs(base - lines_sum) <= tol.sum
        result.add("recap_base", ok, [f"{ref}.base"], f"lines sum to {lines_sum}")
        if vat is not None:
            per_rate = r2(base * rate / HUNDRED)
            per_line = line_vat.get(rate, Decimal(0))
            ok = abs(vat - per_rate) <= tol.sum or abs(vat - per_line) <= tol.sum
            result.add("recap_vat", ok, [f"{ref}.vat"], f"{per_rate} per rate, {per_line} per line")


def _lines_total(
    result: ValidationResult, header: dict[str, str], lines: list[dict[str, str]], tol: Tolerance
) -> None:
    """The lines against the printed totals, so a line left out cannot pass. The recap already
    holds them per rate; without one (scans), the net total or the total itself does."""
    nets = [_num(line, "line_net") for line in lines]
    if not lines or any(n is None for n in nets) or _rows(header, "recap"):
        return
    fees = [n for f in _rows(header, "fees") if (n := parse_number(f.get("net"))) is not None]
    lines_sum = sum((n for n in nets if n is not None), Decimal(0)) + sum(fees, Decimal(0))
    if (net := _num(header, "total_net")) is not None:
        ok = abs(net - lines_sum) <= tol.sum
        result.add("lines_total", ok, ["total_net"], f"lines sum to {lines_sum}")
        return
    if (total := _num(header, "total")) is None:
        return
    rates = [parse_vat_rate(line.get("vat_rate")) or 0 for line in lines]
    vat = Decimal(0)
    if not header.get("reverse_charge"):
        vat = sum((r2(n * r / HUNDRED) for n, r in zip(nets, rates, strict=True) if n), Decimal(0))
        vat += sum((r2(f * max(rates) / HUNDRED) for f in fees), Decimal(0))
    computed = lines_sum + vat
    # VAT rounded per line may sit a cent per line away from VAT rounded per rate.
    ok = abs(total - computed) <= tol.sum * max(1, len(nets) + len(fees))
    result.add("lines_total", ok, ["total"], f"lines with VAT come to {computed}")


def _totals(result: ValidationResult, header: dict[str, str], tol: Tolerance) -> None:
    recap = _rows(header, "recap")
    net, vat, total = _num(header, "total_net"), _num(header, "total_vat"), _num(header, "total")
    if total is None and _num(header, "amount_due") is None and not result.needs_info:
        # Some layouts print only the amount due; with neither, nothing holds the lines.
        result.add("total", False, ["total", "amount_due"], "no final amount read")
    bases = [parse_number(r.get("base")) for r in recap]
    vats = [parse_number(r.get("vat")) for r in recap]
    if recap and all(b is not None for b in bases):
        sum_base = sum((b for b in bases if b is not None), Decimal(0))
        if net is not None:
            result.add("total_net", abs(net - sum_base) <= tol.sum, ["total_net"])
        if vat is not None and all(v is not None for v in vats):
            sum_vat = sum((v for v in vats if v is not None), Decimal(0))
            result.add("total_vat", abs(vat - sum_vat) <= tol.sum, ["total_vat"])
            net = net if net is not None else sum_base
            vat_total = sum_vat
        else:
            vat_total = vat
    else:
        vat_total = vat
    computed = net + vat_total if net is not None and vat_total is not None else None
    if total is not None and computed is not None:
        result.add("total", abs(total - computed) <= tol.sum, ["total", "total_net", "total_vat"])
    due = _num(header, "amount_due")
    settled = _num(header, "proforma_settled") or Decimal(0)
    base_total = computed if computed is not None else total
    if due is not None and base_total is not None:
        # A settled advance is printed as a deduction ("-20,00") or as a plain amount.
        ok = abs(due - (base_total - abs(settled))) <= tol.sum
        result.add("amount_due", ok, ["amount_due", "proforma_settled"])


def _identity(result: ValidationResult, header: dict[str, str], ours: Ours) -> None:
    for name, valid in (
        ("supplier_ico", is_valid_ico),
        ("supplier_vat_id", is_valid_vat_id),
        ("supplier_iban", is_valid_iban),
        ("buyer_vat_id", is_valid_vat_id),
    ):
        if header.get(name):
            result.add(name, valid(header[name]), [name])
    ico = re.sub(r"\D", "", header.get("buyer_ico") or "")
    vat_id = (header.get("buyer_vat_id") or "").replace(" ", "").upper()
    if ico or vat_id:
        ok = ico in ours.icos or vat_id in ours.vat_ids
        result.add("buyer_is_ours", ok, ["buyer_ico", "buyer_vat_id"])


def _regime(result: ValidationResult, header: dict[str, str], lines: list[dict[str, str]]) -> None:
    rates = [parse_vat_rate(r.get("rate")) for r in _rows(header, "recap")]
    rates += [parse_vat_rate(line.get("vat_rate")) for line in lines]
    known = [r for r in rates if r is not None]
    if not known or any(known):
        return
    supplier_vat = (header.get("supplier_vat_id") or "").replace(" ", "").upper()
    foreign = bool(supplier_vat) and not supplier_vat.startswith("SK")
    ok = bool(header.get("reverse_charge")) and foreign
    result.add(
        "vat_regime",
        ok,
        ["reverse_charge", "supplier_vat_id"],
        "0 % VAT needs an intra-EU supplier and the note",
    )


def _dates(result: ValidationResult, header: dict[str, str]) -> None:
    issue, due = parse_date(header.get("issue_date")), parse_date(header.get("due_date"))
    if issue and due:
        result.add("date_order", due >= issue, ["issue_date", "due_date"])


def _pages(result: ValidationResult, header: dict[str, str], pages_present: int) -> None:
    note = header.get("page_note") or ""
    m = re.search(r"(?:z|/|of)\s*(\d+)\s*$", note.replace(" | ", " ").strip(), re.IGNORECASE)
    if not m:
        return
    printed = int(m[1])
    ok = pages_present >= printed
    result.add("pages_complete", ok, ["page_note"], f"{pages_present} of {printed} pages")
    result.needs_info = result.needs_info or not ok


def _second_currency(result: ValidationResult, header: dict[str, str], tol: Tolerance) -> None:
    total, rate, other = (
        _num(header, "total"),
        _num(header, "fx_rate"),
        _num(header, "second_currency_total"),
    )
    if total is None or rate is None or other is None:
        return
    result.add(
        "second_currency",
        abs(other - r2(total * rate)) <= tol.sum,
        ["second_currency_total", "fx_rate"],
    )


def _credit_note(result: ValidationResult, header: dict[str, str]) -> None:
    result.add(
        "credit_note_original",
        bool(header.get("original_invoice_number")),
        ["original_invoice_number"],
    )
    total = _num(header, "total")
    if total is not None:
        result.add("credit_note_sign", total < 0, ["total"])
