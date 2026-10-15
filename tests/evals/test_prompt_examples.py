"""Few-shot examples are built from dev documents (`claimpilot-eval fewshot`) and sent with every
extraction call, so they must carry tokens, never a personal value. Runs on the committed ground
truth; no PDFs needed."""

import json
from pathlib import Path

from claimpilot_core.settings import repo_root


def test_no_ground_truth_personal_value_appears_in_a_few_shot_example():
    root = repo_root()
    values = {
        p["value"]
        for gt in (root / "data" / "synthetic" / "claims").glob("*/ground_truth.json")
        for d in json.loads(gt.read_text("utf-8"))["documents"]
        for p in d["pii"]
        if len(p["value"]) >= 4
    }
    assert values, "no ground truth found"
    leaks = [
        (ex.name, v)
        for ex in sorted(Path(root / "prompts" / "extraction" / "examples").glob("*.json"))
        for v in values
        if v in ex.read_text("utf-8")
    ]
    assert leaks == []
