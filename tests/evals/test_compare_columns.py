"""A run against its baseline names the per-column notes that moved, so a failure says which
field broke instead of only which metric."""

from claimpilot_evals.compare import column_deltas


def report(notes):
    return {"suite": "invoice_extraction", "metrics": {}, "items": [], "notes": notes}


BASE = report(["DE-0001 pohoda: lines 3/3", "column ean: 640/640", "column name: 761/777"])


def test_a_column_that_fell_is_named_worst_first():
    now = report(["column ean: 414/640", "column name: 755/777"])
    assert column_deltas(now, BASE) == [
        "column ean: 100.0% -> 64.7% (-226)",
        "column name: 97.9% -> 97.2% (-6)",
    ]


def test_columns_that_held_or_rose_are_not_named():
    now = report(["column ean: 640/640", "column name: 770/777"])
    assert column_deltas(now, BASE) == []


def test_without_a_baseline_or_notes_there_is_nothing_to_say():
    assert column_deltas(report(["column ean: 1/2"]), None) == []
    assert column_deltas(report([]), BASE) == []
