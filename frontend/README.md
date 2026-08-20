# Frontend

The VIGILOX review interface. Plain HTML, CSS and JavaScript, served by
FastAPI. No build step, no framework.

```text
frontend/
├── pages/
│   ├── index.html          review queue        -> GET /review
│   └── review_detail.html  review workspace    -> GET /review/{document_id}
└── static/
    ├── dashboard.css
    ├── dashboard.js        review queue
    └── review_detail.js    review workspace
```

## How it is served

`backend/app/main.py` mounts `frontend/static/` at `/review/static` and
returns the two pages from `frontend/pages/`. Both directories are
resolved from the single project-root anchor in
`backend/app/core/paths.py`, so they do not depend on the working
directory.

Asset URLs are absolute (`/review/static/dashboard.css`), which is why
moving this directory out of the backend package in Phase 8.1 required no
HTML changes.

## Contract with the backend

The frontend is a pure API consumer and holds no authority:

- It never supplies reviewer identity. `reviewer_id` in a review request
  body is legacy and ignored by the backend; the server resolves the
  reviewer itself.
- It renders machine values and human-corrected *effective values* as
  distinct things. It must never present a correction as if it were the
  machine output.
- Error responses are read from `error.code` and `error.message`. The
  top-level `detail` field is legacy.

## Filenames

`dashboard.*` still reflects the Phase 7B naming. Three tests in
`tests/dashboard/` fetch these exact paths over HTTP, so renaming them
requires updating those tests in the same change.
