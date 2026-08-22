# Frontend

The VIGILOX product interface. Plain HTML, CSS and vanilla JavaScript,
served by FastAPI. No build step, no framework.

```text
frontend/
├── pages/
│   ├── dashboard.html       operations overview  -> GET /dashboard
│   ├── upload.html          upload and analyse   -> GET /upload
│   ├── documents.html       document browser     -> GET /documents
│   ├── index.html           review queue         -> GET /review
│   └── review_detail.html   review workspace     -> GET /review/{id}
└── static/
    ├── css/
    │   ├── tokens.css        the only token owner
    │   ├── base.css          reset, type, focus, reduced motion
    │   ├── layout.css        shell, navigation, grid
    │   ├── components.css    buttons, cards, badges, tables, dialog
    │   ├── workspace.css     the document review screen only
    │   └── responsive.css    every breakpoint, in one place
    ├── js/
    │   ├── api.js            the only file that calls fetch
    │   ├── common.js         safe DOM helpers, formatters, badges
    │   ├── vocabulary.js     backend codes -> readable language
    │   ├── dashboard_page.js GET /dashboard
    │   ├── documents_page.js GET /documents
    │   ├── upload.js         GET /upload
    │   └── workspace/
    │       ├── tabs.js             accessible tab controller
    │       ├── source_panel.js     image + OCR evidence overlay
    │       ├── fields_view.js      values, confidence, evidence
    │       ├── validation_view.js  dates, expiry, findings
    │       ├── result_view.js      final record, history, raw data
    │       └── review_actions.js   approve / correct / reject
    ├── dashboard.js          review queue      -> GET /review
    ├── review_detail.js      workspace controller
    └── dashboard.css         retired, no rules
```

## Historical filenames

Two names do not describe what they contain, and are kept deliberately.

`dashboard.js` is the **Review Queue**, not the Dashboard. The Dashboard
at `/dashboard` is `js/dashboard_page.js`. The old name is retained
because real browsers have the URL cached and several tests in
`tests/dashboard/` fetch it by path.

`dashboard.css` is **retired**. It was 2,041 lines covering the shell,
the queue and the detail screen, plus its own `:root` token block. All of
it is gone: the tokens moved to `css/tokens.css` in Phase 8.4, and the
page rules died when the Review Queue and workspace were rebuilt on the
design system in Phase 8.9 and 8.10. The file remains so the URL keeps
resolving. Do not add rules to it.

## How it is served

`backend/app/main.py` mounts `frontend/static/` at `/review/static` and
serves each page from `frontend/pages/` through one helper,
`serve_frontend_page`. Both directories resolve from the single
project-root anchor in `backend/app/core/paths.py`, so they do not depend
on the working directory.

The filename passed to that helper is a module-level literal at every
call site. No request value reaches it, so no page route can become a
path-traversal read — including `/review/{document_id}`, which serves the
same file for every id and lets the browser read the id back out of
`window.location`.

Asset URLs are absolute (`/review/static/css/tokens.css`), which is why
moving this directory out of the backend package in Phase 8.1 required no
HTML changes.

## Contract with the backend

The frontend is a pure API consumer and holds no authority.

- **It never supplies reviewer identity.** `reviewer_id` in a review
  request body is legacy and ignored; the server resolves the reviewer
  itself. There is no input anywhere in the product through which a
  browser could assert one, and the workspace suite asserts that by
  enumerating every input on the page.
- **`can_review` is displayed, not enforced.** Hiding a submit button is
  a convenience. The backend authorises every write regardless.
- **Machine values and human corrections are never interchangeable.** A
  corrected field shows the machine reading, the correction and the
  effective value together, with distinct colour families for
  `MACHINE` and `HUMAN_CORRECTION`.
- **`PENDING_REVIEW` and `REJECTED` publish no effective values.**
  `FinalRecordService` returns none for either, and the UI says so
  rather than presenting the machine reading as a usable result.
- **Errors are read from `error.code`, `error.message` and
  `error.request_id`.** The top-level `detail` field is legacy and is
  consulted only as a fallback, inside `api.js`.

## Rules enforced by tests

These are not conventions. `tests/dashboard/test_phase8_frontend_audit.py`
walks every file on disk and fails the build if any of them breaks.

| Rule | Why |
| --- | --- |
| Only `js/api.js` may call `fetch` | One place parses responses, normalises the error contract and reads the request id |
| No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` or `eval` | OCR text, extracted values, filenames and reviewer notes are untrusted input |
| No `console.*` | Frontend payloads carry OCR text and extracted identity values |
| No timer may issue a request | No screen polls |
| No credential material | Ever |
| Only `css/tokens.css` may declare tokens | A second `:root` is how two stylesheets start disagreeing |
| Every `var()` must resolve to a declared token | Otherwise the property silently falls back |
| The navigation block is byte-identical on every page | Five hand-written copies drift |
| One `h1` per page, no skipped heading level | Heading navigation is how many people read |
| No `role="button"` or `role="dialog"` on a div | Real elements bring focus, keyboard behaviour and announcements for free |
| Every form control has a label | No exceptions, including the evidence toggle |
| Every `<button>` declares its type | The default is submit |
| Every `aria-*` reference points at an existing id | A dangling reference announces nothing |
| Every shipped module is loaded by a page | An unloaded module is dead code |

## Testing approach

Asserting on source text proves a string is present. It cannot prove that
four Approve clicks submit once, that a read-only reviewer cannot reach a
submit path, or that a missing document id never becomes
`/review/undefined`.

So the suites **execute** the real modules under Node against
`tests/dashboard/dom_stub.js`, which parses the shipped HTML into a real
element tree. A renamed id or a moved element breaks the test rather than
being papered over, and the stub throws on any `innerHTML` assignment or
`console` call, so those rules cannot be violated silently.

See `docs/phases/phase8-ui-requirements.md` for the design constraints,
and each `tests/dashboard/test_phase8_*.py` header for what that screen
guarantees.
