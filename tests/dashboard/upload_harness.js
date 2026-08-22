/* ==========================================================
   VIGILOX UPLOAD HARNESS
   PHASE 8.7
   ==========================================================

   Executes frontend/static/js/upload.js under Node with a
   minimal DOM stub, so the upload behaviour is actually RUN
   rather than pattern-matched in the source text.

   This is what lets the Python test assert real outcomes:
   which files are rejected, that a replaced file revokes its
   predecessor's object URL, that a second analyze call is
   dropped, and that a missing document_id does not navigate.

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const STATIC_JS = path.join(PROJECT_ROOT, "frontend", "static", "js");


/* ==========================================================
   DOM STUB
   ==========================================================
   Only what upload.js touches. Elements record their own
   state so assertions can inspect it.
   ========================================================== */

function makeElement(id) {

    return {
        id: id,
        hidden: false,
        disabled: false,
        textContent: "",
        src: null,
        value: "",
        attributes: {},
        classes: new Set(),
        listeners: {},
        children: [],

        classList: {
            add(name) { this.owner.classes.add(name); },
            remove(...names) {
                names.forEach((n) => this.owner.classes.delete(n));
            },
            contains(name) { return this.owner.classes.has(name); },
            toggle(name, on) {
                if (on) { this.owner.classes.add(name); }
                else { this.owner.classes.delete(name); }
            }
        },

        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) {
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name]
                : null;
        },
        removeAttribute(name) {
            delete this.attributes[name];
            /* A real <img> drops its resolved source when the
               src attribute is removed. Mirror that, or the
               harness would report a stale preview. */
            if (name === "src") { this.src = null; }
        },

        addEventListener(name, handler) {
            this.listeners[name] = this.listeners[name] || [];
            this.listeners[name].push(handler);
        },

        appendChild(child) { this.children.push(child); return child; },
        removeChild(child) {
            const i = this.children.indexOf(child);
            if (i !== -1) { this.children.splice(i, 1); }
            return child;
        },
        get firstChild() {
            return this.children.length ? this.children[0] : null;
        },

        focus() { this.focused = true; },

        fire(name, event) {
            (this.listeners[name] || []).forEach((h) => h(event || {}));
        },

        style: {}
    };
}


function buildDocument(ids) {

    const registry = {};

    ids.forEach((id) => {
        const el = makeElement(id);
        el.classList.owner = el;
        registry[id] = el;
    });

    return {
        readyState: "complete",
        registry: registry,
        listeners: {},

        getElementById(id) {
            return registry[id] || null;
        },

        /* markActiveNav in common.js queries navigation
           items. The harness has no nav, so an empty list is
           the correct answer. */
        querySelectorAll() {
            return [];
        },

        createElement(tag) {
            const el = makeElement("<" + tag + ">");
            el.classList.owner = el;
            el.tagName = tag;
            return el;
        },

        addEventListener(name, handler) {
            this.listeners[name] = this.listeners[name] || [];
            this.listeners[name].push(handler);
        }
    };
}


const ELEMENT_IDS = [
    "drop-zone", "file-input", "upload-validation",
    "file-card", "file-preview", "file-name", "file-type",
    "file-size", "remove-button",
    /* PHASE 12.18. The card now outlives SELECTED, so the two
       parts of it that must NOT outlive SELECTED need their own
       handles: the Replace/Remove pair, and the "Ready to
       analyze" badge row. */
    "file-actions", "file-ready-row",
    "processing-panel", "processing-message",
    /* The note that carries the retry explanation and the
       durable-queue wording. */
    "processing-note",
    "success-panel", "success-facts",
    "error-panel", "error-title", "error-message", "error-meta",
    // PHASE 10.3. The duplicate actions container.
    "error-actions",
    "analyze-button", "retry-button",
    // shell nodes, so initShell finds nothing unexpected
    "shell-reviewer-name", "shell-reviewer-role",
    "shell-reviewer-access", "shell-reviewer-avatar",
    "status-indicator", "status-text"
];


/* ==========================================================
   HARNESS STATE
   ========================================================== */

/* ==========================================================
   PER-WINDOW STATE
   ==========================================================
   Object URLs, navigations, submissions and scheduled timers
   all used to be module-level arrays that boot() reset.

   That is a defect, and it is the second time this directory
   has had it. Checks run concurrently: one boot's reset wipes
   another's arrays, so a count could belong to any check and
   runTimers() in one check could fire another's callbacks. It
   is not a flake -- it is a test that reports the wrong thing
   deterministically, and it took a genuinely failing
   assertion to expose it.

   Everything now lives on the window that owns it.
   ========================================================== */

let analyzeBehaviour = { mode: "pending" };


function makeFile(name, type, size) {
    return { name: name, type: type, size: size };
}


/* ==========================================================
   BUILD THE SANDBOX
   ========================================================== */

function buildWindow() {

    const documentStub = buildDocument(ELEMENT_IDS);

    /* Closed over by the window's own methods, so there is no
       `this` to be rebound by vm.runInNewContext and no
       sharing between concurrent checks. */
    const record = {
        objectUrls: { created: [], revoked: [] },
        navigations: [],
        analyzeCalls: [],
        timers: []
    };

    const win = {
        location: {
            pathname: "/upload",
            assign(url) { record.navigations.push(url); }
        },

        URL: {
            createObjectURL(file) {
                const url =
                    "blob:vigilox/" + record.objectUrls.created.length;
                record.objectUrls.created.push({
                    url: url,
                    name: file.name
                });
                return url;
            },
            revokeObjectURL(url) {
                record.objectUrls.revoked.push(url);
            }
        },

        FormData: class FormData {
            constructor() { this.entries = []; }
            append(k, v) { this.entries.push([k, v]); }
        },

        setInterval() { return 1; },
        clearInterval() {},

        /* ==============================================
           PHASE 9.4
           ==============================================
           Timers used to be inert stubs, which was fine
           while the only timer on the page rotated a
           message. The poll loop changed that: an inert
           setTimeout means the job is submitted and its
           outcome never arrives, so every terminal state
           reads as still-processing.

           They are now recorded and fired explicitly by
           runTimers(). Nothing fires on its own, which is
           deliberate -- it turns the poll sequence into
           something a test steps through rather than races
           against.
           ============================================== */

        /* The queue is captured lexically rather than held
           on the window as this.pendingTimers.

           That was the first attempt and it silently did
           nothing: the page module runs inside
           vm.runInNewContext, so `this` inside a window
           method is the contextified global proxy and not the
           sandbox object the harness holds. Timers were
           recorded somewhere the harness could not see, so
           runTimers() always fired nothing and every terminal
           state read as still-processing.

           A closure has no such ambiguity. */

        setTimeout(fn, delay) {
            record.timers.push({
                fn: fn,
                delay: delay,
                cleared: false
            });
            return record.timers.length;
        },

        clearTimeout(handle) {
            const entry = record.timers[handle - 1];

            if (entry) {
                entry.cleared = true;
            }
        },

        runTimers() {
            /* Drained before firing, so a callback that
               schedules the next poll does not extend this
               pass into an infinite loop. */
            const due = record.timers.slice();
            record.timers.length = 0;

            due.forEach(function (entry) {
                if (!entry.cleared) {
                    entry.fn();
                }
            });

            return due.length;
        },

        /* upload.js aborts the request in flight when the
           loop is retired. */
        AbortController: class AbortController {
            constructor() {
                this.signal = { aborted: false, reason: null };
            }
            abort(reason) {
                this.signal.aborted = true;
                this.signal.reason = reason || "aborted";
            }
        },

        addEventListener(name, handler) {
            this.listeners = this.listeners || {};
            this.listeners[name] = this.listeners[name] || [];
            this.listeners[name].push(handler);
        },

        fetch() {
            return Promise.reject(new Error("fetch must not be called"));
        },

        console: { log() {}, warn() {}, error() {} }
    };

    win.window = win;
    win.document = documentStub;
    win.global = win;
    win.record = record;

    return win;
}


function loadScript(win, filename) {
    const code = fs.readFileSync(path.join(STATIC_JS, filename), "utf8");
    vm.runInNewContext(code, win, { filename: filename });
}


function boot() {

    /* Snapshot the behaviour at boot.

       analyzeBehaviour is a module-level variable that each
       check sets before calling boot(). The synchronous part
       of every check runs in order, so the value is right at
       this instant -- but the endpoint stubs below are called
       later, from a poll, by which time another check has set
       it to something else.

       That is the same class of defect as the shared counters:
       concurrent checks reading one mutable module variable.
       Capturing it here pins each window to the behaviour it
       was booted with. */
    const behaviour = analyzeBehaviour;

    const win = buildWindow();

    loadScript(win, "api.js");
    loadScript(win, "common.js");
    loadScript(win, "vocabulary.js");

    /* ==================================================
       PHASE 9.4
       ==================================================
       upload.js submits a job and polls for its state; it no
       longer calls analyzeDocument. So the stub moved, and
       analyzeCalls now counts job submissions -- which is the
       same property every assertion below was actually about:
       how many times the page asked the server to process
       this document.

       analyzeDocument is stubbed to throw, so a silent
       regression back to the synchronous route fails loudly
       instead of passing.

       The behaviour modes are unchanged in meaning:

           resolve   the document processes successfully
           reject    the submission itself is refused
           pending   the job stays in flight

       "resolve" now needs two steps, because the outcome
       arrives from a poll rather than from the submission. The
       payload's document_id is carried into the completed job
       so the existing navigation assertions still read the
       same field.
       ================================================== */

    win.VigiloxApi.endpoints.createDocumentJob = function (file) {

        win.record.analyzeCalls.push(file);

        if (behaviour.mode === "reject") {
            return Promise.reject(behaviour.error);
        }

        return Promise.resolve({
            job_id: "harness-job-1",
            status: "QUEUED",
            is_terminal: false
        });
    };

    win.VigiloxApi.endpoints.getDocumentJob = function () {

        /* ==================================================
           PHASE 12.18 - AN EXPLICIT SEQUENCE OF STATES
           ==================================================
           The three original modes could only express
           "eventually COMPLETED", "refused at submission" and
           "never answers". None of them can show what the page
           looks like while a job is QUEUED, PROCESSING,
           RETRY_WAIT, FAILED or a DUPLICATE -- which is
           exactly what the release blockers are about.

           sequence mode returns the supplied payloads in
           order, one per poll, and repeats the last one
           forever. Every payload is a literal written by the
           test, so a status the backend can produce can be
           put on screen here without a provider, a worker or a
           document.
           ================================================== */
        if (behaviour.mode === "sequence") {

            const list = behaviour.jobs || [];

            const index = Math.min(
                behaviour.polls || 0,
                list.length - 1
            );

            behaviour.polls = (behaviour.polls || 0) + 1;

            return Promise.resolve(
                Object.assign(
                    {
                        job_id: "harness-job-1",
                        is_terminal: false
                    },
                    list[index] || {}
                )
            );
        }

        if (behaviour.mode === "resolve") {

            const payload = behaviour.payload || {};

            return Promise.resolve({
                job_id: "harness-job-1",
                status: "COMPLETED",
                is_terminal: true,
                /* Deliberately reads document_id straight off
                   the configured payload, so a test that
                   omits it still exercises the
                   missing-reference path. */
                document_id: payload.document_id,
                /* The fields the success panel now shows, all
                   of them real job columns. */
                original_filename: "guard.jpg",
                content_type: "image/jpeg",
                size_bytes: 2048,
                attempt_count: 1,
                max_attempts: 3
            });
        }

        if (behaviour.mode === "reject") {
            return Promise.reject(behaviour.error);
        }

        return Promise.resolve({
            job_id: "harness-job-1",
            status: "PROCESSING",
            current_stage: "OCR",
            is_terminal: false
        });
    };

    win.VigiloxApi.endpoints.analyzeDocument = function () {
        throw new Error(
            "upload.js must not call analyzeDocument. The " +
            "Upload page uses the async job API."
        );
    };

    /* getHealth / getReviewerIdentity are called by initShell.
       Resolve them quietly so no unhandled rejection appears. */
    win.VigiloxApi.endpoints.getHealth = function () {
        return Promise.resolve({ status: "ok" });
    };
    win.VigiloxApi.endpoints.getReviewerIdentity = function () {
        return Promise.resolve({
            reviewer: { reviewer_id: "harness", role: "REVIEWER", can_review: true }
        });
    };

    loadScript(win, "upload.js");

    return win;
}


/* ==========================================================
   CHECKS
   ========================================================== */

const results = {};


function check(name, fn) {
    try {
        results[name] = fn();
    } catch (e) {
        results[name] = { error: String(e && e.message || e) };
    }
}


/* ---------- module surface ---------- */

check("module_loaded", () => {
    const win = boot();
    return {
        exposed: Boolean(win.VigiloxUpload),
        max_bytes: win.VigiloxUpload.MAX_BYTES,
        allowed_types: win.VigiloxUpload.ALLOWED_TYPES,
        states: Object.keys(win.VigiloxUpload.STATE),
        initial_state: win.VigiloxUpload.getState(),
        processing_messages: win.VigiloxUpload.PROCESSING_MESSAGES
    };
});


/* ---------- validation ---------- */

check("validation", () => {
    const win = boot();
    const v = win.VigiloxUpload.validateFile;

    const cases = {
        jpeg_ok: v(makeFile("a.jpg", "image/jpeg", 1024)),
        png_ok: v(makeFile("a.png", "image/png", 1024)),
        webp_ok: v(makeFile("a.webp", "image/webp", 1024)),
        jpeg_alt_ext_ok: v(makeFile("a.jpeg", "image/jpeg", 1024)),

        pdf_rejected: v(makeFile("a.pdf", "application/pdf", 1024)),
        gif_rejected: v(makeFile("a.gif", "image/gif", 1024)),
        svg_rejected: v(makeFile("a.svg", "image/svg+xml", 1024)),
        bmp_rejected: v(makeFile("a.bmp", "image/bmp", 1024)),
        tiff_rejected: v(makeFile("a.tif", "image/tiff", 1024)),

        empty_rejected: v(makeFile("a.jpg", "image/jpeg", 0)),
        no_file_rejected: v(null),

        at_limit_ok: v(makeFile("a.jpg", "image/jpeg", 10 * 1024 * 1024)),
        over_limit_rejected: v(makeFile("a.jpg", "image/jpeg", 10 * 1024 * 1024 + 1)),

        // 10,000,000 < 10 MiB, so a decimal limit would wrongly reject this
        decimal_boundary_ok: v(makeFile("a.jpg", "image/jpeg", 10000001)),

        long_name_rejected: v(makeFile("x".repeat(260) + ".jpg", "image/jpeg", 1024)),

        // dragged file with no reported type but a valid extension
        blank_type_valid_ext_ok: v(makeFile("a.png", "", 1024)),
        blank_type_bad_ext_rejected: v(makeFile("a.exe", "", 1024))
    };

    return cases;
});


/* ---------- selection + object URL lifecycle ---------- */

check("object_url_lifecycle", () => {
    const win = boot();
    const input = win.document.getElementById("file-input");

    const first = makeFile("first.jpg", "image/jpeg", 2048);
    input.fire("change", { target: { files: [first] } });

    const afterFirst = {
        created: win.record.objectUrls.created.length,
        revoked: win.record.objectUrls.revoked.length,
        state: win.VigiloxUpload.getState()
    };

    const second = makeFile("second.png", "image/png", 4096);
    input.fire("change", { target: { files: [second] } });

    const afterReplace = {
        created: win.record.objectUrls.created.length,
        revoked: win.record.objectUrls.revoked.length,
        revoked_first: win.record.objectUrls.revoked.indexOf(win.record.objectUrls.created[0].url) !== -1
    };

    win.document.getElementById("remove-button").fire("click", {});

    const afterRemove = {
        revoked: win.record.objectUrls.revoked.length,
        state: win.VigiloxUpload.getState(),
        preview_src: win.document.getElementById("file-preview").src
    };

    // unload must release too
    (win.listeners.beforeunload || []).forEach((h) => h({}));

    return {
        after_first: afterFirst,
        after_replace: afterReplace,
        after_remove: afterRemove,
        all_created_revoked:
            win.record.objectUrls.created.every(
                (c) => win.record.objectUrls.revoked.indexOf(c.url) !== -1
            )
    };
});


/* ==========================================================
   PHASE 12.18 - THE PREVIEW SURVIVES PROCESSING
   ==========================================================
   RELEASE BLOCKER 1.

   applyState used to read

       nodes.fileCard.hidden = next !== STATE.SELECTED

   so the card holding the preview image disappeared the
   instant Analyze was pressed, and stayed gone through
   processing, success and failure. A person watching a job sit
   in RETRY_WAIT for minutes had nothing on screen telling them
   WHICH document was queued.

   These checks walk the job through every status the backend
   can report and assert the preview is still there.
   ========================================================== */

/**
 * Fire the scheduled poll and wait for its promise to settle.
 *
 * runTimers() alone is not enough. It invokes the timer
 * callback, which calls the stubbed endpoint and gets a
 * promise -- the DOM is not touched until that promise's
 * continuation runs, and continuations run after the current
 * synchronous block. A check that read the DOM straight after
 * runTimers() saw the state from BEFORE the poll, which is why
 * the first version of these checks reported "Uploading
 * document" for a job the stub had already answered as
 * RETRY_WAIT.
 *
 * setImmediate drains the microtask queue between steps, the
 * same way the existing polling checks in this file do.
 */
function step(win) {
    return new Promise(function (resolve) {
        setImmediate(function () {
            win.runTimers();
            setImmediate(resolve);
        });
    });
}


function previewSnapshot(win) {
    const card = win.document.getElementById("file-card");
    const image = win.document.getElementById("file-preview");
    const actions = win.document.getElementById("file-actions");

    return {
        state: win.VigiloxUpload.getState(),
        card_visible: card.hidden !== true,
        image_visible: image.hidden !== true,
        preview_src: image.src || "",
        /* A blob: URL and nothing resembling a path. */
        src_is_object_url: String(image.src || "").indexOf("blob:") === 0,
        actions_visible: actions ? actions.hidden !== true : null,
        filename_shown:
            win.document.getElementById("file-name").textContent
    };
}

function selectAndSubmit(win, name) {
    const input = win.document.getElementById("file-input");

    input.fire("change", {
        target: { files: [makeFile(name || "guard.jpg", "image/jpeg", 4096)] }
    });

    const ready = previewSnapshot(win);

    win.document.getElementById("analyze-button").fire("click", {});

    return ready;
}


check("preview_survives_every_job_status", () => {

    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            { status: "QUEUED", attempt_count: 1, max_attempts: 3 },
            {
                status: "PROCESSING",
                current_stage: "OCR",
                attempt_count: 1,
                max_attempts: 3
            },
            {
                status: "RETRY_WAIT",
                attempt_count: 2,
                max_attempts: 3,
                error_code: "PROVIDER_RATE_LIMITED",
                error_message:
                    "The document intelligence service is at capacity.",
                next_attempt_at: "2026-08-22T07:31:25+00:00"
            }
        ]
    };

    const win = boot();

    const ready = selectAndSubmit(win);

    const seen = { READY: ready };

    return ["QUEUED", "PROCESSING", "RETRY_WAIT"].reduce(
        function (chain, label) {
            return chain.then(function () {
                return step(win).then(function () {
                    seen[label] = previewSnapshot(win);
                });
            });
        },
        Promise.resolve()
    ).then(function () {
    return {
        states: seen,
        /* One selection, one submission. A preview must never
           cost a second upload. */
        analyze_calls: win.record.analyzeCalls.length,
        object_urls_created: win.record.objectUrls.created.length,
        processing_message:
            win.document.getElementById("processing-message").textContent,
        processing_note:
            win.document.getElementById("processing-note").textContent
    };
    });
});


check("preview_survives_completed_and_failed", () => {

    /* COMPLETED navigates away, so the assertion is that the
       preview was still present on the last frame before the
       navigation rather than after it. */
    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            { status: "PROCESSING", attempt_count: 1, max_attempts: 3 },
            {
                status: "COMPLETED",
                is_terminal: true,
                document_id: "doc-abc",
                original_filename: "guard.jpg",
                content_type: "image/jpeg",
                size_bytes: 4096,
                attempt_count: 2,
                max_attempts: 3
            }
        ]
    };

    const completedWin = boot();
    selectAndSubmit(completedWin);

    let duringProcessing = null;
    let afterCompleted = null;

    const completedChain = step(completedWin)
        .then(function () {
            duringProcessing = previewSnapshot(completedWin);
            return step(completedWin);
        })
        .then(function () {
            afterCompleted = previewSnapshot(completedWin);
        });

    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            {
                status: "FAILED",
                is_terminal: true,
                error_code: "UNSUPPORTED_DOCUMENT",
                error_message: "That document type is not supported.",
                attempt_count: 3,
                max_attempts: 3
            }
        ]
    };

    const failedWin = boot();
    selectAndSubmit(failedWin);

    return completedChain
        .then(function () {
            return step(failedWin);
        })
        .then(function () {
    const afterFailed = previewSnapshot(failedWin);

    return {
        during_processing: duringProcessing,
        after_completed: afterCompleted,
        navigated: completedWin.record.navigations.length > 0,
        after_failed: afterFailed,
        /* A FAILED job must not leave an <img> with no src
           painted as a broken image. */
        failed_image_has_src:
            String(
                failedWin.document.getElementById("file-preview").src || ""
            ).length > 0
    };
        });
});


check("preview_survives_duplicate", () => {

    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            {
                status: "FAILED",
                is_terminal: true,
                error_code: "DUPLICATE_DOCUMENT",
                error_message:
                    "This document has already been processed.",
                duplicate_of_document_id: "doc-original",
                attempt_count: 1,
                max_attempts: 3
            }
        ]
    };

    const win = boot();
    selectAndSubmit(win, "already-seen.jpg");

    return step(win).then(function () {
    return {
        snapshot: previewSnapshot(win),
        error_title:
            win.document.getElementById("error-title").textContent,
        /* Still exactly one submission: a duplicate does not
           re-upload. */
        analyze_calls: win.record.analyzeCalls.length
    };
    });
});


check("retry_wait_reports_real_attempt_and_time", () => {

    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            {
                status: "RETRY_WAIT",
                attempt_count: 2,
                max_attempts: 3,
                error_code: "PROVIDER_RATE_LIMITED",
                error_message:
                    "The document intelligence service is at capacity. " +
                    "This document is queued and will be retried " +
                    "automatically.",
                next_attempt_at: "2026-08-22T07:31:25+00:00"
            }
        ]
    };

    const win = boot();
    selectAndSubmit(win);

    return step(win).then(function () {

    const note =
        win.document.getElementById("processing-note").textContent;

    /* The expected local rendering, computed the same way the
       page computes it, so the assertion does not depend on
       the timezone the suite happens to run in. */
    const expected = new Date("2026-08-22T07:31:25+00:00")
        .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

    return {
        message:
            win.document.getElementById("processing-message").textContent,
        note: note,
        mentions_capacity:
            note.toLowerCase().indexOf("capacity") !== -1,
        mentions_queued_and_automatic:
            note.toLowerCase().indexOf("retry automatically") !== -1,
        expected_local_time: expected,
        note_has_expected_time: note.indexOf(expected) !== -1,
        says_can_leave:
            note.toLowerCase().indexOf("leave this page") !== -1,
        /* Never hard-coded. */
        has_two_of_three:
            win.document
                .getElementById("processing-message")
                .textContent.indexOf("2 of 3") !== -1
    };
    });
});


check("retry_wait_without_next_attempt_invents_nothing", () => {

    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            {
                status: "RETRY_WAIT",
                attempt_count: 3,
                max_attempts: 3,
                error_code: "PROVIDER_RATE_LIMITED",
                error_message: "At capacity.",
                next_attempt_at: null
            }
        ]
    };

    const win = boot();
    selectAndSubmit(win);

    return step(win).then(function () {

    const note =
        win.document.getElementById("processing-note").textContent;

    return {
        note: note,
        /* No time sentence at all when the backend gave none.
           The page must not compute one. */
        mentions_next_attempt:
            note.toLowerCase().indexOf("next attempt") !== -1,
        has_dangling_around:
            note.indexOf("around .") !== -1 ||
            note.indexOf("around  ") !== -1,
        still_reports_attempts:
            win.document
                .getElementById("processing-message")
                .textContent.indexOf("3 of 3") !== -1
    };
    });
});


check("processing_note_resets_after_retry_clears", () => {

    /* A job that retries and is then picked up must stop
       showing the retry explanation. */
    analyzeBehaviour = {
        mode: "sequence",
        polls: 0,
        jobs: [
            {
                status: "RETRY_WAIT",
                attempt_count: 2,
                max_attempts: 3,
                error_code: "PROVIDER_RATE_LIMITED",
                error_message: "At capacity.",
                next_attempt_at: "2026-08-22T07:31:25+00:00"
            },
            {
                status: "PROCESSING",
                current_stage: "OCR",
                attempt_count: 2,
                max_attempts: 3
            }
        ]
    };

    const win = boot();
    selectAndSubmit(win);

    let whileWaiting = "";
    let afterResume = "";

    return step(win)
        .then(function () {
            whileWaiting = win.document
                .getElementById("processing-note").textContent;
            return step(win);
        })
        .then(function () {
            afterResume = win.document
                .getElementById("processing-note").textContent;

    return {
        while_waiting_mentions_capacity:
            whileWaiting.toLowerCase().indexOf("capacity") !== -1,
        after_resume_mentions_capacity:
            afterResume.toLowerCase().indexOf("capacity") !== -1,
        after_resume_says_background:
            afterResume.toLowerCase().indexOf("background") !== -1
    };
        });
});


check("no_filesystem_path_is_exposed", () => {

    const win = boot();

    /* A browser gives a File no path, but a hostile or
       mistaken name can still LOOK like one. Whatever the
       name, the preview src must be a blob: URL. */
    const input = win.document.getElementById("file-input");

    input.fire("change", {
        target: {
            files: [
                makeFile(
                    "C:\\Users\\DELL\\Desktop\\secret.jpg",
                    "image/jpeg",
                    2048
                )
            ]
        }
    });

    const image = win.document.getElementById("file-preview");
    const src = String(image.src || "");

    return {
        src_is_object_url: src.indexOf("blob:") === 0,
        src_has_drive_letter: /[A-Za-z]:\\/.test(src),
        src_has_backslash: src.indexOf("\\") !== -1,
        /* The name is still shown to the user, as text. */
        name_rendered_as_text:
            win.document.getElementById("file-name").textContent.length > 0
    };
});


/* ---------- invalid selection does not enter SELECTED ---------- */

check("invalid_selection", () => {
    const win = boot();
    const input = win.document.getElementById("file-input");

    input.fire("change", {
        target: { files: [makeFile("a.pdf", "application/pdf", 1024)] }
    });

    return {
        state: win.VigiloxUpload.getState(),
        analyze_disabled:
            win.document.getElementById("analyze-button").disabled,
        message_shown:
            win.document.getElementById("upload-validation").textContent,
        zone_marked_invalid:
            win.document.getElementById("drop-zone").classes.has("is-invalid"),
        // an invalid pick must not create a preview
        object_urls_created: win.record.objectUrls.created.length
    };
});


/* ---------- analyze cannot run without a file ---------- */

check("analyze_requires_file", () => {
    const win = boot();

    win.document.getElementById("analyze-button").fire("click", {});

    return {
        analyze_calls: win.record.analyzeCalls.length,
        state: win.VigiloxUpload.getState()
    };
});


/* ---------- duplicate submission blocked ---------- */

check("duplicate_submission_blocked", () => {
    analyzeBehaviour = { mode: "pending" };

    const win = boot();
    const input = win.document.getElementById("file-input");

    input.fire("change", {
        target: { files: [makeFile("a.jpg", "image/jpeg", 2048)] }
    });

    const button = win.document.getElementById("analyze-button");

    button.fire("click", {});
    const afterFirst = {
        calls: win.record.analyzeCalls.length,
        state: win.VigiloxUpload.getState(),
        disabled: button.disabled,
        pending_class: button.classes.has("is-pending"),
        aria_busy: win.document
            .getElementById("processing-panel")
            .getAttribute("aria-busy")
    };

    // three more attempts while the first is still in flight
    button.fire("click", {});
    button.fire("click", {});
    button.fire("click", {});

    return {
        after_first: afterFirst,
        total_calls: win.record.analyzeCalls.length
    };
});


/* ---------- success navigates with the real document_id ---------- */

check("success_navigation", () => {
    analyzeBehaviour = {
        mode: "resolve",
        payload: {
            status: "success",
            document_id: "abc-123-real",
            analysis: {
                extraction: { document_type: "guard_license" },
                review_decision: {
                    decision: "REVIEW_REQUIRED",
                    review_required: true,
                    priority: "HIGH"
                }
            }
        }
    };

    const win = boot();
    win.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("a.jpg", "image/jpeg", 2048)] }
    });
    win.document.getElementById("analyze-button").fire("click", {});

    /* PHASE 9.4. The outcome now arrives from a poll rather
       than from the submission, so the scheduled timer is
       fired before the state is read. Two drains: the first
       runs the poll, the second runs the navigation timeout
       that a completed job schedules. */
    return new Promise((resolve) => {
        setImmediate(() => {
          win.runTimers();
          setImmediate(() => {
            resolve({
                state: win.VigiloxUpload.getState(),
                success_hidden:
                    win.document.getElementById("success-panel").hidden,
                fact_count: win.document
                    .getElementById("success-facts").children.length,
                analyze_hidden:
                    win.document.getElementById("analyze-button").hidden
            });
        });
    });
          });
});


/* ---------- missing document_id must NOT navigate ---------- */

check("missing_document_id", () => {
    analyzeBehaviour = {
        mode: "resolve",
        payload: { status: "success", analysis: {} }   // no document_id
    };

    const win = boot();
    win.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("a.jpg", "image/jpeg", 2048)] }
    });
    win.document.getElementById("analyze-button").fire("click", {});

    /* PHASE 9.4. The outcome now arrives from a poll rather
       than from the submission, so the scheduled timer is
       fired before the state is read. Two drains: the first
       runs the poll, the second runs the navigation timeout
       that a completed job schedules. */
    return new Promise((resolve) => {
        setImmediate(() => {
          win.runTimers();
          setImmediate(() => {
            resolve({
                state: win.VigiloxUpload.getState(),
                navigations: win.record.navigations.slice(),
                error_message: win.document
                    .getElementById("error-message").textContent
            });
        });
    });
          });
});


/* ---------- structured error rendering + retry ---------- */

check("structured_error", () => {
    const win0 = boot();
    const ApiError = win0.VigiloxApi.ApiError;

    analyzeBehaviour = {
        mode: "reject",
        error: new ApiError({
            status: 400,
            code: "UNSUPPORTED_FILE_TYPE",
            message: "Unsupported file type.",
            requestId: "req-abc-123"
        })
    };

    const win = boot();
    win.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("a.jpg", "image/jpeg", 2048)] }
    });
    win.document.getElementById("analyze-button").fire("click", {});

    /* PHASE 9.4. The outcome now arrives from a poll rather
       than from the submission, so the scheduled timer is
       fired before the state is read. Two drains: the first
       runs the poll, the second runs the navigation timeout
       that a completed job schedules. */
    return new Promise((resolve) => {
        setImmediate(() => {
          win.runTimers();
          setImmediate(() => {
            const metaText = win.document
                .getElementById("error-meta")
                .children.map((c) => c.textContent)
                .join(" | ");

            // retry returns to SELECTED, keeping the file
            win.document.getElementById("retry-button").fire("click", {});

            resolve({
                state_after_error: "ERROR",
                message: win.document
                    .getElementById("error-message").textContent,
                meta: metaText,
                navigations: win.record.navigations.slice(),
                state_after_retry: win.VigiloxUpload.getState(),
                retry_reenables_analyze:
                    win.document.getElementById("analyze-button")
                        .disabled === false
            });
        });
    });
          });
});


/* ---------- network error wording ---------- */

check("network_error", () => {
    const win0 = boot();
    const ApiError = win0.VigiloxApi.ApiError;

    analyzeBehaviour = {
        mode: "reject",
        error: new ApiError({
            status: 0,
            code: "NETWORK_ERROR",
            message: "Could not reach the VIGILOX API.",
            isNetworkError: true
        })
    };

    const win = boot();
    win.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("a.jpg", "image/jpeg", 2048)] }
    });
    win.document.getElementById("analyze-button").fire("click", {});

    /* PHASE 9.4. The outcome now arrives from a poll rather
       than from the submission, so the scheduled timer is
       fired before the state is read. Two drains: the first
       runs the poll, the second runs the navigation timeout
       that a completed job schedules. */
    return new Promise((resolve) => {
        setImmediate(() => {
          win.runTimers();
          setImmediate(() => {
            resolve({
                title: win.document.getElementById("error-title").textContent,
                state: win.VigiloxUpload.getState()
            });
        });
    });
          });
});


/* ---------- FormData used, no manual content-type ---------- */

check("multipart_request", () => {
    const win = boot();

    // exercise the REAL analyzeDocument from api.js
    let captured = null;
    win.fetch = function (path, init) {
        captured = { path: path, init: init };
        return Promise.resolve({
            ok: true,
            status: 200,
            headers: { get: () => "req-1" },
            json: () => Promise.resolve({ document_id: "x" })
        });
    };

    loadScript(win, "api.js");

    win.VigiloxApi.endpoints.analyzeDocument(
        makeFile("a.jpg", "image/jpeg", 10)
    );

    /* PHASE 9.4. The outcome now arrives from a poll rather
       than from the submission, so the scheduled timer is
       fired before the state is read. Two drains: the first
       runs the poll, the second runs the navigation timeout
       that a completed job schedules. */
    return new Promise((resolve) => {
        setImmediate(() => {
          win.runTimers();
          setImmediate(() => {
            const headers = (captured && captured.init.headers) || {};
            resolve({
                path: captured && captured.path,
                method: captured && captured.init.method,
                body_is_formdata:
                    captured &&
                    captured.init.body instanceof win.FormData,
                form_field:
                    captured && captured.init.body.entries.length
                        ? captured.init.body.entries[0][0]
                        : null,
                // the browser must set the boundary itself
                content_type_set: Object.keys(headers).some(
                    (k) => k.toLowerCase() === "content-type"
                )
            });
        });
    });
          });
});


/* ==========================================================
   RUN
   ========================================================== */

Promise.all(
    Object.keys(results).map((k) =>
        Promise.resolve(results[k]).then((v) => { results[k] = v; })
    )
).then(() => {
    process.stdout.write(JSON.stringify(results, null, 2));
});
