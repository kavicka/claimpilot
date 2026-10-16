"""`make finetune`: train an invoice extraction adapter and promote it only through the eval gate
(ADR-014).

    uv run claimpilot-eval finetune --name invoice-20261016 [--iters 300] [--rebuild-data]

1. training data from the train split (plus handler corrections), unless it is already built;
2. `mlx_lm lora` on the base model, the Ollama models unloaded first so both fit in memory;
3. `mlx_lm.server` with the base model, the adapter chosen per request;
4. invoice_extraction on dev with both invoice steps on the adapter, against the baseline;
5. only if the gate passes: the test split once, and config/providers.yaml points the invoice
   steps at the adapter. The reports and the new providers.yaml are committed by hand.
"""

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from claimpilot_core.llm.cassette import CassetteMode
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_evals.compare import BASELINES, check, column_deltas, deltas

BASE_MODEL = "mlx-community/Qwen3-8B-4bit"
STEPS = ("invoice_header", "invoice_lines")
SUITE = "invoice_extraction"
RISING = "line_cell_accuracy"  # what an adapter is for: it must read more line cells


def promotion_problems(report: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Every gate of the suite as for any change, and line-cell accuracy must rise."""
    problems = check(report, baseline)
    new, old = report["metrics"][RISING]["value"], baseline["metrics"][RISING]["value"]
    if not new > old:
        problems.append(f"{SUITE}.{RISING} did not rise ({old:.2%} -> {new:.2%})")
    return problems


def promote(providers_text: str, base: str, adapter: str) -> str:
    """config/providers.yaml with the invoice steps on the adapter; comments and the other steps
    stay as they are."""
    out = providers_text
    for step in STEPS:
        pattern = re.compile(
            rf'^(\s*{step}:\s*\{{\s*)(?:provider: \w+, )?model: "[^"]*"(?:, adapter: "[^"]*")?',
            re.MULTILINE,
        )
        out, n = pattern.subn(rf'\g<1>provider: mlx, model: "{base}", adapter: "{adapter}"', out)
        if n != 1:
            raise ValueError(f"step {step} not found once in providers.yaml")
    return out


def lora_config(adapter_path: Path, data: Path, *, base: str, iters: int) -> dict[str, Any]:
    return {
        "model": base,
        "train": True,
        "data": str(data),
        "fine_tune_type": "lora",
        "adapter_path": str(adapter_path),
        "mask_prompt": True,  # learn the answers, not the prompts
        "num_layers": 16,
        "batch_size": 1,
        "grad_accumulation_steps": 4,
        "iters": iters,
        "learning_rate": 1e-4,
        "max_seq_length": 6400,  # the longest training call is 6.1k tokens
        "grad_checkpoint": True,
        "steps_per_report": 20,
        "steps_per_eval": 100,
        "val_batches": 25,
        "save_every": 100,
        "seed": 7,
        "lora_parameters": {"rank": 16, "scale": 20.0, "dropout": 0.05},
    }


def _unload_ollama() -> None:
    url = get_settings().ollama_url
    try:
        loaded = httpx.get(f"{url}/api/ps", timeout=5).json().get("models", [])
    except httpx.HTTPError:
        return
    for m in loaded:
        httpx.post(f"{url}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def _wait_for(url: str, proc: subprocess.Popen, timeout: float = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("mlx_lm.server exited")
        try:
            if httpx.get(f"{url}/v1/models", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    raise TimeoutError("mlx_lm.server did not come up")


def _eval(split: str, overrides: dict[str, str]) -> tuple[dict[str, Any], Path]:
    from claimpilot_evals.cli import run_suite
    from claimpilot_evals.report import write
    from claimpilot_evals.suites.common import RunContext

    ctx = RunContext(
        split=split, limit=None, overrides=overrides, cassette_mode=CassetteMode.AUTO, options={}
    )
    path = write(asyncio.run(run_suite(SUITE, ctx)))
    return json.loads(path.read_text("utf-8")), path


def run(name: str, *, iters: int, base: str = BASE_MODEL, rebuild_data: bool = False) -> int:
    from claimpilot_evals.finetune import build_dataset

    settings = get_settings()
    data = repo_root() / "data" / "finetune" / "invoices"
    if rebuild_data or not (data / "train.jsonl").exists():
        print("training data:", json.dumps(build_dataset(data)))
    adapter = settings.adapters_dir / name
    adapter.mkdir(parents=True, exist_ok=True)
    config = adapter / "lora.yaml"
    config.write_text(yaml.safe_dump(lora_config(adapter, data, base=base, iters=iters)), "utf-8")

    _unload_ollama()
    # Fixed argv, our own interpreter and paths: no shell, no outside input.
    lora = [sys.executable, "-m", "mlx_lm", "lora", "--config", str(config)]
    subprocess.run(lora, check=True)  # noqa: S603

    port = settings.mlx_url.rsplit(":", 1)[-1]
    serve = [sys.executable, "-m", "mlx_lm", "server", "--model", base, "--port", port]
    server = subprocess.Popen(serve)  # noqa: S603
    try:
        _wait_for(settings.mlx_url, server)
        overrides = {s: f"mlx:{base}+{name}" for s in STEPS}
        report, path = _eval("dev", overrides)
        baseline = json.loads((BASELINES / f"{SUITE}-dev.json").read_text("utf-8"))
        print(f"{name} ({path.name}) vs baseline")
        print("\n".join(deltas(report, baseline)))
        problems = promotion_problems(report, baseline)
        if problems:
            for line in column_deltas(report, baseline):
                print(f"  {line}")
            for p in problems:
                print(f"  GATE: {p}")
            print("not promoted")
            return 1
        _, test_path = _eval("test", overrides)
        print(f"test split: {test_path.name}")
    finally:
        server.terminate()
        server.wait(timeout=60)

    providers = settings.config_dir / "providers.yaml"
    providers.write_text(promote(providers.read_text("utf-8"), base, name), "utf-8")
    print(
        f"promoted: {SUITE} steps now on mlx:{base}+{name}; commit the reports and providers.yaml"
    )
    return 0
