"""Compare a report with its baseline and apply the gate rules from config/evals.yaml.

    uv run claimpilot-eval-compare --latest            # every suite with a baseline
    uv run claimpilot-eval-compare --suite pii

Exit code 1 when any gate trips or a suite is stale (a prompt changed without a new recording).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from claimpilot_core.settings import repo_root
from claimpilot_evals.report import Metric, latest, load

BASELINES = repo_root() / "evals" / "baselines"


def gates() -> dict[str, dict[str, dict]]:
    return yaml.safe_load((repo_root() / "config" / "evals.yaml").read_text("utf-8"))["suites"]


def _failed_ids(report: dict[str, Any], metric: str) -> set[str]:
    """Items that count against a metric. Items carry tags naming the metrics they belong to."""
    return {
        i["id"] for i in report["items"] if not i["ok"] and (not i["tags"] or metric in i["tags"])
    }


def check(report: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    problems: list[str] = []
    suite = report["suite"]
    if report.get("stale"):
        problems.append(
            f"{suite}: stale cassettes for {', '.join(report['stale'])}; run `make eval` and commit"
        )
    for name, rule in gates().get(suite, {}).items():
        metric = report["metrics"].get(name)
        if metric is None:
            continue
        kind = rule["gate"]
        if kind == "zero":
            if metric["num"] > 0:
                problems.append(f"{suite}.{name} = {metric['num']} (must be 0)")
            continue
        if baseline is None or name not in baseline["metrics"]:
            continue
        base = baseline["metrics"][name]
        if kind == "item_level":
            drop_pp = (base["value"] - metric["value"]) * 100
            if drop_pp > rule.get("max_drop_pp", 1.0):
                problems.append(
                    f"{suite}.{name} dropped {drop_pp:.1f} pp "
                    f"({base['value']:.1%} -> {metric['value']:.1%})"
                )
        elif kind == "claim_level":
            new = _failed_ids(report, name) - _failed_ids(baseline, name)
            if len(new) > rule.get("max_new_failures", 0):
                problems.append(
                    f"{suite}.{name}: {len(new)} newly failing ({', '.join(sorted(new)[:6])})"
                )
    return problems


def _show(m: dict[str, Any]) -> str:
    return Metric(m["value"], m["num"], m["den"]).show()


def deltas(report: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    out = []
    for name, m in report["metrics"].items():
        if baseline and name in baseline["metrics"]:
            out.append(f"  {name}: {_show(baseline['metrics'][name])} -> {_show(m)}")
        else:
            out.append(f"  {name}: {_show(m)}")
    return out


def compare_suite(suite: str, split: str, report_path: Path | None = None) -> list[str]:
    path = report_path or latest(suite, split)
    if path is None:
        return [f"{suite}: no report for split {split}"]
    report = load(path)
    base_path = BASELINES / f"{suite}-{split}.json"
    baseline = json.loads(base_path.read_text("utf-8")) if base_path.exists() else None
    print(f"{suite} ({path.name}) vs {'baseline' if baseline else 'no baseline'}")
    print("\n".join(deltas(report, baseline)))
    problems = check(report, baseline)
    for p in problems:
        print(f"  GATE: {p}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(prog="claimpilot-eval-compare")
    parser.add_argument("--suite")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--latest", action="store_true", help="every suite that has a baseline")
    args = parser.parse_args()
    suites = (
        [args.suite]
        if args.suite
        else sorted({p.stem.rsplit("-", 1)[0] for p in BASELINES.glob("*.json")})
    )
    problems = []
    for suite in suites:
        problems += compare_suite(suite, args.split)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
