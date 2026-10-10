"""Eval runner.

uv run claimpilot-eval run --suite pii --split dev
uv run claimpilot-eval run --suite extraction --model extraction=qwen3:30b-a3b-instruct-2507-q4_K_M
uv run claimpilot-eval run --suite all --replay        # CI: recorded responses only
uv run claimpilot-eval baseline --suite pii            # promote the latest report
"""

import argparse
import asyncio
import importlib
import json
import shutil
import sys
from datetime import UTC, datetime

from claimpilot_core.llm.cassette import CassetteMissingError, CassetteMode
from claimpilot_core.llm.gateway import collect_calls
from claimpilot_core.llm.prompts import load_prompt
from claimpilot_core.logging import configure_logging
from claimpilot_evals.compare import BASELINES, compare_suite
from claimpilot_evals.report import Report, git_meta, latest, ops_from_calls, write
from claimpilot_evals.suites import SUITES
from claimpilot_evals.suites.common import RunContext


async def run_suite(name: str, ctx: RunContext) -> Report:
    module = importlib.import_module(f"claimpilot_evals.suites.{name}")
    with collect_calls() as calls:
        try:
            report = await module.run(ctx)
        except CassetteMissingError as exc:
            report = Report(name, ctx.split)
            report.stale.append(exc.request.prompt_id or "?")
            report.notes.append(str(exc))
    prompts = sorted({c.prompt for c in calls if c.prompt})
    report.meta.update(
        created=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        git=git_meta(),
        dataset=ctx.dataset.version(ctx.split),
        seed=ctx.dataset.manifest(ctx.split)["seed"],
        cassette_mode=ctx.cassette_mode.value,
        overrides=ctx.overrides,
        options=ctx.options,
        prompts={p: load_prompt(p).tag for p in prompts},
        models=sorted({c.model for c in calls}),
        limit=ctx.limit,
    )
    report.ops = ops_from_calls(calls, per=max(1, len(report.items)))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="claimpilot-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--suite", required=True, help=f"one of {SUITES} or 'all'")
    r.add_argument("--split", default="dev", choices=["dev", "test"])
    r.add_argument("--limit", type=int)
    r.add_argument("--model", action="append", default=[], help="step=model, or *=model")
    r.add_argument(
        "--opt", action="append", default=[], help="suite option key=value, e.g. scan_path=vision"
    )
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--replay", action="store_true")
    r.add_argument(
        "--fast", action="store_true", help="replay where recorded, call the model otherwise"
    )
    sub.add_parser("fewshot", help="rebuild extraction few-shot examples from dev")
    sub.add_parser(
        "adversarial-build", help="rebuild the prompt-injection cases in data/adversarial"
    )
    sub.add_parser("export-corrections", help="write handler corrections as a dataset (JSONL)")
    sd = sub.add_parser("seed", help="upload synthetic claims through the api")
    sd.add_argument("--split", default="dev")
    sd.add_argument("--n", type=int, default=5)
    sd.add_argument("--ids", nargs="*", help="scenario ids instead of the first n")
    b = sub.add_parser("baseline")
    b.add_argument("--suite", required=True)
    b.add_argument("--split", default="dev")
    args = parser.parse_args()
    configure_logging("WARNING")

    if args.cmd == "seed":
        from claimpilot_evals.seed import seed

        for row in seed(args.split, args.n, args.ids):
            print(row)
        return

    if args.cmd == "export-corrections":
        from claimpilot_evals.corrections import export

        print(asyncio.run(export()))
        return

    if args.cmd == "adversarial-build":
        from claimpilot_evals.adversarial import build as build_adversarial

        print(build_adversarial())
        return

    if args.cmd == "fewshot":
        from claimpilot_evals.fewshot import build

        for name, examples in build().items():
            print(f"{name}: {[e['source'] for e in examples]}")
        return

    if args.cmd == "baseline":
        src = latest(args.suite, args.split)
        if src is None:
            sys.exit(f"no report for {args.suite}/{args.split}")
        BASELINES.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, BASELINES / f"{args.suite}-{args.split}.json")
        print(f"baseline {args.suite}-{args.split} <- {src.name}")
        return

    cassette = (
        CassetteMode.RECORD
        if args.record
        else CassetteMode.REPLAY
        if args.replay
        else CassetteMode.AUTO
        if args.fast
        else CassetteMode.OFF
    )
    overrides = dict(m.split("=", 1) for m in args.model)
    suites = SUITES if args.suite == "all" else [args.suite]
    failed = False
    for name in suites:
        options = dict(o.split("=", 1) for o in args.opt)
        ctx = RunContext(
            split=args.split,
            limit=args.limit,
            overrides=overrides,
            cassette_mode=cassette,
            options=options,
        )
        report = asyncio.run(run_suite(name, ctx))
        path = write(report)
        print(json.dumps({k: v.show() for k, v in report.metrics.items()}, ensure_ascii=False))
        print(f"report: {path}")
        failed |= bool(compare_suite(name, args.split, path))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
