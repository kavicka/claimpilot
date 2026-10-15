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

# Run by name only, never in `all`: they need macOS and the generated PDFs; CI cannot replay them.
LOCAL_SUITES = ["masking"]
