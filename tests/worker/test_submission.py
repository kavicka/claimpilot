import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from claimpilot_core.domain import ClaimType, Coverage
from claimpilot_core.llm.types import LLMResponse, ModelSpec
from claimpilot_worker.submission.submit import map_payload, submit

ROOT = Path(__file__).resolve().parents[2]
MAPPING = {
    "<PERSON_1>": "Jana Kováčová",
    "<RC_1>": "905605/0003",
    "<IBAN_1>": "SK3112000000198742637541",
}


def payload(**over):
    p, missing = map_payload(
        policy_number="CP12345678",
        claim_type=ClaimType.MEDICAL,
        insured_token="<PERSON_1>",
        birth_number_token="<RC_1>",
        iban_token="<IBAN_1>",
        event_date=date(2026, 2, 14),
        event_country="AT",
        items=[
            {
                "ref": "I1",
                "coverage": Coverage.MEDICAL,
                "claimed_eur": Decimal("279.50"),
                "payout_eur": Decimal("229.50"),
                "clauses": ["A4.1", "A4.3"],
            }
        ],
        handler_id="h",
    )
    p.update(over)
    return p, missing


class FakeCore:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    async def code_list(self, name):
        return {"country": {"AT": "AT", "DE": "DE"}, "claim_type": {"MED": "medical expenses"}}.get(
            name, {}
        )

    async def submit(self, body, key):
        self.sent.append(body)
        return self.responses.pop(0)


class Settings:
    prompts_dir = ROOT / "prompts"


class FakeGateway:
    """Plays scripted model turns and records every request the agent would send to a model."""

    settings = Settings()

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    def spec_for(self, step):
        return ModelSpec(model="fake")

    async def complete(self, req, tools=None):
        self.requests.append(req)
        turn = self.turns.pop(0)
        return LLMResponse(
            text=turn.get("text", ""),
            tool_calls=turn.get("tool_calls", []),
            model="fake",
            provider="t",
        )


def call(name, args):
    return {"function": {"name": name, "arguments": args}}


def test_mapper_fills_codes_and_totals():
    p, missing = payload()
    assert missing == []
    assert p["claim_type_code"] == "MED"
    assert p["items"][0] == {
        "ref": "I1",
        "coverage_code": "MED",
        "claimed_eur": "279.50",
        "payout_eur": "229.50",
        "decision": "PAY",
        "clause_refs": ["A4.1", "A4.3"],
    }
    assert p["total_payout"] == "229.50"


def test_mapper_reports_missing_values_instead_of_guessing():
    _, missing = map_payload(
        policy_number=None,
        claim_type=ClaimType.MEDICAL,
        insured_token="<PERSON_1>",
        birth_number_token=None,
        iban_token="<IBAN_1>",
        event_date=date(2026, 2, 14),
        event_country=None,
        items=[],
        handler_id="h",
    )
    assert set(missing) == {"policy_number", "insured.birth_number", "event_country"}


async def test_first_try_rehydrates_only_at_the_core_boundary():
    core = FakeCore([(201, {"core_claim_id": "CCS-1"})])
    gw = FakeGateway([])
    p, missing = payload()
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    assert (r.status, r.first_try, r.used_agent) == ("registered", True, False)
    assert core.sent[0]["insured"]["name"] == "Jana Kováčová"
    assert core.sent[0]["iban"] == "SK3112000000198742637541"
    assert p["insured"]["name"] == "<PERSON_1>"  # the payload object itself keeps tokens


async def test_agent_fixes_a_code_list_mismatch():
    p, missing = payload(event_country="AUT")
    errors = {
        "detail": [
            {
                "loc": ["body", "event_country"],
                "msg": "ISO 3166 alpha-2",
                "type": "not_in_code_list",
            }
        ]
    }
    fixed = dict(p, event_country="AT")
    core = FakeCore([(422, errors), (201, {"core_claim_id": "CCS-2"})])
    gw = FakeGateway(
        [
            {"tool_calls": [call("get_code_list", {"name": "country"})]},
            {"tool_calls": [call("submit_claim", {"payload": fixed})]},
        ]
    )
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    assert (r.status, r.submissions, r.used_agent) == ("registered", 2, True)
    assert core.sent[1]["event_country"] == "AT"
    sent_to_model = json.dumps(
        [m.model_dump() for req in gw.requests for m in req.messages], ensure_ascii=False
    )
    assert "Kováčová" not in sent_to_model and "905605" not in sent_to_model
    assert "<PERSON_1>" in sent_to_model


async def test_agent_stops_after_three_submissions():
    p, missing = payload(event_country="AUT")
    err = (
        422,
        {"detail": [{"loc": ["body", "event_country"], "type": "not_in_code_list", "msg": "x"}]},
    )
    core = FakeCore([err, err, err, err])
    gw = FakeGateway(
        [{"tool_calls": [call("submit_claim", {"payload": p})]}] * 4
        + [{"text": '{"status": "needs_handler", "fields": ["event_country"]}'}]
    )
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    assert r.status == "needs_handler"
    assert len(core.sent) == 3
    assert r.fields == ["event_country"]


async def test_missing_values_go_back_to_the_handler_without_submitting():
    p, _ = payload()
    core = FakeCore([])
    r = await submit(
        p, ["iban"], mapping=MAPPING, core=core, gateway=FakeGateway([]), idempotency_key="k"
    )
    assert (r.status, r.fields, core.sent) == ("needs_handler", ["iban"], [])


async def test_agent_cannot_change_amounts_or_personal_fields():
    p, missing = payload(event_country="AUT")
    err = (
        422,
        {"detail": [{"loc": ["body", "event_country"], "type": "not_in_code_list", "msg": "x"}]},
    )
    sneaky = dict(p, event_country="AT", total_payout="9999.00")
    core = FakeCore([err])
    gw = FakeGateway(
        [
            {"tool_calls": [call("submit_claim", {"payload": sneaky})]},
            {"text": '{"status": "registered", "core_claim_id": "CCS-FAKE"}'},
        ]
    )
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    assert len(core.sent) == 1  # the sneaky payload was never sent
    assert r.status == "needs_handler"  # a self-reported registration does not count
    assert r.core_claim_id is None


async def test_core_errors_reach_the_agent_without_input_echoes():
    p, missing = payload(event_country="AUT")
    echo = {
        "detail": [
            {
                "loc": ["body", "insured"],
                "type": "x",
                "msg": "bad insured Jana Kováčová",
                "input": {"name": "Jana Kováčová", "birth_number": "905605/0003"},
            }
        ]
    }
    core = FakeCore([(422, echo)])
    gw = FakeGateway([{"text": '{"status": "needs_handler", "fields": ["insured.name"]}'}])
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    seen = json.dumps(
        [m.model_dump() for req in gw.requests for m in req.messages], ensure_ascii=False
    )
    assert "Kováčová" not in seen and "905605" not in seen
    assert r.fields == ["insured.name"]


def test_unreadable_claimed_amount_goes_back_to_the_handler():
    _, missing = map_payload(
        policy_number="CP12345678",
        claim_type=ClaimType.MEDICAL,
        insured_token="<PERSON_1>",
        birth_number_token="<RC_1>",
        iban_token="<IBAN_1>",
        event_date=date(2026, 2, 14),
        event_country="AT",
        items=[
            {
                "ref": "I1",
                "coverage": Coverage.MEDICAL,
                "claimed_eur": None,
                "payout_eur": Decimal("0"),
                "clauses": [],
            }
        ],
        handler_id="h",
    )
    assert missing == ["items.I1.claimed_eur"]


async def test_unknown_code_list_is_an_answer_not_a_crash():
    p, missing = payload(event_country="AUT")
    err = (
        422,
        {"detail": [{"loc": ["body", "event_country"], "type": "not_in_code_list", "msg": "x"}]},
    )
    core = FakeCore([err])
    gw = FakeGateway(
        [
            {"tool_calls": [call("get_code_list", {"name": "event_date"})]},
            {"text": '{"status": "needs_handler", "fields": ["event_country"]}'},
        ]
    )
    r = await submit(p, missing, mapping=MAPPING, core=core, gateway=gw, idempotency_key="k")
    assert r.status == "needs_handler"
    assert "no code list" in gw.requests[-1].messages[-1].content
