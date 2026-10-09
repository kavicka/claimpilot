"""Submission: a deterministic mapper fills every field it can; an agent handles code-list
mismatches and 422 errors, with at most 3 submissions. The agent works on tokenized values; the
submit tool re-hydrates them from the vault at the moment of sending (ADR-003). Anything missing
goes back to the handler instead of being guessed.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from claimpilot_core.domain import ClaimType, Coverage
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.prompts import load_prompt
from claimpilot_core.llm.types import ChatMessage, LLMRequest
from claimpilot_core.pii.guard import rehydrate
from claimpilot_worker.submission.core_client import CoreClient

CLAIM_TYPE_CODE = {
    ClaimType.MEDICAL: "MED",
    ClaimType.ACCIDENT: "ACC",
    ClaimType.LUGGAGE: "LUG",
    ClaimType.CANCELLATION: "CXL",
}
COVERAGE_CODE = {
    Coverage.MEDICAL: "MED",
    Coverage.ACCIDENT: "ACC",
    Coverage.LUGGAGE: "LUG",
    Coverage.DELAY: "DLY",
    Coverage.CANCELLATION: "CXL",
    Coverage.LIABILITY: "LIA",
}
MAX_SUBMITS = 3
MAX_TURNS = 8

CODE_LISTS = {"claim_type", "coverage", "country", "currency", "decision"}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_code_list",
            "description": "Allowed codes of the core system for one field.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": sorted(CODE_LISTS),
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_claim",
            "description": "Submit the claim payload (JSON object) to the core system.",
            "parameters": {
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
            },
        },
    },
]


@dataclass
class SubmissionResult:
    status: str  # registered | needs_handler | failed
    core_claim_id: str | None
    submissions: int
    first_try: bool
    used_agent: bool
    fields: list[str] = field(default_factory=list)
    final_payload: dict[str, Any] | None = None
    errors: list[Any] = field(default_factory=list)


def map_payload(
    *,
    policy_number: str | None,
    claim_type: ClaimType | None,
    insured_token: str | None,
    birth_number_token: str | None,
    iban_token: str | None,
    event_date: date | None,
    event_country: str | None,
    items: list[dict[str, Any]],
    handler_id: str,
) -> tuple[dict, list[str]]:
    """The payload with tokens, and the fields the mapper could not fill."""
    missing = [
        name
        for name, value in [
            ("policy_number", policy_number),
            ("claim_type_code", claim_type),
            ("insured.name", insured_token),
            ("insured.birth_number", birth_number_token),
            ("iban", iban_token),
            ("event_date", event_date),
            ("event_country", event_country),
        ]
        if not value
    ]
    missing += [f"items.{i['ref']}.claimed_eur" for i in items if i["claimed_eur"] is None]
    payout = sum((Decimal(str(i["payout_eur"])) for i in items), Decimal(0))
    payload = {
        "policy_number": policy_number,
        "claim_type_code": CLAIM_TYPE_CODE.get(claim_type) if claim_type else None,
        "insured": {"name": insured_token, "birth_number": birth_number_token},
        "event_date": event_date.isoformat() if event_date else None,
        "event_country": event_country,
        "iban": iban_token,
        "currency": "EUR",
        "total_payout": f"{payout:.2f}",
        "items": [
            {
                "ref": i["ref"],
                "coverage_code": COVERAGE_CODE.get(i["coverage"], str(i["coverage"])),
                "claimed_eur": f"{Decimal(str(i['claimed_eur'])):.2f}"
                if i["claimed_eur"] is not None
                else None,
                "payout_eur": f"{Decimal(str(i['payout_eur'])):.2f}",
                "decision": "PAY" if Decimal(str(i["payout_eur"])) > 0 else "DECLINE",
                "clause_refs": i["clauses"],
            }
            for i in items
        ],
        "handler_id": handler_id,
    }
    return payload, missing


def _hydrate(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return rehydrate(value, mapping)
    if isinstance(value, dict):
        return {k: _hydrate(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_hydrate(v, mapping) for v in value]
    return value


# The agent may change only code-list values; every other field must stay as the mapper built it.
CODE_FIELDS = {"claim_type_code", "event_country", "currency"}
ITEM_CODE_FIELDS = {"coverage_code"}
FIELD_PATH = re.compile(r"^[a-z_]+(\.[a-z0-9_]+)*$")


def changed_non_code_fields(original: dict[str, Any], new: dict[str, Any]) -> list[str]:
    bad = [
        k for k in original if k not in CODE_FIELDS and k != "items" and new.get(k) != original[k]
    ]
    bad += [k for k in new if k not in original]
    old_items, new_items = original.get("items", []), new.get("items", [])
    if len(old_items) != len(new_items):
        bad.append("items")
    for o, n in zip(old_items, new_items, strict=False):
        bad += [
            f"items.{o.get('ref')}.{k}" for k in o if k not in ITEM_CODE_FIELDS and n.get(k) != o[k]
        ]
    return bad


def scrub_errors(errors: Any, mapping: dict[str, str]) -> Any:
    """Core-system errors without echoes of the input, and with vault values turned back into
    tokens, before the agent (a model) sees them."""
    reverse = sorted(((v, k) for k, v in mapping.items() if v), key=lambda x: -len(x[0]))

    def tok(text: str) -> str:
        for value, token in reverse:
            text = text.replace(value, token)
        return text

    if isinstance(errors, list):
        return [scrub_errors(e, mapping) for e in errors]
    if isinstance(errors, dict):
        return {
            k: scrub_errors(v, mapping)
            for k, v in errors.items()
            if k not in ("input", "ctx", "url")
        }
    if isinstance(errors, str):
        return tok(errors)
    return errors


async def submit(
    payload: dict[str, Any],
    missing: list[str],
    *,
    mapping: dict[str, str],
    core: CoreClient,
    gateway: LLMGateway,
    idempotency_key: str,
) -> SubmissionResult:
    if missing:
        return SubmissionResult("needs_handler", None, 0, False, False, missing, payload)
    status, body = await core.submit(_hydrate(payload, mapping), idempotency_key)
    if status == 201:
        return SubmissionResult("registered", body["core_claim_id"], 1, True, False, [], payload)
    if status != 422:
        return SubmissionResult("failed", None, 1, False, False, [], payload, [body])
    return await _agent(
        payload,
        scrub_errors(body.get("detail", []), mapping),
        mapping=mapping,
        core=core,
        gateway=gateway,
        idempotency_key=idempotency_key,
    )


async def _agent(
    payload: dict[str, Any],
    first_errors: list[dict],
    *,
    mapping: dict[str, str],
    core: CoreClient,
    gateway: LLMGateway,
    idempotency_key: str,
) -> SubmissionResult:
    prompt = load_prompt("submission/agent", gateway.settings.prompts_dir)
    messages = prompt.render(payload=json.dumps(payload, ensure_ascii=False, indent=1))
    messages.append(
        ChatMessage(
            role="user",
            content="The first submission returned these errors:\n"
            + json.dumps(first_errors, ensure_ascii=False),
        )
    )
    submissions, last_payload = 1, payload
    errors: list[Any] = [first_errors]
    spec = gateway.spec_for("submission")
    for _ in range(MAX_TURNS):
        req = LLMRequest(
            step="submission",
            spec=spec,
            messages=messages,
            prompt_id=prompt.prompt_id,
            prompt_hash=prompt.sha,
        )
        resp = await gateway.complete(req, tools=TOOLS)
        if not resp.tool_calls:
            # Registration counts only when the core system answered 201 to a submit call (above).
            # Whatever the agent says at the end goes to the handler as a list of field names.
            try:
                final = json.loads(resp.text)
            except ValueError:
                final = {}
            fields = [
                f for f in final.get("fields", []) if isinstance(f, str) and FIELD_PATH.match(f)
            ]
            return SubmissionResult(
                "needs_handler",
                None,
                submissions,
                False,
                True,
                fields or ["(the agent could not fix the submission)"],
                last_payload,
                errors,
            )
        messages.append(
            ChatMessage(role="assistant", content=resp.text or "", tool_calls=resp.tool_calls)
        )
        for call in resp.tool_calls:
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            if fn.get("name") == "get_code_list":
                name = args.get("name", "")
                # The schema enum is a hint, not a guarantee: a model may ask for any field.
                result: Any = (
                    await core.code_list(name)
                    if name in CODE_LISTS
                    else {"error": f"no code list for {name!r}; lists: {sorted(CODE_LISTS)}"}
                )
            elif fn.get("name") == "submit_claim" and submissions < MAX_SUBMITS:
                candidate = args.get("payload") or {}
                bad = changed_non_code_fields(payload, candidate)
                if bad:
                    result = {"error": f"refused: only code-list fields may change, not {bad[:6]}"}
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=json.dumps(result, ensure_ascii=False),
                            tool_name=fn.get("name"),
                        )
                    )
                    continue
                last_payload = candidate
                submissions += 1
                status, body = await core.submit(_hydrate(last_payload, mapping), idempotency_key)
                if status == 201:
                    return SubmissionResult(
                        "registered",
                        body["core_claim_id"],
                        submissions,
                        False,
                        True,
                        [],
                        last_payload,
                        errors,
                    )
                clean = scrub_errors(body.get("detail", body), mapping)
                errors.append(clean)
                result = {"status": status, "errors": clean}
            else:
                result = {"error": "no more submissions allowed; report the fields to the handler"}
            messages.append(
                ChatMessage(
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False),
                    tool_name=fn.get("name"),
                )
            )
    return SubmissionResult(
        "needs_handler",
        None,
        submissions,
        False,
        True,
        ["(agent did not finish)"],
        last_payload,
        errors,
    )
