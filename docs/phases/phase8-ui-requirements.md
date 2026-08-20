# Phase 8 UI Requirements (recorded, not yet implemented)

Captured before Phase 8.3 so it is not lost. Nothing here is built yet.

## Mandatory: first-class Upload Document experience

Navigation should eventually be:

```text
Dashboard | Upload Document | Documents | Review Queue
```

The upload screen uses the **existing** endpoint. No new backend route.

```text
POST /api/v1/documents/analyze
```

### Expected UX

- drag-and-drop plus browse/select
- supported-type and size indication
- client-side validation feedback
- document preview before submit
- progress and processing state
- visible pipeline stages: OCR → extraction → validation →
  anomaly/expiry
- redirect to, or inline presentation of, the final result

### Backend constraints — do not weaken

| Constraint | Value |
| --- | --- |
| Accepted types | JPG, JPEG, PNG, WEBP |
| Max size | 10 MiB, measured from actual streamed bytes |
| Not accepted | PDF, batch upload (later phase, needs approval) |

Client-side validation is a convenience layer only. The server remains
authoritative: it re-validates content type, counts real bytes rather
than trusting `Content-Length`, and strips client path components from
filenames.

### Result presentation

Document type · processing status · review status · extracted identity
fields · expiry/validity · confidence · evidence validation · anomalies ·
review requirement · final effective record.

## Constraints inherited from the current codebase

Two file-naming facts that affect UI work:

1. `frontend/static/` still uses the Phase 7B names `dashboard.css`,
   `dashboard.js`, `review_detail.js`. Three tests in `tests/dashboard/`
   fetch those exact paths over HTTP. Renaming them (for example to
   `review_queue.*`) or splitting the CSS into
   `tokens/base/components/layout/responsive` must update those tests in
   the same change.

2. `review_detail.js` is ~4,000 lines with 8 separate `fetch()` call
   sites. That duplication is the natural seam for extracting shared
   `api.js` / `common.js` modules.

## UI must not weaken existing guarantees

- Machine values and human-corrected effective values must be presented
  as visibly distinct. Never show a correction as machine output.
- The frontend never supplies reviewer identity. `reviewer_id` in a
  review request body is legacy and ignored server-side.
- Read errors from `error.code` / `error.message`; top-level `detail` is
  legacy compatibility.
- Reviewed documents stay locked. Action buttons must disable during
  submission to prevent duplicate review attempts.
