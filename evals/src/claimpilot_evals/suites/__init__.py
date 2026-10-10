"""One module per pipeline step. Each exposes `async def run(ctx) -> Report`."""

SUITES = [
    "doc_type",
    "pii",
    "extraction",
    "routing",
    "retrieval",
    "coverage",
    "submission",
    "summaries",
    "injection",
    "adversarial",
]
