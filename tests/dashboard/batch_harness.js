/* ==========================================================
   VIGILOX BATCH UPLOAD HARNESS
   PHASE 9.4
   ==========================================================
   Executes js/upload_batch.js and js/upload.js against the
   real shipped upload page, and reports both behaviour and
   computed visibility.

   The interesting claims are the ones a single-file test
   cannot make:

     - one invalid file does not reject its siblings, and the
       invalid one is named
     - removing a file removes that file
     - the count cap holds, and the overflow is reported
     - four submit clicks create one batch
     - one polling chain covers the whole batch, not one
       timer per file
     - a mixed terminal batch shows two Open Document links
       and one safe failure sentence, at the same time
     - a completed job with no document_id produces no link
       and no navigation

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");

const WIDTHS = [1920, 1440, 1366, 1024, 768, 390];

const results = {};

function check(name, fn) {
    try {
        results[name] = fn();
    } catch (error) {
        results[name] = {
            harness_error: String(error && error.stack || error)
        };
    }
}


/* ==========================================================
   BOOT
   ========================================================== */

function boot(behaviour) {
    const win = stub.createWindow({ pathname: "/upload" });

    stub.loadPage(win, "upload.html");
    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");
    stub.loadScript(win, "js/vocabulary.js");

    const endpoints = win.VigiloxApi.endpoints;

    /* On the window, not in module scope: checks run
       concurrently and a shared counter attributes one boot's
       requests to another. */
    win.calls = { batch: 0, status: 0, job: 0, files: 0 };

    endpoints.createDocumentJob = function () {
        win.calls.job += 1;
        return Promise.resolve({
            job_id: "j", status: "QUEUED", is_terminal: false
        });
    };

    endpoints.getDocumentJob = function () {
        return Promise.resolve({
            job_id: "j", status: "PROCESSING",
            current_stage: "OCR", is_terminal: false
        });
    };

    endpoints.createDocumentBatch = function (files) {
        win.calls.batch += 1;
        win.calls.files = files.length;

        if (behaviour.batchRejects) {
            return Promise.reject(behaviour.batchRejects);
        }

        return Promise.resolve(behaviour.created);
    };

    endpoints.getDocumentBatch = function () {
        const index = win.calls.status;
        win.calls.status += 1;

        const sequence = behaviour.statuses || [];

        return Promise.resolve(
            sequence[Math.min(index, sequence.length - 1)]
        );
    };

    endpoints.getHealth = function () {
        return Promise.resolve({ status: "ok" });
    };

    endpoints.getReviewerIdentity = function () {
        return Promise.resolve({
            reviewer: {
                reviewer_id: "r",
                role: "REVIEWER",
                can_review: true
            }
        });
    };

    stub.loadScript(win, "js/upload.js");
    stub.loadScript(win, "js/upload_batch.js");
    win.document.ready();

    return win;
}

function toBatchMode(win) {
    const batch = win.document.getElementById("mode-batch");
    win.document.getElementById("mode-single").checked = false;
    batch.checked = true;
    batch.fire("change", {});
}

function toSingleMode(win) {
    const single = win.document.getElementById("mode-single");
    win.document.getElementById("mode-batch").checked = false;
    single.checked = true;
    single.fire("change", {});
}

function pick(win, files) {
    win.document
        .getElementById("batch-file-input")
        .fire("change", { target: { files: files } });
}

function file(name, type, size) {
    return { name: name, type: type, size: size };
}

function settle(times) {
    return new Promise(function (resolve) {
        let count = 0;
        const step = function () {
            count += 1;
            if (count > times) { return resolve(); }
            setImmediate(step);
        };
        step();
    });
}

function displayed(win, id, width) {
    const vis = stub.createVisibility("upload.html", { width: width });
    const node = win.document.getElementById(id);
    return Boolean(node) && vis.isDisplayed(node);
}

function listRows(win, id) {
    return win.document
        .getElementById(id)
        .childNodes
        .filter(function (node) { return node.nodeType === 1; });
}


/* Every scenario below shares this batch shape: three valid
   files queued, one rejected at validation, then a mixed
   terminal outcome. */
const MIXED = {
    created: {
        batch_id: "b1",
        submitted_count: 4,
        queued_count: 3,
        rejected: [
            {
                original_filename: "notes.txt",
                error_code: "UNSUPPORTED_FILE_TYPE",
                error_message: "not supported"
            }
        ],
        jobs: [
            { job_id: "j1", status: "QUEUED", original_filename: "a.jpg" },
            { job_id: "j2", status: "QUEUED", original_filename: "b.png" },
            { job_id: "j3", status: "QUEUED", original_filename: "c.webp" }
        ]
    },
    statuses: [
        {
            batch_id: "b1",
            status: "PROCESSING",
            counts: {
                QUEUED: 1, PROCESSING: 1, RETRY_WAIT: 1,
                COMPLETED: 0, FAILED: 0
            },
            jobs: [
                {
                    job_id: "j1", status: "PROCESSING",
                    current_stage: "OCR", original_filename: "a.jpg"
                },
                {
                    job_id: "j2", status: "RETRY_WAIT",
                    attempt_count: 1, max_attempts: 3,
                    original_filename: "b.png",
                    error_code: "PROVIDER_RATE_LIMITED",
                    error_message: "at capacity"
                },
                {
                    job_id: "j3", status: "QUEUED",
                    original_filename: "c.webp"
                }
            ]
        },
        {
            batch_id: "b1",
            status: "COMPLETED_WITH_FAILURES",
            counts: {
                QUEUED: 0, PROCESSING: 0, RETRY_WAIT: 0,
                COMPLETED: 2, FAILED: 1
            },
            jobs: [
                {
                    job_id: "j1", status: "COMPLETED",
                    document_id: "doc-a", original_filename: "a.jpg"
                },
                {
                    job_id: "j2", status: "COMPLETED",
                    document_id: "doc-b", original_filename: "b.png"
                },
                {
                    job_id: "j3", status: "FAILED",
                    original_filename: "c.webp",
                    error_code: "UNSUPPORTED_DOCUMENT",
                    error_message: "Not a supported document type."
                }
            ]
        }
    ]
};


/* ==========================================================
   1. MODE SWITCH
   ========================================================== */

check("mode_switch", function () {

    const win = boot(MIXED);
    const observed = {};
    const violations = [];

    WIDTHS.forEach(function (width) {
        observed["single@" + width] = {
            single: displayed(win, "single-mode", width),
            batch: displayed(win, "batch-mode", width),
            single_actions: displayed(win, "single-actions", width),
            batch_actions: displayed(win, "batch-actions", width)
        };
    });

    toBatchMode(win);

    WIDTHS.forEach(function (width) {
        observed["batch@" + width] = {
            single: displayed(win, "single-mode", width),
            batch: displayed(win, "batch-mode", width),
            single_actions: displayed(win, "single-actions", width),
            batch_actions: displayed(win, "batch-actions", width)
        };
    });

    Object.keys(observed).forEach(function (key) {
        const shown = observed[key];

        /* Exactly one panel, and its actions with it. */
        if (shown.single === shown.batch) {
            violations.push({ key: key, both_or_neither: true });
        }

        if (shown.single !== shown.single_actions) {
            violations.push({ key: key, actions_mismatch: "single" });
        }

        if (shown.batch !== shown.batch_actions) {
            violations.push({ key: key, actions_mismatch: "batch" });
        }
    });

    const radios = win.document
        .querySelectorAll('input[name="upload-mode"]');

    return {
        observed: observed,
        violations: violations,
        mode_after_switch: win.VigiloxUpload.getMode(),
        radio_count: radios.length,
        /* Real radios in a real radiogroup: arrow keys,
           grouping and "1 of 2" come from the platform. */
        is_radiogroup: Boolean(
            win.document.querySelectorAll('[role="radiogroup"]').length
        ),
        every_radio_labelled: radios.every(function (radio) {
            return win.document
                .querySelectorAll('label[for="' + radio.id + '"]')
                .length === 1;
        })
    };
});


/* ==========================================================
   2. SELECTION AND VALIDATION
   ========================================================== */

check("selection_validation", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    pick(win, [
        file("a.jpg", "image/jpeg", 4096),
        file("b.png", "image/png", 8192),
        file("c.webp", "image/webp", 2048),
        file("notes.txt", "text/plain", 100),
        file("huge.jpg", "image/jpeg", 11 * 1024 * 1024),
        file("empty.png", "image/png", 0),
        /* No type reported: the extension is the fallback,
           never an override. */
        file("typeless.jpg", "", 1024),
        file("typeless.exe", "", 1024)
    ]);

    const batch = win.VigiloxBatchUpload;
    const selection = batch.getSelection();

    const byName = {};
    selection.forEach(function (entry) {
        byName[entry.name] = entry.reason;
    });

    const rows = listRows(win, "batch-file-list");

    return {
        selected: selection.length,
        /* Every file is represented, valid or not: a person
           has to see which one is the problem. */
        rows_rendered: rows.length,
        valid: selection.filter(function (e) {
            return e.reason === null;
        }).length,
        reasons: byName,
        count_text: win.document
            .getElementById("batch-selection-count").textContent,
        submit_enabled: win.document
            .getElementById("batch-submit-button").disabled === false,
        /* Each remove control names its own file. */
        remove_labels: rows.map(function (row) {
            const buttons = row.querySelectorAll("button");
            return buttons.length
                ? buttons[0].getAttribute("aria-label")
                : null;
        })
    };
});


check("selection_removal_and_cap", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    pick(win, [
        file("a.jpg", "image/jpeg", 4096),
        file("b.png", "image/png", 8192),
        file("huge.jpg", "image/jpeg", 11 * 1024 * 1024)
    ]);

    const batch = win.VigiloxBatchUpload;
    const before = batch.getSelection().map(function (e) {
        return e.name;
    });

    /* Remove the oversized one, which is the third row. */
    const rows = listRows(win, "batch-file-list");
    rows[2].querySelectorAll("button")[0].fire("click", {});

    const afterRemoval = batch.getSelection().map(function (e) {
        return e.name;
    });

    /* Focus must land somewhere deliberate: the element it was
       on has just left the tree. */
    const focusedAfterRemoval = win.document.activeElement
        ? (win.document.activeElement.id ||
            win.document.activeElement.tagName)
        : null;

    /* Now overflow the cap. */
    const many = [];
    for (let i = 0; i < 40; i += 1) {
        many.push(file("x" + i + ".jpg", "image/jpeg", 1024));
    }
    pick(win, many);

    const capped = batch.getSelection().length;
    const overflowMessage = win.document
        .getElementById("batch-validation").textContent;

    /* Clear resets everything. */
    win.document.getElementById("batch-clear-button")
        .fire("click", {});

    return {
        before: before,
        after_removal: afterRemoval,
        focused_after_removal: focusedAfterRemoval,
        max_files: batch.MAX_FILES,
        capped_at: capped,
        overflow_reported: overflowMessage.length > 0,
        overflow_message: overflowMessage,
        after_clear: batch.getSelection().length,
        clear_disabled_when_empty: win.document
            .getElementById("batch-clear-button").disabled
    };
});


/* ==========================================================
   3. SUBMISSION
   ========================================================== */

check("submission", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    pick(win, [
        file("a.jpg", "image/jpeg", 4096),
        file("b.png", "image/png", 8192),
        file("c.webp", "image/webp", 2048),
        file("notes.txt", "text/plain", 100)
    ]);

    const button = win.document
        .getElementById("batch-submit-button");

    for (let i = 0; i < 4; i += 1) {
        button.fire("click", {});
    }

    return settle(4).then(function () {

        const batch = win.VigiloxBatchUpload;

        return {
            batch_calls_for_four_clicks: win.calls.batch,
            /* Only the valid files are sent. */
            files_submitted: win.calls.files,
            batch_id: batch.getBatchId(),
            polling: batch.isPolling(),
            /* One batch chain, never one timer per file. */
            timers_scheduled: win.record.timers.length,
            progress_shown: displayed(win, "batch-progress", 1440),
            select_hidden: !displayed(win, "batch-select", 1440),
            /* The server-rejected file is named, once, and
               never appears in the results list. */
            rejected_note: win.document
                .getElementById("batch-validation").textContent,
            summary_text: win.document
                .getElementById("batch-summary")
                .textContent.replace(/\s+/g, " ").trim(),
            aria_busy: win.document
                .getElementById("batch-progress")
                .getAttribute("aria-busy")
        };
    });
});


/* ==========================================================
   4. POLLING AND MIXED RESULTS
   ========================================================== */

check("polling_and_results", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    pick(win, [
        file("a.jpg", "image/jpeg", 4096),
        file("b.png", "image/png", 8192),
        file("c.webp", "image/webp", 2048)
    ]);

    win.document.getElementById("batch-submit-button")
        .fire("click", {});

    return settle(4).then(function () {

        win.runTimers();

        return settle(4).then(function () {

            const working = {
                state: win.document
                    .getElementById("batch-progress-state").textContent,
                summary: win.document
                    .getElementById("batch-summary")
                    .textContent.replace(/\s+/g, " ").trim(),
                rows: listRows(win, "batch-results").map(function (row) {
                    return row.textContent
                        .replace(/\s+/g, " ").trim();
                }),
                polling: win.VigiloxBatchUpload.isPolling(),
                polls: win.calls.status
            };

            win.runTimers();

            return settle(4).then(function () {

                const links = win.document
                    .getElementById("batch-results")
                    .querySelectorAll("a");

                return {
                    working: working,
                    terminal: {
                        summary: win.document
                            .getElementById("batch-summary")
                            .textContent.replace(/\s+/g, " ").trim(),
                        rows: listRows(win, "batch-results")
                            .map(function (row) {
                                return row.textContent
                                    .replace(/\s+/g, " ").trim();
                            }),
                        /* Two successes and one failure, side
                           by side. One failed item must not
                           erase its siblings. */
                        document_links: links.map(function (a) {
                            return a.getAttribute("href");
                        }),
                        polling: win.VigiloxBatchUpload.isPolling(),
                        submitting:
                            win.VigiloxBatchUpload.isSubmitting(),
                        select_available:
                            displayed(win, "batch-select", 1440),
                        aria_busy: win.document
                            .getElementById("batch-progress")
                            .getAttribute("aria-busy"),
                        polls: win.calls.status
                    }
                };
            });
        });
    });
});


check("polling_stops", function () {

    /* Unload. */
    const unloadWin = boot(MIXED);
    toBatchMode(unloadWin);
    pick(unloadWin, [file("a.jpg", "image/jpeg", 4096)]);
    unloadWin.document.getElementById("batch-submit-button")
        .fire("click", {});

    /* Leaving batch mode. */
    const switchWin = boot(MIXED);
    toBatchMode(switchWin);
    pick(switchWin, [file("a.jpg", "image/jpeg", 4096)]);
    switchWin.document.getElementById("batch-submit-button")
        .fire("click", {});

    return settle(4).then(function () {

        const pollingBeforeUnload =
            unloadWin.VigiloxBatchUpload.isPolling();
        const pollsBeforeUnload = unloadWin.calls.status;

        unloadWin.fireWindowEvent("beforeunload");
        unloadWin.runTimers();

        const pollingBeforeSwitch =
            switchWin.VigiloxBatchUpload.isPolling();

        toSingleMode(switchWin);
        switchWin.runTimers();

        return settle(4).then(function () {
            return {
                polling_before_unload: pollingBeforeUnload,
                polling_after_unload:
                    unloadWin.VigiloxBatchUpload.isPolling(),
                polls_before_unload: pollsBeforeUnload,
                polls_after_unload: unloadWin.calls.status,

                polling_before_switch: pollingBeforeSwitch,
                polling_after_switch:
                    switchWin.VigiloxBatchUpload.isPolling(),
                batch_painted_after_switch:
                    displayed(switchWin, "batch-mode", 1440),
                single_painted_after_switch:
                    displayed(switchWin, "single-mode", 1440),

                max_polls: unloadWin.VigiloxBatchUpload.MAX_POLLS,
                poll_interval_ms:
                    unloadWin.VigiloxBatchUpload.POLL_INTERVAL_MS
            };
        });
    });
});


/* ==========================================================
   5. SAFETY
   ========================================================== */

/* ==========================================================
   PHASE 12.18 - BATCH ROW IDENTITY AND OBJECT URL SAFETY
   ==========================================================
   The release brief asks whether a batch row carries enough
   identity for a person to tell which document is queued,
   processing, retrying, completed, failed, duplicate or
   invalid -- and whether object URLs are managed safely when
   rows are removed or the batch is reset.

   The answer to the second is that batch mode creates NONE.
   Rows are identified by filename, type, size and a state
   badge, so there is nothing to leak and nothing to revoke.

   That is asserted rather than assumed, because "there are no
   object URLs" is only true until somebody adds a thumbnail.
   If one is ever added, this check fails and whoever added it
   has to add the revocation too.

   Single-file upload is the opposite case: it DOES create a
   preview, and upload_harness.js asserts its whole lifecycle.
   ========================================================== */

check("row_identity_and_no_object_urls", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    /* Three valid and one rejected -- the mixture a person
       actually drops in. */
    pick(win, [
        file("licence-front.jpg", "image/jpeg", 4096),
        file("badge.png", "image/png", 8192),
        file("card.webp", "image/webp", 2048),
        file("contract.pdf", "application/pdf", 1024)
    ]);

    const rows = listRows(win, "batch-file-list");

    function textsOf(selector) {
        return rows.map(function (row) {
            const found = row.querySelectorAll(selector);
            return found.length ? found[0].textContent : null;
        });
    }

    const afterSelect = {
        object_urls_created: win.record.objectUrls.created.length,
        rows: rows.length,
        names: textsOf(".batch-file-name"),
        types: textsOf(".batch-file-type"),
        sizes: textsOf(".batch-file-size"),
        /* Every row says what state it is in. */
        states: rows.map(function (row) {
            const badges = row.querySelectorAll(".badge");
            return badges.length ? badges[0].textContent : null;
        })
    };

    /* Remove one row, then clear the whole selection. Neither
       may leave an unrevoked URL -- vacuously true today, and
       the assertion is what keeps it true. */
    if (rows.length) {
        const buttons = rows[0].querySelectorAll("button");
        if (buttons.length) {
            buttons[0].fire("click", {});
        }
    }

    const afterRemove = {
        object_urls_created: win.record.objectUrls.created.length,
        object_urls_revoked: win.record.objectUrls.revoked.length
    };

    const clear = win.document.getElementById(
        "batch-clear-button"
    );

    if (clear) {
        clear.fire("click", {});
    }

    /* fireWindowEvent, which is what this stub provides --
       win.listeners is the other harness's shape. */
    win.fireWindowEvent("beforeunload");

    return {
        after_select: afterSelect,
        after_remove: afterRemove,
        after_reset: {
            object_urls_created:
                win.record.objectUrls.created.length,
            object_urls_revoked:
                win.record.objectUrls.revoked.length
        },
        /* Whatever was created must have been revoked. With
           zero created this is trivially satisfied, and it
           stops being trivial the moment a thumbnail appears. */
        every_url_revoked:
            win.record.objectUrls.created.every(function (entry) {
                return (
                    win.record.objectUrls.revoked.indexOf(
                        entry.url
                    ) !== -1
                );
            })
    };
});


check("hostile_filename", function () {

    const win = boot(MIXED);
    toBatchMode(win);

    const nasty = '<img src=x onerror=alert(1)>.jpg';
    const quoted = '"><script>alert(1)</script>.png';

    pick(win, [
        file(nasty, "image/jpeg", 1024),
        file(quoted, "image/png", 1024)
    ]);

    const list = win.document.getElementById("batch-file-list");

    return {
        /* Rendered as text, so the payload is visible as
           characters rather than executed. */
        text_contains_payload:
            list.textContent.indexOf("onerror") !== -1 &&
            list.textContent.indexOf("script") !== -1,
        img_elements: list.querySelectorAll("img").length,
        script_elements: list.querySelectorAll("script").length,
        rows: listRows(win, "batch-file-list").length,
        /* The remove label carries the filename too, and it
           is an attribute rather than markup. */
        remove_labels: listRows(win, "batch-file-list")
            .map(function (row) {
                const buttons = row.querySelectorAll("button");
                return buttons.length
                    ? buttons[0].getAttribute("aria-label")
                    : null;
            })
    };
});


check("completed_without_document_id", function () {

    const win = boot({
        created: {
            batch_id: "b2",
            jobs: [
                {
                    job_id: "j9", status: "QUEUED",
                    original_filename: "a.jpg"
                }
            ]
        },
        statuses: [
            {
                batch_id: "b2",
                status: "COMPLETED",
                counts: { COMPLETED: 1 },
                jobs: [
                    {
                        job_id: "j9", status: "COMPLETED",
                        document_id: null,
                        original_filename: "a.jpg"
                    }
                ]
            }
        ]
    });

    toBatchMode(win);
    pick(win, [file("a.jpg", "image/jpeg", 1024)]);
    win.document.getElementById("batch-submit-button")
        .fire("click", {});

    return settle(4).then(function () {
        win.runTimers();

        return settle(4).then(function () {

            const list = win.document
                .getElementById("batch-results");

            return {
                /* No link, because there is nothing to link
                   to. /review/undefined must be impossible. */
                links: list.querySelectorAll("a").length,
                explains:
                    list.textContent
                        .indexOf("no reference was returned") !== -1,
                navigations: win.record.navigations.slice()
            };
        });
    });
});


check("submit_failure_restores_selection", function () {

    const win = boot({
        batchRejects: new (
            stub.createWindow().Error || Error
        )("boom"),
        created: null
    });

    /* A real ApiError, so the rendering path is the one used
       in production. */
    const ApiError = win.VigiloxApi.ApiError;

    win.VigiloxApi.endpoints.createDocumentBatch = function () {
        win.calls.batch += 1;
        return Promise.reject(new ApiError({
            status: 400,
            code: "BATCH_TOO_LARGE",
            message: "A batch may contain at most 20 files.",
            requestId: "req-b-1"
        }));
    };

    toBatchMode(win);
    pick(win, [file("a.jpg", "image/jpeg", 4096)]);
    win.document.getElementById("batch-submit-button")
        .fire("click", {});

    return settle(4).then(function () {
        return {
            error_shown: displayed(win, "batch-error", 1440),
            title: win.document
                .getElementById("batch-error-title").textContent,
            message: win.document
                .getElementById("batch-error-message").textContent,
            meta: win.document
                .getElementById("batch-error-meta")
                .textContent.replace(/\s+/g, " ").trim(),
            /* The selection survives, so a rejected batch does
               not force the files to be picked again. */
            selection_kept:
                win.VigiloxBatchUpload.getSelection().length,
            selection_shown: displayed(win, "batch-selection", 1440),
            select_shown: displayed(win, "batch-select", 1440),
            progress_hidden: !displayed(win, "batch-progress", 1440),
            submitting: win.VigiloxBatchUpload.isSubmitting(),
            can_resubmit: win.document
                .getElementById("batch-submit-button")
                .disabled === false
        };
    });
});


/* ==========================================================
   6. RESPONSIVE
   ========================================================== */

check("responsive_contract", function () {

    const fs = require("fs");
    const path = require("path");

    const source = fs.readFileSync(
        path.join(
            stub.PROJECT_ROOT,
            "frontend", "static", "css", "responsive.css"
        ),
        "utf8"
    );

    /* The two grids that break first, and the mode switch. */
    return {
        summary_reflows:
            /\.batch-summary\s*\{[^}]*grid-template-columns/.test(
                source
            ),
        file_row_stacks:
            /\.batch-file\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/
                .test(source),
        mode_switch_stacks:
            /\.mode-switch\s*\{[^}]*flex-direction:\s*column/.test(
                source
            ),
        /* Long filenames wrap at every width, so the rule
           belongs with the component rather than a
           breakpoint. */
        filename_wraps: /overflow-wrap:\s*anywhere/.test(
            fs.readFileSync(
                path.join(
                    stub.PROJECT_ROOT,
                    "frontend", "static", "css", "components.css"
                ),
                "utf8"
            )
        )
    };
});


/* ==========================================================
   RUN
   ========================================================== */

Promise.all(
    Object.keys(results).map(function (key) {
        return Promise.resolve(results[key]).then(function (value) {
            results[key] = value;
        });
    })
).then(function () {
    process.stdout.write(JSON.stringify(results, null, 2));
});
