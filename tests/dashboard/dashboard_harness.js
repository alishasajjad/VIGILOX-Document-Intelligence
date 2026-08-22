/* ==========================================================
   VIGILOX DASHBOARD HARNESS
   PHASE 8.6B
   ==========================================================

   Executes frontend/static/js/dashboard_page.js under Node
   against the shared DOM stub, so the Dashboard behaviour is
   RUN rather than pattern-matched.

   The element ids come from the shipped dashboard.html, so a
   renamed id fails the test instead of quietly rendering into
   nothing.

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");


/* ==========================================================
   FIXTURE
   ==========================================================
   Shaped exactly like GET /api/v1/dashboard/summary. Distinct
   values per field so a mis-wired card is visible rather than
   coincidentally right.
   ========================================================== */

function summaryFixture(overrides) {
    return Object.assign(
        {
            status: "success",
            total_documents: 41,
            review: {
                pending_review: 7,
                auto_accepted: 12,
                review_required: 19,
                approved: 5,
                corrected: 3,
                rejected: 2
            },
            expiry: {
                expired: 6,
                expires_today: 1,
                expiring_soon: 4,
                active: 27,
                not_available: 3
            },
            pending_review_priority: {
                high: 4,
                medium: 2,
                low: 1
            },
            recent_documents: [
                {
                    document_id: "doc-aaa",
                    filename: "guard_front.jpg",
                    document_type: "guard_license",
                    processing_status: "PROCESSED",
                    machine_decision: "REVIEW_REQUIRED",
                    priority: "HIGH",
                    final_state: "PENDING_REVIEW",
                    expiry_status: "EXPIRED",
                    expiry_date: "2024-01-01",
                    created_at: "2026-08-01T09:15:00",
                    processed_at: "2026-08-01T09:15:20"
                },
                {
                    document_id: "doc-bbb",
                    filename: "badge.png",
                    document_type: "sia_badge",
                    processing_status: "PROCESSED",
                    machine_decision: "AUTO_ACCEPT",
                    priority: "NONE",
                    final_state: "AUTO_ACCEPTED",
                    expiry_status: "ACTIVE",
                    expiry_date: "2029-05-05",
                    created_at: "2026-08-02T10:00:00",
                    processed_at: "2026-08-02T10:00:30"
                }
            ]
        },
        overrides || {}
    );
}


/* ==========================================================
   BOOT
   ========================================================== */

/*
   Counters live on the window, not on the module.

   Checks are started together and their promise callbacks
   interleave, so a module-level counter would attribute one
   boot's requests to another and every "exactly one request"
   claim would be meaningless. This was a real defect in the
   first version of this harness.
*/

function boot(behaviour) {
    const calls = { summary: 0, documents: 0, health: 0, reviewer: 0 };

    const win = stub.createWindow({
        pathname: "/dashboard",
    });

    /* The real shipped page, parsed into a real element
       tree. A renamed id or a moved element breaks the
       test rather than being papered over. */
    stub.loadPage(win, "dashboard.html");

    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");

    const endpoints = win.VigiloxApi.endpoints;

    endpoints.getDashboardSummary = function () {
        calls.summary += 1;
        return behaviour.summary(calls.summary);
    };

    /* Present so the test can prove the Dashboard does NOT
       call it. Every recent row comes from the summary. */
    endpoints.getDocuments = function () {
        calls.documents += 1;
        return Promise.resolve({ items: [], total: 0 });
    };

    endpoints.getHealth = function () {
        calls.health += 1;
        return Promise.resolve({ status: "ok" });
    };

    endpoints.getReviewerIdentity = function () {
        calls.reviewer += 1;
        return Promise.resolve({
            reviewer: {
                reviewer_id: "harness",
                role: "REVIEWER",
                source: "LOCAL_ENV",
                can_review: true
            }
        });
    };

    stub.loadScript(win, "js/dashboard_page.js");
    win.document.ready();

    win.calls = calls;

    return win;
}


function resolved(payload) {
    return {
        summary: function () {
            return Promise.resolve(payload);
        }
    };
}

function rejected(error) {
    return {
        summary: function () {
            return Promise.reject(error);
        }
    };
}

function pending() {
    return {
        summary: function () {
            return new Promise(function () {});
        }
    };
}


/* Let queued promise callbacks run. */
function settle() {
    return new Promise(function (resolve) {
        setImmediate(function () {
            setImmediate(resolve);
        });
    });
}


/* ==========================================================
   INSPECTION HELPERS
   ========================================================== */

function textOf(win, id) {
    const node = win.document.getElementById(id);
    return node ? node.textContent : null;
}

function hrefsIn(win, id) {
    const node = win.document.getElementById(id);
    if (!node) {
        return [];
    }
    return node.querySelectorAll("a").map(function (a) {
        return a.getAttribute("href");
    });
}

function statCards(win, id) {
    const node = win.document.getElementById(id);
    if (!node) {
        return [];
    }
    return node.querySelectorAll(".stat-card").map(function (card) {
        const label = card.querySelector(".stat-label");
        const value = card.querySelector(".stat-value");
        const hint = card.querySelector(".stat-hint");
        return {
            label: label ? label.textContent : null,
            value: value ? value.textContent : null,
            hint: hint ? hint.textContent : null,
            modifiers: {
                attention: card.classList.contains("is-attention"),
                critical: card.classList.contains("is-critical")
            }
        };
    });
}

function metricRows(win, id) {
    const node = win.document.getElementById(id);
    if (!node) {
        return [];
    }
    return node.querySelectorAll(".metric-row").map(function (row) {
        const label = row.querySelector(".metric-row-label");
        const value = row.querySelector(".metric-row-value");
        return {
            label: label ? label.textContent.trim() : null,
            value: value ? value.textContent : null
        };
    });
}


/* ==========================================================
   CHECKS
   ========================================================== */

const results = {};
const queue = [];

function check(name, fn) {
    queue.push(
        Promise.resolve()
            .then(fn)
            .then(
                function (value) {
                    results[name] = value;
                },
                function (error) {
                    results[name] = {
                        error: String((error && error.message) || error)
                    };
                }
            )
    );
}


/* ---------- module surface ---------- */

check("module_surface", function () {
    const win = boot(pending());
    const mod = win.VigiloxDashboard;

    return {
        exposed: Boolean(mod),
        expiry_statuses: mod.EXPIRY_ROWS.map(function (r) {
            return r.status;
        }),
        expiry_keys: mod.EXPIRY_ROWS.map(function (r) {
            return r.key;
        }),
        priorities: mod.PRIORITY_ROWS.map(function (r) {
            return r.priority;
        })
    };
});


/* ---------- exactly one summary request, no documents call ---------- */

check("single_request", function () {
    const win = boot(resolved(summaryFixture()));

    return settle().then(function () {
        return {
            summary_calls: win.calls.summary,
            documents_calls: win.calls.documents,
            intervals_started: win.record.intervals.length
        };
    });
});


/* ---------- loading shows skeletons, never zeros ---------- */

check("loading_state", function () {
    const win = boot(pending());
    const loading = win.document.getElementById("dashboard-loading");

    return {
        loading_visible: loading.hidden === false,
        body_hidden: win.document.getElementById("dashboard-body").hidden,
        error_hidden: win.document.getElementById("dashboard-error").hidden,
        empty_hidden: win.document.getElementById("dashboard-empty").hidden,
        skeleton_count: loading.querySelectorAll(".skeleton").length,
        /* No figure may be shown while loading. A zero here
           would read as "nothing pending". */
        loading_text: loading.textContent.replace(/\s+/g, ""),
        refresh_disabled:
            win.document.getElementById("refresh-button").disabled
    };
});


/* ---------- success render ---------- */

check("success_render", function () {
    const win = boot(resolved(summaryFixture()));

    return settle().then(function () {
        return {
            body_visible:
                win.document.getElementById("dashboard-body").hidden === false,
            loading_hidden:
                win.document.getElementById("dashboard-loading").hidden,
            primary_cards: statCards(win, "primary-summary"),
            outcome_cards: statCards(win, "review-outcomes"),
            expiry_rows: metricRows(win, "expiry-breakdown"),
            attention_hidden: win.document.getElementById(
                "review-attention-section"
            ).hidden,
            attention_rows: metricRows(win, "review-attention"),
            recent_row_count: win.document
                .getElementById("recent-documents")
                .querySelectorAll("tbody tr").length,
            recent_hrefs: hrefsIn(win, "recent-documents"),
            refresh_enabled:
                win.document.getElementById("refresh-button").disabled === false
        };
    });
});


/* ---------- attention section hides when nothing is pending ---------- */

check("no_pending_hides_attention", function () {
    const win = boot(
        resolved(
            summaryFixture({
                review: {
                    pending_review: 0,
                    auto_accepted: 12,
                    review_required: 10,
                    approved: 5,
                    corrected: 3,
                    rejected: 2
                }
            })
        )
    );

    return settle().then(function () {
        return {
            attention_hidden: win.document.getElementById(
                "review-attention-section"
            ).hidden,
            attention_empty:
                win.document.getElementById("review-attention")
                    .childElementCount === 0,
            pending_card_attention: statCards(win, "primary-summary")[1]
                .modifiers.attention
        };
    });
});


/* ---------- empty database ---------- */

check("empty_state", function () {
    const win = boot(
        resolved(
            summaryFixture({
                total_documents: 0,
                recent_documents: []
            })
        )
    );

    return settle().then(function () {
        const empty = win.document.getElementById("dashboard-empty");
        return {
            empty_visible: empty.hidden === false,
            body_hidden: win.document.getElementById("dashboard-body").hidden,
            has_upload_cta: empty
                .querySelectorAll("a")
                .some(function (a) {
                    return a.getAttribute("href") === "/upload";
                }),
            /* No zero-filled cards behind the empty state. */
            primary_cards: statCards(win, "primary-summary").length
        };
    });
});


/* ---------- structured error + retry ---------- */

check("error_state", function () {
    const failure = {
        status: 500,
        code: "DASHBOARD_SUMMARY_LOAD_FAILED",
        message: "Failed to load dashboard summary.",
        requestId: "req-9f2c",
        isNetworkError: false
    };

    const win = boot(rejected(failure));

    return settle().then(function () {
        const panel = win.document.getElementById("dashboard-error");
        const text = panel.textContent;

        return {
            error_visible: panel.hidden === false,
            body_hidden: win.document.getElementById("dashboard-body").hidden,
            loading_hidden:
                win.document.getElementById("dashboard-loading").hidden,
            shows_code: text.indexOf("DASHBOARD_SUMMARY_LOAD_FAILED") !== -1,
            shows_message:
                text.indexOf("Failed to load dashboard summary.") !== -1,
            shows_request_id: text.indexOf("req-9f2c") !== -1,
            has_retry: panel.querySelectorAll("button").length,
            /* Never a stack trace: the API does not return one
               and the UI must not imply it does. */
            mentions_traceback:
                text.toLowerCase().indexOf("traceback") !== -1
        };
    });
});


check("retry_recovers", function () {
    let attempt = 0;

    const win = boot({
        summary: function () {
            attempt += 1;
            if (attempt === 1) {
                return Promise.reject({
                    status: 503,
                    code: "SERVICE_UNAVAILABLE",
                    message: "Temporarily unavailable.",
                    requestId: "req-1"
                });
            }
            return Promise.resolve(summaryFixture());
        }
    });

    return settle()
        .then(function () {
            const button = win.document
                .getElementById("dashboard-error")
                .querySelector("button");
            button.click();
            return settle();
        })
        .then(function () {
            return {
                attempts: attempt,
                body_visible:
                    win.document.getElementById("dashboard-body").hidden ===
                    false,
                error_hidden:
                    win.document.getElementById("dashboard-error").hidden
            };
        });
});


/* ---------- concurrent refresh is collapsed to one request ---------- */

check("concurrent_refresh_guard", function () {
    const win = boot(pending());
    const refresh = win.document.getElementById("refresh-button");

    refresh.click();
    refresh.click();
    refresh.click();
    refresh.click();

    return {
        /* One from init; the four clicks all land while the
           first read is still in flight. */
        summary_calls: win.calls.summary
    };
});


/* ---------- retry cannot double-fire ---------- */

check("retry_double_click_guard", function () {
    const win = boot(
        rejected({
            status: 500,
            code: "X",
            message: "y",
            requestId: "r"
        })
    );

    return settle().then(function () {
        const before = win.calls.summary;
        const button = win.document
            .getElementById("dashboard-error")
            .querySelector("button");

        /* The first click leaves the module loading, so the
           next three are dropped. */
        button.click();
        button.click();
        button.click();
        button.click();

        return {
            calls_before: before,
            calls_after: win.calls.summary
        };
    });
});


/* ---------- a recent row without an id must not link ---------- */

check("missing_document_id_is_safe", function () {
    const win = boot(
        resolved(
            summaryFixture({
                recent_documents: [
                    {
                        filename: "orphan.jpg",
                        document_type: "id_card",
                        final_state: "PENDING_REVIEW",
                        expiry_status: "NOT_AVAILABLE",
                        created_at: "2026-08-05T08:00:00"
                    }
                ]
            })
        )
    );

    return settle().then(function () {
        const hrefs = hrefsIn(win, "recent-documents");
        return {
            hrefs: hrefs,
            builds_undefined_link: hrefs.some(function (href) {
                return (
                    href.indexOf("undefined") !== -1 ||
                    href.indexOf("null") !== -1
                );
            }),
            row_text: win.document
                .getElementById("recent-documents")
                .textContent
        };
    });
});


/* ---------- document ids are encoded into the link ---------- */

check("document_id_encoded", function () {
    const win = boot(
        resolved(
            summaryFixture({
                recent_documents: [
                    {
                        document_id: "a/b?c=1&d",
                        filename: "weird.jpg",
                        document_type: "id_card",
                        final_state: "APPROVED",
                        expiry_status: "ACTIVE",
                        created_at: "2026-08-05T08:00:00"
                    }
                ]
            })
        )
    );

    return settle().then(function () {
        return { hrefs: hrefsIn(win, "recent-documents") };
    });
});


/* ---------- untrusted filename is rendered as text ---------- */

check("filename_is_text_not_markup", function () {
    const hostile = '<img src=x onerror="alert(1)">.jpg';

    const win = boot(
        resolved(
            summaryFixture({
                recent_documents: [
                    {
                        document_id: "doc-x",
                        filename: hostile,
                        document_type: "guard_license",
                        final_state: "APPROVED",
                        expiry_status: "ACTIVE",
                        created_at: "2026-08-05T08:00:00"
                    }
                ]
            })
        )
    );

    return settle().then(function () {
        const container = win.document.getElementById("recent-documents");
        return {
            /* The literal characters survive as text ... */
            renders_literally:
                container.textContent.indexOf(hostile) !== -1,
            /* ... and no element was created from them. */
            img_elements: container.querySelectorAll("img").length
        };
    });
});


/* ---------- no extracted identity data on the dashboard ---------- */

check("no_personal_data_rendered", function () {
    const win = boot(
        resolved(
            summaryFixture({
                recent_documents: [
                    {
                        document_id: "doc-p",
                        filename: "licence.jpg",
                        document_type: "guard_license",
                        final_state: "APPROVED",
                        expiry_status: "ACTIVE",
                        expiry_date: "2029-01-01",
                        created_at: "2026-08-05T08:00:00",
                        /* Fields the API does not send for a
                           summary row. If the renderer ever
                           started echoing unknown keys these
                           would appear. */
                        full_name: "SAMPLE,JANE",
                        id_number: "12345678",
                        licence_number: "GL-99887766"
                    }
                ]
            })
        )
    );

    return settle().then(function () {
        const text = win.document.getElementById("dashboard-body").textContent;
        return {
            leaks_name: text.indexOf("SAMPLE,JANE") !== -1,
            leaks_id_number: text.indexOf("12345678") !== -1,
            leaks_licence: text.indexOf("GL-99887766") !== -1
        };
    });
});


/* ---------- expiry vocabulary ---------- */

check("expiry_labels", function () {
    const win = boot(resolved(summaryFixture()));

    return settle().then(function () {
        const node = win.document.getElementById("expiry-breakdown");
        return {
            badge_labels: node
                .querySelectorAll(".badge")
                .map(function (b) {
                    return b.textContent;
                }),
            badge_classes: node
                .querySelectorAll(".badge")
                .map(function (b) {
                    return b.className;
                })
        };
    });
});


/* ---------- no invented statistics anywhere on the page ---------- */

check("no_invented_metrics", function () {
    const win = boot(resolved(summaryFixture()));

    return settle().then(function () {
        const text = win.document
            .getElementById("dashboard-body")
            .textContent.toLowerCase();

        const banned = [
            "accuracy",
            "average confidence",
            "risk score",
            "sla",
            "automation rate",
            "time saved",
            "throughput",
            "model score"
        ];

        return {
            found: banned.filter(function (word) {
                return text.indexOf(word) !== -1;
            }),
            /* No percentage figure: the dashboard reports
               counts, and there is no authoritative rate. */
            has_percent_figure: /\d\s*%/.test(text)
        };
    });
});


/* ---------- shell wiring ---------- */

check("shell_wiring", function () {
    const win = boot(resolved(summaryFixture()));

    return settle().then(function () {
        return {
            reviewer_calls: win.calls.reviewer,
            health_calls: win.calls.health
        };
    });
});


/* ==========================================================
   OUTPUT
   ========================================================== */

Promise.all(queue).then(function () {
    process.stdout.write(JSON.stringify(results, null, 1));
});
