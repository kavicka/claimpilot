"""Generate the synthetic dataset.

    uv run claimpilot-datagen generate --seed 42          # 60 claims into data/synthetic/claims
    uv run claimpilot-datagen generate --seed 42 --no-llm # template narratives only

Writes per claim: the documents and ground_truth.json. Writes per split: manifest-<split>.json
(committed; generated files are not). Writes policies.json, the policy register core_mock serves.
"""

import argparse
import hashlib
import json
import random
import shutil
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from claimpilot_core.fx import FxSnapshot
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.logging import configure_logging
from claimpilot_core.policy import load_products
from claimpilot_core.settings import repo_root
from claimpilot_datagen.documents import DocumentBuilder
from claimpilot_datagen.model import Scenario
from claimpilot_datagen.narrative import Narrator
from claimpilot_datagen.reference import apply_reference_payout
from claimpilot_datagen.render import render
from claimpilot_datagen.scenarios import Sampler

GENERATOR_VERSION = "1.1"  # 1.1: dates of birth are PII in the ground truth


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value))


def _dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=_json_default) + "\n", "utf-8"
    )


def ground_truth(s: Scenario, docs: list[dict], fx: FxSnapshot) -> dict:
    p = s.person
    return {
        "scenario_id": s.scenario_id,
        "split": s.split,
        "archetype": s.archetype,
        "edge_cases": sorted(set(s.edge_cases)),
        "claim_type": s.claim_type,
        "product": s.product,
        "policy_number": s.policy.policy_number,
        "duplicate_of": s.duplicate_of,
        "destination": s.destination.code,
        "trip": {"start": s.trip_start, "end": s.trip_end},
        "event_date": s.event_date,
        "expected": {
            "status": s.expected_status,
            "queue": s.expected_queue,
            "rule": s.expected_rule,
            "total_payout_eur": s.expected_total_payout_eur,
            "deductible_eur": s.expected_deductible_eur,
            "by_coverage": s.expected_by_coverage,
        },
        "items": [
            {
                "ref": i.ref,
                "description_sk": i.description_sk,
                "coverage": i.coverage,
                "category": i.category,
                "amount": i.amount,
                "currency": i.currency,
                "amount_eur": fx.to_eur(i.amount, i.currency),
                "doc_id": i.doc_id,
                "verdict": i.verdict,
                "clause_ids": i.clause_ids,
                "exclusion": i.exclusion,
                "valuables": i.valuables,
            }
            for i in s.items
        ],
        "documents": docs,
        "insured": {
            "name": p.full_name,
            "birth_number": p.birth_number,
            "birth_date": p.birth_date,
            "address": p.address,
            "phone": p.phone,
            "email": p.email,
            "iban": p.iban,
            "id_card": p.id_card,
            "czech": p.czech,
        },
        "facts": s.facts,
    }


def policy_register(scenarios: list[Scenario]) -> list[dict]:
    seen: dict[str, dict] = {}
    for s in scenarios:
        pol = s.policy
        seen[pol.policy_number] = {
            "policy_number": pol.policy_number,
            "product": pol.product,
            "kind": pol.kind,
            "start": pol.start,
            "end": pol.end,
            "issue_date": pol.issue_date,
            "premium": pol.premium,
            "insured": [{"name": x.full_name, "birth_number": x.birth_number} for x in pol.insured],
            "prior_paid": {str(k): v for k, v in pol.prior_paid.items()},
        }
    return sorted(seen.values(), key=lambda r: r["policy_number"])


def generate(seed: int, out: Path, *, use_llm: bool, limit: int | None = None) -> dict:
    root = repo_root()
    fx = FxSnapshot.load(root / "config" / "fx_rates.yaml")
    catalog = load_products(root / "data" / "policies" / "products.yaml")
    scenarios = Sampler(seed, fx).build()
    for s in scenarios:
        apply_reference_payout(s, catalog, fx)
    if limit:
        scenarios = scenarios[:limit]

    gateway = LLMGateway() if use_llm else None
    narrator = Narrator(root / "data" / "generator" / "narratives.json", gateway)
    builder = DocumentBuilder(catalog, narrator)

    claims_dir = out / "claims"
    if claims_dir.exists():
        shutil.rmtree(claims_dir)
    claims_dir.mkdir(parents=True)
    manifests: dict[str, list[dict]] = {"dev": [], "test": []}
    files_by_ref: dict[str, Path] = {}
    docs_gt_all: dict[str, list[dict]] = {}

    for s in scenarios:
        cdir = claims_dir / s.scenario_id
        cdir.mkdir()
        docs_gt = []
        for d in s.docs:
            built = builder.build(s, d)
            rng = random.Random(f"{seed}/{s.scenario_id}/{d.doc_id}")
            if d.copy_of:
                src = files_by_ref[d.copy_of]
                data, ext = src.read_bytes(), src.suffix.lstrip(".")
                src_sid, src_doc = d.copy_of.split("/")
                original = next(x for x in docs_gt_all[src_sid] if x["doc_id"] == src_doc)
                pages, pii, dpi = original["pages"], original["pii"], original.get("scan_dpi")
            else:
                r = render(built, d, rng)
                data, ext, pages, pii, dpi = r.data, r.ext, r.pages, r.pii, r.dpi
            name = f"{d.doc_id}_{d.doc_type.value}.{ext}"
            path = cdir / name
            path.write_bytes(data)
            files_by_ref[f"{s.scenario_id}/{d.doc_id}"] = path
            docs_gt.append({
                "doc_id": d.doc_id,
                "file": name,
                "doc_type": d.doc_type,
                "language": d.language,
                "locale": d.locale,
                "scan": d.scan or bool(d.copy_of and dpi),
                "scan_dpi": dpi,
                "image_format": ext if ext != "pdf" else None,
                "handwriting": d.handwriting,
                "injection": d.injection is not None,
                "copy_of": d.copy_of,
                "reprint_of": d.reprint_of,
                "pages": pages,
                "sha256": hashlib.sha256(data).hexdigest(),
                "fields": built.fields,
                "pii": pii,
            })  # fmt: skip
        docs_gt_all[s.scenario_id] = docs_gt
        gt = ground_truth(s, docs_gt, fx)
        _dump(cdir / "ground_truth.json", gt)
        manifests[s.split].append({
            "scenario_id": s.scenario_id,
            "archetype": s.archetype,
            "expected_queue": s.expected_queue,
            "expected_status": s.expected_status,
            "files": [{"file": x["file"], "sha256": x["sha256"]} for x in docs_gt],
        })  # fmt: skip
    narrator.save(prune=limit is None)
    for split, rows in manifests.items():
        _dump(
            out / f"manifest-{split}.json",
            {"seed": seed, "generator": GENERATOR_VERSION, "claims": rows},
        )
    _dump(out / "policies.json", policy_register(scenarios))
    return {
        "claims": len(scenarios),
        "documents": sum(len(s.docs) for s in scenarios),
        "narratives_generated": narrator.generated,
        "narratives_fallback": narrator.fallbacks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="claimpilot-datagen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", type=Path, default=None)
    g.add_argument("--no-llm", action="store_true")
    g.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    configure_logging("WARNING")
    out = args.out or repo_root() / "data" / "synthetic"
    stats = generate(args.seed, out, use_llm=not args.no_llm, limit=args.limit)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
