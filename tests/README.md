# Tests

Standalone executable test scripts, not pytest. Each file has a `main()`
and is run directly.

The project root must be importable. Either use the module form, or
export `PYTHONPATH` and use the path form:

```powershell
$env:PYTHONIOENCODING = "utf-8"

# module form
.\.venv\Scripts\python.exe -m tests.api.test_phase7c_readiness

# path form
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe .\tests\api\test_phase7c_readiness.py
```

The regression runner exports `PYTHONPATH` itself, so it needs no setup:

```powershell
.\.venv\Scripts\python.exe .\scripts\verification\run_phase7c7g_regressions.py
```

## Categories

| Directory | Contains |
| --- | --- |
| `unit/` | Isolated logic. No database, no HTTP. |
| `integration/` | Services against real PostgreSQL. |
| `api/` | HTTP contracts via `TestClient`. |
| `security/` | Reviewer identity, spoofing, duplicate/concurrent review. |
| `storage/` | Path safety, deletion, integrity, reconciliation. |
| `dashboard/` | Contracts between the dashboard assets and the backend. |
| `e2e/` | Full workflows across many components. |
| `real_dependencies/` | Real PaddleOCR, real Groq, real PostgreSQL. |
| `legacy/` | Quarantined and superseded. Excluded from the gate. |

## Conventions

- Tests that touch storage use an isolated `TemporaryDirectory`. Real
  managed storage is never mutated.
- Tests that write to PostgreSQL clean up only the IDs they created.
- Tests that need determinism use a pipeline double rather than the real
  LLM. Real OCR/LLM coverage lives in `real_dependencies/`.

## Real-dependency tests

These call external services for real and consume Groq daily tokens.
Once the quota is exhausted they fail with `groq.RateLimitError: 429`,
which is an external limit rather than a code defect. They also require
the synthetic images in `samples/`.
