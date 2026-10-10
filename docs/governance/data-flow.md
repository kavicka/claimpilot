# Data flow

Personal data is replaced by tokens once, in the worker, before any model call. Only two code paths
turn tokens back into values: the api (for the handler's screen) and the submission step (for the
core system).

```mermaid
flowchart LR
    U[Client / portal] -->|PDF, JPG, PNG| API[api]
    API -->|files| FS[(storage)]
    API -->|job| Q[(Redis)]
    Q --> W[worker]
    FS --> W
    W -->|1 parse, OCR| W
    W -->|2 detect PII, tokenize| V[(pii.vault<br/>Fernet-encrypted)]
    W -->|3 redacted text only| M[Local models<br/>Ollama]
    W -->|page images, scans only| MV[Local vision model]
    W --> DB[(Postgres<br/>tokens, not values)]
    W -->|redacted prompts, tokens, latency| LF[Langfuse<br/>self-hosted]
    API -->|re-hydrates for the handler| H[Handler UI]
    DB --> API
    V --> API
    W -->|re-hydrated at submit| CORE[Core claims system]
    V --> W
    MCP[MCP server] -->|service token: tokens only| API
```

| Hop | Data | Personal data |
| --- | --- | --- |
| Upload to storage | Original files | Yes, unchanged |
| Parse and OCR (worker, local) | Text blocks with positions | Yes, inside the worker |
| Model calls (text) | Redacted page text, field list, examples | No: tokens such as `<PERSON_1>` |
| Model calls (vision, scans only) | Page images | Yes: allowed only for local models; the vision step refuses any other provider. Values it reads are tokenized at once, with fresh detection, because OCR may have missed a name the image shows; new values go to the vault |
| Checksum checks (worker, in memory) | IBAN and birth number digits | Yes, re-hydrated from the vault for the check; only the boolean result is kept |
| Database | Extracted values, decisions, letters | Tokens; values only in `pii.vault`, encrypted |
| Langfuse traces | Prompts and outputs | Tokens only; page images replaced by a count |
| Logs | Step events | No: vault values are scrubbed, database errors are cut to their first line |
| Handler UI | Everything the handler needs | Yes, re-hydrated per request for a logged-in handler. A handler's correction with a new personal value goes to the vault under a new token |
| MCP server | Claims, fields, decisions | Tokens only (service account, read-only); no page images |
| Core-system errors | 422 details for the submission agent | Echoed input removed and vault values turned back into tokens before the agent sees them |
| Core system | Approved claim | Yes, re-hydrated at the moment of submission |

Phase 2 (Bedrock) changes one hop: text model calls leave the machine. They carry tokens only, and the
vision path stays local or sends images with PII regions masked from the OCR boxes.
