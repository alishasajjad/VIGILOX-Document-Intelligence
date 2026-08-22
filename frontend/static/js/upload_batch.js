/* ==========================================================
   VIGILOX BATCH UPLOAD
   PHASE 9.4
   ==========================================================
   Selection, submission and status for a batch of documents.

   Separate from upload.js because it is a distinct flow with
   its own state -- a list rather than one file, one batch
   request rather than one job request, one polling loop
   covering many children -- and not because upload.js was
   getting long.


   ONE POLLING LOOP, NOT ONE PER FILE
   ----------------------------------------------------------
   GET /api/v1/document-batches/{id} returns every child job's
   state in one response, so the batch view is driven by a
   single chain of requests no matter how many documents are
   in it.

   Twenty files with a timer each would be twenty requests
   every interval for information one request already carries.
   Since OCR is the entire cost and takes tens of seconds, that
   would be twenty times the load to learn the same thing.


   WHAT IS NEVER INVENTED
   ----------------------------------------------------------
   No percentage, and no aggregate progress bar. The pipeline
   cannot report progress inside a document, so the honest
   resolution is a count of documents in each real state plus
   the advisory stage the worker last wrote.

   Every state string comes from the job row. The vocabulary
   lives in js/vocabulary.js with the rest of the code-to-
   language translation.
   ========================================================== */

(function (global) {

    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* ======================================================
       LIMITS
       ======================================================
       MAX_FILES mirrors DEFAULT_MAX_BATCH_FILES in
       backend/app/services/job_service.py, and the Python
       suite asserts the two are equal -- so this cannot drift
       into a number the server will reject.

       It is a mirror rather than a fetched value because the
       alternative is a configuration endpoint whose only
       purpose is to tell the browser a number it needs before
       it can render a hint. The server remains authoritative:
       it re-checks the count and returns BATCH_TOO_LARGE, and
       that response is rendered like any other failure.

       MAX_BYTES and the accepted types come from the single
       document flow, because they are the same rules. An async
       endpoint that accepted what the sync one rejected would
       be a way around the validation rather than a second
       entrance to it.
       ====================================================== */

    var MAX_FILES = 20;

    var MAX_BYTES = 10 * 1024 * 1024;

    var ALLOWED_TYPES = {
        "image/jpeg": true,
        "image/png": true,
        "image/webp": true
    };

    var ALLOWED_EXTENSIONS = {
        jpg: true,
        jpeg: true,
        png: true,
        webp: true
    };

    /* Same cadence as the single flow, for the same reason. */
    var POLL_INTERVAL_MS = 2000;

    var MAX_POLLS = 900;


    /* ======================================================
       MODULE STATE
       ====================================================== */

    /* Selected files, each { file, id, reason }. reason is a
       sentence when the file is not acceptable, null when it
       is. Invalid files stay in the list on purpose -- so the
       person can see which one is the problem and remove it,
       rather than being told "some files were rejected". */
    var selection = [];

    var nextId = 0;

    var submitting = false;

    var batchId = null;

    /* Same discipline as the single flow: a token that any
       running loop compares against, so a retired loop cannot
       keep writing to the panel. */
    var pollToken = 0;

    var pollController = null;

    var pollTimer = null;

    var nodes = {};

    var ready = false;


    /* ======================================================
       VALIDATION
       ======================================================
       Deliberately the same checks as the single flow, in the
       same order, so the two modes cannot disagree about what
       is acceptable.
       ====================================================== */

    function fileExtension(name) {

        var text = String(name || "");
        var dot = text.lastIndexOf(".");

        if (dot === -1 || dot === text.length - 1) {
            return "";
        }

        return text.slice(dot + 1).toLowerCase();
    }

    function validateFile(file) {

        if (!file) {
            return "No file was provided.";
        }

        if (!file.name) {
            return "This file has no name.";
        }

        /* An empty file passes a type check and fails
           everything after it, so it is caught here where the
           message can say why. */
        if (typeof file.size === "number" && file.size === 0) {
            return "This file is empty.";
        }

        if (typeof file.size === "number" && file.size > MAX_BYTES) {
            return (
                "This file is " +
                ui.formatBytes(file.size) +
                ". The limit is " +
                ui.formatBytes(MAX_BYTES) +
                "."
            );
        }

        var type = String(file.type || "").toLowerCase();
        var extension = fileExtension(file.name);

        /* The type is checked first because it is what the
           server checks. The extension is a fallback for
           browsers that report an empty type, never an
           override. */
        if (type) {

            if (!ALLOWED_TYPES[type]) {
                return (
                    "This is not a supported document type. " +
                    "Use JPG, PNG or WEBP."
                );
            }

            return null;
        }

        if (!ALLOWED_EXTENSIONS[extension]) {
            return (
                "This is not a supported document type. " +
                "Use JPG, PNG or WEBP."
            );
        }

        return null;
    }


    /* ======================================================
       SELECTION
       ====================================================== */

    function validCount() {

        return selection.filter(function (entry) {
            return entry.reason === null;
        }).length;
    }

    function addFiles(files) {

        var added = 0;
        var overflow = 0;
        var index = 0;

        for (index = 0; index < files.length; index += 1) {

            if (selection.length >= MAX_FILES) {
                overflow += 1;
                continue;
            }

            var file = files[index];

            selection.push({
                id: "batch-item-" + nextId,
                file: file,
                reason: validateFile(file)
            });

            nextId += 1;
            added += 1;
        }

        if (overflow) {
            setValidation(
                "Only " +
                ui.formatCount(MAX_FILES) +
                " documents can be processed in one batch. " +
                ui.formatCount(overflow) +
                " were not added."
            );

        } else {
            setValidation("");
        }

        renderSelection();

        return added;
    }

    function removeAt(id) {

        selection = selection.filter(function (entry) {
            return entry.id !== id;
        });

        setValidation("");
        renderSelection();
    }

    function clearSelection() {

        selection = [];
        setValidation("");

        /* Reset the input so choosing the SAME files again
           still fires a change event. */
        if (nodes.input) {
            nodes.input.value = "";
        }

        renderSelection();
    }

    function setValidation(message) {

        nodes.validation.textContent = message || "";
        nodes.validation.hidden = !message;
    }


    /* ======================================================
       SELECTION RENDERING
       ====================================================== */

    function renderSelection() {

        var rows = [];
        var index = 0;

        for (index = 0; index < selection.length; index += 1) {
            rows.push(selectionRow(selection[index]));
        }

        ui.replaceChildren(nodes.list, rows);

        nodes.selection.hidden = selection.length === 0;

        var usable = validCount();

        nodes.count.textContent =
            ui.formatCount(usable) +
            " of " +
            ui.formatCount(selection.length) +
            " ready, " +
            ui.formatCount(MAX_FILES) +
            " maximum";

        /* Nothing to submit when nothing is valid. The button
           is disabled rather than hidden, so its label still
           explains what the screen is for. */
        nodes.submit.disabled = submitting || usable === 0;

        nodes.clear.disabled = submitting || selection.length === 0;
    }

    function selectionRow(entry) {

        var file = entry.file;
        var invalid = entry.reason !== null;

        var meta = [
            ui.el("span", {
                className: "batch-file-type",
                /* textContent: a browser-reported type is
                   still input. */
                text: file.type || fileExtension(file.name) ||
                    "Unknown type"
            }),
            ui.el("span", {
                className: "batch-file-size",
                text: typeof file.size === "number"
                    ? ui.formatBytes(file.size)
                    : ""
            })
        ];

        var children = [
            ui.el("div", {
                className: "batch-file-main",
                children: [
                    ui.el("span", {
                        className: "batch-file-name",
                        /* The only place an uploaded filename
                           is rendered. textContent, so a name
                           containing markup is text. */
                        text: file.name
                    }),
                    ui.el("div", {
                        className: "batch-file-meta",
                        children: meta
                    })
                ]
            }),

            ui.el("div", {
                className: "batch-file-state",
                children: [
                    invalid
                        ? ui.badge("Cannot process", "badge-state-rejected")
                        : ui.badge("Ready", "badge-neutral")
                ]
            })
        ];

        if (invalid) {
            children.push(
                ui.el("p", {
                    className: "batch-file-reason",
                    text: entry.reason
                })
            );
        }

        /* One remove control per row, labelled with the file
           it removes -- "Remove" twenty times over is useless
           to anyone navigating by control. */
        var remove = ui.el("button", {
            className: "btn btn-ghost btn-sm",
            attrs: {
                type: "button",
                "aria-label": "Remove " + file.name
            },
            text: "Remove"
        });

        remove.addEventListener("click", function () {
            removeAt(entry.id);

            /* Focus has to go somewhere deliberate: the
               element it was on has just been removed from the
               tree, and the browser would otherwise drop focus
               to the body and lose the keyboard user's place. */
            if (selection.length) {
                var buttons = nodes.list.querySelectorAll("button");

                if (buttons.length) {
                    buttons[buttons.length - 1].focus();
                    return;
                }
            }

            nodes.input.focus();
        });

        children.push(
            ui.el("div", {
                className: "batch-file-actions",
                children: [remove]
            })
        );

        return ui.el("li", {
            className: invalid
                ? "batch-file is-invalid"
                : "batch-file",
            children: children
        });
    }


    /* ======================================================
       SUBMISSION
       ====================================================== */

    function submit() {

        /* Two guards, as in the single flow: the module flag
           stops a programmatic or keyboard double-fire, and
           the button is disabled for pointer users. A
           duplicate batch is a second set of real documents,
           not a retry. */
        if (submitting) {
            return;
        }

        var usable = selection.filter(function (entry) {
            return entry.reason === null;
        });

        if (!usable.length) {
            setValidation(
                "None of the selected files can be processed."
            );
            return;
        }

        submitting = true;

        stopPolling();

        nodes.error.hidden = true;
        nodes.selection.hidden = true;
        nodes.progress.hidden = false;
        nodes.progress.setAttribute("aria-busy", "true");
        nodes.select.hidden = true;

        nodes.submit.disabled = true;
        nodes.clear.disabled = true;

        ui.setButtonPending(nodes.submit, true);

        nodes.progressState.textContent = "Uploading documents";

        var token = pollToken;

        api.endpoints.createDocumentBatch(
            usable.map(function (entry) {
                return entry.file;
            })
        ).then(
            function (batch) {

                if (token !== pollToken) {
                    return;
                }

                ui.setButtonPending(nodes.submit, false);
                nodes.submit.disabled = true;

                if (!batch || !batch.batch_id) {

                    submitting = false;

                    renderBatchError(
                        new api.ApiError({
                            status: 0,
                            code: "INVALID_BATCH_RESPONSE",
                            message:
                                "The batch was accepted but no " +
                                "reference was returned. Check " +
                                "the Documents page before " +
                                "submitting again."
                        })
                    );
                    return;
                }

                batchId = batch.batch_id;

                /* Files the server refused at validation are
                   reported here and never appear again, since
                   they have no job to poll. */
                renderRejected(batch.rejected || []);

                /* The 202 already carries the child jobs, so
                   they are rendered immediately rather than
                   leaving the list empty for one interval. */
                renderBatch({
                    batch_id: batchId,
                    status: "QUEUED",
                    counts: countsFromJobs(batch.jobs || []),
                    jobs: batch.jobs || []
                });

                schedulePoll(batchId, token, 0);
            },
            function (error) {

                if (token !== pollToken) {
                    return;
                }

                submitting = false;

                ui.setButtonPending(nodes.submit, false);

                /* The selection is restored, so a rejected
                   batch does not force the files to be picked
                   again. */
                nodes.progress.hidden = true;
                nodes.select.hidden = false;
                nodes.selection.hidden = selection.length === 0;

                renderBatchError(error);
                renderSelection();
            }
        );
    }

    function countsFromJobs(jobs) {

        var counts = {};
        var index = 0;

        for (index = 0; index < jobs.length; index += 1) {

            var status = jobs[index].status;

            counts[status] = (counts[status] || 0) + 1;
        }

        return counts;
    }


    /* ======================================================
       POLLING
       ======================================================
       One chain for the whole batch. setTimeout rather than
       setInterval, scheduled only after each answer arrives,
       so a slow response cannot cause requests to stack.
       ====================================================== */

    function stopPolling() {

        pollToken += 1;

        if (pollTimer !== null) {
            global.clearTimeout(pollTimer);
            pollTimer = null;
        }

        if (pollController !== null) {
            pollController.abort();
            pollController = null;
        }
    }

    function schedulePoll(id, token, polls) {

        if (token !== pollToken) {
            return;
        }

        pollTimer = global.setTimeout(function () {
            pollBatch(id, token, polls);
        }, POLL_INTERVAL_MS);
    }

    function pollBatch(id, token, polls) {

        if (token !== pollToken) {
            return;
        }

        if (polls > MAX_POLLS) {

            submitting = false;

            nodes.progress.setAttribute("aria-busy", "false");

            nodes.progressState.textContent =
                "This batch is taking longer than expected. " +
                "It is still queued on the server - check the " +
                "Documents page before submitting again.";

            return;
        }

        pollController = new global.AbortController();

        api.endpoints.getDocumentBatch(id, {
            signal: pollController.signal
        }).then(
            function (batch) {

                if (token !== pollToken) {
                    return;
                }

                renderBatch(batch);

                if (isTerminal(batch)) {

                    submitting = false;

                    stopPolling();

                    nodes.progress.setAttribute("aria-busy", "false");

                    /* Selecting a new batch has to be possible
                       once this one is finished. */
                    nodes.select.hidden = false;
                    nodes.clear.disabled = false;

                    return;
                }

                schedulePoll(id, token, polls + 1);
            },
            function (error) {

                if (token !== pollToken) {
                    return;
                }

                if (
                    error &&
                    (error.code === "REQUEST_ABORTED" ||
                        error.name === "AbortError")
                ) {
                    return;
                }

                /* A single failed poll is not a failed batch.
                   The jobs are safe on the server, so keep
                   asking. */
                schedulePoll(id, token, polls + 1);
            }
        );
    }

    function isTerminal(batch) {

        if (!batch || !batch.jobs) {
            return false;
        }

        /* Derived from the children rather than from the
           batch's own status string, so a status this build
           does not recognise cannot strand the loop. */
        return batch.jobs.every(function (job) {
            return job.status === "COMPLETED" ||
                job.status === "FAILED";
        });
    }


    /* ======================================================
       BATCH RENDERING
       ====================================================== */

    var SUMMARY_ROWS = [
        { key: "QUEUED", label: "Queued" },
        { key: "PROCESSING", label: "Processing" },
        { key: "RETRY_WAIT", label: "Retrying" },
        { key: "COMPLETED", label: "Completed" },
        { key: "FAILED", label: "Failed" }
    ];

    function renderBatch(batch) {

        var counts = batch.counts || {};

        var total = SUMMARY_ROWS.reduce(function (sum, row) {
            return sum + (counts[row.key] || 0);
        }, 0);

        var cells = [
            summaryCell("Total", total)
        ];

        SUMMARY_ROWS.forEach(function (row) {
            cells.push(
                summaryCell(row.label, counts[row.key] || 0)
            );
        });

        ui.replaceChildren(nodes.summary, cells);

        var described = vocabulary.describeJobStatus(
            batch.status,
            null
        );

        nodes.progressState.textContent = described.label;

        var rows = (batch.jobs || []).map(resultRow);

        ui.replaceChildren(nodes.results, rows);
    }

    function summaryCell(label, value) {

        return ui.el("div", {
            className: "batch-summary-cell",
            children: [
                ui.el("span", {
                    className: "batch-summary-label",
                    text: label
                }),
                ui.el("span", {
                    className: "batch-summary-value numeric",
                    text: ui.formatCount(value)
                })
            ]
        });
    }

    function resultRow(job) {

        var described = vocabulary.describeJobStatus(
            job.status,
            job.current_stage
        );

        var children = [
            ui.el("div", {
                className: "batch-file-main",
                children: [
                    ui.el("span", {
                        className: "batch-file-name",
                        text: job.original_filename
                    }),
                    ui.el("div", {
                        className: "batch-file-meta",
                        children: [
                            ui.el("span", {
                                className: "batch-file-type",
                                text: described.detail || ""
                            })
                        ]
                    })
                ]
            }),

            ui.el("div", {
                className: "batch-file-state",
                children: [
                    ui.jobStatusBadge(job.status)
                ]
            })
        ];

        /* RETRY_WAIT is not a failure, and saying which
           attempt it is on is the difference between "working"
           and "broken" for somebody watching. */
        if (
            job.status === "RETRY_WAIT" &&
            job.attempt_count &&
            job.max_attempts
        ) {
            children.push(
                ui.el("p", {
                    className: "batch-file-reason",
                    text:
                        "Attempt " +
                        ui.formatCount(job.attempt_count) +
                        " of " +
                        ui.formatCount(job.max_attempts) +
                        " did not succeed. This document will " +
                        "be retried automatically."
                })
            );
        }

        /* The job's own safe sentence. Server-authored
           vocabulary, so there is nothing to sanitise -- and
           nothing here reads a traceback, a path or a worker
           identity, because the payload does not carry them. */
        if (job.status === "FAILED" && job.error_message) {
            children.push(
                ui.el("p", {
                    className: "batch-file-reason",
                    text: job.error_message
                })
            );
        }

        var actions = [];

        if (job.status === "COMPLETED") {

            /* documentLink returns null when the id is blank,
               which is what makes /review/undefined
               impossible. */
            var link = ui.documentLink(
                job.document_id,
                "Open Document",
                "btn btn-secondary btn-sm"
            );

            if (link) {
                actions.push(link);

            } else {
                /* Completed with no reference is a real
                   possibility and it is said plainly rather
                   than rendered as a dead link. */
                children.push(
                    ui.el("p", {
                        className: "batch-file-reason",
                        text:
                            "This document was processed but " +
                            "no reference was returned. Check " +
                            "the Documents page."
                    })
                );
            }
        }

        if (actions.length) {
            children.push(
                ui.el("div", {
                    className: "batch-file-actions",
                    children: actions
                })
            );
        }

        return ui.el("li", {
            className: "batch-file",
            children: children
        });
    }

    function renderRejected(rejected) {

        if (!rejected.length) {
            return;
        }

        /* ==================================================
           PHASE 10.3
           ==================================================
           A duplicate inside a batch is separated from a
           genuine rejection, because the two need different
           words and different actions.

           A file rejected for its type or size is a problem
           with that file. A duplicate is not: the document is
           already on file, or already being processed, and
           there is somewhere to go and look. Lumping both
           under "not accepted" would hide that.

           Both are still reported per file by name. "Some
           files were rejected" is not actionable.
           ================================================== */

        var duplicates = rejected.filter(function (entry) {
            return vocabulary.isDuplicateCode(entry.error_code);
        });

        var failures = rejected.filter(function (entry) {
            return !vocabulary.isDuplicateCode(entry.error_code);
        });

        var messages = [];

        if (failures.length) {

            messages.push(
                ui.formatCount(failures.length) +
                " file(s) were not accepted and are not part " +
                "of this batch: " +
                failures.map(function (entry) {
                    return entry.original_filename || "a file";
                }).join(", ")
            );
        }

        if (duplicates.length) {

            messages.push(
                ui.formatCount(duplicates.length) +
                " file(s) were already processed or are " +
                "already being processed, so they were not " +
                "queued again: " +
                duplicates.map(function (entry) {
                    return entry.original_filename || "a file";
                }).join(", ")
            );
        }

        setValidation(
            messages.join(" ")
        );

        renderDuplicateLinks(duplicates);
    }

    /* ======================================================
       WHERE TO GO FOR EACH DUPLICATE
       PHASE 10.3
       ======================================================
       Each duplicate carries a reference: an existing
       document, or the job already processing those bytes.
       Rendered as a link per file so the row is actionable
       rather than merely explained.

       Files whose duplicate carries no reference -- possible
       when the job it collided with finished in between --
       are named in the message above and simply have no link.
       ====================================================== */

    function renderDuplicateLinks(duplicates) {

        if (!nodes.duplicateList) {
            return;
        }

        var rows = duplicates.map(function (entry) {

            var name = entry.original_filename || "a file";

            var children = [
                ui.el("span", {
                    className: "table-primary-cell",
                    text: name
                })
            ];

            if (entry.existing_document_id) {

                children.push(
                    ui.documentLink(
                        entry.existing_document_id,
                        "Open existing document",
                        "btn btn-secondary btn-sm"
                    )
                );

            } else if (entry.existing_job_id) {

                children.push(
                    ui.el("span", {
                        className: "table-secondary-text",
                        text:
                            "Already being processed in this " +
                            "run"
                    })
                );
            }

            return ui.el("li", {
                className: "batch-duplicate-row",
                children: children
            });
        });

        ui.replaceChildren(nodes.duplicateList, rows);

        nodes.duplicateList.hidden = rows.length === 0;
    }

    function renderBatchError(error) {

        var isApiError = error && error.code !== undefined;

        nodes.errorTitle.textContent =
            isApiError && error.isNetworkError
                ? "Cannot reach VIGILOX"
                : "Batch could not be submitted";

        nodes.errorMessage.textContent =
            isApiError
                ? error.message
                : "Something went wrong. Please try again.";

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

        nodes.error.hidden = false;
    }


    /* ======================================================
       MODE
       ======================================================
       Called by upload.js when the mode switch changes, so one
       module owns the switch and this one owns what happens to
       the batch when it is left.
       ====================================================== */

    function setActive(active) {

        if (!ready) {
            return;
        }

        if (!active) {
            /* Leaving batch mode retires the loop. Polling a
               batch nobody is looking at is load for nothing,
               and the jobs carry on server-side regardless. */
            stopPolling();
        }

        if (active && batchId && submitting) {
            /* Returning to a batch that is still running picks
               the loop back up rather than leaving a frozen
               panel. */
            schedulePoll(batchId, pollToken, 0);
        }
    }


    /* ======================================================
       WIRING
       ====================================================== */

    function bindDragAndDrop() {

        nodes.select.addEventListener("dragover", function (event) {
            event.preventDefault();
            nodes.select.classList.add("is-dragover");
        });

        nodes.select.addEventListener("dragleave", function () {
            nodes.select.classList.remove("is-dragover");
        });

        nodes.select.addEventListener("drop", function (event) {
            event.preventDefault();
            nodes.select.classList.remove("is-dragover");

            var dropped = event.dataTransfer &&
                event.dataTransfer.files;

            if (dropped && dropped.length) {
                addFiles(dropped);
            }
        });
    }

    function init() {

        nodes = {
            select: ui.byId("batch-select"),
            input: ui.byId("batch-file-input"),
            validation: ui.byId("batch-validation"),
            duplicateList: ui.byId("batch-duplicate-list"),
            selection: ui.byId("batch-selection"),
            count: ui.byId("batch-selection-count"),
            list: ui.byId("batch-file-list"),
            progress: ui.byId("batch-progress"),
            progressState: ui.byId("batch-progress-state"),
            summary: ui.byId("batch-summary"),
            results: ui.byId("batch-results"),
            error: ui.byId("batch-error"),
            errorTitle: ui.byId("batch-error-title"),
            errorMessage: ui.byId("batch-error-message"),
            errorMeta: ui.byId("batch-error-meta"),
            submit: ui.byId("batch-submit-button"),
            clear: ui.byId("batch-clear-button")
        };

        /* A page without the batch markup is not an error --
           this module is only loaded by the upload page, but
           being defensive costs one check and avoids throwing
           during a partial render. */
        if (!nodes.input || !nodes.submit) {
            return;
        }

        nodes.input.addEventListener("change", function (event) {

            var files = event.target.files;

            if (files && files.length) {
                addFiles(files);
            }
        });

        nodes.input.addEventListener("focus", function () {
            nodes.select.classList.add("is-focused");
        });

        nodes.input.addEventListener("blur", function () {
            nodes.select.classList.remove("is-focused");
        });

        nodes.submit.addEventListener("click", submit);

        nodes.clear.addEventListener("click", function () {
            clearSelection();
            nodes.input.focus();
        });

        bindDragAndDrop();

        global.addEventListener("beforeunload", function () {
            stopPolling();
        });

        ready = true;

        setValidation("");
        renderSelection();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }


    /* ======================================================
       EXPORTED
       ====================================================== */

    global.VigiloxBatchUpload = {
        MAX_FILES: MAX_FILES,
        MAX_BYTES: MAX_BYTES,
        ALLOWED_TYPES: ALLOWED_TYPES,
        POLL_INTERVAL_MS: POLL_INTERVAL_MS,
        MAX_POLLS: MAX_POLLS,
        validateFile: validateFile,
        setActive: setActive,
        getSelection: function () {
            return selection.map(function (entry) {
                return {
                    id: entry.id,
                    name: entry.file.name,
                    reason: entry.reason
                };
            });
        },
        getBatchId: function () {
            return batchId;
        },
        isPolling: function () {
            return pollTimer !== null;
        },
        isSubmitting: function () {
            return submitting;
        }
    };

}(window));
