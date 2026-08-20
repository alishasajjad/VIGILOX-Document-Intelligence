# Pending validation items

Open items that are **not** architecture-migration failures. Each is a
separate validation task with its own trigger.

---

## 1. Evaluation benchmark revalidation

**Status:** pending
**Category:** benchmark revalidation, not a migration failure
**Owner decision needed:** when to spend ~63 Groq document runs

`evaluation/reports/` currently holds:

| Metric | Value |
| --- | --- |
| Document type accuracy | 100% |
| Field accuracy (normalized) | 98.64% |
| Field accuracy (exact) | 95.92% |
| Critical-field normalized | 99.40% |
| False `AUTO_ACCEPT` | 0 |

Those numbers were produced **before** the Phase 7C.8 extraction-prompt
change, which tightened rule 7 so non-date text values must be copied
verbatim from their OCR evidence (labels may be excluded, word order may
not be changed).

`evaluation/archive/before_prompt_rule7_.../` is a snapshot taken in
preparation for a rerun. The rerun never happened, so `reports/` and
`archive/` currently hold identical numbers.

### Why the numbers are probably fine

The Phase 6D ground truth already uses verbatim printed forms —
`SAMPLE,JANE`, `M.GREEN`, `S.SMITH`, and `issuer: "TX DPS"` with the
`ISSUED BY` label excluded. The prompt change aligned the model with that
existing contract rather than against it, so exact-match accuracy should
if anything improve.

That is inference, not measurement. Do not quote these figures as
current until the rerun happens.

### How to revalidate

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m scripts.evaluation.evaluation_runner
.\.venv\Scripts\python.exe -m scripts.evaluation.evaluation_metrics
```

Archive the existing reports first. Budget for ~63 Groq document runs,
which exceeds the on-demand daily token allowance in one sitting.

---

## 2. Local sensitive sample file

**Status:** awaiting owner action
**Category:** data hygiene

`samples/id_card.jpg` is a photograph of an apparently **real** national
identity card carrying a government ID number, full name, date of birth
and residential address.

Verified state:

- `samples/` is gitignored in full
- the file is not tracked and not staged
- it appears in **no** commit on **any** branch

No code depends on it any more. Tests and the preprocessing benchmark
read tracked synthetic fixtures from `evaluation/images/`.

**Recommended:** delete or replace the local file. It was left in place
because deleting a user file needs explicit approval.

---

## 3. Groq daily token quota

**Status:** environmental
**Category:** external provider limit

The two real-dependency tests each cost roughly 6,400 Groq tokens
against a 200,000 tokens-per-day on-demand allowance. Repeated
full-suite runs exhaust it, after which both tests fail with
`groq.RateLimitError: 429`.

That is a provider limit, not a defect. When it happens, verify the
failure is `RateLimitError` and not `ImportError`, `FileNotFoundError`
or an assertion, then wait rather than retrying in a loop.

There is no retry/backoff layer in the extraction service. Adding one
belongs to Phase 9 (performance / async), not to Phase 8.
