"""Day 1 smoke tests against the local models.

Checks that the stack can do what the pipeline needs before any step is built: schema JSON with
thinking off, tool calling, Slovak and German writing, the vision model, embeddings, and MPS in
the native worker environment. Writes `evals/reports/smoke-<date>.md`.

    uv run claimpilot-smoke
"""

import asyncio
import base64
import io
import json
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.prompts import load_prompt
from claimpilot_core.llm.types import LLMRequest
from claimpilot_core.logging import configure_logging
from claimpilot_core.settings import get_settings, repo_root

INVOICE_TEXT = """Privatklinik Alpenblick GmbH, Dorfstrasse 12, 6370 Kitzbühel, Österreich
RECHNUNG Nr. AK-2026-04417        Datum: 14.02.2026
Patient: <PERSON_1>
Pos  Leistung                         Betrag
1    Ambulante Untersuchung           120,00
2    Röntgen Handgelenk                95,50
3    Gipsverband                       64,00
Gesamtbetrag                          279,50 EUR
Zahlbar innerhalb 14 Tagen."""


class InvoiceLine(BaseModel):
    description: str
    amount: Decimal


class SmokeInvoice(BaseModel):
    invoice_number: str
    issue_date: str
    currency: str
    total: Decimal
    line_items: list[InvoiceLine]


class VisionInvoice(BaseModel):
    invoice_number: str
    total: Decimal
    currency: str


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    seconds: float
    extra: dict = field(default_factory=dict)


def _invoice_image() -> str:
    img = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    lines = [
        "Farmacia Centrale, Via Roma 8, Milano",
        "FATTURA N. FC-88123     Data 03/03/2026",
        "Ibuprofene 400mg            12,40",
        "Garza sterile                 6,90",
        "TOTALE EUR                   19,30",
    ]
    for i, line in enumerate(lines):
        draw.text((40, 40 + i * 70), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def _timed(name: str, coro) -> Check:
    started = time.perf_counter()
    try:
        ok, detail, extra = await coro
    except Exception as exc:
        ok, detail, extra = False, f"{type(exc).__name__}: {exc}", {}
    return Check(name, ok, detail, time.perf_counter() - started, extra)


async def check_json(gw: LLMGateway, think: bool) -> tuple[bool, str, dict]:
    spec = gw.spec_for("smoke").model_copy(update={"think": think})
    gen = await gw.generate_json(
        "smoke", "smoke/invoice_json", SmokeInvoice, {"text": INVOICE_TEXT}, spec=spec
    )
    v = gen.value
    ok = (
        v.invoice_number == "AK-2026-04417"
        and v.total == Decimal("279.50")
        and v.currency == "EUR"
        and len(v.line_items) == 3
    )
    usage = gen.response.usage
    detail = (
        f"{spec.model} think={think}: {usage.tokens_out} output tokens, {usage.latency_ms} ms, "
        f"thinking chars={len(gen.response.thinking or '')}, values {'exact' if ok else 'WRONG'}, "
        f"attempts={gen.attempts}"
        + (f" (first reply failed: {gen.errors[0].splitlines()[1:3]})" if gen.errors else "")
    )
    return ok, detail, {"tokens_out": usage.tokens_out, "latency_ms": usage.latency_ms}


async def check_tools(gw: LLMGateway) -> tuple[bool, str, dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_code_list",
                "description": "Return the allowed codes for a field of the core claims system.",
                "parameters": {
                    "type": "object",
                    "properties": {"field": {"type": "string", "enum": ["claim_type", "country"]}},
                    "required": ["field"],
                },
            },
        }
    ]
    from claimpilot_core.llm.types import ChatMessage

    req = LLMRequest(
        step="smoke",
        spec=gw.spec_for("smoke"),
        messages=[
            ChatMessage(
                role="user",
                content="Before submitting a claim, find which claim_type codes the core "
                "system accepts. Use the tool.",
            )
        ],
    )
    _, message = await gw.client.chat(req, tools=tools)
    calls = message.get("tool_calls") or []
    ok = bool(calls) and calls[0]["function"]["name"] == "get_code_list"
    args = calls[0]["function"].get("arguments") if calls else None
    return ok, f"tool_calls={json.dumps(calls, ensure_ascii=False)[:200]}", {"args": args}


async def check_text(gw: LLMGateway, prompt_id: str, variables: dict, must: list[str]) -> tuple:
    gen = await gw.generate_text("smoke", prompt_id, variables)
    text = gen.value
    missing = [m for m in must if m.lower() not in text.lower()]
    ok = not missing
    detail = f"{len(text.split())} words; missing={missing}"
    return ok, detail, {"text": text}


async def check_vision(gw: LLMGateway) -> tuple[bool, str, dict]:
    spec = gw.spec_for("extraction_vision")
    gen = await gw.generate_json(
        "extraction_vision",
        "smoke/vision_invoice",
        VisionInvoice,
        {},
        images=[_invoice_image()],
        spec=spec,
    )
    v = gen.value
    ok = v.invoice_number == "FC-88123" and v.total == Decimal("19.30") and v.currency == "EUR"
    return ok, f"{spec.model}: {v.model_dump_json()} in {gen.response.usage.latency_ms} ms", {}


async def check_embeddings(gw: LLMGateway) -> tuple[bool, str, dict]:
    texts = [
        "Poistenie sa nevzťahuje na úrazy pod vplyvom alkoholu.",
        "Výluka: škody spôsobené po požití alkoholických nápojov.",
        "Batožina bola stratená leteckou spoločnosťou.",
    ]
    vecs = await gw.embed(texts)

    def cos(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb)

    related, unrelated = cos(vecs[0], vecs[1]), cos(vecs[0], vecs[2])
    ok = len(vecs[0]) == 1024 and related > unrelated
    return (
        ok,
        f"dim={len(vecs[0])}, alcohol~alcohol {related:.3f} > alcohol~luggage {unrelated:.3f}",
        {},
    )


async def check_mps() -> tuple[bool, str, dict]:
    import torch

    ok = torch.backends.mps.is_available()
    return ok, f"torch {torch.__version__}, mps available={ok}", {}


async def run() -> list[Check]:
    gw = LLMGateway()
    try:
        available = set(await gw.client.list_models())
        needed = {gw.spec_for(s).model for s in ("smoke", "extraction_vision", "summaries")}
        needed.add(gw.embedding_model)
        missing = {m for m in needed if m not in available and f"{m}:latest" not in available}
        checks = [
            Check("models pulled", not missing, f"missing={sorted(missing)}", 0.0),
            await _timed("MPS in worker env", check_mps()),
            await _timed("JSON schema, thinking off", check_json(gw, think=False)),
            await _timed("JSON schema, thinking on", check_json(gw, think=True)),
            await _timed("Tool calling", check_tools(gw)),
            await _timed(
                "Slovak formal letter",
                check_text(
                    gw,
                    "smoke/letter_sk",
                    {
                        "name": "Ing. Jana Kováčová",
                        "reference": "CP-2026-000123",
                        "amount": "214,50",
                        "deductible": "65,00",
                    },
                    ["214,50", "Vážen", "čl. 7"],
                ),
            ),
            await _timed(
                "German group summary",
                check_text(
                    gw,
                    "smoke/summary_de",
                    {
                        "facts": "Schadenfall CP-2026-000123, Produkt Standard. "
                        "Handgelenksbruch beim Skifahren in Kitzbühel am 14.02.2026. "
                        "Rechnung 279,50 EUR. Selbstbehalt 65,00 EUR. "
                        "Empfehlung: Auszahlung 214,50 EUR."
                    },
                    ["214,50", "Kitzbühel"],
                ),
            ),
            await _timed("Vision model on a rendered invoice", check_vision(gw)),
            await _timed("Embeddings (bge-m3)", check_embeddings(gw)),
        ]
    finally:
        await gw.aclose()
    return checks


def write_report(checks: list[Check], out: Path) -> None:
    lines = [
        f"# Smoke report {date.today().isoformat()}",
        "",
        "| Check | Result | Seconds | Detail |",
        "| --- | --- | ---: | --- |",
    ]
    for c in checks:
        detail = c.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c.name} | {'pass' if c.ok else 'FAIL'} | {c.seconds:.1f} | {detail} |")
    texts = [(c.name, c.extra["text"]) for c in checks if "text" in c.extra]
    if texts:
        lines += ["", "## Generated text for manual review", ""]
        for name, text in texts:
            lines += [f"### {name}", "", text, ""]
    prompts = ["smoke/invoice_json", "smoke/letter_sk", "smoke/summary_de", "smoke/vision_invoice"]
    lines += ["", "Prompts: " + ", ".join(load_prompt(p).tag for p in prompts)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    configure_logging("WARNING")
    get_settings()
    checks = asyncio.run(run())
    out = repo_root() / "evals" / "reports" / f"smoke-{date.today().isoformat()}.md"
    write_report(checks, out)
    for c in checks:
        print(f"{'PASS' if c.ok else 'FAIL'}  {c.name:38} {c.seconds:6.1f}s  {c.detail}")
    print(f"report: {out}")
    raise SystemExit(0 if all(c.ok for c in checks) else 1)


if __name__ == "__main__":
    main()
