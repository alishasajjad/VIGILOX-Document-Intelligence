# Tests

Standalone executable test scripts, not pytest. Each file has a `main()`
and is run directly.

Run from the repository root. Module form is canonical and needs no
`PYTHONPATH`:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m tests.api.test_phase7c_readiness
```

The regression runner exports `PYTHONPATH` to its child processes, so it
needs no setup either:

```powershell
# standard - no real PaddleOCR/Groq
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions --exclude-real

# full release gate
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions
```

Running a test **file directly** does still require `PYTHONPATH`, because
`sys.path[0]` becomes the test's own directory. Test files deliberately
carry no `sys.path` bootstrap: that pattern is confined to `scripts/`,
where tools are meant to be launched by hand. Prefer the module form.

```powershell
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe .\tests\api\test_phase7c_readiness.py
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

## Fixtures

Every data file the suite reads is tracked in Git, so a fresh clone can
run the whole suite without any private or locally-supplied document.

Document fixtures come from `evaluation/images/`:

| Fixture | Used by |
| --- | --- |
| `evaluation/images/guard_license/guard_001.jpg` | provenance e2e, real pipeline persistence, pipeline service |
| `evaluation/images/id_card/id_001.jpg` | OCR, preprocessing |
| `evaluation/images/sia_badge/sia_001.jpg` | OCR, preprocessing |

### Why `evaluation/images/` rather than `tests/fixtures/`

`guard_001.jpg` is byte-identical to the document these tests always
used, so reusing it changed no OCR line ID and no expectation. It is also
already tracked, carries ground-truth metadata in
`evaluation/ground_truth/labels.jsonl`, and is stable by design:
`scripts/evaluation/generate_synthetic_documents.py` generates from index
2 upward and never regenerates the `*_001` seed documents. Copying it
into `tests/fixtures/` would have duplicated 40 KB for no gain.

`test_phase7c_real_provenance_e2e.py` asserts exact OCR line IDs against
this image, so it is the most change-sensitive fixture in the repository.
The generator carries a comment warning against lowering its ranges.

### `samples/` is not used

`samples/` is gitignored in full and **no test reads it**. It contains a
document with apparent real personal data, so it must never be committed.
Anything under `samples/` is local scratch only.

## Real-dependency tests

These call external services for real and consume Groq daily tokens.
Once the quota is exhausted they fail with `groq.RateLimitError: 429`,
which is an external limit rather than a code defect — verify the error
type before suspecting a regression.
