"""The eval gate an invoice adapter must pass before it replaces the model (ADR-014)."""

from claimpilot_evals.finetune_run import promote, promotion_problems

PROVIDERS = """\
steps:
  extraction:        { model: "qwen3:30b-a3b-instruct-2507-q4_K_M", num_predict: 6144 }
  invoice_header:    { model: "qwen3:30b-a3b-instruct-2507-q4_K_M", num_predict: 4096 }
  invoice_lines:     { model: "qwen3:30b-a3b-instruct-2507-q4_K_M", num_ctx: 24576, num_predict: 8192 }  # lines
"""


def report(**values):
    metrics = {
        "kind_accuracy": (0.99, 59, 60),
        "header_field_accuracy": (0.98, 98, 100),
        "line_recall": (1.0, 10, 10),
        "line_cell_accuracy": (0.990, 990, 1000),
        "leaked_values_in_payloads": (0, 0, 0),
    }
    for k, v in values.items():
        metrics[k] = v
    return {
        "suite": "invoice_extraction",
        "items": [],
        "metrics": {k: {"value": v, "num": n, "den": d} for k, (v, n, d) in metrics.items()},
    }


def test_an_adapter_that_reads_more_cells_and_drops_nothing_passes():
    better = report(line_cell_accuracy=(0.995, 995, 1000))
    assert promotion_problems(better, report()) == []


def test_an_adapter_that_reads_no_more_cells_does_not_pass():
    assert any("line_cell_accuracy" in p for p in promotion_problems(report(), report()))


def test_a_drop_beyond_the_tolerance_elsewhere_does_not_pass():
    worse = report(line_cell_accuracy=(0.995, 995, 1000), header_field_accuracy=(0.95, 95, 100))
    assert any("header_field_accuracy" in p for p in promotion_problems(worse, report()))


def test_a_leak_does_not_pass():
    leaky = report(line_cell_accuracy=(0.995, 995, 1000), leaked_values_in_payloads=(1, 1, 0))
    assert any("leaked" in p for p in promotion_problems(leaky, report()))


def test_promotion_points_the_invoice_steps_at_the_adapter_and_keeps_the_rest():
    out = promote(PROVIDERS, "mlx-community/Qwen3-8B-4bit", "invoice-20261016")
    lines = out.splitlines()
    assert lines[1] == PROVIDERS.splitlines()[1]  # claims untouched
    assert lines[2] == (
        '  invoice_header:    { provider: mlx, model: "mlx-community/Qwen3-8B-4bit", '
        'adapter: "invoice-20261016", num_predict: 4096 }'
    )
    assert 'adapter: "invoice-20261016", num_ctx: 24576, num_predict: 8192 }  # lines' in lines[3]
