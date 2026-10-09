# ClaimPilot

AI pipeline that takes travel-insurance claim documents from intake to a handler-approved decision.
Runs fully local: Ollama models on a Mac, Postgres and Redis in Docker. Synthetic data only.

```
make up        # Postgres, Redis, api, core_mock, mcp_server + migrations
make worker    # native worker (MPS)
make smoke     # check the local models
make test
```

Status: Phase 1 in progress. Architecture decisions in [docs/adr](docs/adr), discovery in
[docs/discovery](docs/discovery).
