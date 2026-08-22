/* ==========================================================
   VIGILOX VISIBILITY HARNESS
   PHASE 8 FINAL VISUAL QA
   ==========================================================
   Every other harness in this directory asks whether the
   JavaScript set element.hidden. This one asks whether the
   user would actually see the element, by running the shipped
   stylesheets through the display cascade in css_engine.js.

   It exists because those are different questions, and the
   difference shipped. The upload page set hidden on four
   mutually exclusive panels perfectly correctly, and the
   browser painted all four, because .alert, .file-card,
   .processing-panel and .btn set display and an author rule
   outranks the user-agent [hidden] rule. In real Chrome the
   page read "Analysis in progress", "Document analyzed
   successfully" and "Analysis failed" at the same time, over
   a file card whose <img> had no src and so rendered as a
   broken image, with "Analyze Document" and "Try Again" side
   by side.

   Eleven modules hide and show things. So the check is not
   "does upload.js work" but "can any state machine in this
   product paint two mutually exclusive states at once", and
   it is asked at six viewport widths, because a responsive
   rule is just as capable of breaking exclusivity as a
   component rule.

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");
const cssEngine = require("./css_engine.js");

const PAGES = [
    "dashboard.html",
    "upload.html",
    "documents.html",
    "index.html",
    "review_detail.html"
];

/* Large desktop, standard desktop, laptop, small laptop,
   tablet, phone. The laptop widths are the ones that found the
   tab-row overflow. */
const WIDTHS = [1920, 1440, 1366, 1024, 768, 390];

const results = {};

function check(name, fn) {
    try {
        results[name] = fn();
    } catch (error) {
        results[name] = { harness_error: String(error && error.stack || error) };
    }
}


/* ==========================================================
   TREE WALK
   ==========================================================
   The stub has no "*" support in querySelectorAll for the
   document root, and walking explicitly is clearer about what
   is being visited anyway.
   ========================================================== */

function walk(node, visit) {
    if (node.nodeType === 1) {
        visit(node);
    }
    (node.childNodes || []).forEach(function (child) {
        walk(child, visit);
    });
}

function label(node) {
    if (node.id) {
        return "#" + node.id;
    }
    if (node.className) {
        return "<" + node.tagName + " class=" + node.className + ">";
    }
    return "<" + node.tagName + ">";
}


/* ==========================================================
   1. STATIC: NOTHING MARKED HIDDEN MAY BE PAINTED
   ==========================================================
   Covers the initial render of every page at every width. This
   is the check that catches a new component class defeating
   [hidden] again.
   ========================================================== */

check("static_hidden_never_painted", function () {
    const leaks = [];
    let checked = 0;

    PAGES.forEach(function (page) {
        const win = stub.createWindow();
        stub.loadPage(win, page);

        WIDTHS.forEach(function (width) {
            const vis = stub.createVisibility(page, { width: width });

            walk(win.document.documentElement || win.document.body, function (node) {
                if (node.hidden !== true) {
                    return;
                }

                checked += 1;

                if (vis.isDisplayed(node)) {
                    leaks.push({
                        page: page,
                        width: width,
                        element: label(node),
                        why: vis.explain(node)
                    });
                }
            });
        });
    });

    return {
        elements_checked: checked,
        widths: WIDTHS.length,
        pages: PAGES.length,
        leaks: leaks
    };
});


/* ==========================================================
   2. THE [hidden] RULE ITSELF
   ==========================================================
   Asserted directly, because it is the single line holding all
   of the above up, and because a future author deleting it
   should read a sentence explaining why it is there rather
   than a list of thirty failing assertions.
   ========================================================== */

check("hidden_rule_wins", function () {
    const win = stub.createWindow();
    stub.loadPage(win, "upload.html");

    /* .btn and [hidden] have identical specificity -- one class
       each. So without !important the winner is decided by
       source order, and base.css is linked before
       components.css, which means .btn wins and hidden does
       nothing. This records that reasoning as a test. */
    const button = win.document.getElementById("retry-button");
    const engine = cssEngine.createEngine("upload.html", { width: 1440 });

    const rules = engine.matchingRules(button, stub.selectorMatches);

    const hiddenRule = rules.filter(function (rule) {
        return rule.selector === "[hidden]";
    })[0] || null;

    const btnRule = rules.filter(function (rule) {
        return rule.selector === ".btn";
    })[0] || null;

    return {
        button_is_hidden_in_html: button.hidden === true,
        hidden_rule_found: Boolean(hiddenRule),
        hidden_rule_important: Boolean(hiddenRule && hiddenRule.important),
        hidden_rule_source: hiddenRule ? hiddenRule.source : null,
        btn_rule_found: Boolean(btnRule),
        btn_sets_display: btnRule ? btnRule.value : null,
        /* The whole point: equal specificity, and base.css is
           earlier, so only !important saves it. */
        same_specificity:
            Boolean(hiddenRule && btnRule) &&
            cssEngine.compareSpecificity(
                hiddenRule.specificity,
                btnRule.specificity
            ) === 0,
        hidden_declared_before_btn:
            Boolean(hiddenRule && btnRule) &&
            hiddenRule.order < btnRule.order,
        resolved: engine.displayOf(button, stub.selectorMatches).value
    };
});


/* ==========================================================
   3. UPLOAD STATE MACHINE, BY WHAT IS PAINTED
   ==========================================================
   IDLE -> SELECTED -> ANALYZING -> SUCCESS | ERROR, driven
   through the real module against the real page.
   ========================================================== */

const UPLOAD_REGIONS = {
    drop_zone: "drop-zone",
    file_card: "file-card",
    processing: "processing-panel",
    success: "success-panel",
    error: "error-panel"
};

const UPLOAD_CONTROLS = {
    analyze: "analyze-button",
    retry: "retry-button",
    remove: "remove-button"
};

function makeFile(name, type, size) {
    return { name: name, type: type, size: size };
}

function bootUpload(win, behaviour) {
    stub.loadPage(win, "upload.html");
    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");
    /* upload.js now reads job status labels from the shared
       vocabulary, so the page loads it and so must this. */
    stub.loadScript(win, "js/vocabulary.js");

    const endpoints = win.VigiloxApi.endpoints;

    /* PHASE 9.4. These checks predate the async migration and
       used to stub analyzeDocument, which upload.js no longer
       calls. Leaving them that way did not fail loudly -- the
       real createDocumentJob was reached, its fetch failed,
       and the page went to ERROR asynchronously, which some
       checks read before the rejection landed and some after.
       One passed by timing and one failed.

       That is worth recording: a stub pointed at a retired
       endpoint is indistinguishable from a working test until
       something forces the timing. */

    endpoints.createDocumentJob = function () {
        if (behaviour && behaviour.mode === "reject") {
            return Promise.reject(behaviour.error);
        }
        if (behaviour && behaviour.mode === "pending") {
            /* Resolves into a job that stays QUEUED, which
               holds the page in its waiting state so that
               state can be observed. */
            return Promise.resolve({
                job_id: "job-vis-pending",
                status: "QUEUED",
                is_terminal: false
            });
        }
        return Promise.resolve({
            job_id: "job-vis-1",
            status: "QUEUED",
            is_terminal: false
        });
    };

    endpoints.getDocumentJob = function () {
        if (behaviour && behaviour.mode === "pending") {
            return Promise.resolve({
                job_id: "job-vis-pending",
                status: "PROCESSING",
                current_stage: "OCR",
                is_terminal: false
            });
        }
        return Promise.resolve({
            job_id: "job-vis-1",
            status: "COMPLETED",
            document_id: "doc-vis-1",
            is_terminal: true
        });
    };

    /* Still stubbed so nothing can quietly fall back to the
       synchronous route. */
    endpoints.analyzeDocument = function () {
        throw new Error(
            "upload.js must not call analyzeDocument; the " +
            "Upload page uses the job API."
        );
    };

    endpoints.getReviewerIdentity = function () {
        return Promise.resolve({
            reviewer_id: "r1",
            display_name: "Test Reviewer",
            role: "REVIEWER",
            identity_source: "STUB",
            can_review: true
        });
    };

    endpoints.getHealth = function () {
        return Promise.resolve({ status: "ok" });
    };

    stub.loadScript(win, "js/upload.js");

    /* upload.js defers init to DOMContentLoaded whenever the
       document is still loading, which it is until this is
       called. Without it the module registers its listeners
       and never runs, and every state below would read as
       IDLE -- which looks like a pass. */
    win.document.ready();

    return win;
}

function paintedUpload(win, width) {
    const vis = stub.createVisibility("upload.html", { width: width });
    const shown = {};

    Object.keys(UPLOAD_REGIONS).forEach(function (key) {
        const node = win.document.getElementById(UPLOAD_REGIONS[key]);
        shown[key] = Boolean(node) && vis.isDisplayed(node);
    });

    Object.keys(UPLOAD_CONTROLS).forEach(function (key) {
        const node = win.document.getElementById(UPLOAD_CONTROLS[key]);
        shown[key] = Boolean(node) && vis.isDisplayed(node);
    });

    return shown;
}

/* The regions that describe a processing outcome. Exactly one
   of these -- or none, before anything has happened -- may be
   painted at any moment. */
const OUTCOME_REGIONS = ["processing", "success", "error"];

function outcomeCount(shown) {
    return OUTCOME_REGIONS.filter(function (key) {
        return shown[key];
    }).length;
}

check("upload_state_exclusivity", function () {
    const observed = {};
    const violations = [];

    WIDTHS.forEach(function (width) {

        /* ---- IDLE ---- */
        const idleWin = stub.createWindow({ pathname: "/upload" });
        bootUpload(idleWin, null);

        record("idle", width, paintedUpload(idleWin, width), idleWin);

        /* ---- SELECTED ---- */
        const selectedWin = stub.createWindow({ pathname: "/upload" });
        bootUpload(selectedWin, null);
        selectedWin.document.getElementById("file-input").fire("change", {
            target: { files: [makeFile("guard.jpg", "image/jpeg", 4096)] }
        });

        record("selected", width, paintedUpload(selectedWin, width), selectedWin);

        /* ---- ANALYZING ---- */
        const analyzingWin = stub.createWindow({ pathname: "/upload" });
        bootUpload(analyzingWin, { mode: "pending" });
        analyzingWin.document.getElementById("file-input").fire("change", {
            target: { files: [makeFile("guard.jpg", "image/jpeg", 4096)] }
        });
        analyzingWin.document.getElementById("analyze-button").fire("click", {});

        record("analyzing", width, paintedUpload(analyzingWin, width), analyzingWin);
    });

    function record(state, width, shown, win) {
        const key = state + "@" + width;

        observed[key] = shown;

        if (outcomeCount(shown) > 1) {
            violations.push({
                state: state,
                width: width,
                painted: OUTCOME_REGIONS.filter(function (region) {
                    return shown[region];
                })
            });
        }

        /* A visible <img> with no source is the broken-image
           icon. That is what the real browser showed. */
        const preview = win.document.getElementById("file-preview");
        const vis = stub.createVisibility("upload.html", { width: width });

        if (
            preview &&
            vis.isDisplayed(preview) &&
            !preview.src
        ) {
            violations.push({
                state: state,
                width: width,
                broken_preview: true
            });
        }
    }

    return {
        observed: observed,
        violations: violations
    };
});


/* ==========================================================
   4. TERMINAL UPLOAD STATES
   ==========================================================
   SUCCESS and ERROR settle asynchronously, so they are
   observed after the microtask queue drains.
   ========================================================== */

check("upload_terminal_states", function () {
    const successWin = stub.createWindow({ pathname: "/upload" });
    bootUpload(successWin, null);
    successWin.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("guard.jpg", "image/jpeg", 4096)] }
    });
    successWin.document.getElementById("analyze-button").fire("click", {});

    const ApiError = successWin.VigiloxApi.ApiError;

    const errorWin = stub.createWindow({ pathname: "/upload" });
    bootUpload(errorWin, {
        mode: "reject",
        error: new ApiError({
            status: 422,
            code: "UNSUPPORTED_DOCUMENT",
            message: "That document type is not supported.",
            requestId: "req-vis-1"
        })
    });
    errorWin.document.getElementById("file-input").fire("change", {
        target: { files: [makeFile("guard.jpg", "image/jpeg", 4096)] }
    });
    errorWin.document.getElementById("analyze-button").fire("click", {});

    return new Promise(function (resolve) {
        setImmediate(function () {

            /* The outcome now arrives from a poll rather than
               from the submit response, so the timer has to be
               advanced before the terminal state exists. */
            successWin.runTimers();
            errorWin.runTimers();

            setImmediate(function () {
              setImmediate(function () {
                const violations = [];
                const observed = {};

                WIDTHS.forEach(function (width) {
                    const success = paintedUpload(successWin, width);
                    const failure = paintedUpload(errorWin, width);

                    observed["success@" + width] = success;
                    observed["error@" + width] = failure;

                    if (outcomeCount(success) !== 1 || !success.success) {
                        violations.push({
                            state: "success",
                            width: width,
                            painted: OUTCOME_REGIONS.filter(function (r) {
                                return success[r];
                            })
                        });
                    }

                    if (outcomeCount(failure) !== 1 || !failure.error) {
                        violations.push({
                            state: "error",
                            width: width,
                            painted: OUTCOME_REGIONS.filter(function (r) {
                                return failure[r];
                            })
                        });
                    }

                    /* Analyze and Try Again are alternatives,
                       never a pair. */
                    if (success.analyze && success.retry) {
                        violations.push({
                            state: "success",
                            width: width,
                            both_buttons: true
                        });
                    }
                    if (failure.analyze && failure.retry) {
                        violations.push({
                            state: "error",
                            width: width,
                            both_buttons: true
                        });
                    }
                });

                resolve({ observed: observed, violations: violations });
              });
            });
        });
    });
});


/* ==========================================================
   4b. THE ASYNC JOB FLOW
   ==========================================================
   PHASE 9.4 replaced a synchronous request with a job and a
   poll loop, which is a material change to the state machine
   that produced the original reported defect.

   So the same question is asked again, of the new flow: can
   the page ever paint two mutually exclusive states at once?
   QUEUED, PROCESSING and RETRY_WAIT all share the ANALYZING
   visual state -- they are all "the user is waiting" -- and
   only the label differs. That is deliberate, and it is
   exactly the sort of sharing that could go wrong.
   ========================================================== */

function bootAsyncUpload(win, behaviour) {
    stub.loadPage(win, "upload.html");
    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");
    stub.loadScript(win, "js/vocabulary.js");

    const endpoints = win.VigiloxApi.endpoints;

    /* Counters live on the window, not in module scope. Checks
       run concurrently, and a module-global counter attributes
       one boot's requests to another -- which happened, and
       made every "exactly one request" claim meaningless. */
    win.calls = { create: 0, status: 0 };

    endpoints.createDocumentJob = function () {
        win.calls.create += 1;

        if (behaviour.createRejects) {
            return Promise.reject(behaviour.createRejects);
        }

        return Promise.resolve(behaviour.created);
    };

    endpoints.getDocumentJob = function () {
        const index = win.calls.status;
        win.calls.status += 1;

        const sequence = behaviour.statuses || [];

        return Promise.resolve(
            sequence[Math.min(index, sequence.length - 1)]
        );
    };

    endpoints.getReviewerIdentity = function () {
        return Promise.resolve({
            reviewer_id: "r",
            display_name: "R",
            role: "REVIEWER",
            identity_source: "S",
            can_review: true
        });
    };

    endpoints.getHealth = function () {
        return Promise.resolve({ status: "ok" });
    };

    stub.loadScript(win, "js/upload.js");
    win.document.ready();

    return win;
}

function selectFile(win) {
    win.document.getElementById("file-input").fire("change", {
        target: {
            files: [
                { name: "guard.jpg", type: "image/jpeg", size: 4096 }
            ]
        }
    });
}

/* Lets the promise chain settle. The stub's timers never fire
   on their own, so a poll only advances when a test says so --
   which turns a race into an observable sequence. */
function settle(times) {
    return new Promise(function (resolve) {
        let count = 0;

        const step = function () {
            count += 1;

            if (count > times) {
                return resolve();
            }

            setImmediate(step);
        };

        step();
    });
}

check("async_upload_states", function () {

    const observed = {};
    const violations = [];

    const scenarios = [
        {
            name: "queued",
            created: {
                job_id: "j1",
                status: "QUEUED",
                is_terminal: false
            },
            statuses: [],
            expect: "processing"
        },
        {
            name: "processing",
            created: {
                job_id: "j2",
                status: "QUEUED",
                is_terminal: false
            },
            statuses: [
                {
                    job_id: "j2",
                    status: "PROCESSING",
                    current_stage: "OCR",
                    is_terminal: false
                }
            ],
            polls: 1,
            expect: "processing"
        },
        {
            name: "retry_wait",
            created: {
                job_id: "j3",
                status: "QUEUED",
                is_terminal: false
            },
            statuses: [
                {
                    job_id: "j3",
                    status: "RETRY_WAIT",
                    attempt_count: 1,
                    max_attempts: 3,
                    error_code: "PROVIDER_RATE_LIMITED",
                    error_message: "at capacity",
                    is_terminal: false
                }
            ],
            polls: 1,
            expect: "processing"
        },
        {
            name: "completed",
            created: {
                job_id: "j4",
                status: "QUEUED",
                is_terminal: false
            },
            statuses: [
                {
                    job_id: "j4",
                    status: "COMPLETED",
                    document_id: "doc-1",
                    is_terminal: true
                }
            ],
            polls: 1,
            expect: "success"
        },
        {
            name: "failed",
            created: {
                job_id: "j5",
                status: "QUEUED",
                is_terminal: false
            },
            statuses: [
                {
                    job_id: "j5",
                    status: "FAILED",
                    error_code: "UNSUPPORTED_DOCUMENT",
                    error_message: "Not a supported document type.",
                    is_terminal: true
                }
            ],
            polls: 1,
            expect: "error"
        }
    ];

    return scenarios.reduce(function (chain, scenario) {

        return chain.then(function () {

            const win = stub.createWindow({ pathname: "/upload" });

            bootAsyncUpload(win, scenario);
            selectFile(win);

            win.document
                .getElementById("analyze-button")
                .fire("click", {});

            return settle(4).then(function () {

                let advanced = Promise.resolve();

                for (let i = 0; i < (scenario.polls || 0); i += 1) {
                    advanced = advanced.then(function () {
                        win.runTimers();
                        return settle(4);
                    });
                }

                return advanced.then(function () {

                    WIDTHS.forEach(function (width) {

                        const shown = paintedUpload(win, width);
                        const key = scenario.name + "@" + width;

                        observed[key] = {
                            painted: OUTCOME_REGIONS.filter(function (r) {
                                return shown[r];
                            }),
                            analyze: shown.analyze,
                            retry: shown.retry
                        };

                        if (outcomeCount(shown) !== 1) {
                            violations.push({
                                scenario: scenario.name,
                                width: width,
                                painted: observed[key].painted
                            });
                        }

                        if (!shown[scenario.expect]) {
                            violations.push({
                                scenario: scenario.name,
                                width: width,
                                expected: scenario.expect,
                                missing: true
                            });
                        }

                        if (shown.analyze && shown.retry) {
                            violations.push({
                                scenario: scenario.name,
                                width: width,
                                both_buttons: true
                            });
                        }
                    });

                    observed[scenario.name + ":label"] =
                        win.document
                            .getElementById("processing-message")
                            .textContent;

                    observed[scenario.name + ":calls"] = {
                        create: win.calls.create,
                        status: win.calls.status
                    };

                    observed[scenario.name + ":polling"] =
                        win.VigiloxUpload.isPolling();
                });
            });
        });

    }, Promise.resolve()).then(function () {
        return { observed: observed, violations: violations };
    });
});

check("async_polling_discipline", function () {

    /* One submission per click storm, polling that stops on a
       terminal state and on unload, and no leaked object URL. */
    const win = stub.createWindow({ pathname: "/upload" });

    bootAsyncUpload(win, {
        created: {
            job_id: "j6",
            status: "QUEUED",
            is_terminal: false
        },
        statuses: [
            {
                job_id: "j6",
                status: "PROCESSING",
                current_stage: "OCR",
                is_terminal: false
            }
        ]
    });

    selectFile(win);

    const button = win.document.getElementById("analyze-button");

    for (let i = 0; i < 4; i += 1) {
        button.fire("click", {});
    }

    return settle(4).then(function () {

        const createdAfterClicks = win.calls.create;
        const pollingWhileWorking = win.VigiloxUpload.isPolling();

        /* Two poll rounds, to prove the loop chains rather
           than firing once. */
        win.runTimers();

        return settle(4).then(function () {
            win.runTimers();

            return settle(4).then(function () {

                const pollsBeforeUnload = win.calls.status;

                win.fireWindowEvent("beforeunload");
                win.runTimers();

                return settle(4).then(function () {

                    const urls = win.record.objectUrls;

                    return {
                        create_calls_for_four_clicks:
                            createdAfterClicks,

                        polling_while_working:
                            pollingWhileWorking,

                        polls_chained:
                            pollsBeforeUnload >= 2,

                        polls_before_unload:
                            pollsBeforeUnload,

                        polls_after_unload:
                            win.calls.status,

                        polling_after_unload:
                            win.VigiloxUpload.isPolling(),

                        object_urls_created:
                            urls.created.length,

                        object_urls_revoked:
                            urls.revoked.length,

                        max_polls:
                            win.VigiloxUpload.MAX_POLLS,

                        poll_interval_ms:
                            win.VigiloxUpload.POLL_INTERVAL_MS
                    };
                });
            });
        });
    });
});


/* ==========================================================
   5. WORKSPACE REVIEW CONTROLS
   ==========================================================
   Normal mode offers Approve, Correct, Reject. Correction mode
   replaces them with Submit Corrections and Cancel. A reviewed
   document offers nothing. All three asserted by what is
   painted, at every width.
   ========================================================== */

const REVIEW_CONTROLS = {
    approve: "approve-button",
    correct: "correct-button",
    reject: "reject-button",
    submit: "submit-correction-button",
    cancel: "cancel-correction-button"
};

function paintedReview(win, width) {
    const vis = stub.createVisibility("review_detail.html", { width: width });
    const shown = {};

    Object.keys(REVIEW_CONTROLS).forEach(function (key) {
        const node = win.document.getElementById(REVIEW_CONTROLS[key]);
        shown[key] = Boolean(node) && vis.isDisplayed(node);
    });

    return shown;
}

check("workspace_control_exclusivity", function () {
    /* The correction panel is driven directly rather than
       through a full document load, because the question here
       is purely about which controls are painted in which
       mode. The full-load path is covered by
       workspace_harness.js. */
    const win = stub.createWindow({ pathname: "/review/doc-vis-1" });
    stub.loadPage(win, "review_detail.html");

    /* The review panel, the reviewer block and the form all
       start hidden, because whether a form appears at all is
       decided by the server's can_review. Reveal that chain
       first: the question here is which controls compete
       inside a form that is already being offered, and with
       the chain still hidden every control would read as "not
       painted", which looks like a pass. */
    [
        "detail-content",
        "human-review-panel",
        "authenticated-reviewer-section",
        "human-review-form"
    ].forEach(function (id) {
        const node = win.document.getElementById(id);

        if (node) {
            node.hidden = false;
        }
    });

    const ids = Object.keys(REVIEW_CONTROLS).map(function (key) {
        return REVIEW_CONTROLS[key];
    });

    const missing = ids.filter(function (id) {
        return !win.document.getElementById(id);
    });

    if (missing.length) {
        return { missing_controls: missing };
    }

    const observed = {};
    const violations = [];

    function apply(mode) {
        const normal = mode === "normal";

        win.document.getElementById("approve-button").hidden = !normal;
        win.document.getElementById("correct-button").hidden = !normal;
        win.document.getElementById("reject-button").hidden = !normal;
        win.document.getElementById("submit-correction-button").hidden = normal;

        /* Cancel lives inside the correction panel, so the
           panel is what opens and closes. Toggling only the
           button would leave Cancel reading as absent in
           correction mode, which would pass for the wrong
           reason. This mirrors what review_actions.js does. */
        win.document.getElementById("correction-panel").hidden = normal;
        win.document.getElementById("cancel-correction-button").hidden = false;
    }

    ["normal", "correcting"].forEach(function (mode) {
        apply(mode);

        WIDTHS.forEach(function (width) {
            const shown = paintedReview(win, width);

            observed[mode + "@" + width] = shown;

            /* Approve and Reject are two different decisions
               and are both meant to be on offer at once, so
               counting visible submitters is the wrong rule --
               it fails the correct design.

               The reported ambiguity was narrower and real:
               Submit Corrections sitting beside Approve and
               Reject, so three buttons commit a review and
               only one of them is about the corrections the
               reviewer just typed. That is the rule. */
            if (shown.submit && (shown.approve || shown.reject)) {
                violations.push({
                    mode: mode,
                    width: width,
                    submit_beside_decision: true
                });
            }

            /* Correction mode has to actually offer a way out,
               or Escape is the only exit. */
            if (mode === "correcting" && !shown.cancel) {
                violations.push({
                    mode: mode,
                    width: width,
                    no_cancel_in_correction_mode: true
                });
            }

            if (mode === "normal" && (shown.submit || shown.cancel)) {
                violations.push({
                    mode: mode,
                    width: width,
                    correction_controls_leaked: true
                });
            }

            if (mode === "correcting" && (shown.approve || shown.reject || shown.correct)) {
                violations.push({
                    mode: mode,
                    width: width,
                    normal_controls_leaked: true
                });
            }
        });
    });

    /* Reviewed and locked: the whole form goes. */
    const form = win.document.getElementById("human-review-form");
    const locked = win.document.getElementById("review-locked-message");

    if (form && locked) {
        form.hidden = true;
        locked.hidden = false;

        WIDTHS.forEach(function (width) {
            const vis = stub.createVisibility("review_detail.html", { width: width });
            const shown = paintedReview(win, width);

            observed["locked@" + width] = shown;

            if (vis.isDisplayed(form)) {
                violations.push({ mode: "locked", width: width, form_painted: true });
            }

            Object.keys(shown).forEach(function (key) {
                if (shown[key]) {
                    violations.push({
                        mode: "locked",
                        width: width,
                        control_painted: key
                    });
                }
            });

            if (!vis.isDisplayed(locked)) {
                violations.push({
                    mode: "locked",
                    width: width,
                    notice_missing: true
                });
            }
        });
    } else {
        violations.push({ mode: "locked", missing: true });
    }

    return { observed: observed, violations: violations };
});


/* ==========================================================
   6. THE !important INVENTORY
   ==========================================================
   [hidden] needs !important. Nothing should acquire it by
   accident, so the full set is pinned here and a new one has
   to be added deliberately.
   ========================================================== */

check("important_inventory", function () {
    const fs = require("fs");
    const path = require("path");
    const cssRoot = path.join(
        stub.PROJECT_ROOT, "frontend", "static", "css"
    );

    const found = [];

    fs.readdirSync(cssRoot).sort().forEach(function (name) {
        if (!/\.css$/.test(name)) {
            return;
        }

        const source = cssEngine.stripComments(
            fs.readFileSync(path.join(cssRoot, name), "utf8")
        );

        source.split("\n").forEach(function (line, index) {
            if (line.indexOf("!important") !== -1) {
                found.push({
                    file: name,
                    line: index + 1,
                    text: line.trim()
                });
            }
        });
    });

    return { declarations: found, count: found.length };
});


/* ==========================================================
   7. TAB ROW GEOMETRY
   ==========================================================
   Honest scope note: this engine resolves display, not layout.
   It cannot measure rendered text, so it cannot prove the six
   workspace tabs fit their column -- only a browser can.

   What it can pin is the geometry that was changed to make
   them fit, so the fix cannot be silently reverted, plus the
   fact that overflow-x remains the fallback for genuinely
   narrow windows.
   ========================================================== */

check("tab_geometry", function () {
    const fs = require("fs");
    const path = require("path");

    const source = fs.readFileSync(
        path.join(
            stub.PROJECT_ROOT,
            "frontend", "static", "css", "workspace.css"
        ),
        "utf8"
    );

    const clean = cssEngine.stripComments(source);

    function block(selector) {
        const at = clean.indexOf(selector + " {");

        if (at === -1) {
            return null;
        }

        return clean.slice(at, clean.indexOf("}", at));
    }

    const tablist = block(".tablist");
    const tab = block(".tab");

    return {
        tablist_found: Boolean(tablist),
        tab_found: Boolean(tab),
        /* The fallback for narrow windows, which is the
           accepted behaviour there. */
        tablist_scrolls: Boolean(tablist) &&
            /overflow-x\s*:\s*auto/.test(tablist),
        tablist_thin_scrollbar: Boolean(tablist) &&
            /scrollbar-width\s*:\s*thin/.test(tablist),
        /* No horizontal padding on the strip and no gap
           between tabs: 24px and 20px respectively, recovered
           for the labels. */
        tablist_no_side_padding: Boolean(tablist) &&
            /padding\s*:\s*0\s*;/.test(tablist),
        tablist_no_gap: Boolean(tablist) &&
            /gap\s*:\s*0\s*;/.test(tablist),
        /* Uniform space-3 rather than space-4 side padding. */
        tab_padding: Boolean(tab) &&
            /padding\s*:\s*var\(--space-3\)\s*;/.test(tab),
        tab_font: Boolean(tab) &&
            /font-size\s*:\s*var\(--text-sm\)\s*;/.test(tab),
        tab_nowrap: Boolean(tab) &&
            /white-space\s*:\s*nowrap/.test(tab),
        measured_in_browser: false
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
