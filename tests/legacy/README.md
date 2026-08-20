# Legacy tests (quarantined)

These two files were already failing **before** the Phase 8 repository
restructure. They were quarantined here rather than deleted so the
historical coverage they represent stays readable, and rather than left
in place so the regression gate stays honest.

They are excluded from
`scripts/verification/run_phase7c7g_regressions.py`.

## `test_phase7a_review_queue.py`

Asserts an exact **global** review-queue ordering. That assertion only
holds when the database contains nothing but this test's own documents,
so any residue from another run breaks it.

Superseded by `tests/integration/test_phase7a_review_queue_isolated.py`,
which scopes its assertions to its own documents and passes.

To see the residue that breaks it:

```powershell
.\.venv\Scripts\python.exe .\scripts\maintenance\clean_test_residue.py
```

Reviving it would mean rescoping the assertions to documents the test
created, not clearing the database before every run.

## `test_phase6c_end_to_end.py`

A Phase 6C real-pipeline test that expects HTTP 200 from
`POST /api/v1/documents/analyze` with the live OCR + Groq pipeline. It
predates the current real-dependency tests and has no isolation or
cleanup.

Superseded by `tests/real_dependencies/test_real_pipeline_persistence.py`
and `tests/real_dependencies/test_phase7c_real_provenance_e2e.py`.
