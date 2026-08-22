# Pending validation items

Open items that are **not** architecture-migration failures. Each is a
separate validation task with its own trigger.

---

## 1. Evaluation benchmark revalidation

**Status:** IN PROGRESS — 57 / 63 scored, blocked on the Groq daily
allowance
**Category:** benchmark revalidation, not a migration failure

### What happened

The rerun this item asked for was started in Phase 12.17 against the
current code. It reached **57 of 63 documents** and then Groq refused:

```
Limit 200000, Used 196625, Requested 4512
```

The six outstanding samples are all ID cards:

```
id_015  id_016  id_017  id_018  id_020  id_021
```

Roughly 30,000 tokens of allowance are needed to finish them. Every one
of the six failed with a `RateLimitError` 429 and nothing else — no
assertion, no import error, no missing file. The code was never the
problem.

**Nothing was lost and nothing was reset.** The prior reports were
archived to `evaluation/archive/phase12_pre_final_20260822/` before the
run started, and all 56 successful predictions are in
`evaluation/results/predictions.jsonl`.

### Finishing it

```bash
python -m scripts.evaluation.evaluation_runner    # resumes; never --reset
python -m scripts.evaluation.evaluation_metrics
```

The runner retries only samples with no successful record, so this
re-scores nothing that already succeeded. `evaluation_metrics` refuses to
score a partial run — it names the missing samples rather than reporting
56 documents as though they were 63.

Phase 12.17 also fixed the runner's retry pacing: it now waits as long as
the provider asks (`try again in 8m11s`, capped at 15 minutes) instead of
a flat 65 seconds sized for a per-minute limit. A resume should therefore
ride out the window unattended.

### The metric definition changed, and the numbers below are superseded

The original entry quoted **critical-field normalised 99.40%**. That
figure used an evaluation-only critical-field list which omitted
`issuer` — a field production treats as critical. Evaluation now
**imports** the production definition, and a test asserts the two agree.

On the same predictions, the corrected figure is **99.05% (208/210)**.
The denominator is confirmed arithmetically: 21 SIA badges × 4 + 21 guard
licences × 4 + 21 ID cards × 2 = 210.

**That is a metric-definition fix, not a model regression.** No prediction
changed; a denominator that was too narrow was replaced by the correct
one, and an error already happening is now counted. Compare future runs
against 99.05% (208/210), and see
[../evaluation/evaluation.md](../evaluation/evaluation.md).

### Release-critical

**False AUTO_ACCEPT must be 0.** It cannot be determined from a partial
run, so this item gates the release regardless of how the other numbers
look.

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

## 3. Real-dependency release verification

**Status:** CLOSED at the end of Phase 8
**Category:** was an external provider limit, not a defect

| Gate | Result |
| --- | --- |
| Standard development gate | 49 / 49 PASS *(as of Phase 8)* |
| Real-dependency release gate | 51 / 51 PASS *(as of Phase 8)* |

**These counts are historical.** The suite has grown considerably since:
Phase 9 added the job and batch suites, Phase 10 the intelligence suites,
Phase 11 the deployment suites, and Phase 12.6 registered four
real-dependency suites that no runner had been executing. For the current
count see
[../release/v1-production-readiness.md](../release/v1-production-readiness.md).

Both real-dependency tests now pass with real PaddleOCR, real Groq and
real PostgreSQL. They were previously reported as `EXTERNAL_BLOCKED`
because Groq refused the request on the tokens-per-day allowance; that
was a quota refusal and never evidence about the code.

```text
GROUP - REAL DEPENDENCY TESTS
[PASS]  29.6s  tests/real_dependencies/test_real_pipeline_persistence.py
[PASS]  39.7s  tests/real_dependencies/test_phase7c_real_provenance_e2e.py

MODE: FULL RELEASE GATE
PASSED  : 51
FAILED  : 0
BLOCKED : 0
MISSING : 0
```

The classification stays in the runner, because the quota will be
exhausted again. See item 4.

To reproduce:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m scripts.verification.run_phase7c7g_regressions
```

---

## 4. Groq daily token quota

**Status:** environmental
**Category:** external provider limit

The two real-dependency tests each cost roughly 6,400 Groq tokens
against a 200,000 tokens-per-day on-demand allowance. Repeated
full-suite runs exhaust it, after which both tests fail with
`groq.RateLimitError: 429`.

That is a provider limit, not a defect. When it happens, verify the
failure is `RateLimitError` and not `ImportError`, `FileNotFoundError`
or an assertion, then wait rather than retrying in a loop.

### Superseded: there IS a retry layer now

The original entry ended "there is no retry/backoff layer in the
extraction service. Adding one belongs to Phase 9". Phase 9 and Phase
10.4 built it, at three levels:

| Level | Setting | What it retries |
| --- | --- | --- |
| Inside one HTTP request | `VIGILOX_GROQ_MAX_RETRIES` (1) | a 429 that a short sleep clears |
| Structured-output recovery | `VIGILOX_EXTRACTION_ATTEMPTS` (3) | a provider 400 saying it could not match the schema |
| The job layer | `max_attempts` + backoff, `RETRY_WAIT` | anything transient, without holding a worker |

The provider retry is deliberately **1**, not the SDK default of 2:
generation measures about 1.3s, and a job-layer retry is far cheaper than
a second in-request attempt because it does not re-run the 28s median
OCR pass inside a held lease.

None of this creates quota. A sustained 429 still means the allowance is
gone, and the correct response is still to wait — see
[../operations/production-runbook.md](../operations/production-runbook.md).

**Do not change extraction logic because of a 429.** It is a quota
signal, not a correctness signal.

---

## 5. Visual browser verification of the Phase 8 interface

**Status:** LARGELY CLOSED in Phase 12.16 — a narrow manual residue
remains
**Category:** manual verification, not a defect

### What changed

The original entry said "this environment has no browser automation: no
Playwright, no Selenium, no Puppeteer". That was true of the *libraries*
and it led to the wrong conclusion, because **Chrome itself was already
installed**. Chrome's own command line renders and screenshots without
any driver:

```bash
python scripts/verification/browser_acceptance.py
```

Installing a browser was correctly out of scope. Driving the one that was
already there needed no dependency at all.

### What is now verified in a real layout engine

| Property | Result |
| --- | --- |
| Every page renders after its JavaScript runs | ✅ 4 pages, post-JS DOM captured |
| Page titles | ✅ all five `<Page> · VIGILOX` |
| Favicon served | ✅ HTTP 200, 7376 bytes |
| Canonical icon linked | ✅ every page |
| **Horizontal overflow** | ✅ **measured** at 8 widths, 320–1440px: `scrollWidth == clientWidth` on all four pages |
| Every asset the browser requested | ✅ no 404, no 500 |
| Screenshots for review | ✅ 20, in `output/browser-acceptance/` |

### Two defects this found, both now fixed

1. **Load failures were silent to a screen reader.** Four of five pages'
   load-state containers had no live region. 11 containers gained
   `role="alert"` / `role="status"`.

2. **A flex axis flip wasted ~180px inside the Documents filter card.**
   `.toolbar-search` carries `flex: 1 1 260px`; at ≤767px the toolbar
   becomes `flex-direction: column`, and `flex-basis` follows the main
   axis — so "260px wide" silently became "260px tall, and grow". Reading
   the two rules side by side does not reveal it; rendering the page at
   520px with data loaded does. The card went from ~1140px to ~575px.

### Two traps recorded so nobody repeats them

**Headless Chrome clamps `--window-size` to about 500px** in every
headless mode. A 390px screenshot is a 512px layout cropped to 390 —
which looks exactly like horizontal overflow and produced one reported
defect that did not exist. Narrow widths are therefore rendered inside an
iframe, which is not clamped, and overflow is *measured* rather than
eyeballed.

**The application's CSP blocks an inline measuring script**, correctly.
The measurement runs against captured post-JavaScript snapshots on a
throwaway server rather than weakening production's CSP. `X-Frame-Options:
DENY` likewise blocks framing the live app — also correct, also worked
around rather than relaxed.

### What still needs an eye

The script cannot click, and it cannot judge. Remaining:

- colour contrast and visual balance — look at the 20 screenshots
- the evidence overlay landing on the right glyphs on a real document.
  The arithmetic is verified numerically (a `[30, 20, 180, 60]` box in a
  600x400 image resolves to 5%, 5%, 25%, 10%, and six kinds of unusable
  box are refused rather than clamped), but that it *looks* right still
  needs a person
- a corrected field being unmistakably distinct from a machine reading
- the interactive flows: upload modes, review submission, tab switching.
  These are covered by the harness tests, which drive the real modules —
  but not by a real browser

The manual checklist is in
[../release/v1-production-readiness.md](../release/v1-production-readiness.md)
§20.
