/* ==========================================================
   VIGILOX DASHBOARD
   PHASE 8.6B
   ==========================================================

   Owns GET /dashboard.

   NOT TO BE CONFUSED WITH dashboard.js, which owns the Review
   Queue at GET /review. That file predates this one and keeps
   its name because browsers and existing tests reference it.


   ONE REQUEST
   ----------------------------------------------------------
   Everything on this screen comes from a single
   GET /api/v1/dashboard/summary. The counts are SQL
   aggregates; none of them is computed by walking rows in
   JavaScript, and recent_documents arrives inside the same
   payload so the Documents list API is never called here.

   There is no polling. The page loads once, and the reviewer
   can ask for a fresh read with Refresh.


   NO INVENTED METRICS
   ----------------------------------------------------------
   Accuracy, average confidence, risk score, automation rate,
   SLA attainment and time saved are all absent, because the
   backend defines none of them. The only derived figure is
   "Human reviewed", which is the sum of the three human
   outcome counts the API already returns, and which is
   exactly the set of documents that carry a human review.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;


    /* ======================================================
       EXPIRY PRESENTATION
       ======================================================
       Order is worst-first, so the row a reviewer needs is at
       the top. The keys are the five authoritative statuses
       emitted by date_validation.expiry.status; the labels are
       presentation only.
       ====================================================== */

    var EXPIRY_ROWS = [
        { key: "expired", status: "EXPIRED" },
        { key: "expires_today", status: "EXPIRES_TODAY" },
        { key: "expiring_soon", status: "EXPIRING_SOON" },
        { key: "active", status: "ACTIVE" },
        { key: "not_available", status: "NOT_AVAILABLE" }
    ];


    var PRIORITY_ROWS = [
        { key: "high", priority: "HIGH" },
        { key: "medium", priority: "MEDIUM" },
        { key: "low", priority: "LOW" }
    ];


    /* ======================================================
       DOM
       ====================================================== */

    var nodes = {};

    function collectNodes() {
        nodes = {
            loading: ui.byId("dashboard-loading"),
            error: ui.byId("dashboard-error"),
            empty: ui.byId("dashboard-empty"),
            body: ui.byId("dashboard-body"),
            primary: ui.byId("primary-summary"),
            attentionSection: ui.byId("review-attention-section"),
            attention: ui.byId("review-attention"),
            outcomes: ui.byId("review-outcomes"),
            expiry: ui.byId("expiry-breakdown"),
            recent: ui.byId("recent-documents"),
            refresh: ui.byId("refresh-button")
        };
    }


    /* ======================================================
       STATE
       ======================================================
       `loading` guards against a second concurrent read. Two
       overlapping Refresh clicks would otherwise race and the
       later response could be the older one.
       ====================================================== */

    var loading = false;

    function setPanels(state) {
        if (nodes.loading) {
            nodes.loading.hidden = state !== "loading";
        }
        if (nodes.error) {
            nodes.error.hidden = state !== "error";
        }
        if (nodes.empty) {
            nodes.empty.hidden = state !== "empty";
        }
        if (nodes.body) {
            nodes.body.hidden = state !== "ready";
        }
    }


    /* ======================================================
       LOADING SKELETON
       ======================================================
       Zeros are withheld while loading. "0 Pending Review"
       and "not loaded yet" look identical to a reader and
       only one of them is true.
       ====================================================== */

    function renderSkeleton() {
        if (!nodes.loading) {
            return;
        }
        ui.replaceChildren(nodes.loading, [
            ui.skeletonCards(4),
            ui.el("div", {
                className: "card",
                children: [
                    ui.el("div", {
                        className: "card-body",
                        children: [ui.skeletonRows(5, 4)]
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       PRIMARY SUMMARY
       ====================================================== */

    function renderPrimary(summary) {
        var review = summary.review || {};

        /* Sum of the three server-side outcome counts. Every
           document with a human review has exactly one of
           APPROVE / CORRECT / REJECT, so this is a count of
           reviewed documents rather than a new statistic. */
        var humanReviewed =
            (review.approved || 0) +
            (review.corrected || 0) +
            (review.rejected || 0);

        var pending = review.pending_review || 0;

        ui.replaceChildren(nodes.primary, [
            ui.statCard({
                label: "Total Documents",
                value: summary.total_documents
            }),
            ui.statCard({
                label: "Pending Review",
                value: review.pending_review,
                hint:
                    review.review_required !== undefined
                        ? review.review_required +
                          " flagged by the machine"
                        : null,
                modifier: pending > 0 ? "is-attention" : null,
                href: pending > 0 ? "/review" : null,
                linkLabel: "Open review queue"
            }),
            ui.statCard({
                label: "Auto Accepted",
                value: review.auto_accepted,
                hint: "No human review required"
            }),
            ui.statCard({
                label: "Human Reviewed",
                value: humanReviewed,
                hint: "Approved, corrected or rejected"
            })
        ]);
    }


    /* ======================================================
       REVIEW ATTENTION
       ======================================================
       Rendered only when work is actually waiting. An empty
       "Requires attention" panel trains reviewers to ignore
       the panel.
       ====================================================== */

    function renderAttention(summary) {
        var review = summary.review || {};
        var pending = review.pending_review || 0;

        if (!nodes.attentionSection) {
            return;
        }

        if (pending < 1) {
            nodes.attentionSection.hidden = true;
            ui.clear(nodes.attention);
            return;
        }

        nodes.attentionSection.hidden = false;

        var priorities = summary.pending_review_priority || {};

        var rows = PRIORITY_ROWS.map(function (row) {
            return ui.metricRow({
                badge: ui.priorityBadge(row.priority),
                value: priorities[row.key]
            });
        });

        ui.replaceChildren(nodes.attention, [
            ui.el("div", {
                className: "attention-panel",
                children: [
                    ui.el("div", {
                        className: "attention-body",
                        children: [
                            ui.el("p", {
                                className: "attention-title",
                                text:
                                    pending === 1
                                        ? "1 document is waiting for human review"
                                        : pending +
                                          " documents are waiting for human review"
                            }),
                            ui.el("p", {
                                className: "attention-description",
                                text:
                                    "VIGILOX could not confirm these " +
                                    "documents on its own evidence. " +
                                    "Priority is assigned by the review " +
                                    "queue, not by this page."
                            }),
                            ui.el("div", {
                                className: "attention-actions",
                                children: [
                                    ui.el("a", {
                                        className: "btn btn-primary",
                                        text: "View Review Queue",
                                        attrs: { href: "/review" }
                                    })
                                ]
                            })
                        ]
                    }),
                    ui.el("div", {
                        className: "attention-metrics",
                        children: rows
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       REVIEW OUTCOMES
       ====================================================== */

    function renderOutcomes(summary) {
        var review = summary.review || {};

        ui.replaceChildren(nodes.outcomes, [
            ui.statCard({
                label: "Approved",
                value: review.approved,
                hint: "Machine values accepted as-is"
            }),
            ui.statCard({
                label: "Corrected",
                value: review.corrected,
                hint: "One or more values replaced by a reviewer"
            }),
            ui.statCard({
                label: "Rejected",
                value: review.rejected,
                hint: "Final, and not usable downstream",
                modifier:
                    (review.rejected || 0) > 0 ? "is-critical" : null
            })
        ]);
    }


    /* ======================================================
       EXPIRY BREAKDOWN
       ====================================================== */

    function renderExpiry(summary) {
        var expiry = summary.expiry || {};

        ui.replaceChildren(
            nodes.expiry,
            EXPIRY_ROWS.map(function (row) {
                return ui.metricRow({
                    badge: ui.expiryBadge(row.status),
                    value: expiry[row.key]
                });
            })
        );
    }


    /* ======================================================
       RECENT DOCUMENTS
       ======================================================
       Summary columns only.

       No extracted identity value appears here. Name, licence
       number, ID number and date of birth are all deliberately
       absent: a browsable index of document contents is not
       something this screen should be.
       ====================================================== */

    function recentRow(item) {
        var open = ui.documentLink(
            item.document_id,
            "Open",
            "btn btn-secondary btn-sm"
        );

        return ui.el("tr", {
            children: [
                ui.el("td", {
                    children: [
                        ui.el("div", {
                            className: "table-primary-cell",
                            text: ui.displayValue(item.filename)
                        }),
                        ui.el("div", {
                            className: "table-secondary-text",
                            text: ui.formatDocumentType(
                                item.document_type
                            )
                        })
                    ]
                }),
                ui.el("td", {
                    children: [ui.finalStateBadge(item.final_state)]
                }),
                ui.el("td", {
                    children: [ui.expiryBadge(item.expiry_status)]
                }),
                ui.el("td", {
                    className: "table-secondary-text",
                    text: ui.formatDateTime(
                        item.processed_at || item.created_at
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

    function renderRecent(summary) {
        var items = summary.recent_documents || [];

        if (!items.length) {
            ui.replaceChildren(nodes.recent, [
                ui.emptyState({
                    title: "No documents yet",
                    description:
                        "Processed documents appear here as " +
                        "soon as the first upload completes."
                })
            ]);
            return;
        }

        var head = ui.el("thead", {
            children: [
                ui.el("tr", {
                    children: [
                        "Document",
                        "Final State",
                        "Expiry",
                        "Processed",
                        ""
                    ].map(function (label) {
                        return ui.el("th", {
                            text: label,
                            attrs: { scope: "col" }
                        });
                    })
                })
            ]
        });

        var bodyRows = ui.el("tbody", {
            children: items.map(recentRow)
        });

        ui.replaceChildren(nodes.recent, [
            ui.el("div", {
                className: "table-wrap",
                children: [
                    ui.el("table", {
                        className: "table",
                        children: [head, bodyRows]
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       EMPTY DASHBOARD
       ====================================================== */

    function renderEmpty() {
        ui.replaceChildren(nodes.empty, [
            ui.el("div", {
                className: "card",
                children: [
                    ui.el("div", {
                        className: "card-body",
                        children: [
                            ui.el("div", {
                                className: "empty-state",
                                children: [
                                    ui.el("p", {
                                        className: "empty-title",
                                        text: "No documents have been analysed yet"
                                    }),
                                    ui.el("p", {
                                        className: "empty-description",
                                        text:
                                            "Upload a Security Guard Licence, " +
                                            "ID Card or SIA Badge and VIGILOX " +
                                            "will read it, check every field " +
                                            "against its own OCR evidence and " +
                                            "decide whether a reviewer is needed."
                                    }),
                                    ui.el("div", {
                                        className: "empty-actions",
                                        children: [
                                            ui.el("a", {
                                                className: "btn btn-primary",
                                                text: "Upload Document",
                                                attrs: { href: "/upload" }
                                            })
                                        ]
                                    })
                                ]
                            })
                        ]
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       RENDER
       ====================================================== */

    function render(summary) {
        if (!summary || summary.total_documents === 0) {
            renderEmpty();
            setPanels("empty");
            return;
        }

        renderPrimary(summary);
        renderAttention(summary);
        renderOutcomes(summary);
        renderExpiry(summary);
        renderRecent(summary);

        setPanels("ready");
    }


    /* ======================================================
       ERROR
       ======================================================
       Structured contract: error.code, error.message and
       error.request_id. `detail` is only the fallback inside
       the shared client.
       ====================================================== */

    function renderError(error) {
        ui.replaceChildren(nodes.error, [
            ui.retryableErrorState(error, {
                title: "Could not load the dashboard",
                onRetry: load
            })
        ]);
        setPanels("error");
    }


    /* ======================================================
       LOAD
       ====================================================== */

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

        return api.endpoints.getDashboardSummary().then(
            function (payload) {
                loading = false;
                if (nodes.refresh) {
                    ui.setButtonPending(nodes.refresh, false);
                }
                render(payload);
                return payload;
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
       INIT
       ====================================================== */

    function init() {
        collectNodes();

        if (nodes.refresh) {
            nodes.refresh.addEventListener("click", function () {
                load();
            });
        }

        ui.initShell();

        return load();
    }

    if (global.document) {
        global.document.addEventListener(
            "DOMContentLoaded",
            init
        );
    }


    global.VigiloxDashboard = {
        init: init,
        load: load,
        render: render,
        renderError: renderError,
        EXPIRY_ROWS: EXPIRY_ROWS,
        PRIORITY_ROWS: PRIORITY_ROWS
    };

}(typeof window !== "undefined" ? window : globalThis));
