/* ==========================================================
   VIGILOX UPLOAD
   PHASE 8.7
   ==========================================================

   Drives the Upload Document screen.

   It wraps the EXISTING synchronous endpoint

       POST /api/v1/documents/analyze

   through the shared client in api.js. No new upload API and
   no second fetch implementation.


   TRUTHFUL PROCESSING
   ----------------------------------------------------------
   The endpoint is synchronous and reports no stage
   information, so this module shows an indeterminate spinner
   and rotating high-level messages ONLY.

   There is deliberately no percentage, no progress bar and no
   claim that a specific internal stage has finished. Any
   number here would be fabricated.


   SAFE RENDERING
   ----------------------------------------------------------
   Filenames, server messages and detected document types are
   untrusted. Everything is written with textContent or built
   as DOM nodes. This module contains no innerHTML.


   VALIDATION IS NOT A SECURITY BOUNDARY
   ----------------------------------------------------------
   Client checks exist to give fast feedback. The backend
   re-validates content type, counts real streamed bytes and
   normalises the filename. The server remains authoritative.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* ======================================================
       UPLOAD CONTRACT
       ======================================================
       Mirrors the backend exactly.

       MAX_BYTES is 10 * 1024 * 1024, matching
       MAX_UPLOAD_BYTES in backend/app/main.py. It is NOT
       10,000,000: a 10.4 MB file would pass a decimal check
       and then be rejected by the server.
       ====================================================== */

    var MAX_BYTES = 10 * 1024 * 1024;

    /* Mirrors ALLOWED_CONTENT_TYPES in
       backend/app/api/request_validation.py. Deliberately not
       image/*: GIF, SVG, TIFF and BMP are not supported. */
    var ALLOWED_TYPES = [
        "image/jpeg",
        "image/png",
        "image/webp"
    ];

    /* Extensions are a secondary check only. Browsers
       sometimes report an empty type for a dragged file. */
    var ALLOWED_EXTENSIONS = [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ];

    var MAX_FILENAME_LENGTH = 255;


    /* ======================================================
       STATES
       ======================================================
       One explicit state at a time, rather than a set of
       loosely related booleans.
       ====================================================== */

    var STATE = {
        IDLE: "IDLE",
        SELECTED: "SELECTED",
        ANALYZING: "ANALYZING",
        SUCCESS: "SUCCESS",
        ERROR: "ERROR"
    };


    /* ======================================================
       POLLING
       ======================================================
       PHASE 9.4. The page used to rotate five invented
       sentences on a timer while a synchronous request blocked
       for the whole pipeline -- an eighteen second median on
       measured documents, thirty-three at worst. The sentences
       were decoration: nothing was telling the page anything,
       so "Extracting and validating information" appeared
       whether or not extraction had started.

       Now the document becomes a job and the page asks the
       server what is actually happening.

       The interval is deliberately unhurried. OCR is the
       whole cost and it takes tens of seconds, so polling
       faster would produce many identical answers and achieve
       nothing but load. Every poll is a real request, which is
       why this must not go through the shared-GET
       deduplication in api.js.

       PROCESSING_MESSAGES is kept, unused by the timer, purely
       because the Phase 8.7 suite asserts the page never
       claims a numeric percentage and reads this list to do
       it. It is now what it always should have been: a list of
       strings that are not percentages.
       ====================================================== */

    /* The note under the spinner in its resting form. Kept as
       a constant because RETRY_WAIT replaces it and every
       other status has to be able to put it back.

       It says the job survives the page, which is true: the
       job row and its bytes are committed before this page is
       told the job exists, the worker claims independently, and
       nothing in the API cancels a job on client disconnect. */
    var DEFAULT_PROCESSING_NOTE =
        "You can leave this page. Processing continues in " +
        "the background and the document will appear in " +
        "Documents when it is done.";


    var POLL_INTERVAL_MS = 1500;

    /* A job that never reaches a terminal state must not be
       polled forever. At 1.5 seconds this is twenty minutes,
       comfortably beyond the worst measured document plus its
       retry budget, after which the page says so rather than
       spinning silently. */
    var MAX_POLLS = 800;

    var PROCESSING_MESSAGES = [
        "Uploading document",
        "Queued for processing",
        "Reading the document",
        "Extracting information",
        "Validating the result"
    ];


    /* ======================================================
       MODULE STATE
       ====================================================== */

    var state = STATE.IDLE;
    var selectedFile = null;
    var previewUrl = null;
    var messageTimer = null;

    /* Guards against a second in-flight submission. */
    var submitting = false;

    /* ======================================================
       POLLING STATE
       ======================================================
       pollToken is what makes duplicate polling loops
       impossible. Every loop captures the token it started
       with and stops the moment the module's token has moved
       on, so a retry, a new selection or an unload orphans the
       old loop rather than leaving two of them writing to the
       same panel.

       pollController aborts the request in flight, so leaving
       the page does not leave a socket open waiting for an
       answer nobody will read.
       ====================================================== */

    var pollToken = 0;

    var pollController = null;

    var pollTimer = null;

    var activeJobId = null;

    var nodes = {};


    /* ======================================================
       OBJECT URL LIFECYCLE
       ======================================================
       Every createObjectURL is paired with a revoke, on
       replace, on remove and on unload. An un-revoked URL
       keeps the whole file alive in memory.
       ====================================================== */

    function releasePreview() {

        if (previewUrl) {
            global.URL.revokeObjectURL(previewUrl);
            previewUrl = null;
        }
    }

    function createPreview(file) {

        /* Revoke the previous URL BEFORE creating the next,
           so replacing a file never leaks the old one. */
        releasePreview();

        previewUrl = global.URL.createObjectURL(file);

        return previewUrl;
    }


    /* ======================================================
       VALIDATION
       ======================================================
       Returns null when the file is acceptable, or a
       human-readable reason. Messages describe what the user
       should do, not what the code checked.
       ====================================================== */

    function fileExtension(name) {

        var text = String(name || "");
        var dot = text.lastIndexOf(".");

        return dot === -1 ? "" : text.slice(dot).toLowerCase();
    }

    function validateFile(file) {

        if (!file) {
            return "Please select a document before analyzing.";
        }

        /* A browser reports size 0 for an empty file and for
           some unreadable ones. Either way there is nothing
           to analyze. */
        if (file.size === 0) {
            return (
                "That file appears to be empty. " +
                "Please select a different document."
            );
        }

        if (file.size > MAX_BYTES) {
            return (
                "File exceeds the 10 MB limit. " +
                "Please upload a smaller image."
            );
        }

        var type = String(file.type || "").toLowerCase();
        var extension = fileExtension(file.name);

        var typeAllowed = ALLOWED_TYPES.indexOf(type) !== -1;
        var extensionAllowed =
            ALLOWED_EXTENSIONS.indexOf(extension) !== -1;

        /* Accept when the reported MIME type is allowed, or
           when the type is missing but the extension is
           allowed. A wrong type with a right extension is
           still rejected by the server. */
        if (!typeAllowed && !(type === "" && extensionAllowed)) {
            return (
                "Unsupported file type. " +
                "Please upload a JPG, PNG or WEBP image."
            );
        }

        if (String(file.name || "").length > MAX_FILENAME_LENGTH) {
            return (
                "That filename is too long. " +
                "Please rename the file and try again."
            );
        }

        return null;
    }


    /* ======================================================
       RENDERING
       ====================================================== */

    function setValidationMessage(message) {

        ui.setStatusMessage(
            nodes.validation,
            message || "",
            "error"
        );

        nodes.dropZone.classList.toggle(
            "is-invalid",
            Boolean(message)
        );
    }

    function renderSelectedFile(file) {

        nodes.preview.src = createPreview(file);

        /* Paired with the hide in clearSelection. An <img> with
           no src that is not hidden renders as the browser's
           broken-image icon plus the alt text -- and now that
           the card outlives SELECTED, a src-less preview would
           actually be on screen rather than inside a hidden
           container. */
        nodes.preview.hidden = false;

        /* textContent: a filename is untrusted input. */
        nodes.fileName.textContent = file.name;

        nodes.fileType.textContent =
            file.type || fileExtension(file.name) || "Unknown type";

        nodes.fileSize.textContent = ui.formatBytes(file.size);
    }

    function renderSuccessFacts(job) {

        /* ==================================================
           PHASE 9.4
           ==================================================
           This used to summarise the analyze response:
           document type, machine decision, whether human
           review was required, priority.

           A job response does not carry any of that, and it
           should not. A job row is queue state; putting the
           extraction into it would make it a second, staler
           copy of the document record, in a table nobody
           thinks of as holding personal data.

           So the panel now confirms what was submitted rather
           than what was found. Which is honest, and is also
           the right division of labour: this panel is on
           screen for 900ms before the workspace takes over,
           and the workspace owns the result.

           Fetching the document just to fill four rows for
           under a second would be a request spent on
           decoration.
           ================================================== */

        var rows = [];

        function addRow(label, value) {

            if (ui.isBlank(value)) {
                return;
            }

            rows.push(
                ui.el("div", {
                    className: "detail-row",
                    children: [
                        ui.el("span", {
                            className: "detail-label",
                            text: label
                        }),
                        ui.el("span", {
                            className: "detail-value",
                            text: value
                        })
                    ]
                })
            );
        }

        /* textContent throughout: a filename is untrusted
           input. */
        addRow(
            "Document",
            job.original_filename
        );

        addRow(
            "Type",
            job.content_type
        );

        addRow(
            "Size",
            typeof job.size_bytes === "number" && job.size_bytes > 0
                ? ui.formatBytes(job.size_bytes)
                : null
        );

        /* Only worth saying when it is not the obvious answer.
           "Processed on attempt 1" is noise; "attempt 2 of 3"
           tells somebody that a retry happened and worked. */
        if (
            typeof job.attempt_count === "number" &&
            job.attempt_count > 1
        ) {
            addRow(
                "Attempts",
                ui.formatCount(job.attempt_count) +
                    " of " +
                    ui.formatCount(job.max_attempts)
            );
        }

        ui.replaceChildren(nodes.successFacts, rows);
    }

    /* ======================================================
       DUPLICATE SOURCE
       PHASE 10.3
       ======================================================
       A duplicate is NOT a failure, and the panel says so.

       The danger styling is dropped for an informational tone,
       the title comes from the shared vocabulary, and the
       actions are whatever the server said is available. A
       rejection the user cannot act on is the silent discard
       the policy exists to prevent, so the reference the API
       returned is turned into something clickable.

       The hash is not here, and there is nowhere for it to be:
       the API never sent one.
       ====================================================== */

    function renderDuplicateActions(error) {

        var details = (error && error.details) || {};
        var actions = [];

        /* CASE 1: a document already exists for these bytes.
           Open it. */
        if (details.existing_document_id) {

            actions.push(
                ui.documentLink(
                    details.existing_document_id,
                    "Open existing document",
                    "btn btn-primary btn-sm"
                )
            );
        }

        /* CASE 2: a job is already running for these bytes.
           Follow it rather than starting a second one -- the
           page already knows how to poll a job, so this is
           the same waiting experience the user would have had
           if their own upload had been the first. */
        if (details.existing_job_id) {

            /* Created and then wired, which is the convention
               everywhere else in this frontend. ui.el takes
               className, text, attrs and children -- it has
               no event-handler option, so a handler passed to
               it would be dropped and the button would look
               real and do nothing. */
            var follow = ui.el("button", {
                className: "btn btn-primary btn-sm",
                attrs: { type: "button" },
                text: "Follow existing job"
            });

            follow.addEventListener("click", function () {
                followJob(details.existing_job_id);
            });

            actions.push(follow);
        }

        /* CASE 3: deliberately analyse it again.
           Offered ONLY when a completed document exists.
           While a job is still running there is nothing a
           second identical job could add, and the backend
           refuses it regardless -- so offering the button
           would promise something that cannot happen. */
        if (
            error.code === "DUPLICATE_DOCUMENT" &&
            selectedFile
        ) {
            var again = ui.el("button", {
                className: "btn btn-secondary btn-sm",
                attrs: { type: "button" },
                text: "Analyse again"
            });

            again.addEventListener("click", function () {
                analyze({ reprocess: true });
            });

            actions.push(again);
        }

        /* Optional, like the batch-mode nodes: a page
           without the container simply shows no actions
           rather than failing to render the error at all. */
        if (!nodes.errorActions) {
            return;
        }

        ui.replaceChildren(nodes.errorActions, actions);

        nodes.errorActions.hidden = actions.length === 0;
    }

    function renderDuplicate(error) {

        var described = vocabulary.describeDuplicate(
            error.code
        );

        /* Informational, not danger. Nothing failed. */
        nodes.error.className = "alert alert-info";

        nodes.errorTitle.textContent = described.title;

        /* The server sentence, which already says what to do
           about it. */
        nodes.errorMessage.textContent = error.message;

        var meta = [];

        if (described.explanation) {
            meta.push(
                ui.el("span", { text: described.explanation })
            );
        }

        if (error.requestId) {
            meta.push(
                ui.el("span", {
                    text: "Support Request ID: " + error.requestId
                })
            );
        }

        ui.replaceChildren(nodes.errorMeta, meta);

        renderDuplicateActions(error);
    }

    function renderError(error) {

        var isApiError = error && error.code !== undefined;

        /* PHASE 10.3. Handled first and separately, because
           everything below assumes a failure. */
        if (
            isApiError &&
            vocabulary.isDuplicateCode(error.code)
        ) {
            renderDuplicate(error);
            return;
        }

        /* Restored, in case a duplicate was shown before this
           one. Without this, a real failure after a duplicate
           would inherit the informational styling and read as
           harmless. */
        nodes.error.className = "alert alert-danger";

        if (nodes.errorActions) {
            ui.replaceChildren(nodes.errorActions, []);
            nodes.errorActions.hidden = true;
        }

        nodes.errorTitle.textContent =
            isApiError && error.isNetworkError
                ? "Cannot reach VIGILOX"
                : "Analysis failed";

        nodes.errorMessage.textContent =
            isApiError
                ? error.message
                : "Something went wrong. Please try again.";

        /* Stable code and request id, for support. Never a
           stack trace: the API does not return one. */
        var meta = [];

        if (isApiError && error.code) {
            meta.push(
                ui.el("span", { text: "Error code: " + error.code })
            );
        }

        if (isApiError && error.requestId) {
            meta.push(
                ui.el("span", {
                    text: "Support Request ID: " + error.requestId
                })
            );
        }

        ui.replaceChildren(nodes.errorMeta, meta);
    }


    /* ======================================================
       STATE TRANSITIONS
       ======================================================
       One function owns every visibility decision, so the UI
       can never show two states at once.
       ====================================================== */

    function applyState(next) {

        state = next;

        nodes.dropZone.hidden = next !== STATE.IDLE;

        /* ==================================================
           THE CARD SURVIVES THE STATE CHANGE
           ==================================================
           This used to be `next !== STATE.SELECTED`, which
           meant the card -- and the preview image inside it --
           disappeared the instant Analyze was pressed. From
           then until the document reached the workspace there
           was nothing on screen showing WHICH image had been
           submitted: a spinner, a filename in the panel below,
           and no picture.

           That mattered most in exactly the situation the
           product is in during a provider rate limit. A job in
           RETRY_WAIT can sit for minutes, and the one thing a
           person wants while waiting is confirmation that the
           right document is in the queue.

           The card now persists through ANALYZING, SUCCESS and
           ERROR. Only IDLE hides it, because in IDLE there is
           no file to describe.

           What does NOT persist is the ability to change the
           selection -- see fileActions below.
           ================================================== */
        nodes.fileCard.hidden = next === STATE.IDLE;

        /* Replace and Remove are selection-time controls. Once
           the document is a job on the server, swapping the
           local file would change nothing and only misleads. */
        if (nodes.fileActions) {
            nodes.fileActions.hidden = next !== STATE.SELECTED;
        }

        /* "Ready to analyze" stops being true the moment it is
           analyzed. The panels below carry the live status, so
           this badge simply retires rather than lying. */
        if (nodes.fileReadyRow) {
            nodes.fileReadyRow.hidden = next !== STATE.SELECTED;
        }

        nodes.processing.hidden = next !== STATE.ANALYZING;
        nodes.processing.setAttribute(
            "aria-busy",
            next === STATE.ANALYZING ? "true" : "false"
        );

        nodes.success.hidden = next !== STATE.SUCCESS;

        nodes.error.hidden = next !== STATE.ERROR;

        /* Analyze is available only with a valid selection.
           It is hidden once the document is on its way to the
           workspace, so it cannot be pressed again, and it is
           hidden in ERROR because Try Again replaces it there.

           Leaving it visible in ERROR put "Analyze Document"
           and "Try Again" side by side, which is two buttons
           for one decision. It was reported from a real
           browser, and it survived the original test suite
           because that suite asserted retryButton.hidden was
           false and never asked what else was on screen
           beside it. */
        nodes.analyzeButton.hidden =
            next === STATE.SUCCESS || next === STATE.ERROR;

        /* ORDER MATTERS.
           setButtonPending(..., false) clears the disabled
           attribute, so the pending state is applied FIRST
           and the real enablement rule is applied after it.
           Doing this the other way round left Analyze
           clickable with no file selected. */
        ui.setButtonPending(
            nodes.analyzeButton,
            next === STATE.ANALYZING
        );

        nodes.analyzeButton.disabled = next !== STATE.SELECTED;

        nodes.retryButton.hidden = next !== STATE.ERROR;

        if (next !== STATE.IDLE && next !== STATE.SELECTED) {
            setValidationMessage("");
        }
    }


    /* ======================================================
       PROCESSING MESSAGES
       ======================================================
       Rotated on a slow interval. Fast churn in an aria-live
       region would spam a screen reader, which is why the
       cadence is deliberately unhurried.
       ====================================================== */

    function stopPolling() {

        /* Invalidating the token first means any loop already
           past its own check will still fail its next one. */
        pollToken += 1;

        if (pollTimer !== null) {
            global.clearTimeout(pollTimer);
            pollTimer = null;
        }

        if (pollController !== null) {
            pollController.abort();
            pollController = null;
        }

        activeJobId = null;
    }

    /* Kept as a no-op name so the shutdown path below and the
       existing tests keep one vocabulary. There is no longer a
       message timer to stop; there is a poll loop. */
    function stopProcessingMessages() {
        stopPolling();
    }

    function renderJobStatus(job) {

        var described = vocabulary.describeJobStatus(
            job && job.status,
            job && job.current_stage
        );

        /* One line, from the server. The label is the state,
           the detail is the advisory stage when there is
           one. */
        var text = described.label;

        if (described.detail) {
            text = described.label + " - " + described.detail;
        }

        nodes.processingMessage.textContent = text;

        /* A job that was in RETRY_WAIT and is now claimed again
           must not keep the retry explanation. Restoring the
           default here means the note always describes the
           state the panel is currently showing. */
        if (nodes.processingNote) {
            nodes.processingNote.textContent = DEFAULT_PROCESSING_NOTE;
        }
    }

    /**
     * A human local time for a backend timestamp, or null.
     *
     * The time is ALWAYS the backend's next_attempt_at. This
     * never computes a retry moment: the scheduler owns that
     * decision, and a number invented here would drift from it
     * and then be wrong in a way nobody could explain.
     *
     * Returns null for a missing, empty or unparseable value,
     * and the caller says nothing rather than guessing.
     */
    function formatRetryTime(value) {

        if (!value) {
            return null;
        }

        var when = new global.Date(value);

        if (isNaN(when.getTime())) {
            return null;
        }

        /* toLocaleTimeString without a locale argument uses the
           viewer's own, which is the only correct answer for
           "when will this happen" shown to a person. */
        try {
            return when.toLocaleTimeString([], {
                hour: "numeric",
                minute: "2-digit"
            });

        } catch (error) {
            return when.toLocaleTimeString();
        }
    }

    function renderRetryWait(job) {

        /* ==================================================
           WAITING IS NOT STUCK
           ==================================================
           A job in RETRY_WAIT during a provider rate limit is
           working exactly as designed, and the previous
           version of this panel said so in a way that read as
           a stall: a spinner, a label, and nothing about why
           or for how long.

           Three facts turn it from "broken" into "waiting",
           and all three come from the API:

             attempt_count / max_attempts   how far along
             error_code                     why it is waiting
             next_attempt_at                when it resumes

           Nothing here is computed locally and nothing is
           hard-coded -- notably not "attempt 1 of 3".
           ================================================== */

        var described = vocabulary.describeJobStatus(
            job.status,
            null
        );

        var text = described.label;

        if (job.attempt_count && job.max_attempts) {
            text =
                described.label +
                " - attempt " +
                ui.formatCount(job.attempt_count) +
                " of " +
                ui.formatCount(job.max_attempts);
        }

        nodes.processingMessage.textContent = text;

        if (!nodes.processingNote) {
            return;
        }

        /* ==================================================
           THE NOTE CARRIES THE REASON AND THE TIME
           ==================================================
           Assembled as separate sentences so a missing
           next_attempt_at simply drops one, rather than
           producing "will retry around ." */

        var sentences = [];

        if (job.error_code === "PROVIDER_RATE_LIMITED") {
            sentences.push(
                "The extraction provider is temporarily at " +
                    "capacity."
            );

        } else if (job.error_message) {
            /* The backend's safe message. It is written for a
               person and carries no OCR text, no field values
               and no filename. */
            sentences.push(job.error_message);
        }

        sentences.push(
            "Your document is safely queued and will retry " +
                "automatically."
        );

        var at = formatRetryTime(job.next_attempt_at);

        if (at) {
            sentences.push("Next attempt around " + at + ".");
        }

        sentences.push(
            "You can leave this page - processing continues " +
                "in the background."
        );

        /* textContent, not innerHTML: error_message is server
           text and this is a rendering path, not a template. */
        nodes.processingNote.textContent = sentences.join(" ");
    }


    /* ======================================================
       POLL LOOP
       ======================================================
       setTimeout rather than setInterval, scheduled only after
       each answer arrives. An interval would keep firing while
       a slow response was outstanding and stack requests on a
       server that is already busy.
       ====================================================== */

    function pollJob(jobId, token, polls) {

        if (token !== pollToken) {
            return;
        }

        if (polls > MAX_POLLS) {

            submitting = false;

            /* ==============================================
               THE CEILING IS NOT A FAILURE
               ==============================================
               Hitting it means this PAGE stopped watching, not
               that the job stopped. The distinction became
               important with provider rate limiting: a job in
               RETRY_WAIT can legitimately outlast twenty
               minutes of polling, and the old wording --
               "taking longer than expected", in the error
               panel -- read as a failure the user should do
               something about.

               The code is now STILL_PROCESSING so nothing
               downstream classifies it as a processing error,
               and the wording tells the truth: the work
               continues and there is a place to see it.
               ============================================== */
            renderError(
                new api.ApiError({
                    status: 0,
                    code: "STILL_PROCESSING",
                    message:
                        "This page has stopped watching, but " +
                        "processing continues in the " +
                        "background. The document will appear " +
                        "in Documents when it is done - do " +
                        "not upload it again."
                })
            );

            applyState(STATE.ERROR);
            return;
        }

        pollController = new global.AbortController();

        api.endpoints.getDocumentJob(jobId, {
            signal: pollController.signal
        }).then(
            function (job) {

                if (token !== pollToken) {
                    return;
                }

                handleJobUpdate(job, token, polls);
            },
            function (error) {

                if (token !== pollToken) {
                    return;
                }

                /* An aborted poll is not a failure. It means
                   this loop was deliberately retired. */
                if (
                    error &&
                    (error.code === "REQUEST_ABORTED" ||
                        error.name === "AbortError")
                ) {
                    return;
                }

                /* A single failed poll is not a failed
                   document. The job is safe on the server, so
                   keep asking -- a dropped connection should
                   not turn a document that is processing
                   normally into a reported failure. */
                schedulePoll(jobId, token, polls + 1);
            }
        );
    }

    function schedulePoll(jobId, token, polls) {

        if (token !== pollToken) {
            return;
        }

        pollTimer = global.setTimeout(function () {
            pollJob(jobId, token, polls);
        }, POLL_INTERVAL_MS);
    }

    function handleJobUpdate(job, token, polls) {

        if (!job || !job.status) {
            schedulePoll(job && job.job_id, token, polls + 1);
            return;
        }

        if (job.status === "COMPLETED") {

            stopPolling();

            var documentId = job.document_id;

            /* The document id must come from the server.
               Never construct or guess one. */
            if (!documentId) {

                submitting = false;

                renderError(
                    new api.ApiError({
                        status: 0,
                        code: "INVALID_JOB_RESPONSE",
                        message:
                            "The document was processed but no " +
                            "document reference was returned. " +
                            "Check the Documents page before " +
                            "uploading again."
                    })
                );

                applyState(STATE.ERROR);
                return;
            }

            renderSuccessFacts(job);
            applyState(STATE.SUCCESS);

            /* submitting stays true: this page is leaving and
               must not accept another submission. */
            global.setTimeout(function () {
                global.location.assign(
                    "/review/" + encodeURIComponent(documentId)
                );
            }, 900);

            return;
        }

        if (job.status === "FAILED") {

            stopPolling();

            submitting = false;

            /* The job's own code and sentence. Both are
               server-authored vocabulary, so there is nothing
               to sanitise here. */
            renderError(
                new api.ApiError({
                    status: 0,
                    code: job.error_code || "PROCESSING_FAILED",
                    message:
                        job.error_message ||
                        "This document could not be processed."
                })
            );

            applyState(STATE.ERROR);
            return;
        }

        /* QUEUED, PROCESSING, RETRY_WAIT: still working. All
           three share one visual state, because they are all
           "the user is waiting" -- only the label differs, and
           the label comes from the server. */
        if (job.status === "RETRY_WAIT") {
            renderRetryWait(job);

        } else {
            renderJobStatus(job);
        }

        schedulePoll(job.job_id, token, polls + 1);
    }


    /* ======================================================
       FILE SELECTION
       ====================================================== */

    function selectFile(file) {

        /* A new selection always clears the previous outcome,
           so no stale success or error survives. */
        var reason = validateFile(file);

        if (reason) {
            clearSelection();
            setValidationMessage(reason);
            applyState(STATE.IDLE);
            return;
        }

        selectedFile = file;

        setValidationMessage("");
        renderSelectedFile(file);
        applyState(STATE.SELECTED);
    }

    function clearSelection() {

        selectedFile = null;

        releasePreview();

        nodes.preview.removeAttribute("src");

        /* Hidden as well as src-less. Removing the attribute
           alone leaves an element the browser paints as a
           broken image. */
        nodes.preview.hidden = true;

        nodes.fileName.textContent = "";
        nodes.fileType.textContent = "";
        nodes.fileSize.textContent = "";

        ui.replaceChildren(nodes.errorMeta, []);
        ui.replaceChildren(nodes.successFacts, []);

        /* Reset the input so choosing the SAME file again
           still fires a change event. */
        nodes.fileInput.value = "";
    }

    function removeFile() {

        clearSelection();
        setValidationMessage("");
        applyState(STATE.IDLE);
        nodes.fileInput.focus();
    }


    /* ======================================================
       FOLLOW AN EXISTING JOB
       PHASE 10.3
       ======================================================
       Attach the normal polling loop to a job somebody else
       already started for these exact bytes.

       Nothing is created. This is the difference between
       "your file is already being handled, here is its
       progress" and starting a second identical pipeline run.
       ====================================================== */

    function followJob(jobId) {

        if (!jobId) {
            return;
        }

        stopPolling();

        submitting = true;

        applyState(STATE.ANALYZING);

        nodes.processingMessage.textContent =
            "Following the job already processing this file";

        activeJobId = jobId;

        var token = pollToken;

        /* One interval, not an immediate fetch: the poller
           owns every request to the job endpoint, so there is
           only one place that can be in flight. */
        schedulePoll(jobId, token, 0);
    }


    /* ======================================================
       ANALYZE
       ====================================================== */

    function analyze(options) {

        var reprocess =
            options && options.reprocess === true;

        /* Two guards: the module flag stops a programmatic or
           keyboard double-fire, and the button is disabled for
           pointer users. A duplicate submission would be a
           second real document, not a retry. */
        if (submitting) {
            return;
        }

        var reason = validateFile(selectedFile);

        if (reason) {
            setValidationMessage(reason);
            return;
        }

        submitting = true;

        /* Any previous loop is retired before a new one
           starts, so a retry can never leave two loops
           writing to the same panel. */
        stopPolling();

        applyState(STATE.ANALYZING);

        nodes.processingMessage.textContent =
            "Uploading document";

        var token = pollToken;

        api.endpoints.createDocumentJob(selectedFile, {
            reprocess: reprocess
        }).then(
            function (job) {

                if (token !== pollToken) {
                    return;
                }

                var jobId = job && job.job_id;

                if (!jobId) {

                    submitting = false;

                    renderError(
                        new api.ApiError({
                            status: 0,
                            code: "INVALID_JOB_RESPONSE",
                            message:
                                "The document was accepted but no " +
                                "processing reference was " +
                                "returned. Check the Documents " +
                                "page before uploading again."
                        })
                    );

                    applyState(STATE.ERROR);
                    return;
                }

                activeJobId = jobId;

                /* The 202 already carries the job's state, so
                   it is rendered immediately rather than
                   leaving the panel blank for one interval. */
                handleJobUpdate(job, token, 0);
            },
            function (error) {

                if (token !== pollToken) {
                    return;
                }

                /* The selected file is kept, so a retry does
                   not force the user to pick it again. */
                submitting = false;

                renderError(error);
                applyState(STATE.ERROR);
            }
        );
    }

    function retry() {

        stopPolling();

        if (selectedFile) {
            applyState(STATE.SELECTED);
        } else {
            applyState(STATE.IDLE);
        }
    }


    /* ======================================================
       DRAG AND DROP
       ======================================================
       An enhancement. Every action here is also reachable
       through the native file input.
       ====================================================== */

    function bindDragAndDrop() {

        ["dragenter", "dragover"].forEach(function (name) {

            nodes.dropZone.addEventListener(name, function (event) {
                event.preventDefault();
                nodes.dropZone.classList.add("is-dragging");
            });
        });

        ["dragleave", "dragend"].forEach(function (name) {

            nodes.dropZone.addEventListener(name, function () {
                nodes.dropZone.classList.remove("is-dragging");
            });
        });

        nodes.dropZone.addEventListener("drop", function (event) {

            event.preventDefault();
            nodes.dropZone.classList.remove("is-dragging");

            var transfer = event.dataTransfer;

            if (!transfer || !transfer.files || !transfer.files.length) {
                return;
            }

            /* Exactly one file. Dropping several takes the
               first and says so, rather than silently
               ignoring the rest. */
            if (transfer.files.length > 1) {
                setValidationMessage(
                    "One document at a time. Using the first file."
                );
            }

            selectFile(transfer.files[0]);
        });

        /* The browser would otherwise navigate away from the
           page when a file is dropped outside the zone. */
        global.addEventListener("dragover", function (event) {
            event.preventDefault();
        });

        global.addEventListener("drop", function (event) {
            event.preventDefault();
        });
    }


    /* ======================================================
       INITIALISE
       ====================================================== */

    /* ======================================================
       MODE SWITCH
       ======================================================
       PHASE 9.4. Single document or batch. Two panels, exactly
       one visible, which is the same exclusivity rule the rest
       of this page follows and is checked the same way.

       Switching away from single mode retires any poll loop it
       had running: a job carries on server-side regardless, so
       polling a panel nobody is looking at is load for
       nothing. The batch module does the same in reverse
       through setActive().
       ====================================================== */

    var MODES = {
        SINGLE: "single",
        BATCH: "batch"
    };

    var mode = MODES.SINGLE;

    function applyMode(next) {

        mode = next;

        var single = next === MODES.SINGLE;

        nodes.singleMode.hidden = !single;
        nodes.batchMode.hidden = single;

        nodes.singleActions.hidden = !single;
        nodes.batchActions.hidden = single;

        if (single) {
            /* Nothing to do for the single flow: its own state
               machine still owns what is visible inside its
               panel. */
            setValidationMessage("");

        } else {
            /* Leaving single mode mid-analysis abandons the
               view, not the work. The job is durable. */
            stopPolling();
            submitting = false;
            applyState(STATE.IDLE);
            clearSelection();
        }

        if (global.VigiloxBatchUpload) {
            global.VigiloxBatchUpload.setActive(!single);
        }
    }

    function bindModeSwitch() {

        if (!nodes.modeSingle || !nodes.modeBatch) {
            return;
        }

        nodes.modeSingle.addEventListener("change", function () {
            if (nodes.modeSingle.checked) {
                applyMode(MODES.SINGLE);
            }
        });

        nodes.modeBatch.addEventListener("change", function () {
            if (nodes.modeBatch.checked) {
                applyMode(MODES.BATCH);
            }
        });
    }


    function init() {

        nodes = {
            dropZone: ui.byId("drop-zone"),
            fileInput: ui.byId("file-input"),
            validation: ui.byId("upload-validation"),

            fileCard: ui.byId("file-card"),
            preview: ui.byId("file-preview"),
            fileActions: ui.byId("file-actions"),
            fileReadyRow: ui.byId("file-ready-row"),

            /* Mode switch and the two panels it toggles. */
            modeSingle: ui.byId("mode-single"),
            modeBatch: ui.byId("mode-batch"),
            singleMode: ui.byId("single-mode"),
            batchMode: ui.byId("batch-mode"),
            singleActions: ui.byId("single-actions"),
            batchActions: ui.byId("batch-actions"),
            fileName: ui.byId("file-name"),
            fileType: ui.byId("file-type"),
            fileSize: ui.byId("file-size"),
            removeButton: ui.byId("remove-button"),

            processing: ui.byId("processing-panel"),
            processingMessage: ui.byId("processing-message"),
            processingNote: ui.byId("processing-note"),

            success: ui.byId("success-panel"),
            successFacts: ui.byId("success-facts"),

            error: ui.byId("error-panel"),
            errorTitle: ui.byId("error-title"),
            errorMessage: ui.byId("error-message"),
            errorMeta: ui.byId("error-meta"),
            errorActions: ui.byId("error-actions"),

            analyzeButton: ui.byId("analyze-button"),
            retryButton: ui.byId("retry-button")
        };

        if (!nodes.dropZone || !nodes.fileInput) {
            return;
        }

        /* Shell: navigation state, reviewer identity and the
           liveness indicator, from the shared module. */
        ui.initShell();

        nodes.fileInput.addEventListener("change", function (event) {

            var files = event.target.files;

            if (files && files.length) {
                selectFile(files[0]);
            }
        });

        /* Reflect input focus on the zone, so keyboard users
           see where they are even though the input itself is
           visually hidden. */
        nodes.fileInput.addEventListener("focus", function () {
            nodes.dropZone.classList.add("is-focused");
        });

        nodes.fileInput.addEventListener("blur", function () {
            nodes.dropZone.classList.remove("is-focused");
        });

        nodes.removeButton.addEventListener("click", removeFile);

        nodes.analyzeButton.addEventListener("click", analyze);

        nodes.retryButton.addEventListener("click", retry);

        bindDragAndDrop();

        /* Release the preview on unload as well as on
           replace and remove. */
        global.addEventListener("beforeunload", function () {
            stopProcessingMessages();
            releasePreview();
        });

        bindModeSwitch();

        applyState(STATE.IDLE);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }


    /* ======================================================
       EXPORTED FOR TESTS
       ====================================================== */

    global.VigiloxUpload = {
        STATE: STATE,
        MAX_BYTES: MAX_BYTES,
        ALLOWED_TYPES: ALLOWED_TYPES,
        ALLOWED_EXTENSIONS: ALLOWED_EXTENSIONS,
        PROCESSING_MESSAGES: PROCESSING_MESSAGES,
        POLL_INTERVAL_MS: POLL_INTERVAL_MS,
        MAX_POLLS: MAX_POLLS,
        validateFile: validateFile,
        getState: function () {
            return state;
        },
        MODES: MODES,
        getMode: function () {
            return mode;
        },
        getActiveJobId: function () {
            return activeJobId;
        },
        isPolling: function () {
            return pollTimer !== null;
        }
    };

}(window));
