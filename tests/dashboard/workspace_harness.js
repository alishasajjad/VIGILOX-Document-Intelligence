/* ==========================================================
   VIGILOX DOCUMENT WORKSPACE HARNESS
   PHASE 8.10 - 8.14
   ==========================================================

   Executes the rebuilt document workspace under Node against
   the shared DOM stub:

       review_detail.js                 page controller
       js/workspace/tabs.js
       js/workspace/source_panel.js
       js/workspace/fields_view.js
       js/workspace/validation_view.js
       js/workspace/result_view.js
       js/workspace/review_actions.js

   The behaviours that matter here cannot be established by
   reading source text:

       the review payload carries no reviewer id
       four Approve clicks submit once
       a read-only reviewer is never shown a submit path
       PENDING_REVIEW and REJECTED publish no effective values
       a corrected field shows machine AND human AND effective
       clearing a field sends null rather than omitting it
       evidence boxes land where the OCR said they were
       raw JSON is never the landing view

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");


/* ==========================================================
   FIXTURE
   ==========================================================
   Shaped exactly like GET /api/v1/documents/{id}, including a
   real OCR line set with bboxes inside a known image size.
   ========================================================== */

const IMAGE_WIDTH = 600;
const IMAGE_HEIGHT = 400;


const OCR_LINES = [
    {
        line_id: "L0",
        text: "TEXAS",
        confidence: 0.9999,
        bbox: [30, 20, 180, 60]
    },
    {
        line_id: "L1",
        text: "PRIVATE SECURITY LICENSE",
        confidence: 0.992,
        bbox: [180, 20, 540, 60]
    },
    {
        line_id: "L2",
        text: "SAMPLE,JANE",
        confidence: 0.9988,
        bbox: [60, 120, 300, 160]
    },
    {
        line_id: "L3",
        text: "LIC 12345678",
        confidence: 0.951,
        bbox: [60, 180, 300, 220]
    },
    {
        line_id: "L4",
        text: "EXPIRES 01/01/2026",
        confidence: 0.94,
        bbox: [60, 240, 320, 280]
    },
    {
        line_id: "L5",
        text: "ISSUED BY TX DPS",
        confidence: 0.9878,
        bbox: [60, 300, 340, 340]
    },
    {
        line_id: "L6",
        /* A line with an unusable bbox, so the harness can
           prove a bad box is skipped rather than clamped. */
        text: "SMUDGED",
        confidence: 0.4,
        bbox: [0, 0, 0, 0]
    }
];


function extraction(overrides) {
    return Object.assign(
        {
            document_type: "guard_license",
            full_name: {
                value: "SAMPLE,JANE",
                source_line_ids: ["L2"]
            },
            licence_number: {
                value: "12345678",
                source_line_ids: ["L3"]
            },
            id_number: {
                value: null,
                source_line_ids: []
            },
            expiry_date: {
                value: "2026-01-01",
                source_line_ids: ["L4"]
            },
            date_of_birth: {
                value: null,
                source_line_ids: []
            },
            issue_date: {
                value: null,
                source_line_ids: []
            },
            issuer: {
                value: "TX DPS",
                source_line_ids: ["L5"]
            }
        },
        overrides || {}
    );
}


function fieldConfidence() {
    return {
        full_name: {
            value: "SAMPLE,JANE",
            confidence: 0.9988,
            status: "VALID"
        },
        licence_number: {
            value: "12345678",
            confidence: 0.951,
            status: "VALID"
        },
        id_number: {
            value: null,
            confidence: null,
            status: "NOT_EXTRACTED"
        },
        expiry_date: {
            value: "2026-01-01",
            confidence: 0.94,
            status: "VALID"
        },
        date_of_birth: {
            value: null,
            confidence: null,
            status: "NOT_EXTRACTED"
        },
        issue_date: {
            value: null,
            confidence: null,
            status: "NOT_EXTRACTED"
        },
        issuer: {
            value: "TX DPS",
            confidence: 0.9878,
            status: "VALID"
        }
    };
}


function dateValidation() {
    return {
        reference_date: "2026-08-20",
        date_fields: {
            date_of_birth: { value: null, status: "NOT_EXTRACTED" },
            issue_date: { value: null, status: "NOT_EXTRACTED" },
            expiry_date: {
                value: "2026-01-01",
                status: "VALID_DATE"
            }
        },
        expiry: {
            value: "2026-01-01",
            status: "EXPIRED",
            days_until_expiry: -231
        },
        logical_issues: [],
        valid: true
    };
}


function anomalyValidation() {
    return {
        document_type: "guard_license",
        valid: false,
        has_anomalies: true,
        error_count: 1,
        warning_count: 1,
        issues: [
            {
                code: "MISSING_CRITICAL_FIELD",
                severity: "ERROR",
                field: "id_number",
                message:
                    "Required field 'id_number' is missing for " +
                    "document type 'guard_license'."
            },
            {
                code: "DOCUMENT_EXPIRED",
                severity: "WARNING",
                field: "expiry_date",
                message: "The document expired 231 day(s) ago."
            }
        ]
    };
}


function reviewDecision() {
    return {
        decision: "REVIEW_REQUIRED",
        review_required: true,
        priority: "HIGH",
        reason_codes: ["MISSING_CRITICAL_FIELD", "DOCUMENT_EXPIRED"],
        issues: anomalyValidation().issues
    };
}


const MACHINE_VALUES = {
    document_type: "guard_license",
    full_name: "SAMPLE,JANE",
    licence_number: "12345678",
    id_number: null,
    expiry_date: "2026-01-01",
    date_of_birth: null,
    issue_date: null,
    issuer: "TX DPS"
};


function machineSources() {
    const sources = {};
    Object.keys(MACHINE_VALUES).forEach(function (name) {
        sources[name] = "MACHINE";
    });
    return sources;
}


/**
 * Final record shaped exactly like FinalRecordService.build().
 */
function finalRecord(status, corrections) {
    if (status === "PENDING_REVIEW") {
        return {
            final_status: "PENDING_REVIEW",
            is_final: false,
            is_usable: false,
            machine_values: MACHINE_VALUES,
            effective_values: null,
            value_sources: null,
            human_action: null
        };
    }

    if (status === "REJECTED") {
        return {
            final_status: "REJECTED",
            is_final: true,
            is_usable: false,
            machine_values: MACHINE_VALUES,
            effective_values: null,
            value_sources: null,
            human_action: "REJECT"
        };
    }

    if (status === "CORRECTED") {
        const effective = Object.assign({}, MACHINE_VALUES);
        const sources = machineSources();

        Object.keys(corrections || {}).forEach(function (name) {
            effective[name] = corrections[name];
            sources[name] = "HUMAN_CORRECTION";
        });

        return {
            final_status: "CORRECTED",
            is_final: true,
            is_usable: true,
            machine_values: MACHINE_VALUES,
            effective_values: effective,
            value_sources: sources,
            human_action: "CORRECT"
        };
    }

    /* PHASE 10.2. Mirrors FinalRecordService.build for
       decision UNSUPPORTED_DOCUMENT with no human review:
       final, not usable, nothing published. */
    if (status === "UNSUPPORTED") {
        return {
            final_status: "UNSUPPORTED",
            is_final: true,
            is_usable: false,
            machine_values: MACHINE_VALUES,
            effective_values: null,
            value_sources: null,
            human_action: null
        };
    }

    if (status === "APPROVED") {
        return {
            final_status: "APPROVED",
            is_final: true,
            is_usable: true,
            machine_values: MACHINE_VALUES,
            effective_values: Object.assign({}, MACHINE_VALUES),
            value_sources: machineSources(),
            human_action: "APPROVE"
        };
    }

    return {
        final_status: "AUTO_ACCEPTED",
        is_final: true,
        is_usable: true,
        machine_values: MACHINE_VALUES,
        effective_values: Object.assign({}, MACHINE_VALUES),
        value_sources: machineSources(),
        human_action: null
    };
}


function documentPayload(options) {
    const config = options || {};

    return {
        status: "success",
        document: Object.assign(
            {
                document_id: "doc-workspace-1",
                original_filename: "guard_front.jpg",
                content_type: "image/jpeg",
                document_type: "guard_license",
                processing_status: "PROCESSED",
                created_at: "2026-08-01T09:15:00",
                updated_at: "2026-08-01T09:15:20"
            },
            config.document || {}
        ),
        analysis:
            config.analysis === null
                ? null
                : Object.assign(
                    {
                        analysis_id: "an-workspace-1",
                        extraction: extraction(),
                        ocr_lines: OCR_LINES,
                        evidence_flags: config.evidenceFlags || [],
                        field_confidence: fieldConfidence(),
                        date_validation: dateValidation(),
                        anomaly_validation: anomalyValidation(),
                        review_decision: reviewDecision(),
                        created_at: "2026-08-01T09:15:20"
                    },
                    config.analysis || {}
                ),
        human_review: config.humanReview || null,
        /* PHASE 10.2. Derived server-side and delivered at the
           top level beside final_record. Defaults to the
           SUPPORTED shape so every existing check keeps
           describing a correctly classified Guard Licence. */
        /* PHASE 10.6. The normalized findings view.

           Deliberately NOT part of the default payload.

           Production always sends it, but the panel still has
           to render a payload that does not -- a document with
           no analysis row has no view to normalize. Leaving it
           out by default means every existing check above
           keeps exercising that fallback, and the four
           normalized_* checks below exercise the new path. */
        findings:
            config.findings === undefined
                ? null
                : config.findings,
        classification:
            config.classification === undefined
                ? {
                    outcome: "SUPPORTED",
                    document_type: "guard_license",
                    supported: true,
                    retryable: false,
                    supported_document_types: [
                        "Security Guard License",
                        "ID Card",
                        "SIA Badge"
                    ],
                    message: null
                }
                : config.classification,
        final_record:
            config.finalRecord === undefined
                ? finalRecord("PENDING_REVIEW")
                : config.finalRecord
    };
}


/* PHASE 10.2. The two non-supported classification shapes, as
   backend/app/domain/classification.py returns them. */
function unsupportedClassification() {
    return {
        outcome: "UNSUPPORTED",
        document_type: "unknown",
        supported: false,
        retryable: false,
        supported_document_types: [
            "Security Guard License",
            "ID Card",
            "SIA Badge"
        ],
        message:
            "VIGILOX could not reliably identify this file " +
            "as one of the currently supported document " +
            "types. No usable record was produced."
    };
}

function unclassifiedClassification() {
    return {
        outcome: "UNCLASSIFIED_NEEDS_REVIEW",
        document_type: "unknown",
        supported: false,
        retryable: false,
        supported_document_types: [
            "Security Guard License",
            "ID Card",
            "SIA Badge"
        ],
        message:
            "VIGILOX could not classify this document, and " +
            "the image quality was too poor to rule out a " +
            "supported document. A reviewer needs to look " +
            "at it."
    };
}


function historyPayload(overrides) {
    return Object.assign(
        {
            document_id: "doc-workspace-1",
            event_count: 2,
            events: [
                {
                    audit_id: "a1",
                    document_id: "doc-workspace-1",
                    event_type: "MACHINE_REVIEW_DECISION",
                    actor_type: "MACHINE",
                    actor_id: "vigilox-pipeline",
                    details: {
                        decision: "REVIEW_REQUIRED",
                        priority: "HIGH",
                        reason_codes: [
                            "MISSING_CRITICAL_FIELD",
                            "DOCUMENT_EXPIRED"
                        ]
                    },
                    created_at: "2026-08-01T09:15:20"
                },
                {
                    audit_id: "a2",
                    document_id: "doc-workspace-1",
                    event_type: "HUMAN_REVIEW",
                    actor_type: "HUMAN",
                    actor_id: "reviewer-7",
                    details: {
                        human_action: "CORRECT",
                        notes: "Licence number was misread.",
                        corrections: {
                            licence_number: "87654321"
                        }
                    },
                    created_at: "2026-08-02T11:00:00"
                }
            ]
        },
        overrides || {}
    );
}


/* ==========================================================
   BOOT
   ========================================================== */

function boot(options) {
    const config = options || {};

    const calls = {
        document: 0,
        reviewer: 0,
        history: 0,
        image: 0,
        imageClassify: 0,
        health: 0,
        submissions: []
    };

    const win = stub.createWindow({
        pathname: "/review/doc-workspace-1",
    });

    /* The real shipped page, parsed into a real element
       tree. A renamed id or a moved element breaks the
       test rather than being papered over. */
    stub.loadPage(win, "review_detail.html");

    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");
    stub.loadScript(win, "js/vocabulary.js");

    const endpoints = win.VigiloxApi.endpoints;

    endpoints.getDocument = function () {
        calls.document += 1;

        if (config.documentError) {
            return Promise.reject(config.documentError);
        }

        const payload = config.payload
            ? config.payload(calls.document)
            : documentPayload({});

        return Promise.resolve(payload);
    };

    endpoints.getReviewerIdentity = function () {
        calls.reviewer += 1;

        if (config.reviewerError) {
            return Promise.reject(config.reviewerError);
        }

        if (config.reviewer === null) {
            return Promise.resolve({ reviewer: null });
        }

        return Promise.resolve({
            reviewer: Object.assign(
                {
                    reviewer_id: "reviewer-7",
                    role: "REVIEWER",
                    source: "LOCAL_ENV",
                    can_review: true
                },
                config.reviewer || {}
            )
        });
    };

    endpoints.getDocumentHistory = function () {
        calls.history += 1;

        if (config.historyError) {
            return Promise.reject(config.historyError);
        }

        return Promise.resolve(
            config.history || historyPayload()
        );
    };

    endpoints.getHealth = function () {
        calls.health += 1;
        return Promise.resolve({ status: "ok" });
    };

    endpoints.submitReview = function (documentId, payload) {
        calls.submissions.push({
            documentId: documentId,
            payload: payload,
            /* Recorded so a test can prove the key is absent
               rather than merely falsy. */
            keys: Object.keys(payload)
        });

        if (config.submitError) {
            return Promise.reject(config.submitError);
        }

        return Promise.resolve({
            status: "success",
            document_id: documentId,
            human_action: payload.action
        });
    };

    /* ======================================================
       THE FAILURE-PATH CLASSIFIER
       ======================================================
       source_panel no longer fetches the image to display it
       -- the element does that. This is now reached ONLY when
       the element's load failed, to find out why and to
       recover a request id for the unavailable state.

       So it is deliberately NOT counted in calls.image: the
       page made one image request (the element) plus, when
       something was already wrong, one diagnostic.
       ====================================================== */
    win.VigiloxApi.request = function (path, opts) {

        calls.imageClassify += 1;

        if (config.imageError) {
            return Promise.reject(config.imageError);
        }

        /* The endpoint is healthy, so a failed element load
           means the bytes did not decode. */
        return Promise.resolve({
            response: {
                blob: function () {
                    return Promise.resolve({
                        size: 1024,
                        type: "image/jpeg"
                    });
                }
            },
            requestId: "req-image"
        });
    };

    /* ======================================================
       PHASE 12.19 - THE IMAGE ELEMENT *IS* THE REQUEST
       ======================================================
       source_panel no longer fetches the image and wraps it
       in a blob. The application's own CSP forbids that:

           img-src 'self' data:

       and a blob: URL is neither, so real Chrome blocked
       every embedded document image while the same URL opened
       directly in a tab rendered perfectly.

       The panel now assigns the same-origin endpoint straight
       to img.src, so THE ELEMENT makes the request. This stub
       therefore models an <img>:

           assigning src counts as the image request
           the load is asynchronous
           it reports load with a size, or error

       calls.image still means "how many times did this page
       ask for the source image", which is what the request
       budget assertion is about -- it is simply counted where
       the request now happens.

       config:
           imageDecodeFails   served, undecodable -> error
           imageError         the endpoint fails  -> error,
                              and the classify fetch rejects
                              with this structured error
           imageWidth/Height  the reported intrinsic size
       ====================================================== */
    (function installImageElement() {

        const image = win.document.getElementById(
            "original-document-image"
        );

        if (!image) {
            return;
        }

        let assigned = null;

        Object.defineProperty(image, "src", {
            configurable: true,

            get: function () {
                return assigned;
            },

            set: function (value) {

                assigned = value;

                if (!value) {
                    return;
                }

                /* The element made a request. */
                calls.image += 1;

                /* Asynchronous, like a real load. Firing
                   synchronously here would settle before
                   source_panel had attached its listeners and
                   the test would prove nothing. */
                setImmediate(function () {

                    if (
                        config.imageDecodeFails
                        || config.imageError
                    ) {
                        image.naturalWidth = 0;
                        image.naturalHeight = 0;
                        image.fire("error", {});
                        return;
                    }

                    /* ONLY when the check asked for a size.

                       Defaulting to a size here would erase
                       the "loaded, size not yet reported"
                       state that
                       highlight_without_intrinsic_size
                       exists to cover. */
                    if (config.imageWidth) {
                        image.naturalWidth = config.imageWidth;
                        image.naturalHeight =
                            config.imageHeight || 0;
                    }

                    image.fire("load", {});
                });
            }
        });
    }());

    stub.loadScript(win, "js/workspace/tabs.js");
    stub.loadScript(win, "js/workspace/source_panel.js");
    stub.loadScript(win, "js/workspace/fields_view.js");
    stub.loadScript(win, "js/workspace/validation_view.js");
    stub.loadScript(win, "js/workspace/result_view.js");
    stub.loadScript(win, "js/workspace/review_actions.js");
    stub.loadScript(win, "review_detail.js");

    win.document.ready();

    win.calls = calls;

    return win;
}


function settle(rounds) {
    let chain = Promise.resolve();
    for (let i = 0; i < (rounds || 6); i += 1) {
        chain = chain.then(function () {
            return new Promise(function (resolve) {
                setImmediate(resolve);
            });
        });
    }
    return chain;
}


/* ==========================================================
   HELPERS
   ========================================================== */

function node(win, id) {
    return win.document.getElementById(id);
}

function textOf(win, id) {
    const found = node(win, id);
    return found ? found.textContent : null;
}

function fieldRows(win) {
    return node(win, "extraction-fields").querySelectorAll(
        ".field-row"
    );
}

function readFieldRow(row) {
    const label = row.querySelector(".field-row-label");
    const value = row.querySelector(".field-value");
    const badges = row.querySelectorAll(".field-row-meta .badge");
    const confidence = row.querySelector(".confidence-value");

    return {
        label: label ? label.textContent : null,
        value: value ? value.textContent : null,
        empty: value ? value.classList.contains("is-empty") : null,
        corrected: row.classList.contains("is-corrected"),
        badges: badges.map(function (b) {
            return { text: b.textContent, className: b.className };
        }),
        confidence: confidence ? confidence.textContent : null,
        evidence_ids: row
            .querySelectorAll(".evidence-id")
            .map(function (e) {
                return e.textContent;
            }),
        evidence_text: row
            .querySelectorAll(".evidence-text")
            .map(function (e) {
                return e.textContent;
            })
    };
}

function overlayBoxes(win) {
    return node(win, "evidence-overlay")
        .querySelectorAll(".evidence-box")
        .map(function (box) {
            return {
                lineId: box.getAttribute("data-line-id"),
                left: box.style.left,
                top: box.style.top,
                width: box.style.width,
                height: box.style.height
            };
        });
}

function setImageSize(win, width, height) {
    const image = node(win, "original-document-image");
    image.naturalWidth = width;
    image.naturalHeight = height;
    return image;
}

function valueRows(win, containerId) {
    return node(win, containerId)
        .querySelectorAll(".value-row")
        .map(function (row) {
            const label = row.querySelector(".value-row-label");
            return {
                label: label ? label.textContent : null,
                corrected: row.classList.contains("is-corrected"),
                cells: row
                    .querySelectorAll(".value-cell")
                    .map(function (cell) {
                        const cellLabel = cell.querySelector(
                            ".value-cell-label"
                        );
                        const cellValue = cell.querySelector(
                            ".value-cell-value"
                        );
                        return {
                            label: cellLabel
                                ? cellLabel.textContent
                                : null,
                            value: cellValue
                                ? cellValue.textContent
                                : null
                        };
                    }),
                source: row
                    .querySelectorAll(".value-row-source .badge")
                    .map(function (b) {
                        return b.textContent;
                    })
            };
        });
}

function tabState(win) {
    return node(win, "workspace-tablist")
        .querySelectorAll('[role="tab"]')
        .map(function (tab) {
            const panel = win.document.getElementById(
                tab.getAttribute("aria-controls")
            );
            return {
                id: tab.id,
                label: tab.textContent,
                selected: tab.getAttribute("aria-selected"),
                tabindex: tab.getAttribute("tabindex"),
                panel_hidden: panel ? panel.hidden : null
            };
        });
}


/* ==========================================================
   CHECKS
   ========================================================== */

const results = {};
const jobs = [];

function check(name, fn) {
    jobs.push(
        Promise.resolve()
            .then(fn)
            .then(
                function (value) {
                    results[name] = value;
                },
                function (error) {
                    results[name] = {
                        error: String((error && error.message) || error),
                        stack: String((error && error.stack) || "")
                            .split("\n")
                            .slice(0, 5)
                            .join(" | ")
                    };
                }
            )
    );
}


/* ---------- module surface ---------- */

check("module_surface", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            workspace: Boolean(win.VigiloxWorkspace),
            tabs: Boolean(win.VigiloxTabs),
            source_panel: Boolean(win.VigiloxSourcePanel),
            fields_view: Boolean(win.VigiloxFieldsView),
            validation_view: Boolean(win.VigiloxValidationView),
            result_view: Boolean(win.VigiloxResultView),
            review_actions: Boolean(win.VigiloxReviewActions),
            vocabulary: Boolean(win.VigiloxVocabulary),
            correctable_fields:
                win.VigiloxReviewActions.CORRECTABLE_FIELDS,
            field_order: win.VigiloxFieldsView.FIELD_ORDER,
            final_field_names: win.VigiloxResultView.FIELD_NAMES
        };
    });
});


/* ---------- request budget ---------- */

check("request_budget", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            document: win.calls.document,
            reviewer: win.calls.reviewer,
            history: win.calls.history,
            image: win.calls.image,
            health: win.calls.health,
            intervals: win.record.intervals.length,
            content_visible: node(win, "detail-content").hidden === false,
            loading_hidden: node(win, "detail-loading").hidden
        };
    });
});


/* ---------- header, facts, badges ---------- */

check("header_and_facts", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            title: textOf(win, "document-title"),
            subtitle: textOf(win, "document-subtitle"),
            badges: node(win, "document-badges")
                .querySelectorAll(".badge")
                .map(function (b) {
                    return b.textContent;
                }),
            facts: node(win, "document-facts")
                .querySelectorAll(".detail-row")
                .map(function (row) {
                    return row.textContent;
                })
        };
    });
});


/* ---------- overview ---------- */

check("overview", function () {
    const win = boot({});

    return settle().then(function () {
        const panel = node(win, "overview-panel");
        return {
            text: panel.textContent,
            rows: panel
                .querySelectorAll(".detail-row")
                .map(function (row) {
                    return row.textContent;
                }),
            note: panel.querySelector(".overview-note")
                ? panel.querySelector(".overview-note").textContent
                : null
        };
    });
});


/* ---------- tabs ---------- */

check("tabs_default", function () {
    const win = boot({});

    return settle().then(function () {
        return { tabs: tabState(win) };
    });
});


check("tabs_keyboard", function () {
    const win = boot({});

    return settle().then(function () {
        const tabs = node(win, "workspace-tablist").querySelectorAll(
            '[role="tab"]'
        );

        const trail = [];

        function record(label) {
            const active = tabState(win).filter(function (t) {
                return t.selected === "true";
            })[0];
            trail.push({ after: label, id: active.id });
        }

        record("initial");

        tabs[0].fire("keydown", { key: "ArrowRight" });
        record("ArrowRight");

        tabs[1].fire("keydown", { key: "ArrowRight" });
        record("ArrowRight");

        tabs[2].fire("keydown", { key: "ArrowLeft" });
        record("ArrowLeft");

        tabs[1].fire("keydown", { key: "End" });
        record("End");

        tabs[tabs.length - 1].fire("keydown", { key: "Home" });
        record("Home");

        /* Wrapping: Left from the first tab goes to the last. */
        tabs[0].fire("keydown", { key: "ArrowLeft" });
        record("ArrowLeft-wrap");

        return {
            trail: trail,
            roving: tabState(win).map(function (t) {
                return t.tabindex;
            }),
            focused_after_arrow:
                win.document.activeElement
                    ? win.document.activeElement.id
                    : null
        };
    });
});


check("tabs_click_switches_panel", function () {
    const win = boot({});

    return settle().then(function () {
        node(win, "tab-raw").click();

        const state = tabState(win);

        return {
            raw_selected: state.filter(function (t) {
                return t.id === "tab-raw";
            })[0],
            fields_hidden: state.filter(function (t) {
                return t.id === "tab-fields";
            })[0].panel_hidden,
            /* Exactly one panel visible. */
            visible_panels: state.filter(function (t) {
                return t.panel_hidden === false;
            }).length
        };
    });
});


/* ---------- extracted fields ---------- */

check("fields_render", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            row_count: fieldRows(win).length,
            rows: fieldRows(win).map(readFieldRow)
        };
    });
});


check("no_overall_confidence", function () {
    const win = boot({});

    return settle().then(function () {
        const text = node(win, "extraction-fields").textContent;
        const lowered = text.toLowerCase();

        return {
            mentions_document_confidence:
                lowered.indexOf("document confidence") !== -1,
            mentions_overall:
                lowered.indexOf("overall confidence") !== -1,
            mentions_average:
                lowered.indexOf("average confidence") !== -1,
            /* The disclaimer is expected to be present. */
            states_absence:
                lowered.indexOf(
                    "no document-level confidence"
                ) !== -1
        };
    });
});


/* ==========================================================
   PHASE 10.6 - THE FIELDS PANEL READS THE NORMALIZED VIEW
   ==========================================================
   Same three evidence problems, delivered two ways: as the
   raw flag strings the panel has always parsed itself, and as
   the normalized findings the backend now sends.

   Both must render identically. If they diverge, the browser
   parser and the backend parser have drifted -- and the
   browser one is the fallback, so the divergence would only
   show up on the older payloads nobody looks at.
   ========================================================== */

const EVIDENCE_FLAG_CASES = [
    "FULL_NAME_EVIDENCE_MISMATCH",
    "ISSUER_CONTEXT_MISSING",
    "LICENCE_NUMBER_INVALID_SOURCE_LINE_ID:L99"
];

function evidenceFindingsView() {
    return normalizedView({
        findings: [
            normalizedFinding({
                code: "FULL_NAME_EVIDENCE_MISMATCH",
                category: "EVIDENCE",
                severity: null,
                message: "Value not found in its evidence.",
                field: "full_name",
                source: "evidence_flags",
                affects_routing: false,
                detail: {
                    flag: "FULL_NAME_EVIDENCE_MISMATCH",
                    kind: "EVIDENCE_MISMATCH",
                    source_line_id: null,
                    known: true
                }
            }),
            normalizedFinding({
                code: "ISSUER_CONTEXT_MISSING",
                category: "EVIDENCE",
                severity: null,
                message: "Expected context missing.",
                field: "issuer",
                source: "evidence_flags",
                affects_routing: false,
                detail: {
                    flag: "ISSUER_CONTEXT_MISSING",
                    kind: "CONTEXT_MISSING",
                    source_line_id: null,
                    known: true
                }
            }),
            normalizedFinding({
                code: "LICENCE_NUMBER_INVALID_SOURCE_LINE_ID",
                category: "EVIDENCE",
                severity: null,
                message: "Cited OCR line does not exist.",
                field: "licence_number",
                source: "evidence_flags",
                affects_routing: false,
                detail: {
                    flag:
                        "LICENCE_NUMBER_INVALID_SOURCE_LINE_ID" +
                        ":L99",
                    kind: "INVALID_SOURCE_LINE_ID",
                    source_line_id: "L99",
                    known: true
                }
            })
        ],
        total: 3,
        unrated_count: 3,
        categories: ["EVIDENCE"],
        quality_assessed: true
    });
}

function readEvidenceProblems(win) {
    return fieldRows(win).map(function (row) {
        const label = row.querySelector(".field-row-label");
        const items = row.querySelectorAll(
            ".evidence-problems li"
        );

        return {
            field: label ? label.textContent : null,
            titles: items.map(function (li) {
                const t = li.querySelector(
                    ".evidence-problem-title"
                );
                return t ? t.textContent : null;
            }),
            refs: items.map(function (li) {
                const r = li.querySelector(
                    ".evidence-problem-ref"
                );
                return r ? r.textContent : null;
            })
        };
    });
}

check("normalized_evidence_in_fields", function () {
    const rawWin = boot({
        payload: function () {
            return documentPayload({
                evidenceFlags: EVIDENCE_FLAG_CASES
            });
        }
    });

    return settle()
        .then(function () {
            const fromFlags = readEvidenceProblems(rawWin);

            const viewWin = boot({
                payload: function () {
                    return documentPayload({
                        evidenceFlags: EVIDENCE_FLAG_CASES,
                        findings: evidenceFindingsView()
                    });
                }
            });

            return settle().then(function () {
                return {
                    from_flags: fromFlags,
                    from_view: readEvidenceProblems(viewWin)
                };
            });
        })
        .then(function (both) {
            return {
                from_flags: both.from_flags,
                from_view: both.from_view,
                identical:
                    JSON.stringify(both.from_flags) ===
                    JSON.stringify(both.from_view),
                /* The cited line has to survive both paths.
                   Without it the problem cannot be checked
                   against the page. */
                view_has_line_ref: both.from_view.some(
                    function (row) {
                        return (
                            row.refs.indexOf("Line L99") !== -1
                        );
                    }
                )
            };
        });
});


check("evidence_problems", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                evidenceFlags: [
                    "FULL_NAME_EVIDENCE_MISMATCH",
                    "ISSUER_CONTEXT_MISSING",
                    "LICENCE_NUMBER_INVALID_SOURCE_LINE_ID:L99"
                ]
            });
        }
    });

    return settle().then(function () {
        const rows = fieldRows(win);

        return {
            problems: rows.map(function (row) {
                const label = row.querySelector(".field-row-label");
                const items = row.querySelectorAll(
                    ".evidence-problems li"
                );
                return {
                    field: label ? label.textContent : null,
                    titles: items.map(function (li) {
                        const t = li.querySelector(
                            ".evidence-problem-title"
                        );
                        return t ? t.textContent : null;
                    }),
                    refs: items.map(function (li) {
                        const r = li.querySelector(
                            ".evidence-problem-ref"
                        );
                        return r ? r.textContent : null;
                    })
                };
            }).filter(function (entry) {
                return entry.titles.length > 0;
            })
        };
    });
});


/* ---------- evidence highlighting ---------- */

check("bbox_arithmetic", function () {
    const win = boot({});

    return settle().then(function () {
        const panel = win.VigiloxSourcePanel;

        return {
            usable: panel.isUsableBox([30, 20, 180, 60], 600, 400),
            zero_area: panel.isUsableBox([0, 0, 0, 0], 600, 400),
            out_of_bounds: panel.isUsableBox(
                [30, 20, 900, 60],
                600,
                400
            ),
            inverted: panel.isUsableBox([180, 60, 30, 20], 600, 400),
            wrong_length: panel.isUsableBox([1, 2, 3], 600, 400),
            non_numeric: panel.isUsableBox(
                [1, 2, "3", 4],
                600,
                400
            ),
            no_size: panel.isUsableBox([30, 20, 180, 60], 0, 0),

            /* 30/600 = 5%, 20/400 = 5%, 150/600 = 25%,
               40/400 = 10% */
            percent: panel.boxToPercent([30, 20, 180, 60], 600, 400),
            percent_bad: panel.boxToPercent(
                [0, 0, 0, 0],
                600,
                400
            )
        };
    });
});


check("evidence_highlight", function () {
    const win = boot({});

    return settle().then(function () {
        setImageSize(win, IMAGE_WIDTH, IMAGE_HEIGHT);

        /* Full Name cites L2. */
        const rows = fieldRows(win);
        const nameRow = rows[1];
        const button = nameRow.querySelector(
            ".field-evidence-actions button"
        );

        button.click();

        const single = overlayBoxes(win);

        /* Expiry Date cites L4. */
        const expiryRow = rows.filter(function (row) {
            const label = row.querySelector(".field-row-label");
            return label && label.textContent === "Expiry Date";
        })[0];

        expiryRow
            .querySelector(".field-evidence-actions button")
            .click();

        return {
            button_label: button.textContent,
            after_name: single,
            after_expiry: overlayBoxes(win),
            caption: textOf(win, "source-caption"),
            active_ids: win.VigiloxSourcePanel.getActiveLineIds()
        };
    });
});


check("unusable_bbox_is_skipped", function () {
    const win = boot({});

    return settle().then(function () {
        setImageSize(win, IMAGE_WIDTH, IMAGE_HEIGHT);

        /* L6 has a zero-area box; L2 is fine. */
        const result = win.VigiloxSourcePanel.highlight([
            "L2",
            "L6",
            "L404"
        ]);

        return {
            result: result,
            boxes: overlayBoxes(win),
            caption: textOf(win, "source-caption")
        };
    });
});


check("highlight_without_intrinsic_size", function () {
    const win = boot({});

    return settle().then(function () {
        /* naturalWidth stays 0: the browser has not decoded
           the image yet. */
        const result = win.VigiloxSourcePanel.highlight(["L2"]);

        return {
            result: result,
            boxes: overlayBoxes(win).length,
            /* Says so, rather than drawing a guess. */
            caption: textOf(win, "source-caption")
        };
    });
});


check("highlight_toggle", function () {
    const win = boot({});

    return settle().then(function () {
        setImageSize(win, IMAGE_WIDTH, IMAGE_HEIGHT);
        win.VigiloxSourcePanel.highlight(["L2", "L3"]);

        const before = overlayBoxes(win).length;

        const toggle = node(win, "highlight-toggle");
        toggle.checked = false;
        toggle.fire("change", {});

        const off = overlayBoxes(win).length;

        toggle.checked = true;
        toggle.fire("change", {});

        return {
            before: before,
            off: off,
            back_on: overlayBoxes(win).length,
            caption_when_off_then_on: textOf(win, "source-caption")
        };
    });
});


check("missing_image_is_not_a_page_failure", function () {
    const win = boot({
        imageError: {
            status: 404,
            code: "DOCUMENT_IMAGE_NOT_FOUND",
            message: "The stored document image is missing.",
            requestId: "req-img-404"
        }
    });

    return settle().then(function () {
        return {
            content_visible:
                node(win, "detail-content").hidden === false,
            image_hidden: node(win, "original-document-image").hidden,
            unavailable_visible:
                node(win, "image-unavailable").hidden === false,
            unavailable_text: textOf(win, "image-unavailable"),
            /* The extracted values are still usable. */
            field_rows: fieldRows(win).length
        };
    });
});


/* ==========================================================
   PHASE 12.18 - A 200 THAT DOES NOT DECODE
   ==========================================================
   RELEASE BLOCKER 2, CASE B.

   The backend is not at fault here and neither is api.js: a
   404 rejects and lands in .catch(), which is the clean
   "original document is not available" state (CASE A, checked
   above by missing_image_is_not_a_page_failure).

   CASE B is the other one. The request succeeds, the bytes are
   not a decodable image, nothing rejects, and the old code had
   already un-hidden the element -- so the browser painted its
   broken-image icon and the alt text. There was no error
   listener anywhere in source_panel.
   ========================================================== */

check("undecodable_image_shows_unavailable_not_broken", function () {

    const win = boot({
        /* The fetch SUCCEEDS. Only the decode fails. */
        imageDecodeFails: true
    });

    return settle().then(function () {

        const image = node(win, "original-document-image");
        const toggle = node(win, "highlight-toggle");

        return {
            /* The page itself is fine -- a missing picture is
               not a page failure. */
            content_visible:
                node(win, "detail-content").hidden === false,

            /* THE POINT: the element must not be left on
               screen with a src the browser cannot render. */
            image_hidden: image.hidden,
            image_src_cleared: !image.src,

            unavailable_visible:
                node(win, "image-unavailable").hidden === false,
            unavailable_text: textOf(win, "image-unavailable"),

            /* Evidence cannot point at a picture that is not
               there. */
            overlay_boxes: overlayBoxes(win).length,
            toggle_disabled: toggle ? toggle.disabled === true : null,
            toggle_checked: toggle ? toggle.checked === true : null,

            /* The reviewer can still do their job. */
            field_rows: fieldRows(win).length
        };
    });
});


check("decoded_image_is_shown_and_evidence_works", function () {

    /* The other half of the same change: a real decode must
       still reveal the image and still draw evidence. A fix
       that hid a working image would be worse than the bug. */
    const win = boot({
        imageWidth: 600,
        imageHeight: 400
    });

    return settle().then(function () {

        const image = node(win, "original-document-image");
        const toggle = node(win, "highlight-toggle");

        win.VigiloxSourcePanel.highlight(["L0"]);

        return {
            image_visible: image.hidden === false,
            image_has_src: Boolean(image.src),
            natural_width: image.naturalWidth,
            unavailable_hidden:
                node(win, "image-unavailable").hidden === true,
            toggle_disabled: toggle ? toggle.disabled === true : null,
            overlay_boxes: overlayBoxes(win).length
        };
    });
});


check("image_src_is_csp_loadable", function () {

    /* ==================================================
       THE REGRESSION THIS EXISTS FOR
       ==================================================
       The panel used to fetch the image and hand the browser
       a blob: URL. The application's own policy is

           img-src 'self' data:

       so every embedded document image was blocked, while the
       same URL opened directly in a tab rendered perfectly --
       a top-level navigation is not an img-src fetch.

       The scheme of the assigned src is therefore not a
       detail. It is the bug.
       ================================================== */

    const win = boot({
        imageWidth: 506,
        imageHeight: 319
    });

    return settle().then(function () {

        const image = node(win, "original-document-image");
        const src = String(image.src || "");
        const toggle = node(win, "highlight-toggle");

        return {
            src: src,

            /* Same-origin and relative: 'self' covers it. */
            is_same_origin_path: src.indexOf("/api/v1/") === 0,

            /* The three schemes img-src 'self' data: does not
               permit, and the one it does. */
            is_blob: src.indexOf("blob:") === 0,
            is_data: src.indexOf("data:") === 0,
            is_absolute_other_origin: /^https?:\/\//.test(src),

            names_the_document:
                src.indexOf("/image") !== -1,

            /* Evidence becomes available only once the image
               has actually loaded. */
            toggle_disabled: toggle ? toggle.disabled === true : null,

            image_visible: image.hidden === false,
            natural_width: image.naturalWidth
        };
    });
});


/* ---------- validation ---------- */

check("validation_render", function () {
    const win = boot({});

    return settle().then(function () {
        const panel = node(win, "validation-content");

        return {
            text: panel.textContent,
            blocks: panel
                .querySelectorAll(".validation-block-title")
                .map(function (t) {
                    return t.textContent;
                }),
            rows: panel
                .querySelectorAll(".detail-row")
                .map(function (row) {
                    return row.textContent;
                }),
            badges: panel
                .querySelectorAll(".badge")
                .map(function (b) {
                    return {
                        text: b.textContent,
                        className: b.className
                    };
                })
        };
    });
});


check("validation_logical_issues", function () {
    const win = boot({
        payload: function () {
            const payload = documentPayload({});
            payload.analysis.date_validation = {
                reference_date: "2026-08-20",
                date_fields: {
                    date_of_birth: {
                        value: "2030-01-01",
                        status: "VALID_DATE"
                    },
                    issue_date: {
                        value: "not-a-date",
                        status: "INVALID_DATE_FORMAT"
                    },
                    expiry_date: {
                        value: "2026-01-01",
                        status: "VALID_DATE"
                    }
                },
                expiry: {
                    value: "2026-01-01",
                    status: "EXPIRED",
                    days_until_expiry: -231
                },
                logical_issues: [
                    {
                        code: "FUTURE_DATE_OF_BIRTH",
                        field: "date_of_birth",
                        message:
                            "Date of birth cannot be in the future."
                    },
                    {
                        code: "ISSUE_DATE_INVALID_FORMAT",
                        field: "issue_date",
                        message:
                            "issue_date value 'not-a-date' is not " +
                            "a valid YYYY-MM-DD date."
                    }
                ],
                valid: false
            };
            return payload;
        }
    });

    return settle().then(function () {
        const items = node(win, "validation-content").querySelectorAll(
            ".issue-item"
        );

        return {
            issues: items.map(function (item) {
                return {
                    title: item.querySelector(".issue-item-title")
                        .textContent,
                    message: item.querySelector(
                        ".issue-item-message"
                    ).textContent,
                    code: item.querySelector(".issue-item-code")
                        .textContent
                };
            }),
            /* The unparseable value is shown exactly as read. */
            raw_value_shown:
                node(win, "validation-content").textContent.indexOf(
                    "not-a-date"
                ) !== -1
        };
    });
});


check("no_expiry_date", function () {
    const win = boot({
        payload: function () {
            const payload = documentPayload({});
            payload.analysis.date_validation = {
                reference_date: "2026-08-20",
                date_fields: {
                    date_of_birth: {
                        value: null,
                        status: "NOT_EXTRACTED"
                    },
                    issue_date: {
                        value: null,
                        status: "NOT_EXTRACTED"
                    },
                    expiry_date: {
                        value: null,
                        status: "NOT_EXTRACTED"
                    }
                },
                expiry: {
                    value: null,
                    status: "NOT_AVAILABLE",
                    days_until_expiry: null
                },
                logical_issues: [],
                valid: true
            };
            return payload;
        }
    });

    return settle().then(function () {
        const text = node(win, "validation-content").textContent;
        return {
            text: text,
            /* No days-remaining figure may be invented when the
               validator sent none. */
            mentions_days: /\d+\s*days?/.test(text)
        };
    });
});


/* ---------- findings ---------- */

check("findings_render", function () {
    const win = boot({});

    return settle().then(function () {
        const panel = node(win, "anomaly-list");

        return {
            summary_badges: panel
                .querySelectorAll(".finding-summary .badge")
                .map(function (b) {
                    return {
                        text: b.textContent,
                        className: b.className
                    };
                }),
            summary_hint: panel.querySelector(
                ".finding-summary .field-hint"
            )
                ? panel.querySelector(
                    ".finding-summary .field-hint"
                ).textContent
                : null,
            items: panel
                .querySelectorAll(".finding-item")
                .map(function (item) {
                    return {
                        severity: item.querySelector(
                            '[class*="badge-severity"]'
                        )
                            ? item.querySelector(
                                '[class*="badge-severity"]'
                            ).textContent
                            : null,
                        severity_class: item.querySelector(
                            '[class*="badge-severity"]'
                        )
                            ? item.querySelector(
                                '[class*="badge-severity"]'
                            ).className
                            : null,
                        title: item.querySelector(".finding-title")
                            .textContent,
                        message: item.querySelector(
                            ".finding-message"
                        ).textContent,
                        code: item.querySelector(".finding-code")
                            .textContent
                    };
                }),
            /* No risk score anywhere. */
            mentions_risk:
                panel.textContent.toLowerCase().indexOf("risk") !== -1,
            has_percent: /\d\s*%/.test(panel.textContent)
        };
    });
});


check("no_findings", function () {
    const win = boot({
        payload: function () {
            const payload = documentPayload({});
            payload.analysis.anomaly_validation = {
                document_type: "guard_license",
                valid: true,
                has_anomalies: false,
                error_count: 0,
                warning_count: 0,
                issues: []
            };
            return payload;
        }
    });

    return settle().then(function () {
        return {
            text: node(win, "anomaly-list").textContent,
            item_count: node(win, "anomaly-list").querySelectorAll(
                ".finding-item"
            ).length
        };
    });
});


check("unknown_severity_not_promoted", function () {
    const win = boot({
        payload: function () {
            const payload = documentPayload({});
            payload.analysis.anomaly_validation = {
                document_type: "guard_license",
                valid: false,
                has_anomalies: true,
                error_count: 0,
                warning_count: 0,
                issues: [
                    {
                        code: "SOMETHING_NEW",
                        severity: "CATASTROPHIC",
                        field: null,
                        message: "A new severity appeared."
                    }
                ]
            };
            return payload;
        }
    });

    return settle().then(function () {
        const badges = node(win, "anomaly-list")
            .querySelectorAll(".finding-item .badge")
            .map(function (b) {
                return { text: b.textContent, className: b.className };
            });

        return {
            badges: badges,
            claims_error: badges.some(function (b) {
                return b.className.indexOf("severity-error") !== -1;
            }),
            claims_warning: badges.some(function (b) {
                return b.className.indexOf("severity-warning") !== -1;
            }),
            /* The unknown code is shown as itself. */
            code_shown:
                node(win, "anomaly-list").textContent.indexOf(
                    "SOMETHING_NEW"
                ) !== -1
        };
    });
});


/* ---------- final record ---------- */

function finalRecordCheck(name, status, corrections) {
    check(name, function () {
        const win = boot({
            payload: function () {
                return documentPayload({
                    finalRecord: finalRecord(status, corrections),
                    humanReview:
                        status === "CORRECTED"
                            ? {
                                human_action: "CORRECT",
                                reviewer_id: "reviewer-7",
                                reviewed_at: "2026-08-02T11:00:00",
                                notes: "Licence number was misread.",
                                corrections: corrections
                            }
                            : status === "APPROVED"
                                ? {
                                    human_action: "APPROVE",
                                    reviewer_id: "reviewer-7",
                                    reviewed_at:
                                        "2026-08-02T11:00:00",
                                    notes: null,
                                    corrections: null
                                }
                                : status === "REJECTED"
                                    ? {
                                        human_action: "REJECT",
                                        reviewer_id: "reviewer-7",
                                        reviewed_at:
                                            "2026-08-02T11:00:00",
                                        notes: "Unreadable.",
                                        corrections: null
                                    }
                                    : null
                });
            }
        });

        return settle().then(function () {
            const record = node(win, "final-record");

            return {
                status_text: record.querySelector(
                    ".final-record-status"
                )
                    ? record.querySelector(".final-record-status")
                        .textContent
                    : null,
                badges: record
                    .querySelectorAll(".badge")
                    .map(function (b) {
                        return b.textContent;
                    }),
                note: record.querySelector(".final-record-note")
                    ? record.querySelector(".final-record-note")
                        .textContent
                    : null,
                classes: record.querySelector(".final-record")
                    ? record.querySelector(".final-record").className
                    : null,
                effective_text: textOf(win, "effective-values"),
                value_rows: valueRows(win, "effective-values"),
                header_badges: node(win, "document-badges")
                    .querySelectorAll(".badge")
                    .map(function (b) {
                        return b.textContent;
                    })
            };
        });
    });
}

/* PHASE 10.2. UNSUPPORTED takes no human review, so it is
   driven exactly like PENDING_REVIEW and AUTO_ACCEPTED: a
   final record with no humanReview beside it. */
finalRecordCheck("final_unsupported", "UNSUPPORTED", null);


/* ==========================================================
   PHASE 10.2 - UNSUPPORTED DOCUMENT WORKSPACE
   ========================================================== */

function classificationCheck(name, classification, status) {
    check(name, function () {
        const win = boot({
            payload: function () {
                return documentPayload({
                    document: {
                        document_type: "unknown"
                    },
                    analysis: {
                        extraction: Object.assign(
                            extraction(),
                            { document_type: "unknown" }
                        ),
                        review_decision:
                            status === "UNSUPPORTED"
                                ? {
                                    decision:
                                        "UNSUPPORTED_DOCUMENT",
                                    review_required: false,
                                    priority: "NONE",
                                    reason_codes: [
                                        "UNKNOWN_DOCUMENT_TYPE"
                                    ],
                                    issues: [
                                        {
                                            code:
                                                "UNKNOWN_DOCUMENT_TYPE",
                                            severity: "ERROR",
                                            field: null,
                                            message:
                                                "Document type " +
                                                "could not be " +
                                                "reliably " +
                                                "classified."
                                        }
                                    ]
                                }
                                : {
                                    decision: "REVIEW_REQUIRED",
                                    review_required: true,
                                    priority: "HIGH",
                                    reason_codes: [
                                        "UNKNOWN_DOCUMENT_TYPE"
                                    ],
                                    issues: [
                                        {
                                            code:
                                                "UNKNOWN_DOCUMENT_TYPE",
                                            severity: "ERROR",
                                            field: null,
                                            message:
                                                "Document type " +
                                                "could not be " +
                                                "reliably " +
                                                "classified."
                                        }
                                    ]
                                }
                    },
                    classification: classification,
                    finalRecord: finalRecord(status, null)
                });
            }
        });

        return settle().then(function () {
            const overview = node(win, "overview-panel");
            const alerts = overview.querySelectorAll(".alert");

            return {
                alert_count: alerts.length,
                alert_text: alerts.length
                    ? alerts[0].textContent
                    : null,
                alert_classes: alerts.length
                    ? alerts[0].className
                    : null,
                overview_text: overview.textContent,
                header_badges: node(win, "document-badges")
                    .querySelectorAll(".badge")
                    .map(function (b) {
                        return b.textContent;
                    }),
                /* The review controls. An unsupported document
                   must offer no way to publish values. */
                form_hidden: node(win, "human-review-form").hidden,
                approve_visible:
                    !node(win, "approve-button").hidden &&
                    !node(win, "human-review-form").hidden,
                locked_hidden: node(win, "review-locked-message").hidden,
                locked_text: node(win, "review-locked-message").textContent,
                effective_text: textOf(win, "effective-values")
            };
        });
    });
}

classificationCheck(
    "classification_unsupported",
    unsupportedClassification(),
    "UNSUPPORTED"
);

classificationCheck(
    "classification_unreadable",
    unclassifiedClassification(),
    "PENDING_REVIEW"
);


/* ==========================================================
   PHASE 10.1 / 10.2 - IMAGE QUALITY IN FINDINGS
   ==========================================================
   Three states, and the difference between the first two is
   the point: a null assessment is NOT ASSESSED, an empty
   findings list is ASSESSED AND CLEAN.
   ========================================================== */

function qualityCheck(name, quality) {
    check(name, function () {
        const win = boot({
            payload: function () {
                return documentPayload({
                    analysis:
                        quality === undefined
                            ? {}
                            : { quality: quality }
                });
            }
        });

        return settle().then(function () {
            const findings = node(win, "anomaly-list");

            return {
                text: findings.textContent,
                quality_items: findings
                    .querySelectorAll(".finding-item")
                    .map(function (item) {
                        return item.textContent;
                    }).length,
                block_titles: findings
                    .querySelectorAll(".validation-block-title")
                    .map(function (b) {
                        return b.textContent;
                    })
            };
        });
    });
}

qualityCheck("quality_not_assessed", null);

qualityCheck("quality_clean", {
    metrics: {
        width: 800,
        height: 500,
        laplacian_variance: 1820.5,
        mean_luminance: 198.4,
        contrast_spread: 28,
        estimated_skew_degrees: 0
    },
    findings: [],
    highest_severity: null,
    error: null
});

qualityCheck("quality_findings", {
    metrics: {
        width: 800,
        height: 500,
        laplacian_variance: 118.25,
        mean_luminance: 122.4,
        contrast_spread: 21,
        estimated_skew_degrees: -10.04
    },
    findings: [
        {
            code: "IMAGE_BLURRY",
            severity: "WARNING",
            message:
                "This image is blurred, so the text read " +
                "from it may be unreliable.",
            metric_name: "laplacian_variance",
            measured_value: 118.25,
            threshold: 350
        },
        {
            code: "ROTATION_CONCERN",
            severity: "WARNING",
            message:
                "This document appears rotated. Text was " +
                "still read, but a straighter photograph or " +
                "scan gives a more reliable result.",
            metric_name: "estimated_skew_degrees",
            measured_value: 10.04,
            threshold: 5
        }
    ],
    highest_severity: "WARNING",
    error: null
});
/* ==========================================================
   PHASE 10.6 - NORMALIZED FINDINGS
   ==========================================================
   payload.findings, built by
   backend/app/domain/findings.py.

   These fixtures mirror that shape. They are NOT a second
   definition of it: test_phase10_finding_normalization
   compares the key sets here against a real normalize_findings
   result, so a fixture that drifts away from the backend fails
   the Python suite rather than quietly testing a shape nothing
   produces.
   ========================================================== */

function normalizedView(options) {
    const config = options || {};

    return Object.assign(
        {
            findings: [],
            total: 0,
            counts: { ERROR: 0, WARNING: 0, INFO: 0 },
            unrated_count: 0,
            unrecognised_severities: [],
            highest_severity: null,
            categories: [],
            quality_assessed: false,
            quality_error: null,
            routing_finding_count: 0
        },
        config
    );
}

function normalizedFinding(options) {
    return Object.assign(
        {
            code: "MISSING_CRITICAL_FIELD",
            category: "ANOMALY",
            severity: "ERROR",
            message: "Required field 'id_number' is missing.",
            field: "id_number",
            source: "anomaly_validation",
            affects_routing: true,
            detail: null
        },
        options || {}
    );
}

/* The full shape: an error, a warning with expiry detail, an
   info, a quality finding with its measurement, and two
   ungraded evidence findings. Ordered worst-first, as the
   backend orders it. */
function populatedView() {
    return normalizedView({
        findings: [
            normalizedFinding({}),
            normalizedFinding({
                code: "IMAGE_UNREADABLE",
                category: "QUALITY",
                severity: "ERROR",
                message: "This image could not be read.",
                field: null,
                source: "quality",
                affects_routing: true,
                detail: {
                    metric_name: "laplacian_variance",
                    measured_value: 9.44,
                    threshold: 40
                }
            }),
            normalizedFinding({
                code: "DOCUMENT_EXPIRED",
                category: "EXPIRY",
                severity: "WARNING",
                message: "The document expired 231 day(s) ago.",
                field: "expiry_date",
                affects_routing: true,
                detail: {
                    expiry_date: "2026-01-01",
                    expiry_status: "EXPIRED",
                    days_until_expiry: -231
                }
            }),
            normalizedFinding({
                code: "FUTURE_ISSUE_DATE",
                category: "DATE",
                severity: "INFO",
                message: "Issue date is in the future.",
                field: "issue_date",
                affects_routing: false,
                detail: null
            }),
            normalizedFinding({
                code: "FULL_NAME_EVIDENCE_MISMATCH",
                category: "EVIDENCE",
                severity: null,
                message:
                    "The extracted value does not appear in " +
                    "the OCR text it cites.",
                field: "full_name",
                source: "evidence_flags",
                affects_routing: false,
                detail: {
                    flag: "FULL_NAME_EVIDENCE_MISMATCH",
                    kind: "EVIDENCE_MISMATCH",
                    source_line_id: null,
                    known: true
                }
            }),
            normalizedFinding({
                code: "EXPIRY_DATE_INVALID_SOURCE_LINE_ID",
                category: "EVIDENCE",
                severity: null,
                message:
                    "The value cites an OCR line that is not " +
                    "part of this document's OCR output.",
                field: "expiry_date",
                source: "evidence_flags",
                affects_routing: false,
                detail: {
                    flag: "EXPIRY_DATE_INVALID_SOURCE_LINE_ID:L9",
                    kind: "INVALID_SOURCE_LINE_ID",
                    source_line_id: "L9",
                    known: true
                }
            })
        ],
        total: 6,
        counts: { ERROR: 2, WARNING: 1, INFO: 1 },
        unrated_count: 2,
        highest_severity: "ERROR",
        categories: [
            "QUALITY",
            "EVIDENCE",
            "ANOMALY",
            "DATE",
            "EXPIRY"
        ],
        quality_assessed: true,
        routing_finding_count: 3
    });
}


function readFindingItems(container) {
    return container.querySelectorAll(".finding-item").map(
        function (item) {
            const title = item.querySelector(".finding-title");
            const badges = item.querySelectorAll(".badge");

            return {
                title: title ? title.textContent : null,
                class_name: String(item.className || ""),
                is_error:
                    String(item.className || "").indexOf(
                        "is-error"
                    ) !== -1,
                is_warning:
                    String(item.className || "").indexOf(
                        "is-warning"
                    ) !== -1,
                is_detail:
                    String(item.className || "").indexOf(
                        "is-detail"
                    ) !== -1,
                badges: badges.map(function (b) {
                    return b.textContent;
                }),
                text: item.textContent
            };
        }
    );
}

function findingsPanel(win) {
    const panel = node(win, "anomaly-list");

    return {
        items: readFindingItems(panel),
        block_titles: panel
            .querySelectorAll(".validation-block-title")
            .map(function (b) {
                return b.textContent;
            }),
        summary_badges: panel
            .querySelectorAll(".finding-summary .badge")
            .map(function (b) {
                return b.textContent;
            }),
        hints: panel
            .querySelectorAll(".field-hint")
            .map(function (h) {
                return h.textContent;
            }),
        text: panel.textContent
    };
}


/* Everything renders, and the shared envelope keys the
   backend guarantees are the ones this panel reads. */
check("normalized_findings", function () {
    const view = populatedView();

    const win = boot({
        payload: function () {
            return documentPayload({
                findings: view,
                analysis: {
                    quality: {
                        metrics: { laplacian_variance: 9.44 },
                        findings: [
                            {
                                code: "IMAGE_UNREADABLE",
                                severity: "ERROR",
                                message:
                                    "This image could not be " +
                                    "read.",
                                metric_name:
                                    "laplacian_variance",
                                measured_value: 9.44,
                                threshold: 40
                            }
                        ],
                        highest_severity: "ERROR",
                        error: null
                    }
                }
            });
        }
    });

    return settle().then(function () {
        const panel = findingsPanel(win);

        return {
            /* The fixture's own shape, echoed back so the
               Python suite can compare it against a real
               normalize_findings result. */
            view_keys: Object.keys(view).sort(),
            finding_keys: Object.keys(view.findings[0]).sort(),

            item_count: panel.items.length,
            block_titles: panel.block_titles,
            summary_badges: panel.summary_badges,

            /* Domain detail that must survive to the screen. */
            has_expiry_days:
                panel.text.indexOf("231 day(s) ago") !== -1,
            has_measurement:
                panel.text.indexOf(
                    "laplacian_variance measured 9.44 against " +
                        "a threshold of 40"
                ) !== -1,
            has_cited_line:
                panel.text.indexOf("Cited OCR line L9") !== -1,
            has_routing_badge:
                panel.items.some(function (item) {
                    return (
                        item.badges.indexOf(
                            "Drove the decision"
                        ) !== -1
                    );
                }),
            text: panel.text
        };
    });
});


/* Error strongest, warning quieter, ungraded detail last and
   plainest -- and no severity chip invented for a finding the
   backend left ungraded. */
check("normalized_hierarchy", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                findings: populatedView()
            });
        }
    });

    return settle().then(function () {
        const panel = findingsPanel(win);

        return {
            weights: panel.items.map(function (item) {
                if (item.is_error) {
                    return "ERROR";
                }
                if (item.is_warning) {
                    return "WARNING";
                }
                if (item.is_detail) {
                    return "DETAIL";
                }
                return "PLAIN";
            }),
            /* An ungraded finding must carry no severity
               badge. A neutral "Notice" chip would read as a
               grade the validator never gave it. */
            ungraded_badges: panel.items
                .filter(function (item) {
                    return item.is_detail;
                })
                .map(function (item) {
                    return item.badges;
                })
        };
    });
});


/* Evidence gets its own restrained section, and the panel says
   why it carries no severity. */
check("normalized_evidence_section", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                findings: populatedView()
            });
        }
    });

    return settle().then(function () {
        const panel = findingsPanel(win);

        return {
            block_titles: panel.block_titles,
            explains_ungraded:
                panel.text.indexOf(
                    "carry no severity of their own"
                ) !== -1,
            /* The evidence rows must be the last graded-free
               block before image quality, not interleaved with
               the record findings. */
            detail_positions: panel.items
                .map(function (item, index) {
                    return item.is_detail ? index : -1;
                })
                .filter(function (index) {
                    return index !== -1;
                })
        };
    });
});


/* A payload with no normalized view still renders its
   findings. This is the real case for a document with no
   analysis row, and for anything holding an older cached
   response. */
check("normalized_fallback", function () {
    const win = boot({
        payload: function () {
            return documentPayload({});
        }
    });

    return settle().then(function () {
        const panel = findingsPanel(win);

        return {
            item_count: panel.items.length,
            /* The raw anomaly issues, rendered exactly as
               before Phase 10.6. */
            titles: panel.items.map(function (item) {
                return item.title;
            }),
            /* And no weight classes, because the fallback path
               never had a normalized severity to draw. */
            weighted: panel.items.filter(function (item) {
                return item.is_error || item.is_warning;
            }).length
        };
    });
});


/* Three quality states, through the normalized path this
   time. NOT ASSESSED and ASSESSED-AND-CLEAN must stay
   distinguishable on screen, not just in the payload. */
function normalizedQualityCheck(name, quality, assessed) {
    check(name, function () {
        const win = boot({
            payload: function () {
                return documentPayload({
                    findings: normalizedView({
                        findings: [normalizedFinding({})],
                        total: 1,
                        counts: { ERROR: 1, WARNING: 0, INFO: 0 },
                        highest_severity: "ERROR",
                        categories: ["ANOMALY"],
                        quality_assessed: assessed,
                        routing_finding_count: 1
                    }),
                    analysis:
                        quality === undefined
                            ? {}
                            : { quality: quality }
                });
            }
        });

        return settle().then(function () {
            const panel = findingsPanel(win);

            return {
                block_titles: panel.block_titles,
                says_not_assessed:
                    panel.text.indexOf("Not assessed") !== -1,
                says_assessed_clean:
                    panel.text.indexOf(
                        "Assessed. No image quality"
                    ) !== -1,
                text: panel.text
            };
        });
    });
}

normalizedQualityCheck(
    "normalized_quality_not_assessed",
    null,
    false
);

normalizedQualityCheck(
    "normalized_quality_clean",
    {
        metrics: { laplacian_variance: 1820.5 },
        findings: [],
        highest_severity: null,
        error: null
    },
    true
);


finalRecordCheck("final_pending", "PENDING_REVIEW", null);
finalRecordCheck("final_rejected", "REJECTED", null);
finalRecordCheck("final_auto_accepted", "AUTO_ACCEPTED", null);
finalRecordCheck("final_approved", "APPROVED", null);
finalRecordCheck("final_corrected", "CORRECTED", {
    licence_number: "87654321",
    id_number: null
});


/* ---------- history ---------- */

check("history_timeline", function () {
    const win = boot({});

    return settle().then(function () {
        const list = node(win, "review-history-list");

        return {
            item_count: list.querySelectorAll(".timeline-item").length,
            titles: list
                .querySelectorAll(".timeline-title")
                .map(function (t) {
                    return t.textContent;
                }),
            actors: list
                .querySelectorAll(".timeline-actor")
                .map(function (t) {
                    return t.textContent;
                }),
            reason_chips: list
                .querySelectorAll(".reason-chip")
                .map(function (c) {
                    return c.textContent;
                }),
            notes: list
                .querySelectorAll(".timeline-notes")
                .map(function (n) {
                    return n.textContent;
                }),
            corrections: list
                .querySelectorAll(".timeline-correction")
                .map(function (c) {
                    return c.textContent;
                }),
            /* Not a JSON dump. */
            has_pre: list.querySelectorAll("pre").length
        };
    });
});


check("history_empty", function () {
    const win = boot({
        history: {
            document_id: "doc-workspace-1",
            event_count: 0,
            events: []
        }
    });

    return settle().then(function () {
        return {
            text: textOf(win, "review-history-list")
        };
    });
});


check("history_error_is_isolated", function () {
    const win = boot({
        historyError: {
            status: 500,
            code: "HISTORY_LOAD_FAILED",
            message: "History could not be loaded.",
            requestId: "req-hist-1"
        }
    });

    return settle().then(function () {
        return {
            /* The rest of the page still works. */
            content_visible:
                node(win, "detail-content").hidden === false,
            field_rows: fieldRows(win).length,
            history_text: textOf(win, "review-history-list"),
            retry_buttons: node(
                win,
                "review-history-list"
            ).querySelectorAll("button").length
        };
    });
});


/* ---------- raw data ---------- */

check("raw_data_is_secondary", function () {
    const win = boot({});

    return settle().then(function () {
        const rawTab = node(win, "tab-raw");
        const rawPanel = node(win, "panel-raw");
        const tabs = tabState(win);

        return {
            /* Never the landing view. */
            selected_on_load: rawTab.getAttribute("aria-selected"),
            panel_hidden_on_load: rawPanel.hidden,
            /* Last in the strip. */
            is_last_tab: tabs[tabs.length - 1].id === "tab-raw",
            first_tab: tabs[0].id,
            /* But present and populated. */
            contains_json:
                node(win, "raw-data").textContent.indexOf(
                    "\"document_id\""
                ) !== -1,
            pre_count: node(win, "raw-data").querySelectorAll("pre")
                .length
        };
    });
});


check("copy_and_download_json", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "copy-json-button").click();
            return settle(2);
        })
        .then(function () {
            const copied = win.record.copied.slice();
            const statusAfterCopy = textOf(win, "workspace-status");

            /* Counted BEFORE the download, because the source
               image already holds one live object URL. That one
               is legitimately alive: the image is on screen. */
            const before = {
                created: win.record.objectUrls.created.length,
                revoked: win.record.objectUrls.revoked.length
            };

            node(win, "download-json-button").click();

            const after = {
                created: win.record.objectUrls.created.length,
                revoked: win.record.objectUrls.revoked.length
            };

            /* Unload should release the image URL too. */
            win.fireWindowEvent("beforeunload");

            return {
                copied_count: copied.length,
                copied_is_json:
                    copied.length > 0 &&
                    copied[0].indexOf("\"document_id\"") !== -1,
                status_after_copy: statusAfterCopy,
                status_after_download: textOf(
                    win,
                    "workspace-status"
                ),
                download_created: after.created - before.created,
                download_revoked: after.revoked - before.revoked,
                image_url_live_before_unload:
                    before.created - before.revoked,
                all_revoked_after_unload:
                    win.record.objectUrls.created.every(function (
                        entry
                    ) {
                        return (
                            win.record.objectUrls.revoked.indexOf(
                                entry.url
                            ) !== -1
                        );
                    })
            };
        });
});


/* ---------- human review states ---------- */

check("review_actionable", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            form_visible: node(win, "human-review-form").hidden === false,
            completed_hidden: node(
                win,
                "completed-review-summary"
            ).hidden,
            locked_hidden: node(win, "review-locked-message").hidden,
            reviewer_section_visible:
                node(win, "authenticated-reviewer-section")
                    .hidden === false,
            reviewer_name: textOf(win, "authenticated-reviewer-name"),
            reviewer_role: textOf(win, "authenticated-reviewer-role"),
            reviewer_source: textOf(
                win,
                "authenticated-reviewer-source"
            ),
            reviewer_access: textOf(
                win,
                "authenticated-reviewer-access"
            ),
            card_classes: node(win, "authenticated-reviewer-card")
                .className,
            buttons: {
                approve: node(win, "approve-button").hidden,
                correct: node(win, "correct-button").hidden,
                reject: node(win, "reject-button").hidden,
                submit_correction: node(
                    win,
                    "submit-correction-button"
                ).hidden
            },
            shell_reviewer: textOf(win, "shell-reviewer-name")
        };
    });
});


check("review_read_only", function () {
    const win = boot({ reviewer: { can_review: false } });

    return settle().then(function () {
        return {
            form_hidden: node(win, "human-review-form").hidden,
            locked_visible:
                node(win, "review-locked-message").hidden === false,
            locked_text: textOf(win, "review-locked-message"),
            card_classes: node(win, "authenticated-reviewer-card")
                .className,
            access_text: textOf(win, "authenticated-reviewer-access")
        };
    });
});


check("review_unauthenticated", function () {
    const win = boot({
        reviewerError: {
            status: 401,
            code: "REVIEWER_AUTHENTICATION_REQUIRED",
            message: "Reviewer authentication is required.",
            requestId: "req-auth",
            isAuthError: function () {
                return true;
            }
        }
    });

    return settle().then(function () {
        return {
            form_hidden: node(win, "human-review-form").hidden,
            locked_visible:
                node(win, "review-locked-message").hidden === false,
            locked_text: textOf(win, "review-locked-message"),
            reviewer_error_visible:
                node(win, "authenticated-reviewer-error").hidden ===
                false,
            reviewer_error_text: textOf(
                win,
                "authenticated-reviewer-error"
            ),
            card_classes: node(win, "authenticated-reviewer-card")
                .className,
            /* The document itself still renders. */
            field_rows: fieldRows(win).length
        };
    });
});


check("review_completed_is_locked", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                finalRecord: finalRecord("CORRECTED", {
                    licence_number: "87654321"
                }),
                humanReview: {
                    human_action: "CORRECT",
                    reviewer_id: "reviewer-7",
                    reviewed_at: "2026-08-02T11:00:00",
                    notes: "Licence number was misread.",
                    corrections: { licence_number: "87654321" }
                }
            });
        }
    });

    return settle().then(function () {
        return {
            completed_visible:
                node(win, "completed-review-summary").hidden === false,
            form_hidden: node(win, "human-review-form").hidden,
            locked_hidden: node(win, "review-locked-message").hidden,
            reviewer_section_hidden: node(
                win,
                "authenticated-reviewer-section"
            ).hidden,
            action: textOf(win, "completed-review-action"),
            reviewer: textOf(win, "completed-reviewer"),
            reviewed_at: textOf(win, "completed-reviewed-at"),
            notes: textOf(win, "completed-review-notes"),
            corrections_text: textOf(
                win,
                "completed-review-corrections"
            ),
            /* The machine reading is preserved beside the
               correction. */
            correction_rows: valueRows(
                win,
                "completed-review-corrections"
            )
        };
    });
});


check("review_auto_accepted_is_locked", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                finalRecord: finalRecord("AUTO_ACCEPTED", null)
            });
        }
    });

    return settle().then(function () {
        return {
            form_hidden: node(win, "human-review-form").hidden,
            completed_hidden: node(
                win,
                "completed-review-summary"
            ).hidden,
            locked_visible:
                node(win, "review-locked-message").hidden === false,
            locked_text: textOf(win, "review-locked-message")
        };
    });
});


/* ---------- approve ---------- */

check("approve_flow", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "approve-button").click();
            return settle(2);
        })
        .then(function () {
            const dialog = node(win, "confirm-dialog");

            const dialogState = {
                open: dialog.open,
                title: textOf(win, "confirm-title"),
                body: textOf(win, "confirm-body"),
                accept_label: textOf(win, "confirm-accept"),
                accept_class: node(win, "confirm-accept").className,
                /* Cancel is focused first, so a stray Enter
                   cannot record a decision. */
                focused: win.document.activeElement
                    ? win.document.activeElement.id
                    : null,
                submissions_before: win.calls.submissions.length
            };

            node(win, "confirm-accept").click();

            return settle(6).then(function () {
                return {
                    dialog: dialogState,
                    dialog_still_open: dialog.open,
                    submissions: win.calls.submissions,
                    /* The reload proves what was stored. */
                    document_reads: win.calls.document,
                    message: textOf(win, "review-message"),
                    focus_returned: win.document.activeElement
                        ? win.document.activeElement.id
                        : null
                };
            });
        });
});


check("approve_cancel_submits_nothing", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "approve-button").click();
            return settle(2);
        })
        .then(function () {
            node(win, "confirm-cancel").click();
            return settle(3);
        })
        .then(function () {
            return {
                submissions: win.calls.submissions.length,
                dialog_open: node(win, "confirm-dialog").open,
                document_reads: win.calls.document,
                focus_returned: win.document.activeElement
                    ? win.document.activeElement.id
                    : null
            };
        });
});


check("payload_has_no_reviewer_id", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "review-notes").value = "Looks right to me.";
            node(win, "approve-button").click();
            return settle(2);
        })
        .then(function () {
            node(win, "confirm-accept").click();
            return settle(6);
        })
        .then(function () {
            const submission = win.calls.submissions[0];
            return {
                keys: submission.keys,
                payload: submission.payload,
                has_reviewer_id:
                    submission.keys.indexOf("reviewer_id") !== -1,
                notes: submission.payload.notes,
                action: submission.payload.action
            };
        });
});


check("duplicate_submission_blocked", function () {
    let release = null;

    const win = boot({});

    /* Hold the submission open so the extra clicks land while
       the first is still in flight. */
    return settle()
        .then(function () {
            win.VigiloxApi.endpoints.submitReview = function (
                documentId,
                payload
            ) {
                win.calls.submissions.push({
                    documentId: documentId,
                    payload: payload,
                    keys: Object.keys(payload)
                });
                return new Promise(function (resolve) {
                    release = resolve;
                });
            };

            node(win, "approve-button").click();
            return settle(2);
        })
        .then(function () {
            node(win, "confirm-accept").click();
            return settle(2);
        })
        .then(function () {
            const duringFlight = {
                submissions: win.calls.submissions.length,
                approve_disabled: node(win, "approve-button").disabled,
                reject_disabled: node(win, "reject-button").disabled,
                correct_disabled: node(win, "correct-button").disabled,
                notes_disabled: node(win, "review-notes").disabled,
                panel_busy: node(
                    win,
                    "human-review-panel"
                ).getAttribute("aria-busy")
            };

            /* Three more attempts while the first is open. */
            node(win, "approve-button").click();
            node(win, "reject-button").click();
            node(win, "approve-button").click();

            return settle(3).then(function () {
                return {
                    during_flight: duringFlight,
                    total_submissions: win.calls.submissions.length
                };
            });
        });
});


/* ---------- correct ---------- */

check("correction_flow", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "correct-button").click();
            return settle(2);
        })
        .then(function () {
            const panel = node(win, "correction-panel");
            const inputs = node(
                win,
                "correction-fields"
            ).querySelectorAll(".correction-input");

            const opened = {
                panel_visible: panel.hidden === false,
                input_count: inputs.length,
                field_names: inputs.map(function (input) {
                    return input.getAttribute("data-field-name");
                }),
                /* The machine reading stays visible beside each
                   input. */
                machine_values: node(win, "correction-fields")
                    .querySelectorAll(".correction-machine-text")
                    .map(function (n) {
                        return n.textContent;
                    }),
                prefilled: inputs.map(function (input) {
                    return input.value;
                }),
                approve_hidden: node(win, "approve-button").hidden,
                submit_visible:
                    node(win, "submit-correction-button").hidden ===
                    false,
                focused: win.document.activeElement
                    ? win.document.activeElement.id
                    : null
            };

            /* Change one value and clear another. */
            inputs.filter(function (input) {
                return (
                    input.getAttribute("data-field-name") ===
                    "licence_number"
                );
            })[0].value = "87654321";

            inputs.filter(function (input) {
                return (
                    input.getAttribute("data-field-name") ===
                    "issuer"
                );
            })[0].value = "";

            node(win, "submit-correction-button").click();

            return settle(2).then(function () {
                return { opened: opened };
            });
        })
        .then(function (carry) {
            const dialogTitle = textOf(win, "confirm-title");

            node(win, "confirm-accept").click();

            return settle(6).then(function () {
                carry.dialog_title = dialogTitle;
                carry.submissions = win.calls.submissions;
                carry.message = textOf(win, "review-message");
                return carry;
            });
        });
});


check("correction_requires_a_change", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "correct-button").click();
            return settle(2);
        })
        .then(function () {
            /* Submit with nothing edited. */
            node(win, "submit-correction-button").click();
            return settle(3);
        })
        .then(function () {
            return {
                submissions: win.calls.submissions.length,
                dialog_open: node(win, "confirm-dialog").open,
                message: textOf(win, "review-message")
            };
        });
});


check("correction_cancel_restores_actions", function () {
    const win = boot({});

    return settle()
        .then(function () {
            node(win, "correct-button").click();
            return settle(2);
        })
        .then(function () {
            node(win, "cancel-correction-button").click();
            return settle(2);
        })
        .then(function () {
            return {
                panel_hidden: node(win, "correction-panel").hidden,
                input_count: node(
                    win,
                    "correction-fields"
                ).querySelectorAll(".correction-input").length,
                approve_visible:
                    node(win, "approve-button").hidden === false,
                submit_hidden: node(win, "submit-correction-button")
                    .hidden,
                submissions: win.calls.submissions.length,
                focused: win.document.activeElement
                    ? win.document.activeElement.id
                    : null
            };
        });
});


check("read_only_reviewer_cannot_open_corrections", function () {
    const win = boot({ reviewer: { can_review: false } });

    return settle()
        .then(function () {
            /* The button is not rendered, so call the module
               directly: a hidden control must not be the only
               thing standing between a read-only user and a
               submit path. */
            const opened =
                win.VigiloxReviewActions.openCorrectionMode();

            return settle(2).then(function () {
                return opened;
            });
        })
        .then(function (opened) {
            return {
                opened: opened,
                panel_hidden: node(win, "correction-panel").hidden,
                message: textOf(win, "review-message")
            };
        });
});


check("read_only_reviewer_cannot_submit", function () {
    const win = boot({ reviewer: { can_review: false } });

    return settle()
        .then(function () {
            return win.VigiloxReviewActions.submitReview(
                "APPROVE",
                null
            );
        })
        .then(function () {
            return settle(3);
        })
        .then(function () {
            return {
                submissions: win.calls.submissions.length,
                dialog_open: node(win, "confirm-dialog").open,
                message: textOf(win, "review-message")
            };
        });
});


/* ---------- submission errors ---------- */

function submitErrorCheck(name, error, expectations) {
    check(name, function () {
        const win = boot({ submitError: error });

        return settle()
            .then(function () {
                node(win, "approve-button").click();
                return settle(2);
            })
            .then(function () {
                node(win, "confirm-accept").click();
                return settle(8);
            })
            .then(function () {
                return {
                    message: textOf(win, "review-message"),
                    document_reads: win.calls.document,
                    reviewer_reads: win.calls.reviewer,
                    submissions: win.calls.submissions.length,
                    approve_enabled:
                        node(win, "approve-button").disabled === false,
                    expectations: expectations || null
                };
            });
    });
}

submitErrorCheck(
    "error_already_reviewed",
    {
        status: 409,
        code: "DOCUMENT_ALREADY_REVIEWED",
        message: "This document already has a human review.",
        requestId: "req-409"
    }
);

submitErrorCheck(
    "error_invalid_review",
    {
        status: 400,
        code: "INVALID_HUMAN_REVIEW",
        message: "The review payload was rejected.",
        requestId: "req-400"
    }
);

submitErrorCheck(
    "error_not_authorized",
    {
        status: 403,
        code: "REVIEWER_NOT_AUTHORIZED",
        message: "This reviewer is not authorized.",
        requestId: "req-403"
    }
);

submitErrorCheck(
    "error_authentication_required",
    {
        status: 401,
        code: "REVIEWER_AUTHENTICATION_REQUIRED",
        message: "Reviewer authentication is required.",
        requestId: "req-401"
    }
);

submitErrorCheck(
    "error_unknown_code",
    {
        status: 500,
        code: "SOMETHING_UNEXPECTED",
        message: "An internal server error occurred.",
        requestId: "req-500"
    }
);


/* ---------- document load failure ---------- */

check("document_load_error", function () {
    const win = boot({
        documentError: {
            status: 404,
            code: "DOCUMENT_NOT_FOUND",
            message: "Document not found.",
            requestId: "req-404"
        }
    });

    return settle().then(function () {
        const panel = node(win, "detail-error");
        const text = panel.textContent;

        return {
            error_visible: panel.hidden === false,
            content_hidden: node(win, "detail-content").hidden,
            loading_hidden: node(win, "detail-loading").hidden,
            shows_code: text.indexOf("DOCUMENT_NOT_FOUND") !== -1,
            shows_message: text.indexOf("Document not found.") !== -1,
            shows_request_id: text.indexOf("req-404") !== -1,
            mentions_traceback:
                text.toLowerCase().indexOf("traceback") !== -1,
            retry_buttons: panel.querySelectorAll("button").length
        };
    });
});


check("document_without_analysis", function () {
    const win = boot({
        payload: function () {
            return documentPayload({
                analysis: null,
                finalRecord: null,
                document: { processing_status: "FAILED" }
            });
        }
    });

    return settle().then(function () {
        return {
            content_visible:
                node(win, "detail-content").hidden === false,
            fields_text: textOf(win, "extraction-fields"),
            validation_text: textOf(win, "validation-content"),
            findings_text: textOf(win, "anomaly-list"),
            final_text: textOf(win, "final-record"),
            locked_text: textOf(win, "review-locked-message")
        };
    });
});


/* ---------- safety ---------- */

check("hostile_content_is_text", function () {
    const hostileName = '<img src=x onerror="alert(1)">.jpg';
    const hostileOcr = "<script>alert(2)</script>";
    const hostileNotes = "<b>bold</b> reviewer note";
    const hostileValue = '<svg onload="alert(3)">';

    const win = boot({
        payload: function () {
            const payload = documentPayload({
                document: { original_filename: hostileName },
                finalRecord: finalRecord("CORRECTED", {
                    full_name: hostileValue
                }),
                humanReview: {
                    human_action: "CORRECT",
                    reviewer_id: "<i>reviewer</i>",
                    reviewed_at: "2026-08-02T11:00:00",
                    notes: hostileNotes,
                    corrections: { full_name: hostileValue }
                }
            });

            payload.analysis.ocr_lines = [
                {
                    line_id: "L0",
                    text: hostileOcr,
                    confidence: 0.9,
                    bbox: [10, 10, 100, 40]
                }
            ];

            payload.analysis.extraction.full_name = {
                value: hostileValue,
                source_line_ids: ["L0"]
            };

            return payload;
        },
        history: historyPayload({
            events: [
                {
                    audit_id: "a1",
                    document_id: "doc-workspace-1",
                    event_type: "HUMAN_REVIEW",
                    actor_type: "HUMAN",
                    actor_id: "<i>reviewer</i>",
                    details: {
                        human_action: "CORRECT",
                        notes: hostileNotes,
                        corrections: { full_name: hostileValue }
                    },
                    created_at: "2026-08-02T11:00:00"
                }
            ]
        })
    });

    return settle().then(function () {
        const body = node(win, "detail-content");
        const text = body.textContent;

        return {
            filename_literal: text.indexOf(hostileName) !== -1,
            ocr_literal: text.indexOf(hostileOcr) !== -1,
            notes_literal: text.indexOf(hostileNotes) !== -1,
            value_literal: text.indexOf(hostileValue) !== -1,
            /* No element was created from any of it.

               The page's own source-document <img> is excluded
               by id: it is declared in the shipped HTML, not
               produced from document content. Counting it here
               would have flagged a legitimate element. */
            img_elements: body
                .querySelectorAll("img")
                .filter(function (image) {
                    return image.id !== "original-document-image";
                }).length,
            script_elements: body.querySelectorAll("script").length,
            svg_elements: body.querySelectorAll("svg").length,
            b_elements: body.querySelectorAll("b").length,
            i_elements: body.querySelectorAll("i").length
        };
    });
});


check("no_reviewer_identity_input", function () {
    const win = boot({});

    return settle().then(function () {
        const body = node(win, "detail-content");

        /* Every input on the page, and what it is for. */
        const inputs = body
            .querySelectorAll("input")
            .map(function (input) {
                return {
                    id: input.id,
                    type: input.getAttribute("type")
                };
            });

        return {
            inputs: inputs,
            /* The legacy editable reviewer id must not exist. */
            has_reviewer_id_input: Boolean(
                win.document.getElementById("reviewer-id")
            ),
            textareas: body
                .querySelectorAll("textarea")
                .map(function (t) {
                    return t.id;
                })
        };
    });
});


check("document_id_from_path", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            id: win.VigiloxWorkspace.getDocumentId(),
            submitted_to: win.calls.submissions.length
                ? win.calls.submissions[0].documentId
                : null
        };
    });
});


/* ==========================================================
   OUTPUT
   ========================================================== */

Promise.all(jobs).then(function () {
    process.stdout.write(JSON.stringify(results, null, 1));
});
