/* ==========================================================
   VIGILOX REVIEW QUEUE
   PHASE 8.9
   ==========================================================

   Owns GET /review.

   THE FILENAME
   ----------------------------------------------------------
   This file keeps the name dashboard.js from Phase 7B. It is
   the Review Queue, not the Dashboard: the Dashboard at
   /dashboard is owned by js/dashboard_page.js. The name is
   retained because browsers have it cached and existing tests
   fetch it by URL; renaming it would break both for no gain.


   WHAT CHANGED IN PHASE 8.9
   ----------------------------------------------------------
   Rewritten onto the Phase 8 design system and the shared API
   client.

       innerHTML string templates    -> safe node building
       raw fetch + `detail` errors   -> shared client and the
                                        structured contract
       bare reason codes             -> readable reasons from
                                        the shared vocabulary
       hand-built escapeHtml         -> gone; textContent does
                                        not need escaping


   THE SERVER DECIDES URGENCY
   ----------------------------------------------------------
   ReviewQueueRepository orders the queue HIGH, MEDIUM, LOW and
   excludes anything already reviewed. Priority comes from
   ReviewDecisionService. Neither is recalculated here, and the
   rows are rendered in the order they arrived.

   The queue API returns the whole filtered set in one bounded
   response and supports no paging, search or sorting. So this
   screen offers none: a sort control over a single response
   that claimed to order the whole dataset would be a lie.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* Mirrors ALLOWED_REVIEW_PRIORITIES. */
    var PRIORITIES = ["HIGH", "MEDIUM", "LOW"];

    /* Mirrors ALLOWED_DOCUMENT_TYPES. */
    var DOCUMENT_TYPES = ["guard_license", "sia_badge", "id_card"];

    /* How many reason chips a row shows before collapsing the
       rest into a count. A row with eleven reasons is not more
       informative than one with three and a "+8". */
    var VISIBLE_REASONS = 3;


    var state = {
        priority: "",
        documentType: ""
    };

    var loading = false;
    var lastResult = null;


    var nodes = {};

    function collectNodes() {
        nodes = {
            summary: ui.byId("queue-summary"),
            form: ui.byId("queue-filter-form"),
            priority: ui.byId("priority-filter"),
            documentType: ui.byId("document-type-filter"),
            reset: ui.byId("reset-filters-button"),
            refresh: ui.byId("refresh-button"),
            status: ui.byId("queue-status"),
            loading: ui.byId("queue-loading"),
            error: ui.byId("queue-error"),
            empty: ui.byId("queue-empty"),
            table: ui.byId("queue-table-container")
        };
    }


    function setPanels(which) {
        if (nodes.loading) {
            nodes.loading.hidden = which !== "loading";
        }
        if (nodes.error) {
            nodes.error.hidden = which !== "error";
        }
        if (nodes.empty) {
            nodes.empty.hidden = which !== "empty";
        }
        if (nodes.table) {
            nodes.table.hidden = which !== "table";
        }
    }


    /* ======================================================
       SUMMARY
       ======================================================
       Counts of the rows the server returned for the current
       filters. Not a second aggregation: it is a tally of the
       one response already on screen.
       ====================================================== */

    function renderSummary(result) {
        var documents = (result && result.documents) || [];

        var counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };

        documents.forEach(function (item) {
            var key = String(item.review_priority || "").toUpperCase();
            if (
                Object.prototype.hasOwnProperty.call(counts, key)
            ) {
                counts[key] += 1;
            }
        });

        ui.replaceChildren(nodes.summary, [
            ui.statCard({
                label: "Pending Reviews",
                value: result ? result.total : null,
                modifier:
                    result && result.total > 0 ? "is-attention" : null
            }),
            ui.statCard({
                label: "High Priority",
                value: counts.HIGH,
                modifier: counts.HIGH > 0 ? "is-critical" : null
            }),
            ui.statCard({
                label: "Medium Priority",
                value: counts.MEDIUM
            }),
            ui.statCard({
                label: "Low Priority",
                value: counts.LOW
            })
        ]);
    }


    /* ======================================================
       REVIEW REASONS
       ======================================================
       reason_codes are the machine-readable contract. The
       reviewer sees the readable title, with the code kept as
       the tooltip so the two are never disconnected.

       An unknown code is humanised and shown rather than
       hidden, so a new backend code never disappears from the
       queue silently.
       ====================================================== */

    function reasonChip(code) {
        var described = vocabulary.describeReasonCode(code);

        return ui.el("span", {
            className:
                "reason-chip" +
                (described.known ? "" : " is-unknown"),
            text: described.title,
            attrs: {
                title:
                    described.code +
                    (described.explanation
                        ? " — " + described.explanation
                        : "")
            }
        });
    }

    function reasonCell(item) {
        var codes = item.reason_codes || [];

        if (!codes.length) {
            return ui.el("span", {
                className: "text-subtle",
                text: "No reason recorded"
            });
        }

        /* De-duplicate. reason_codes carries one entry per
           issue, so the same code repeats when several fields
           fail the same way. */
        var unique = [];
        codes.forEach(function (code) {
            if (unique.indexOf(code) === -1) {
                unique.push(code);
            }
        });

        var shown = unique.slice(0, VISIBLE_REASONS);
        var hidden = unique.length - shown.length;

        var children = shown.map(reasonChip);

        if (hidden > 0) {
            children.push(
                ui.el("span", {
                    className: "reason-chip is-more",
                    text: "+" + hidden + " more",
                    attrs: {
                        title: unique
                            .slice(VISIBLE_REASONS)
                            .join(", ")
                    }
                })
            );
        }

        return ui.el("div", {
            className: "reason-chips",
            children: children
        });
    }


    /* ======================================================
       SEVERITY SUMMARY
       ======================================================
       Counted from the severities the backend attached to each
       anomaly issue. No severity is invented, and a document
       with no issues shows nothing rather than a zero.
       ====================================================== */

    function severityCell(item) {
        var issues = item.anomaly_issues || [];

        var errors = 0;
        var warnings = 0;
        var other = 0;

        issues.forEach(function (issue) {
            var severity = String(issue.severity || "").toUpperCase();
            if (severity === "ERROR") {
                errors += 1;
            } else if (severity === "WARNING") {
                warnings += 1;
            } else {
                other += 1;
            }
        });

        var children = [];

        if (errors) {
            children.push(
                ui.badge(
                    errors + (errors === 1 ? " error" : " errors"),
                    "badge-severity-error"
                )
            );
        }

        if (warnings) {
            children.push(
                ui.badge(
                    warnings +
                        (warnings === 1 ? " warning" : " warnings"),
                    "badge-severity-warning"
                )
            );
        }

        if (other) {
            children.push(
                ui.badge(other + " other", "badge-neutral")
            );
        }

        if (!children.length) {
            return ui.el("span", {
                className: "text-subtle",
                text: "—"
            });
        }

        return ui.el("div", {
            className: "badge-stack",
            children: children
        });
    }


    /* ======================================================
       ROW
       ======================================================
       Every column is metadata or a validation outcome. No
       extracted identity value appears in the queue.

       There is deliberately no expiry column and no confidence
       column: the queue payload carries neither
       date_validation nor field_confidence, and deriving them
       from an anomaly code would be a guess dressed as a fact.
       ====================================================== */

    function queueRow(item) {
        var open = ui.documentLink(
            item.document_id,
            "Open Review",
            "btn btn-primary btn-sm"
        );

        return ui.el("tr", {
            children: [
                ui.el("td", {
                    children: [
                        ui.el("div", {
                            className: "table-primary-cell",
                            text: ui.displayValue(
                                item.original_filename
                            )
                        }),
                        ui.el("div", {
                            className:
                                "table-secondary-text text-mono",
                            text: ui.displayValue(item.document_id)
                        })
                    ]
                }),
                ui.el("td", {
                    text: ui.formatDocumentType(item.document_type)
                }),
                ui.el("td", {
                    children: [
                        ui.priorityBadge(item.review_priority)
                    ]
                }),
                ui.el("td", {
                    children: [reasonCell(item)]
                }),
                ui.el("td", {
                    children: [severityCell(item)]
                }),
                ui.el("td", {
                    className: "table-secondary-text",
                    text: ui.formatDateTime(
                        item.analysis_created_at || item.created_at
                    )
                }),
                ui.el("td", {
                    className: "table-action-cell",
                    children: [
                        open ||
                            ui.el("span", {
                                className: "text-subtle",
                                text: "Unavailable"
                            })
                    ]
                })
            ]
        });
    }


    var COLUMNS = [
        "Document",
        "Type",
        "Priority",
        "Why review is needed",
        "Findings",
        "Processed",
        ""
    ];


    function renderTable(result) {
        var head = ui.el("thead", {
            children: [
                ui.el("tr", {
                    children: COLUMNS.map(function (label) {
                        return ui.el("th", {
                            text: label,
                            attrs: { scope: "col" }
                        });
                    })
                })
            ]
        });

        var body = ui.el("tbody", {
            children: (result.documents || []).map(queueRow)
        });

        ui.replaceChildren(nodes.table, [
            ui.el("div", {
                className: "table-wrap",
                children: [
                    ui.el("table", {
                        className: "table",
                        children: [head, body]
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       STATUS LINE
       ====================================================== */

    function renderStatus(result) {
        if (!nodes.status) {
            return;
        }

        var total = result ? result.total : 0;

        if (!total) {
            nodes.status.textContent = hasFilters()
                ? "No documents match these filters."
                : "Nothing is waiting for review.";
            return;
        }

        nodes.status.textContent =
            total +
            (total === 1
                ? " document is waiting for review"
                : " documents are waiting for review") +
            (hasFilters() ? ", matching the current filters" : "") +
            ".";
    }


    function hasFilters() {
        return Boolean(state.priority || state.documentType);
    }


    /* ======================================================
       EMPTY
       ======================================================
       An empty queue is good news, and a filtered-empty queue
       is a different fact. Saying the wrong one is misleading.
       ====================================================== */

    function renderEmpty() {
        var children;

        if (hasFilters()) {
            var reset = ui.el("button", {
                className: "btn btn-secondary",
                text: "Reset filters",
                attrs: { type: "button" }
            });
            reset.addEventListener("click", resetFilters);

            children = [
                ui.el("p", {
                    className: "empty-title",
                    text: "No documents match these filters"
                }),
                ui.el("p", {
                    className: "empty-description",
                    text:
                        "Other documents may still be waiting " +
                        "for review under a different priority " +
                        "or document type."
                }),
                ui.el("div", {
                    className: "empty-actions",
                    children: [reset]
                })
            ];
        } else {
            children = [
                ui.el("p", {
                    className: "empty-title",
                    text: "Nothing is waiting for review"
                }),
                ui.el("p", {
                    className: "empty-description",
                    text:
                        "Every processed document was either " +
                        "confirmed by VIGILOX on its own " +
                        "evidence or has already been reviewed."
                }),
                ui.el("div", {
                    className: "empty-actions",
                    children: [
                        ui.el("a", {
                            className: "btn btn-secondary",
                            text: "View all documents",
                            attrs: { href: "/documents" }
                        }),
                        ui.el("a", {
                            className: "btn btn-primary",
                            text: "Upload Document",
                            attrs: { href: "/upload" }
                        })
                    ]
                })
            ];
        }

        ui.replaceChildren(nodes.empty, [
            ui.el("div", {
                className: "card-body",
                children: [
                    ui.el("div", {
                        className: "empty-state",
                        children: children
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       ERROR
       ======================================================
       Structured contract. This screen previously read the
       legacy top-level `detail` and showed nothing else; it now
       shows code, message and request id, and `detail` survives
       only as the shared client's fallback.
       ====================================================== */

    function renderError(error) {
        ui.replaceChildren(nodes.error, [
            ui.el("div", {
                className: "card-body",
                children: [
                    ui.retryableErrorState(error, {
                        title: "Unable to load the review queue",
                        onRetry: load
                    })
                ]
            })
        ]);

        if (nodes.status) {
            nodes.status.textContent = "";
        }

        ui.clear(nodes.summary);
        setPanels("error");
    }


    /* ======================================================
       RENDER
       ====================================================== */

    function render(result) {
        lastResult = result;

        renderSummary(result);
        renderStatus(result);

        if (!((result.documents || []).length)) {
            renderEmpty();
            setPanels("empty");
            return;
        }

        renderTable(result);
        setPanels("table");
    }


    /* ======================================================
       LOAD
       ====================================================== */

    function renderSkeleton() {
        ui.replaceChildren(nodes.loading, [
            ui.el("div", {
                className: "card-body",
                children: [ui.skeletonRows(5, 5)]
            })
        ]);
    }

    function load() {
        if (loading) {
            return Promise.resolve(null);
        }

        loading = true;

        renderSkeleton();
        setPanels("loading");

        if (nodes.refresh) {
            ui.setButtonPending(nodes.refresh, true);
        }

        return api.endpoints
            .getReviewQueue({
                priority: state.priority || null,
                documentType: state.documentType || null
            })
            .then(
                function (result) {
                    loading = false;
                    if (nodes.refresh) {
                        ui.setButtonPending(nodes.refresh, false);
                    }
                    render(result);
                    return result;
                },
                function (error) {
                    loading = false;
                    if (nodes.refresh) {
                        ui.setButtonPending(nodes.refresh, false);
                    }
                    renderError(error);
                    return null;
                }
            );
    }


    /* ======================================================
       FILTERS
       ====================================================== */

    function resetFilters() {
        state.priority = "";
        state.documentType = "";

        if (nodes.priority) {
            nodes.priority.value = "";
        }
        if (nodes.documentType) {
            nodes.documentType.value = "";
        }

        load();
    }

    function bindControls() {
        if (nodes.form) {
            nodes.form.addEventListener("submit", function (event) {
                if (event.preventDefault) {
                    event.preventDefault();
                }
                load();
            });
        }

        if (nodes.priority) {
            nodes.priority.addEventListener("change", function () {
                /* Only values the API accepts. A tampered
                   control falls back to "no filter" rather than
                   producing an HTTP 400. */
                var value = nodes.priority.value;
                state.priority =
                    PRIORITIES.indexOf(value) !== -1 ? value : "";
                load();
            });
        }

        if (nodes.documentType) {
            nodes.documentType.addEventListener("change", function () {
                var value = nodes.documentType.value;
                state.documentType =
                    DOCUMENT_TYPES.indexOf(value) !== -1 ? value : "";
                load();
            });
        }

        if (nodes.reset) {
            nodes.reset.addEventListener("click", resetFilters);
        }

        if (nodes.refresh) {
            nodes.refresh.addEventListener("click", function () {
                load();
            });
        }
    }


    /* ======================================================
       INIT
       ====================================================== */

    function init() {
        collectNodes();
        bindControls();

        ui.initShell();

        return load();
    }

    if (global.document) {
        global.document.addEventListener(
            "DOMContentLoaded",
            init
        );
    }


    global.VigiloxReviewQueue = {
        init: init,
        load: load,
        state: state,
        PRIORITIES: PRIORITIES,
        DOCUMENT_TYPES: DOCUMENT_TYPES,
        VISIBLE_REASONS: VISIBLE_REASONS,
        COLUMNS: COLUMNS,
        resetFilters: resetFilters,
        getLastResult: function () {
            return lastResult;
        }
    };

}(typeof window !== "undefined" ? window : globalThis));
