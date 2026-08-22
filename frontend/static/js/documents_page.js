/* ==========================================================
   VIGILOX DOCUMENTS
   PHASE 8.8B
   ==========================================================

   Owns GET /documents.

   SERVER IS THE AUTHORITY
   ----------------------------------------------------------
   Paging, searching, filtering and sorting are all done by
   GET /api/v1/documents. This module holds the query state,
   turns it into request parameters, and renders the page the
   server returned.

   It does NOT sort or filter the rows it received. Sorting one
   bounded page on the client and presenting it as if the whole
   dataset were sorted would be a lie, and a filter the server
   did not apply would show a count that disagrees with the
   rows beneath it.

   The sort keys sent are exactly the five the backend
   whitelists. A column that is not sortable server-side is not
   rendered as a sort control.


   NO CONTENT LEAKAGE
   ----------------------------------------------------------
   Every column here is document metadata. Full name, licence
   number, ID number, date of birth, OCR text and evidence all
   belong to the document workspace, behind a deliberate click,
   not to a browsable index.


   OVERLAPPING REQUESTS
   ----------------------------------------------------------
   Typing in the search box can produce several reads. Each new
   read aborts the previous one, and a response whose sequence
   number is stale is discarded, so the table can never end up
   showing the results of an older query.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;


    /* ======================================================
       CONTRACT MIRRORS
       ======================================================
       Kept identical to the backend on purpose. A control that
       could emit a value outside these sets would produce an
       HTTP 400 the user did not cause.
       ====================================================== */

    var SORT_FIELDS = [
        "created_at",
        "filename",
        "document_type",
        "expiry_date",
        "priority"
    ];

    var DIRECTIONS = ["asc", "desc"];

    var DEFAULT_SORT = "created_at";
    var DEFAULT_DIRECTION = "desc";
    var DEFAULT_PAGE_SIZE = 25;

    /* Matches MAX_PAGE_SIZE in the API. The select never
       offers more, so PAGE_SIZE_TOO_LARGE is unreachable from
       the UI. */
    var MAX_PAGE_SIZE = 100;
    var PAGE_SIZE_CHOICES = [10, 25, 50, 100];

    var MAX_SEARCH_LENGTH = 200;

    var SEARCH_DEBOUNCE_MS = 350;


    /* Column definitions. `sort` is present only where the
       backend can actually order by that column. */
    var COLUMNS = [
        { key: "document", label: "Document", sort: "filename" },
        { key: "type", label: "Type", sort: "document_type" },
        { key: "final_state", label: "Final State", sort: null },
        { key: "machine_decision", label: "Machine", sort: null },
        { key: "review", label: "Review", sort: null },
        { key: "expiry", label: "Expiry", sort: "expiry_date" },
        { key: "priority", label: "Priority", sort: "priority" },
        { key: "processed", label: "Processed", sort: "created_at" },
        { key: "action", label: "", sort: null }
    ];


    /* ======================================================
       QUERY STATE
       ====================================================== */

    var state = {
        page: 1,
        pageSize: DEFAULT_PAGE_SIZE,
        search: "",
        documentType: "",
        finalState: "",
        machineDecision: "",
        expiryStatus: "",
        sort: DEFAULT_SORT,
        direction: DEFAULT_DIRECTION
    };

    var lastResult = null;

    /* Monotonic. Only the newest response is allowed to
       render. */
    var sequence = 0;
    var inFlight = null;
    var searchTimer = null;


    var nodes = {};

    function collectNodes() {
        nodes = {
            form: ui.byId("filter-form"),
            search: ui.byId("search-input"),
            clearSearch: ui.byId("clear-search-button"),
            documentType: ui.byId("document-type-filter"),
            finalState: ui.byId("final-state-filter"),
            machineDecision: ui.byId("machine-decision-filter"),
            expiryStatus: ui.byId("expiry-status-filter"),
            pageSize: ui.byId("page-size-select"),
            reset: ui.byId("reset-filters-button"),
            status: ui.byId("documents-status"),
            loading: ui.byId("documents-loading"),
            error: ui.byId("documents-error"),
            empty: ui.byId("documents-empty"),
            table: ui.byId("documents-table"),
            pagination: ui.byId("documents-pagination")
        };
    }


    /* ======================================================
       URL STATE
       ======================================================
       Refresh, back and a pasted link all reproduce the same
       view. Only non-default values are written, so a plain
       /documents URL stays clean.

       Values are validated on the way IN as well as on the way
       out: a hand-edited query string cannot push an unknown
       sort key into a request.
       ====================================================== */

    function parseQuery(search) {
        var out = {};
        var text = String(search || "").replace(/^\?/, "");

        if (!text) {
            return out;
        }

        text.split("&").forEach(function (pair) {
            if (!pair) {
                return;
            }
            var parts = pair.split("=");
            var key = decodeURIComponent(parts[0] || "");
            var value = decodeURIComponent(
                (parts[1] || "").replace(/\+/g, " ")
            );
            if (key) {
                out[key] = value;
            }
        });

        return out;
    }

    function oneOf(value, allowed, fallback) {
        return allowed.indexOf(value) !== -1 ? value : fallback;
    }

    function readStateFromUrl() {
        var query = parseQuery(global.location.search);

        var page = parseInt(query.page, 10);
        state.page = page > 0 ? page : 1;

        var size = parseInt(query.page_size, 10);
        state.pageSize =
            PAGE_SIZE_CHOICES.indexOf(size) !== -1
                ? size
                : DEFAULT_PAGE_SIZE;

        state.search = String(query.search || "").slice(
            0,
            MAX_SEARCH_LENGTH
        );

        state.documentType = oneOf(
            query.document_type,
            ["guard_license", "sia_badge", "id_card"],
            ""
        );

        state.finalState = oneOf(
            query.final_state,
            [
                "AUTO_ACCEPTED",
                "PENDING_REVIEW",
                /* PHASE 10.2. */
                "UNSUPPORTED",
                "APPROVED",
                "CORRECTED",
                "REJECTED"
            ],
            ""
        );

        state.machineDecision = oneOf(
            query.machine_decision,
            [
                "AUTO_ACCEPT",
                "REVIEW_REQUIRED",
                /* PHASE 10.2. */
                "UNSUPPORTED_DOCUMENT"
            ],
            ""
        );

        state.expiryStatus = oneOf(
            query.expiry_status,
            Object.keys(ui.EXPIRY_LABELS),
            ""
        );

        state.sort = oneOf(query.sort, SORT_FIELDS, DEFAULT_SORT);

        state.direction = oneOf(
            query.direction,
            DIRECTIONS,
            DEFAULT_DIRECTION
        );
    }

    function writeStateToUrl() {
        var parts = [];

        function add(key, value, fallback) {
            if (value === fallback || value === "" || value === null) {
                return;
            }
            parts.push(
                key + "=" + encodeURIComponent(value)
            );
        }

        add("page", state.page, 1);
        add("page_size", state.pageSize, DEFAULT_PAGE_SIZE);
        add("search", state.search, "");
        add("document_type", state.documentType, "");
        add("final_state", state.finalState, "");
        add("machine_decision", state.machineDecision, "");
        add("expiry_status", state.expiryStatus, "");
        add("sort", state.sort, DEFAULT_SORT);
        add("direction", state.direction, DEFAULT_DIRECTION);

        var url =
            "/documents" + (parts.length ? "?" + parts.join("&") : "");

        /* replaceState, not pushState: adjusting a filter is
           not a new place, and pushing would force the user
           through every intermediate keystroke on Back. */
        global.history.replaceState(null, "", url);
    }

    function applyStateToControls() {
        if (nodes.search) {
            nodes.search.value = state.search;
        }
        if (nodes.documentType) {
            nodes.documentType.value = state.documentType;
        }
        if (nodes.finalState) {
            nodes.finalState.value = state.finalState;
        }
        if (nodes.machineDecision) {
            nodes.machineDecision.value = state.machineDecision;
        }
        if (nodes.expiryStatus) {
            nodes.expiryStatus.value = state.expiryStatus;
        }
        if (nodes.pageSize) {
            nodes.pageSize.value = String(state.pageSize);
        }
    }


    /* ======================================================
       FILTER STATE HELPERS
       ====================================================== */

    function hasSearch() {
        return state.search !== "";
    }

    function hasFilters() {
        return Boolean(
            state.documentType ||
            state.finalState ||
            state.machineDecision ||
            state.expiryStatus
        );
    }


    /* ======================================================
       PANELS
       ====================================================== */

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

    function renderSkeleton() {
        ui.replaceChildren(nodes.loading, [
            ui.el("div", {
                className: "card-body",
                children: [ui.skeletonRows(6, 5)]
            })
        ]);
    }


    /* ======================================================
       SORT CONTROLS
       ======================================================
       A real button inside the header cell, so the control is
       reachable by keyboard and announced as a button.

       aria-sort carries the current order on the th, which is
       the attribute assistive technology actually reads.
       ====================================================== */

    function ariaSortValue(column) {
        if (!column.sort || state.sort !== column.sort) {
            return "none";
        }
        return state.direction === "asc" ? "ascending" : "descending";
    }

    function toggleSort(field) {
        if (SORT_FIELDS.indexOf(field) === -1) {
            return;
        }

        if (state.sort === field) {
            state.direction =
                state.direction === "asc" ? "desc" : "asc";
        } else {
            state.sort = field;
            /* A new column starts descending, which puts the
               newest or the highest first. */
            state.direction = "desc";
        }

        /* Reordering changes which rows land on page 1, so an
           old page number would be meaningless. */
        state.page = 1;

        load();
    }

    function headerCell(column) {
        if (!column.sort) {
            return ui.el("th", {
                text: column.label,
                attrs: { scope: "col" }
            });
        }

        var active = state.sort === column.sort;

        var button = ui.el("button", {
            className:
                "sort-button" + (active ? " is-active" : ""),
            attrs: { type: "button" },
            children: [
                ui.el("span", { text: column.label }),
                ui.el("span", {
                    className: "sort-indicator",
                    attrs: { "aria-hidden": "true" },
                    text: active
                        ? state.direction === "asc"
                            ? "↑"
                            : "↓"
                        : "↕"
                })
            ]
        });

        button.addEventListener("click", function () {
            toggleSort(column.sort);
        });

        return ui.el("th", {
            attrs: {
                scope: "col",
                "aria-sort": ariaSortValue(column)
            },
            children: [button]
        });
    }


    /* ======================================================
       ROW
       ====================================================== */

    function reviewCell(item) {
        if (item.is_reviewed) {
            return ui.el("div", {
                children: [
                    ui.el("div", {
                        className: "table-primary-cell",
                        text: ui.humanizeEnum(
                            item.human_review_action
                        )
                    }),
                    ui.el("div", {
                        className: "table-secondary-text",
                        text: ui.displayValue(item.reviewer_id)
                    })
                ]
            });
        }

        if (item.machine_decision === "REVIEW_REQUIRED") {
            return ui.badge("Awaiting review", "badge-warning");
        }

        /* PHASE 10.2. "Not required" is what an auto-accepted
           document gets, and it means VIGILOX already
           confirmed it. An unsupported file was not confirmed
           by anybody -- it was set aside -- so it says so
           rather than borrowing wording that reads as
           approval. */
        if (
            item.machine_decision === "UNSUPPORTED_DOCUMENT"
        ) {
            return ui.el("span", {
                className: "text-subtle",
                text: "Not applicable"
            });
        }

        return ui.el("span", {
            className: "text-subtle",
            text: "Not required"
        });
    }

    function documentRow(item) {
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
                            className: "table-secondary-text text-mono",
                            text: ui.displayValue(item.document_id)
                        })
                    ]
                }),
                ui.el("td", {
                    text: ui.formatDocumentType(item.document_type)
                }),
                ui.el("td", {
                    children: [ui.finalStateBadge(item.final_state)]
                }),
                ui.el("td", {
                    text: ui.humanizeEnum(item.machine_decision)
                }),
                ui.el("td", {
                    children: [reviewCell(item)]
                }),
                ui.el("td", {
                    children: [
                        ui.expiryBadge(item.expiry_status),
                        item.expiry_date
                            ? ui.el("div", {
                                className: "table-secondary-text",
                                text: ui.formatDate(item.expiry_date)
                            })
                            : null
                    ]
                }),
                ui.el("td", {
                    children: [
                        item.priority && item.priority !== "NONE"
                            ? ui.priorityBadge(item.priority)
                            : ui.el("span", {
                                className: "text-subtle",
                                text: "—"
                            })
                    ]
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


    /* ======================================================
       TABLE
       ====================================================== */

    function renderTable(result) {
        var head = ui.el("thead", {
            children: [
                ui.el("tr", {
                    children: COLUMNS.map(headerCell)
                })
            ]
        });

        var body = ui.el("tbody", {
            children: (result.items || []).map(documentRow)
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
       RESULT SUMMARY
       ====================================================== */

    function renderStatus(result) {
        if (!nodes.status) {
            return;
        }

        var total = result.total || 0;

        if (total === 0) {
            /* "No matches" and "nothing here yet" are
               different facts. Saying the wrong one sends a
               user looking for a bug. */
            nodes.status.textContent =
                hasSearch() || hasFilters()
                    ? "No documents match the current filters."
                    : "No documents have been processed yet.";
            return;
        }

        var first = (result.page - 1) * result.page_size + 1;
        var last = Math.min(first + (result.items || []).length - 1, total);

        nodes.status.textContent =
            "Showing " +
            first +
            "–" +
            last +
            " of " +
            total +
            (total === 1 ? " document" : " documents") +
            (result.total_pages > 1
                ? " · page " +
                  result.page +
                  " of " +
                  result.total_pages
                : "");
    }


    /* ======================================================
       PAGINATION
       ======================================================
       Previous / Next only. A numbered pager over an unknown
       number of pages adds controls without adding capability,
       and the count is already announced above the table.
       ====================================================== */

    function pageButton(label, targetPage, enabled, relation) {
        var button = ui.el("button", {
            className: "btn btn-secondary btn-sm",
            text: label,
            attrs: { type: "button", rel: relation }
        });

        button.disabled = !enabled;

        if (enabled) {
            button.addEventListener("click", function () {
                state.page = targetPage;
                load();
            });
        }

        return button;
    }

    function renderPagination(result) {
        if (!nodes.pagination) {
            return;
        }

        var totalPages = result.total_pages || 0;

        if (totalPages <= 1) {
            ui.clear(nodes.pagination);
            return;
        }

        ui.replaceChildren(nodes.pagination, [
            ui.el("div", {
                className: "pagination",
                children: [
                    pageButton(
                        "Previous",
                        result.page - 1,
                        result.page > 1,
                        "prev"
                    ),
                    ui.el("span", {
                        className: "pagination-label",
                        text:
                            "Page " +
                            result.page +
                            " of " +
                            totalPages
                    }),
                    pageButton(
                        "Next",
                        result.page + 1,
                        result.page < totalPages,
                        "next"
                    )
                ]
            })
        ]);
    }


    /* ======================================================
       EMPTY STATES
       ======================================================
       Three distinct situations. Telling a user with an active
       filter that they have no documents at all is wrong and
       sends them looking for a bug.
       ====================================================== */

    function renderEmpty() {
        var children;

        if (hasSearch()) {
            var clear = ui.el("button", {
                className: "btn btn-secondary",
                text: "Clear search",
                attrs: { type: "button" }
            });
            clear.addEventListener("click", clearSearch);

            children = [
                ui.el("p", {
                    className: "empty-title",
                    text: "No documents match that search"
                }),
                ui.el("p", {
                    className: "empty-description",
                    text:
                        "Search covers the filename and the " +
                        "document ID. Document contents are " +
                        "not searched."
                }),
                ui.el("div", {
                    className: "empty-actions",
                    children: [clear]
                })
            ];
        } else if (hasFilters()) {
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
                        "Documents exist, but none of them " +
                        "match the current combination."
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
                    text: "No documents have been processed yet"
                }),
                ui.el("p", {
                    className: "empty-description",
                    text:
                        "Upload a Security Guard Licence, ID " +
                        "Card or SIA Badge to get started."
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
       ====================================================== */

    function renderError(error) {
        ui.replaceChildren(nodes.error, [
            ui.el("div", {
                className: "card-body",
                children: [
                    ui.retryableErrorState(error, {
                        title: "Could not load documents",
                        onRetry: load
                    })
                ]
            })
        ]);

        if (nodes.status) {
            nodes.status.textContent = "";
        }

        ui.clear(nodes.pagination);
        setPanels("error");
    }


    /* ======================================================
       RENDER
       ====================================================== */

    function render(result) {
        lastResult = result;

        renderStatus(result);

        if (!(result.items || []).length) {
            renderEmpty();
            ui.clear(nodes.pagination);
            setPanels("empty");
            return;
        }

        renderTable(result);
        renderPagination(result);
        setPanels("table");
    }


    /* ======================================================
       LOAD
       ======================================================
       Aborts the previous read and discards any response that
       is no longer the newest, so overlapping filter changes
       cannot leave stale rows on screen.
       ====================================================== */

    function load() {
        writeStateToUrl();

        sequence += 1;
        var mine = sequence;

        if (inFlight) {
            inFlight.abort();
        }

        var controller =
            typeof global.AbortController === "function"
                ? new global.AbortController()
                : null;

        inFlight = controller;

        renderSkeleton();
        setPanels("loading");

        return api.endpoints
            .getDocuments(
                {
                    page: state.page,
                    pageSize: state.pageSize,
                    search: state.search || null,
                    documentType: state.documentType || null,
                    finalState: state.finalState || null,
                    machineDecision: state.machineDecision || null,
                    expiryStatus: state.expiryStatus || null,
                    sort: state.sort,
                    direction: state.direction
                },
                { signal: controller ? controller.signal : undefined }
            )
            .then(
                function (result) {
                    if (mine !== sequence) {
                        return null;
                    }
                    inFlight = null;
                    render(result);
                    return result;
                },
                function (error) {
                    if (mine !== sequence) {
                        return null;
                    }
                    inFlight = null;

                    /* An abort is this module's own doing, not
                       a failure to report. */
                    if (error && error.code === "REQUEST_ABORTED") {
                        return null;
                    }

                    renderError(error);
                    return null;
                }
            );
    }


    /* ======================================================
       CONTROL HANDLERS
       ====================================================== */

    function applyFilterChange() {
        /* Any filter change invalidates the page number. Page
           7 of the old result set is not page 7 of the new
           one. */
        state.page = 1;
        load();
    }

    function scheduleSearch() {
        if (searchTimer !== null) {
            global.clearTimeout(searchTimer);
        }

        searchTimer = global.setTimeout(function () {
            searchTimer = null;
            var raw = nodes.search ? nodes.search.value : "";
            state.search = String(raw).trim().slice(
                0,
                MAX_SEARCH_LENGTH
            );
            applyFilterChange();
        }, SEARCH_DEBOUNCE_MS);
    }

    function clearSearch() {
        if (searchTimer !== null) {
            global.clearTimeout(searchTimer);
            searchTimer = null;
        }
        if (nodes.search) {
            nodes.search.value = "";
        }
        state.search = "";
        applyFilterChange();
    }

    function resetFilters() {
        if (searchTimer !== null) {
            global.clearTimeout(searchTimer);
            searchTimer = null;
        }

        state.page = 1;
        state.pageSize = DEFAULT_PAGE_SIZE;
        state.search = "";
        state.documentType = "";
        state.finalState = "";
        state.machineDecision = "";
        state.expiryStatus = "";
        state.sort = DEFAULT_SORT;
        state.direction = DEFAULT_DIRECTION;

        applyStateToControls();
        load();
    }

    function bindControls() {
        if (nodes.form) {
            /* The toolbar is a form so the search input gets
               native semantics, but submitting it must not
               reload the page. */
            nodes.form.addEventListener("submit", function (event) {
                if (event.preventDefault) {
                    event.preventDefault();
                }
                if (searchTimer !== null) {
                    global.clearTimeout(searchTimer);
                    searchTimer = null;
                }
                var raw = nodes.search ? nodes.search.value : "";
                state.search = String(raw).trim().slice(
                    0,
                    MAX_SEARCH_LENGTH
                );
                applyFilterChange();
            });
        }

        if (nodes.search) {
            nodes.search.addEventListener("input", scheduleSearch);
        }

        if (nodes.clearSearch) {
            nodes.clearSearch.addEventListener("click", clearSearch);
        }

        [
            ["documentType", "documentType"],
            ["finalState", "finalState"],
            ["machineDecision", "machineDecision"],
            ["expiryStatus", "expiryStatus"]
        ].forEach(function (pair) {
            var node = nodes[pair[0]];
            if (!node) {
                return;
            }
            node.addEventListener("change", function () {
                state[pair[1]] = node.value;
                applyFilterChange();
            });
        });

        if (nodes.pageSize) {
            nodes.pageSize.addEventListener("change", function () {
                var size = parseInt(nodes.pageSize.value, 10);
                state.pageSize =
                    PAGE_SIZE_CHOICES.indexOf(size) !== -1
                        ? size
                        : DEFAULT_PAGE_SIZE;
                applyFilterChange();
            });
        }

        if (nodes.reset) {
            nodes.reset.addEventListener("click", resetFilters);
        }
    }


    /* ======================================================
       INIT
       ====================================================== */

    function init() {
        collectNodes();
        readStateFromUrl();
        applyStateToControls();
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


    global.VigiloxDocuments = {
        init: init,
        load: load,
        state: state,
        SORT_FIELDS: SORT_FIELDS,
        DIRECTIONS: DIRECTIONS,
        COLUMNS: COLUMNS,
        PAGE_SIZE_CHOICES: PAGE_SIZE_CHOICES,
        MAX_PAGE_SIZE: MAX_PAGE_SIZE,
        MAX_SEARCH_LENGTH: MAX_SEARCH_LENGTH,
        SEARCH_DEBOUNCE_MS: SEARCH_DEBOUNCE_MS,
        DEFAULT_PAGE_SIZE: DEFAULT_PAGE_SIZE,
        toggleSort: toggleSort,
        resetFilters: resetFilters,
        clearSearch: clearSearch,
        getLastResult: function () {
            return lastResult;
        }
    };

}(typeof window !== "undefined" ? window : globalThis));
