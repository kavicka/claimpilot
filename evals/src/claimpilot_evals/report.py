"""Eval reports: metrics, per-item results and everything needed to reproduce the run."""

import json
import resource
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from claimpilot_core.llm.gateway import CallRecord
from claimpilot_core.settings import repo_root

REPORTS = repo_root() / "evals" / "reports"


@dataclass
class Metric:
    value: float
    num: int
    den: int

    def show(self) -> str:
        return f"{self.value:.1%} ({self.num}/{self.den})" if self.den else f"{self.num}"


@dataclass
class ItemResult:
    id: str
    ok: bool
    expected: Any = None
    got: Any = None
    tags: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    suite: str
    split: str
    metrics: dict[str, Metric] = field(default_factory=dict)
    items: list[ItemResult] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    ops: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)  # prompt ids with no cassette in replay mode

    def ratio(self, name: str, num: int, den: int) -> None:
        self.metrics[name] = Metric(num / den if den else 0.0, num, den)

    def count(self, name: str, n: int) -> None:
        self.metrics[name] = Metric(float(n), n, 0)

    def failures(self, n: int = 10) -> list[ItemResult]:
        return [i for i in self.items if not i.ok][:n]


def git_meta() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(  # noqa: S603 - fixed git arguments
                ["git", *args],  # noqa: S607
                cwd=repo_root(),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    return {"sha": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def ops_from_calls(calls: list[CallRecord], per: int) -> dict[str, Any]:
    lat = sorted(c.latency_ms for c in calls if not c.cached)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    return {
        "llm_calls": len(calls),
        "cached_calls": sum(c.cached for c in calls),
        "tokens_in": sum(c.tokens_in for c in calls),
        "tokens_out": sum(c.tokens_out for c in calls),
        "tokens_per_item": round(sum(c.tokens_in + c.tokens_out for c in calls) / per, 1)
        if per
        else 0,
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": p95,
        "worker_peak_rss_mb": round(peak_mb),
        "models": sorted({c.model for c in calls}),
    }


def _md(r: Report) -> str:
    lines = [f"# Eval `{r.suite}` on `{r.split}`", ""]
    m = r.meta
    lines.append(
        f"Run {m.get('created')} · git {m.get('git', {}).get('sha')}"
        f"{' (dirty)' if m.get('git', {}).get('dirty') else ''}"
        f" · dataset {m.get('dataset')} · cassettes {m.get('cassette_mode')}"
    )
    lines += ["", "| Metric | Value |", "| --- | ---: |"]
    lines += [f"| {k} | {v.show()} |" for k, v in r.metrics.items()]
    if r.ops:
        lines += ["", "| Ops | Value |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in r.ops.items()]
    if r.stale:
        lines += ["", f"**Stale cassettes:** {', '.join(r.stale)}"]
    if r.notes:
        lines += ["", *[f"- {n}" for n in r.notes]]
    fails = r.failures(10)
    if fails:
        lines += [
            "",
            "## Top failures",
            "",
            "| Item | Expected | Got | Detail |",
            "| --- | --- | --- | --- |",
        ]
        for f in fails:
            detail = json.dumps(f.detail, ensure_ascii=False)[:160].replace("|", "\\|")
            lines.append(f"| {f.id} | {str(f.expected)[:60]} | {str(f.got)[:60]} | {detail} |")
    return "\n".join(lines) + "\n"


def write(r: Report) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    r.meta.setdefault("created", stamp)
    base = REPORTS / f"{stamp}-{r.suite}-{r.split}"
    data = asdict(r)
    base.with_suffix(".json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), "utf-8"
    )
    base.with_suffix(".md").write_text(_md(r), "utf-8")
    return base.with_suffix(".json")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def latest(suite: str, split: str) -> Path | None:
    found = sorted(REPORTS.glob(f"*-{suite}-{split}.json"))
    return found[-1] if found else None
