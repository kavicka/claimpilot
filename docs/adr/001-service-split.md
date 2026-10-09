# ADR-001: Four deployables, one worker for all pipeline steps

Status: accepted, 2026-10-09

## Decision
api, worker, core_mock and mcp_server deploy separately. All seven pipeline steps run in one arq worker.

## Why
One service per step adds network hops, schemas and deploys without a scaling benefit for a solo build.
The steps share the same models and the same database. The worker scales horizontally: more processes,
same code. The api never calls a model, so PII redaction and tracing have one place to live.

## Consequences
- A step is a module in `services/worker`, not a service. Splitting one out later means moving a module
  behind a queue, not rewriting it.
- core_mock and mcp_server stay separate because they stand in for systems owned by other teams.
