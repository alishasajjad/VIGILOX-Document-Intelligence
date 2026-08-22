# Evaluation

How accuracy is measured, what the numbers mean, and the two places where
a plausible reading of them is wrong.

## The corpus

63 labelled documents, 21 of each supported type:

```
evaluation/images/guard_license/   21
evaluation/images/id_card/         21
evaluation/images/sia_badge/       21
evaluation/ground_truth/labels.jsonl   63 records
```

## Running it

```bash
python -m scripts.evaluation.evaluation_runner              # resume
python -m scripts.evaluation.evaluation_runner --limit 5    # a slice
python -m scripts.evaluation.evaluation_metrics             # score what exists
```

**It is resume-safe and resuming is the default.** The runner reads
`evaluation/results/predictions.jsonl`, skips every sample already
present, and appends. `--reset` discards completed predictions and is
almost never what you want — a full run is a large, paid provider window.

If the Groq allowance runs out mid-run, the completed predictions are
already on disk. Wait for quota and run the same command again.

**Do not change extraction logic because of a 429.** It is a quota
signal, not a correctness signal. Changing prompts, models, retry counts
or field handling in response to one corrupts the comparison the run
exists to make.

### The runner waits as long as the provider asks

A tokens-per-day refusal reads:

```
Limit 200000, Used 196625, Requested 4512.
Please try again in 8m11.183999999s
```

The runner parses that estimate and waits for it, capped at 15 minutes.
It used to wait a flat 65 seconds — sized for a tokens-per-*minute* limit,
where a minute really does clear it. The daily window frees at whatever
rate the tokens were consumed 24 hours earlier; measured during the Phase
12 run, about 240 tokens a minute. Three attempts at 65 seconds covers
195 seconds of an eight-minute wait, so every attempt failed while the
allowance was about to free up.

This is retry *pacing*, not extraction. No prediction changes; only how
long the script waits before asking again.

## Critical fields have one definition

`scripts/evaluation/evaluation_metrics.py` **imports** the critical-field
map from `DocumentAnomalyValidator`, the same object the product routes
on. It does not keep its own list, and a test asserts the two agree.

```
sia_badge       full_name, licence_number, expiry_date, issuer
guard_license   full_name, licence_number, expiry_date, issuer
id_card         full_name, id_number
```

### The baseline correction — read this before comparing numbers

Historical reports quote **99.40% (167/168)** for critical-field
normalised accuracy. **That figure is superseded and should not be used
as the baseline.**

It came from an evaluation-only critical-field list that omitted
`issuer`, which production *does* treat as critical. Using the production
definition on the **same predictions** gives:

```
CORRECTED CRITICAL NORMALISED BASELINE:  99.05%  (208 / 210)
```

**Nothing got worse and no prediction changed.** A denominator that was
too narrow was replaced by the correct one, and an error that was already
happening is now counted. Do not describe the difference as a model
regression or a quality drop — it is a metric-definition fix, and the
older number was measuring the wrong thing.

Compare all future runs against **99.05% (208/210)**.

## Historical metrics

From the last complete 63-document run. Both facts are preserved
deliberately: the originally reported critical figure, and the corrected
one.

| Metric | Value |
|---|---|
| Document type accuracy | 100% (63/63) |
| Exact field accuracy | 95.92% (423/441) |
| Normalised field accuracy | 98.64% (435/441) |
| Known-field normalised accuracy | 98.49% (327/332) |
| Critical normalised — **originally reported** | 99.40% (167/168) ← superseded metric |
| Critical normalised — **corrected definition** | **99.05% (208/210)** ← the baseline |
| Fully correct documents | 93.65% (59/63) |
| Correct nulls | 99.08% (108/109) |
| Hallucinated values | 1 (0.92%) |
| AUTO_ACCEPT | 27 |
| REVIEW_REQUIRED | 36 |
| **False AUTO_ACCEPT** | **0** |

### False AUTO_ACCEPT is the release gate

**It must remain 0.** A false AUTO_ACCEPT is a document with a wrong
critical field that the system accepted without a human looking at it —
the one failure mode with no downstream check. If a run produces any,
that is a release blocker regardless of how good every other number
looks.

## Confidence is not a correctness probability

Measured directly in Phase 10.5, across all 441 fields:

```
total fields                441
confidence range            ~0.944 -> 0.999999
mean over CORRECT fields    0.997323
mean over INCORRECT fields  0.999606     <- higher
AUC                         0.362        <- worse than chance
```

**Incorrect fields scored slightly higher than correct ones.** Confidence
measures how well OCR and the evidence support the text that was
extracted. When the model maps a correctly-read string to the wrong
field, the OCR evidence for that string is excellent — so confidence is
high and the value is wrong.

So confidence must **not** be presented or used as:

- the probability that a field is correct
- AI certainty
- semantic accuracy
- a document-level score (there deliberately is no such score)

It is legitimate as a signal about *OCR and evidence support strength*,
which is what it measures.

**High confidence does not make an error harmless.** Every evaluation run
should report high-confidence wrong fields, high-confidence wrong
*critical* fields, and specifically whether any high-confidence wrong
field was AUTO_ACCEPTED.

## Image quality

Heuristic, and **not** calibrated against downstream accuracy. Its three
states are distinct and must not be collapsed in reporting:

```
null            not assessed
assessed, 0     assessed and clean
assessed, n>0   assessed and flagged
```

"Not assessed" and "assessed, nothing found" are different facts. A
report that renders both as "no quality issues" is losing information.

## Report artifacts

```
evaluation/results/predictions.jsonl        the current run, append-only
evaluation/results/document_results.csv     per document
evaluation/results/field_results.csv        per field
evaluation/reports/summary.json             computed metrics
evaluation/reports/error_cases.csv          every mismatch, for reading
evaluation/reports/confidence_calibration.json
evaluation/archive/                         previous runs, kept
```

Artifacts are **versioned, not overwritten in place** — `archive/` holds
prior runs so a metric change can be re-scored against old predictions
without re-paying for them, which is exactly how the corrected critical
baseline above was established.

**Check a report's own metadata before quoting its figures as current.**
Some archived reports predate later prompt changes and the metric
correction.
