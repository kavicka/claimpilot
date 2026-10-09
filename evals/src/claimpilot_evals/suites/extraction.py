"""Extraction: field accuracy against ground truth, grounding, calibration and payload leakage.

Document types come from ground truth here, so a typing error does not hide an extraction error.
Few-shot source documents are left out of the metrics.
"""

import json
import re
from itertools import pairwise
from typing import Any

from rapidfuzz import fuzz

from claimpilot_core.domain import DocType
from claimpilot_core.fields import kind_of, normalize
from claimpilot_core.pii.guard import fold, rehydrate
from claimpilot_core.schemas.documents import CRITICAL_FIELDS
from claimpilot_core.settings import get_settings
from claimpilot_evals.cache import page_image
from claimpilot_evals.report import ItemResult, Report
from claimpilot_evals.suites.common import RunContext, redact_claim
from claimpilot_worker.extraction.extract import extract_document, extract_document_vision

FREE_TEXT = {"event_description", "anamnesis", "treatment", "remarks", "incident_description"}
FEWSHOT_SOURCES: set[str] = set()


def _fewshot_sources() -> set[str]:
    if not FEWSHOT_SOURCES:
        from claimpilot_core.settings import get_settings

        for path in (get_settings().prompts_dir / "extraction" / "examples").glob("*.json"):
            FEWSHOT_SOURCES.update(e["source"] for e in json.loads(path.read_text("utf-8")))
    return FEWSHOT_SOURCES


def flatten_gt(fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, f in fields.items():
        if isinstance(f, list):
            for i, row in enumerate(f):
                for k, v in row.items():
                    out[f"{name}[{i}].{k}"] = v
        elif isinstance(f.get("printed"), list):
            out[name] = {
                "printed": json.dumps(f["printed"], ensure_ascii=False) if f["printed"] else None,
                "norm": f["printed"],
            }
        else:
            out[name] = f
    return out


DASHES = str.maketrans({"–": "-", "—": "-", "‒": "-", "−": "-"})


def _text_eq(a: str, b: str, *, fuzzy: bool) -> bool:
    fa = " ".join(fold(a.translate(DASHES)).split())
    fb = " ".join(fold(b.translate(DASHES)).split())
    if sum(c.isdigit() for c in fb) >= 0.6 * len(fb.replace(" ", "")):  # phone, IBAN, numbers
        fa, fb = fa.replace(" ", ""), fb.replace(" ", "")
    if fa == fb:
        return True
    return fuzzy and fuzz.ratio(fa, fb) >= 90


def correct(
    name: str,
    gt: dict[str, Any],
    pred_raw: str | None,
    mapping: dict[str, str],
    country: str | None,
) -> bool | None:
    """True/False when comparable; None when both sides are empty."""
    gt_printed = gt.get("printed")
    if gt_printed is None and pred_raw is None:
        return None
    if gt_printed is None or pred_raw is None:
        return False
    pred = rehydrate(pred_raw, mapping)
    leaf = name.rsplit(".", 1)[-1].split("[")[0]
    kind = kind_of(name)
    if kind != "text":
        return normalize(name, pred, country=country) == normalize(
            name, gt_printed, country=country
        )
    if name in ("claim_types", "traveler_names"):
        try:
            got = sorted(fold(x) for x in json.loads(pred))
        except (ValueError, TypeError):
            return False
        return got == sorted(fold(x) for x in gt["norm"])
    return _text_eq(pred, gt_printed, fuzzy=leaf in FREE_TEXT)


ROW = re.compile(r"^(\w+)\[(\d+)\]\.(\w+)$")


def _rows(names: dict[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
    out: dict[str, dict[int, dict[str, Any]]] = {}
    for name, value in names.items():
        if m := ROW.match(name):
            out.setdefault(m[1], {}).setdefault(int(m[2]), {})[m[3]] = value
    return out


def align_rows(
    pred: dict[str, Any], gt: dict[str, Any], mapping: dict[str, str], country: str | None
) -> dict[str, Any]:
    """Match list rows (invoice lines, claimed items) by content, not position. Downstream code
    uses their sum and their set; a model that lists rows in another order did not misread them."""
    out = {n: f for n, f in pred.items() if not ROW.match(n)}
    gt_rows = _rows(gt)
    for lst, prow in _rows(pred).items():
        grow = gt_rows.get(lst, {})

        def score(pi: int, gi: int, lst: str = lst, prow=prow, grow=grow) -> int:
            hits = 0
            for k, g in grow[gi].items():
                f = prow[pi].get(k)
                ok = correct(f"{lst}[{gi}].{k}", g, f.value_raw if f else None, mapping, country)
                hits += bool(ok)
            return hits

        pairs = sorted(
            ((score(pi, gi), pi == gi, pi, gi) for pi in prow for gi in grow), reverse=True
        )
        assign: dict[int, int] = {}
        for hits, _, pi, gi in pairs:
            if hits and pi not in assign and gi not in assign.values():
                assign[pi] = gi
        extra = max(grow, default=-1) + 1
        for pi in sorted(prow):
            if pi not in assign:
                assign[pi], extra = extra, extra + 1
        for pi, fields in prow.items():
            for k, f in fields.items():
                out[f"{lst}[{assign[pi]}].{k}"] = f
    return out


async def run(ctx: RunContext) -> Report:
    report = Report("extraction", ctx.split)
    scan_path = ctx.options.get("scan_path", get_settings().scan_path)  # the pipeline's default
    report.meta["scan_path"] = scan_path
    sources = _fewshot_sources()
    gt_values: list[str] = []
    calib: list[tuple[float, bool]] = []
    skipped = 0
    for claim in ctx.claims():
        rc = redact_claim(claim)
        mapping = {t: v for t, (_, v) in rc.redactor.mapping().items()}
        gt_values += [v for _, v in claim.pii_values()]
        for doc in rc.docs:
            if doc.gt.item_id in sources or (
                ctx.options.get("only_scans") and not doc.gt.data["scan"]
            ):
                skipped += 1
                continue
            doc_type = DocType(doc.gt.doc_type)
            if scan_path == "vision" and doc.gt.data["scan"]:
                images = [
                    page_image(doc.gt.path, p.page, doc.gt.data["sha256"]) for p in doc.parsed.pages
                ]
                ex = await extract_document_vision(
                    doc_type,
                    images,
                    doc.parsed,
                    doc.redacted,
                    ctx.gateway,
                    tokenize=rc.redactor.tokenize,
                    mapping=mapping,
                )
            else:
                ex = await extract_document(
                    doc_type,
                    doc.parsed,
                    doc.redacted,
                    ctx.gateway,
                    language=doc.gt.data["language"],
                    mapping=mapping,
                    exclude_example=doc.gt.item_id,
                )

            country = "US" if doc.gt.data["locale"] == "en-us" else None
            gt = flatten_gt(doc.gt.data["fields"])
            pred = align_rows({f.name: f for f in ex.fields}, gt, mapping, country)
            critical = set(CRITICAL_FIELDS.get(doc_type, []))
            for name in sorted(set(gt) | set(pred)):
                g = gt.get(name, {"printed": None, "norm": None})
                p = pred.get(name)
                ok = correct(name, g, p.value_raw if p else None, mapping, country)
                if ok is None:
                    continue
                tags = ["all_field_f1"] + (["critical_field_accuracy"] if name in critical else [])
                detail = {
                    "doc_type": doc_type.value,
                    "scan": doc.gt.data["scan"],
                    "language": doc.gt.data["language"],
                    "grounded": p.grounded if p else None,
                    "confidence": p.confidence if p else None,
                    "quote": (p.quote or "")[:80] if p else None,
                    "kind": "fp"
                    if g.get("printed") is None
                    else ("fn" if p is None or p.value_raw is None else "pair"),
                }
                if p and p.value_raw is not None:
                    calib.append((p.confidence, bool(ok)))
                report.items.append(
                    ItemResult(
                        f"{doc.gt.item_id}/{name}",
                        bool(ok),
                        g.get("printed"),
                        rehydrate(p.value_raw, mapping) if p and p.value_raw else None,
                        tags,
                        detail,
                    )
                )
    crit = [i for i in report.items if "critical_field_accuracy" in i.tags]
    report.ratio("critical_field_accuracy", sum(i.ok for i in crit), len(crit))
    tp = sum(1 for i in report.items if i.ok)
    fp = sum(1 for i in report.items if not i.ok and i.detail["kind"] in ("fp", "pair"))
    fn = sum(1 for i in report.items if not i.ok and i.detail["kind"] in ("fn", "pair"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    report.metrics["all_field_f1"] = report.metrics.get("all_field_f1") or _metric(
        f1, tp, tp + fp + fn
    )
    report.ratio("all_field_precision", tp, tp + fp)
    report.ratio("all_field_recall", tp, tp + fn)
    grounded = [i for i in report.items if i.detail.get("grounded") is not None]
    report.ratio("grounded_share", sum(bool(i.detail["grounded"]) for i in grounded), len(grounded))
    report.count("leaked_values_in_payloads", len(ctx.recorder.leaks(gt_values)))
    report.metrics["calibration_error"] = _metric(_ece(calib), len(calib), 0)
    report.meta["calibration_bins"] = _bins(calib)
    # Straight-through candidates: claims where every critical field is confident (>= 0.9);
    # "correct" says whether that confidence was deserved.
    per_claim: dict[str, list[tuple[bool, float]]] = {}
    for i in crit:
        per_claim.setdefault(i.id.split("/")[0], []).append(
            (i.ok, i.detail.get("confidence") or 0.0)
        )
    confident = [c for c, rows in per_claim.items() if all(conf >= 0.9 for _, conf in rows)]
    report.ratio("straight_through_rate", len(confident), len(per_claim))
    report.ratio(
        "straight_through_correct",
        sum(all(ok for ok, _ in per_claim[c]) for c in confident),
        len(confident),
    )
    report.notes.append(f"{skipped} few-shot source documents left out of the metrics")
    by_type: dict[str, list[bool]] = {}
    for i in crit:
        by_type.setdefault(i.detail["doc_type"], []).append(i.ok)
    for t, oks in sorted(by_type.items()):
        report.notes.append(f"critical {t}: {sum(oks)}/{len(oks)}")
    scans = [i.ok for i in crit if i.detail["scan"]]
    clean = [i.ok for i in crit if not i.detail["scan"]]
    report.notes.append(
        f"critical on scans {sum(scans)}/{len(scans)}, on digital PDFs {sum(clean)}/{len(clean)}"
    )
    return report


def _metric(value: float, num: int, den: int):
    from claimpilot_evals.report import Metric

    return Metric(value, num, den)


def _bins(calib: list[tuple[float, bool]]) -> list[dict[str, float]]:
    edges = [0.0, 0.3, 0.5, 0.7, 0.85, 0.95, 1.01]
    out = []
    for lo, hi in pairwise(edges):
        rows = [ok for c, ok in calib if lo <= c < hi]
        if rows:
            out.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "n": len(rows),
                    "accuracy": round(sum(rows) / len(rows), 3),
                    "mean_conf": round(sum(c for c, _ in calib if lo <= c < hi) / len(rows), 3),
                }
            )
    return out


def _ece(calib: list[tuple[float, bool]]) -> float:
    total = len(calib)
    if not total:
        return 0.0
    return round(sum(b["n"] / total * abs(b["accuracy"] - b["mean_conf"]) for b in _bins(calib)), 4)
