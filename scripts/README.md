# Scripts

Operational tooling. All commands assume the **repository root** as the
working directory.

```text
scripts/
├── verification/   regression suite and production-invariant checks
├── evaluation/     benchmark runner, metrics, synthetic document generators
├── maintenance/    one-off database and storage operations
└── development/    local profiling and benchmarking
```

---

## Invocation

`PYTHONPATH` is **not** required. Both forms work from the repository
root:

```powershell
# canonical - module form
.\.venv\Scripts\python.exe -m scripts.verification.verify_phase7c7_final

# also supported - direct file
.\.venv\Scripts\python.exe .\scripts\verification\verify_phase7c7_final.py
```

Module form is canonical because Python puts the project root on
`sys.path` itself, so nothing has to be bootstrapped.

### Why direct execution needs a bootstrap

Running a file directly sets `sys.path[0]` to the **script's own
directory**, not the project root, so `backend` and `database` are not
importable and the script dies with:

```text
ModuleNotFoundError: No module named 'backend'
```

Every script here that imports project packages therefore starts with one
identical, clearly-marked block:

```python
PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

This is the **single sanctioned bootstrap pattern**, and it lives only in
`scripts/`. `backend/`, `database/` and `tests/` must never manipulate
`sys.path`: the application is imported as a proper package, and the test
runner exports `PYTHONPATH` to its child processes instead.

If you add a script here that imports project packages, copy that block
verbatim. Note `parents[2]` assumes `scripts/<area>/<script>.py`.

---

## Verification

### Regression suite

Three modes. The default is the full release gate — real-dependency
tests are never quietly dropped from it.

```powershell
# FULL RELEASE GATE - everything, including real PaddleOCR + Groq + PostgreSQL
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions

# STANDARD - everything except real dependencies. Fast, free, no network inference.
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions --exclude-real

# ONLY REAL - just the real-dependency group, e.g. to confirm quota recovery
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions --only-real
```

Use `--exclude-real` during normal development. Real-dependency tests
cost roughly 6,400 Groq tokens each against a 200,000 tokens-per-day
allowance; repeatedly running the full gate exhausts it and then reports
HTTP 429 failures that mean nothing.

Any skipped group is always named in the summary, and the final verdict
says whether the full gate was actually proven. The suite never silently
narrows its own coverage.

### Production invariants

Routes, log-level handling, structured-log secret safety, `.env`
isolation and the production print scan. Fast, and it performs **no**
OCR or LLM inference, so it costs no quota.

```powershell
.\.venv\Scripts\python.exe -m scripts.verification.verify_phase7c7_final
```

---

## Evaluation

Regenerates the Phase 6D benchmark. Costs roughly 63 Groq document runs,
which exceeds the daily on-demand allowance in one sitting — archive the
existing reports first.

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluation.evaluation_runner
.\.venv\Scripts\python.exe -m scripts.evaluation.evaluation_metrics
```

The synthetic document generators seed `evaluation/images/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluation.generate_synthetic_documents
.\.venv\Scripts\python.exe -m scripts.evaluation.generate_synthetic_id_cards
```

⚠️ They generate from index **2** upward and never regenerate the
`*_001` seed documents. `evaluation/images/guard_license/guard_001.jpg`
is a tracked test fixture whose exact OCR line IDs are asserted by
`tests/real_dependencies/test_phase7c_real_provenance_e2e.py`. Do not
lower those ranges.

---

## Maintenance

Read-only, safe to run:

```powershell
# report PostgreSQL rows left behind by old test runs (deletes nothing)
.\.venv\Scripts\python.exe -m scripts.maintenance.clean_test_residue

# inspect duplicate-review protection state
.\.venv\Scripts\python.exe -m scripts.maintenance.check_phase7c_duplicate_reviews
.\.venv\Scripts\python.exe -m scripts.maintenance.inspect_phase7c_duplicate_review
```

**Mutating — read before running:**

```powershell
# deletes the reported residue rows and their cascades
.\.venv\Scripts\python.exe -m scripts.maintenance.clean_test_residue --delete

# applies UNIQUE(document_id) on human_reviews
.\.venv\Scripts\python.exe -m scripts.maintenance.apply_phase7c_unique_review_constraint

# migrates pre-existing duplicate human reviews
.\.venv\Scripts\python.exe -m scripts.maintenance.migrate_phase7c_duplicate_reviews
```

---

## Development

Profiles the image preprocessing pipeline and writes to `output/`.
Uses real PaddleOCR but no LLM, so it costs no Groq quota.

```powershell
.\.venv\Scripts\python.exe -m scripts.development.preprocessing_benchmark
```
