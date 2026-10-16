import httpx
import pytest
import respx

from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_evals.compare import check
from claimpilot_evals.suites.common import PayloadRecorder


def report(suite, metrics, failed_ids=(), tag=None, stale=()):
    items = [{"id": i, "ok": False, "tags": [tag] if tag else []} for i in failed_ids]
    return {"suite": suite, "metrics": metrics, "items": items, "stale": list(stale)}


def m(value, num=0, den=0):
    return {"value": value, "num": num, "den": den}


def test_item_level_gate_allows_one_point_and_trips_above():
    base = report("pii", {"recall_names": m(0.97, 97, 100)})
    assert check(report("pii", {"recall_names": m(0.965, 193, 200)}), base) == []
    problems = check(report("pii", {"recall_names": m(0.95, 95, 100)}), base)
    assert problems and "dropped 2.0 pp" in problems[0]


def test_claim_level_gate_counts_newly_failing_claims_not_percent():
    base = report("routing", {"fraud_recall": m(0.9, 9, 10)}, ["S42-003"], "fraud_recall")
    same_failure = report("routing", {"fraud_recall": m(0.9, 9, 10)}, ["S42-003"], "fraud_recall")
    assert check(same_failure, base) == []
    swapped = report("routing", {"fraud_recall": m(0.9, 9, 10)}, ["S42-011"], "fraud_recall")
    problems = check(swapped, base)
    assert problems and "S42-011" in problems[0]  # same percentage, but a new fraud miss fails


def test_accuracy_gate_tolerates_one_new_failure():
    base = report("routing", {"accuracy": m(0.9, 36, 40)}, ["a", "b", "c", "d"], "accuracy")
    one_new = report(
        "routing", {"accuracy": m(0.875, 35, 40)}, ["a", "b", "c", "d", "e"], "accuracy"
    )
    two_new = report(
        "routing", {"accuracy": m(0.85, 34, 40)}, ["a", "b", "c", "d", "e", "f"], "accuracy"
    )
    assert check(one_new, base) == []
    assert check(two_new, base)


def test_zero_gate_needs_no_baseline():
    assert check(report("pii", {"leaked_values": m(0, 0)}), None) == []
    assert check(report("pii", {"leaked_values": m(1, 1)}), None)


def test_stale_cassettes_fail_the_gate():
    problems = check(report("extraction", {}, stale=["extraction/medical_invoice"]), None)
    assert problems and "stale" in problems[0]


@respx.mock
async def test_payload_recorder_sees_every_model_request(tmp_settings, tmp_path):
    (tmp_path / "prompts" / "x").mkdir(parents=True)
    (tmp_path / "prompts" / "x" / "y.md").write_text("---\nversion: 1\n---\n## user\n{{ text }}")
    tmp_settings.prompts_dir = tmp_path / "prompts"
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}, "model": "m"})
    )
    rec = PayloadRecorder()
    gw = LLMGateway(tmp_settings, event_hooks={"request": [rec]})
    await gw.generate_text("smoke", "x/y", {"text": "Patient <PERSON_1>, RČ <RC_1>"})
    await gw.generate_text("smoke", "x/y", {"text": "Patient Jana Kováčová"})
    assert len(rec.payloads) == 2
    assert rec.leaks(["Jana Kováčová", "905605/0003"]) == ["Jana Kováčová"]


@pytest.mark.parametrize("value", ["Kováčová", "Jana Kovacova"])
def test_leak_check_ignores_diacritics(value):
    rec = PayloadRecorder()
    rec.payloads.append('{"messages": [{"content": "Jana Kovacova"}]}')
    assert rec.leaks([value]) == [value]


def test_list_rows_are_matched_by_content_not_position():
    from types import SimpleNamespace

    from claimpilot_evals.suites.extraction import align_rows

    gt = {
        "total": {"printed": "30,00", "norm": "30.00"},
        "line_items[0].description": {"printed": "EKG", "norm": "EKG"},
        "line_items[0].amount": {"printed": "10,00", "norm": "10.00"},
        "line_items[1].description": {"printed": "Lijekovi", "norm": "Lijekovi"},
        "line_items[1].amount": {"printed": "20,00", "norm": "20.00"},
    }

    def f(v):
        return SimpleNamespace(value_raw=v)

    pred = {
        "total": f("30,00"),
        "line_items[0].description": f("Lijekovi"),
        "line_items[0].amount": f("20,00"),
        "line_items[1].description": f("EKG"),
        "line_items[1].amount": f("10,00"),
        "line_items[2].description": f("Extra"),
    }
    out = align_rows(pred, gt, {}, None)
    assert out["line_items[0].description"].value_raw == "EKG"
    assert out["line_items[1].amount"].value_raw == "20,00"
    assert out["line_items[2].description"].value_raw == "Extra"  # unmatched rows stay extra


def test_min_gate_needs_no_baseline_and_skips_an_empty_metric():
    assert check(report("adversarial", {"injection_detected": m(0.95, 19, 20)}), None) == []
    problems = check(report("adversarial", {"injection_detected": m(0.8, 16, 20)}), None)
    assert problems and "below 90%" in problems[0]
    assert check(report("adversarial", {"injection_detected": m(0.0, 0, 0)}), None) == []
