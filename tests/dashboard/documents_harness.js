/* ==========================================================
   VIGILOX DOCUMENTS HARNESS
   PHASE 8.8B
   ==========================================================

   Executes frontend/static/js/documents_page.js under Node
   against the shared DOM stub.

   The behaviours that only running can prove:

       every request carries the state the controls describe
       a filter change resets the page number
       search is debounced, not fired per keystroke
       an overlapping read is aborted and the stale response
           discarded
       sort toggles direction and only ever sends whitelisted
           keys
       page_size can never exceed the backend maximum
       the URL reproduces the view
       a row with no document_id never links to
           /review/undefined
       empty / search-empty / filtered-empty are distinct

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");


/* ==========================================================
   FIXTURE
   ========================================================== */

function item(overrides) {
    return Object.assign(
        {
            document_id: "doc-1",
            filename: "guard_front.jpg",
            content_type: "image/jpeg",
            document_type: "guard_license",
            processing_status: "PROCESSED",
            machine_decision: "REVIEW_REQUIRED",
            priority: "HIGH",
            final_state: "PENDING_REVIEW",
            human_review_action: null,
            is_reviewed: false,
            expiry_date: "2024-02-03",
            expiry_status: "EXPIRED",
            reviewer_id: null,
            created_at: "2026-08-01T09:15:00",
            processed_at: "2026-08-01T09:15:20",
            reviewed_at: null
        },
        overrides || {}
    );
}


function page(overrides) {
    return Object.assign(
        {
            status: "success",
            items: [
                item({ document_id: "doc-1" }),
                item({
                    document_id: "doc-2",
                    filename: "badge.png",
                    document_type: "sia_badge",
                    machine_decision: "AUTO_ACCEPT",
                    priority: "NONE",
                    final_state: "AUTO_ACCEPTED",
                    expiry_status: "ACTIVE",
                    expiry_date: "2029-04-04"
                }),
                item({
                    document_id: "doc-3",
                    filename: "card.jpg",
                    document_type: "id_card",
                    machine_decision: "REVIEW_REQUIRED",
                    priority: "MEDIUM",
                    final_state: "CORRECTED",
                    human_review_action: "CORRECT",
                    is_reviewed: true,
                    reviewer_id: "reviewer-7",
                    reviewed_at: "2026-08-03T12:00:00",
                    expiry_status: "EXPIRING_SOON",
                    expiry_date: "2026-09-01"
                })
            ],
            total: 61,
            page: 1,
            page_size: 25,
            total_pages: 3
        },
        overrides || {}
    );
}


/* ==========================================================
   BOOT
   ========================================================== */

function boot(options) {
    const config = options || {};

    /* Per-window, because checks interleave. */
    const requests = [];
    const aborted = [];

    const win = stub.createWindow({
        pathname: "/documents",
        search: config.search || "",
    });

    /* The real shipped page, parsed into a real element
       tree. A renamed id or a moved element breaks the
       test rather than being papered over. */
    stub.loadPage(win, "documents.html");

    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");

    /* The real getDocuments builds the query string, so
       intercepting fetch instead of the endpoint keeps that
       code under test. */
    const realGetDocuments = win.VigiloxApi.endpoints.getDocuments;

    win.VigiloxApi.endpoints.getDocuments = function (params, opts) {
        const index = requests.length;

        /* Recover the URL the real client would build. */
        let url = null;
        win.fetch = function (path) {
            url = path;
            return Promise.reject(new Error("intercepted"));
        };
        realGetDocuments(params, opts).catch(function () {});

        requests.push({ params: params, url: url });

        const signal = opts && opts.signal;
        if (signal) {
            const watcher = setInterval(function () {}, 1000);
            clearInterval(watcher);
        }

        const responder = config.respond || function () {
            return Promise.resolve(page());
        };

        return responder(index, requests, function () {
            aborted.push(index);
        }, signal);
    };

    win.VigiloxApi.endpoints.getHealth = function () {
        return Promise.resolve({ status: "ok" });
    };

    win.VigiloxApi.endpoints.getReviewerIdentity = function () {
        return Promise.resolve({
            reviewer: {
                reviewer_id: "harness",
                role: "REVIEWER",
                source: "LOCAL_ENV",
                can_review: true
            }
        });
    };

    stub.loadScript(win, "js/documents_page.js");
    win.document.ready();

    win.requests = requests;
    win.abortedRequests = aborted;

    return win;
}


function settle(times) {
    const rounds = times || 3;
    let chain = Promise.resolve();
    for (let i = 0; i < rounds; i += 1) {
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

function tableRows(win) {
    const table = win.document.getElementById("documents-table");
    return table.querySelectorAll("tbody tr");
}

function headerInfo(win) {
    const table = win.document.getElementById("documents-table");
    return table.querySelectorAll("thead th").map(function (th) {
        const button = th.querySelector("button");
        return {
            label: th.textContent.replace(/[↑↓↕]/g, "").trim(),
            sortable: Boolean(button),
            aria_sort: th.getAttribute("aria-sort")
        };
    });
}

function hrefs(win, id) {
    return win.document
        .getElementById(id)
        .querySelectorAll("a")
        .map(function (a) {
            return a.getAttribute("href");
        });
}

function lastUrl(win) {
    return win.requests.length
        ? win.requests[win.requests.length - 1].url
        : null;
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
                        error: String((error && error.message) || error),
                        stack: String((error && error.stack) || "")
                            .split("\n")
                            .slice(0, 4)
                            .join(" | ")
                    };
                }
            )
    );
}


/* ---------- module surface mirrors the backend contract ---------- */

check("module_surface", function () {
    const win = boot({});
    const mod = win.VigiloxDocuments;

    return {
        exposed: Boolean(mod),
        sort_fields: mod.SORT_FIELDS,
        directions: mod.DIRECTIONS,
        page_size_choices: mod.PAGE_SIZE_CHOICES,
        max_page_size: mod.MAX_PAGE_SIZE,
        max_search_length: mod.MAX_SEARCH_LENGTH,
        default_page_size: mod.DEFAULT_PAGE_SIZE,
        debounce_ms: mod.SEARCH_DEBOUNCE_MS,
        sortable_columns: mod.COLUMNS.filter(function (c) {
            return c.sort;
        }).map(function (c) {
            return c.sort;
        })
    };
});


/* ---------- first load asks for page 1 with defaults ---------- */

check("initial_request", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            request_count: win.requests.length,
            url: lastUrl(win),
            params: win.requests[0].params
        };
    });
});


/* ---------- rows render from real fields ---------- */

check("row_render", function () {
    const win = boot({});

    return settle().then(function () {
        const rows = tableRows(win);
        return {
            row_count: rows.length,
            first_row: rows[0].textContent,
            reviewed_row: rows[2].textContent,
            hrefs: hrefs(win, "documents-table"),
            status: win.document.getElementById(
                "documents-status"
            ).textContent,
            headers: headerInfo(win)
        };
    });
});


/* ---------- no extracted identity value in a row ---------- */

check("no_personal_data", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                page({
                    items: [
                        item({
                            /* Keys the summary schema does not
                               contain. If the renderer ever
                               echoed unknown fields these
                               would show up. */
                            full_name: "SAMPLE,JANE",
                            id_number: "98765432",
                            licence_number: "GL-11223344",
                            date_of_birth: "1990-01-01",
                            ocr_lines: [{ line_id: "L0", text: "TEXAS" }]
                        })
                    ],
                    total: 1,
                    total_pages: 1
                })
            );
        }
    });

    return settle().then(function () {
        const text = win.document.getElementById(
            "documents-table"
        ).textContent;

        return {
            leaks_name: text.indexOf("SAMPLE,JANE") !== -1,
            leaks_id: text.indexOf("98765432") !== -1,
            leaks_licence: text.indexOf("GL-11223344") !== -1,
            leaks_dob: text.indexOf("1990-01-01") !== -1,
            leaks_ocr: text.indexOf("TEXAS") !== -1
        };
    });
});


/* ---------- pagination ---------- */

check("pagination", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const buttons = win.document
                .getElementById("documents-pagination")
                .querySelectorAll("button");

            const before = {
                button_count: buttons.length,
                previous_disabled: buttons[0].disabled,
                next_disabled: buttons[1].disabled,
                label: win.document
                    .getElementById("documents-pagination")
                    .querySelector(".pagination-label").textContent
            };

            buttons[1].click();
            return settle().then(function () {
                return before;
            });
        })
        .then(function (before) {
            return {
                before: before,
                second_request_url: lastUrl(win),
                second_request_page:
                    win.requests[win.requests.length - 1].params.page,
                request_count: win.requests.length
            };
        });
});


check("last_page_disables_next", function () {
    const win = boot({
        search: "?page=3",
        respond: function () {
            return Promise.resolve(
                page({ page: 3, total_pages: 3, total: 61 })
            );
        }
    });

    return settle().then(function () {
        const buttons = win.document
            .getElementById("documents-pagination")
            .querySelectorAll("button");
        return {
            previous_disabled: buttons[0].disabled,
            next_disabled: buttons[1].disabled
        };
    });
});


check("single_page_hides_pagination", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                page({ total: 2, total_pages: 1, page: 1 })
            );
        }
    });

    return settle().then(function () {
        return {
            child_count: win.document.getElementById(
                "documents-pagination"
            ).childElementCount
        };
    });
});


/* ---------- page size is bounded by the backend maximum ---------- */

check("page_size_bounded", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "page-size-select"
            );

            /* A value the backend would reject. */
            select.value = "500";
            select.fire("change", {});

            return settle();
        })
        .then(function () {
            return {
                requested_page_size:
                    win.requests[win.requests.length - 1].params.pageSize,
                offered_choices: win.VigiloxDocuments.PAGE_SIZE_CHOICES,
                max: win.VigiloxDocuments.MAX_PAGE_SIZE
            };
        });
});


/* ---------- a filter change resets the page number ---------- */

check("filter_resets_page", function () {
    const win = boot({ search: "?page=3" });

    return settle()
        .then(function () {
            const first = win.requests[0].params.page;

            const select = win.document.getElementById(
                "final-state-filter"
            );
            select.value = "REJECTED";
            select.fire("change", {});

            return settle().then(function () {
                return first;
            });
        })
        .then(function (firstPage) {
            const latest = win.requests[win.requests.length - 1];
            return {
                initial_page: firstPage,
                page_after_filter: latest.params.page,
                final_state_sent: latest.params.finalState,
                url: latest.url
            };
        });
});


/* ---------- search is debounced ---------- */

check("search_debounce", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const before = win.requests.length;
            const input = win.document.getElementById("search-input");

            /* Six keystrokes. */
            "guard1".split("").forEach(function (ch, index) {
                input.value = "guard1".slice(0, index + 1);
                input.fire("input", {});
            });

            const duringTyping = win.requests.length - before;

            /* Nothing has fired yet; the stub never runs a
               timer on its own. */
            win.runTimers();

            return settle().then(function () {
                return {
                    requests_during_typing: duringTyping,
                    requests_after_debounce:
                        win.requests.length - before,
                    search_sent:
                        win.requests[win.requests.length - 1].params.search,
                    url: lastUrl(win)
                };
            });
        });
});


/* ---------- search is trimmed and length limited ---------- */

check("search_normalised", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const input = win.document.getElementById("search-input");
            input.value = "   " + "x".repeat(250) + "   ";
            input.fire("input", {});
            win.runTimers();
            return settle();
        })
        .then(function () {
            const sent =
                win.requests[win.requests.length - 1].params.search;
            return {
                length: sent.length,
                trimmed: sent.charAt(0) === "x",
                max: win.VigiloxDocuments.MAX_SEARCH_LENGTH
            };
        });
});


/* ---------- clear search ---------- */

check("clear_search", function () {
    const win = boot({ search: "?search=badge" });

    return settle()
        .then(function () {
            const initial = win.requests[0].params.search;
            win.document.getElementById("clear-search-button").click();
            return settle().then(function () {
                return initial;
            });
        })
        .then(function (initial) {
            const latest = win.requests[win.requests.length - 1];
            return {
                initial_search: initial,
                search_after_clear: latest.params.search,
                input_value: win.document.getElementById(
                    "search-input"
                ).value,
                url: latest.url
            };
        });
});


/* ---------- reset restores every default ---------- */

check("reset_filters", function () {
    const win = boot({
        search:
            "?page=2&page_size=50&search=abc&document_type=id_card" +
            "&final_state=REJECTED&machine_decision=AUTO_ACCEPT" +
            "&expiry_status=EXPIRED&sort=filename&direction=asc"
    });

    return settle()
        .then(function () {
            const initial = win.requests[0].params;
            win.document.getElementById("reset-filters-button").click();
            return settle().then(function () {
                return initial;
            });
        })
        .then(function (initial) {
            const latest = win.requests[win.requests.length - 1];
            return {
                initial: initial,
                after_reset: latest.params,
                url: latest.url,
                controls: {
                    search: win.document.getElementById("search-input")
                        .value,
                    document_type: win.document.getElementById(
                        "document-type-filter"
                    ).value,
                    page_size: win.document.getElementById(
                        "page-size-select"
                    ).value
                }
            };
        });
});


/* ---------- sorting ---------- */

check("sorting", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const headers = win.document
                .getElementById("documents-table")
                .querySelectorAll("thead th");

            /* Click the Type column, which sorts by
               document_type. */
            const typeHeader = headers[1];
            typeHeader.querySelector("button").click();

            return settle().then(function () {
                return {
                    first: win.requests[win.requests.length - 1].params
                };
            });
        })
        .then(function (carry) {
            /* Click the same column again to flip direction. */
            const headers = win.document
                .getElementById("documents-table")
                .querySelectorAll("thead th");

            headers[1].querySelector("button").click();

            return settle().then(function () {
                carry.second =
                    win.requests[win.requests.length - 1].params;
                carry.aria = headerInfo(win).map(function (h) {
                    return h.aria_sort;
                });
                return carry;
            });
        });
});


check("sort_only_whitelisted", function () {
    const win = boot({});

    return settle()
        .then(function () {
            /* Directly attempt a key the backend does not
               allow. */
            win.VigiloxDocuments.toggleSort("reviewer_id");
            win.VigiloxDocuments.toggleSort("id_number");
            return settle();
        })
        .then(function () {
            return {
                request_count: win.requests.length,
                sort_sent: win.requests[0].params.sort
            };
        });
});


check("sort_from_hostile_url", function () {
    const win = boot({
        search: "?sort=drop%20table&direction=sideways"
    });

    return settle().then(function () {
        return {
            sort_sent: win.requests[0].params.sort,
            direction_sent: win.requests[0].params.direction
        };
    });
});


/* ---------- URL state ---------- */

check("url_state", function () {
    const win = boot({
        search:
            "?page=2&search=badge&document_type=sia_badge" +
            "&sort=filename&direction=asc"
    });

    return settle().then(function () {
        return {
            restored: win.requests[0].params,
            control_values: {
                search: win.document.getElementById("search-input").value,
                document_type: win.document.getElementById(
                    "document-type-filter"
                ).value
            },
            history_writes: win.record.historyStates.length,
            history_mode: win.record.historyStates.length
                ? win.record.historyStates[0].mode
                : null,
            written_url: win.record.historyStates.length
                ? win.record.historyStates[0].url
                : null
        };
    });
});


check("url_omits_defaults", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            url: win.record.historyStates[0].url
        };
    });
});


/* ---------- overlapping reads ---------- */

check("stale_response_discarded", function () {
    let resolveFirst = null;

    const win = boot({
        respond: function (index) {
            if (index === 0) {
                return new Promise(function (resolve) {
                    resolveFirst = resolve;
                });
            }
            return Promise.resolve(
                page({
                    items: [item({ document_id: "fresh", filename: "fresh.jpg" })],
                    total: 1,
                    total_pages: 1
                })
            );
        }
    });

    /* Second read starts while the first is still open. */
    const select = win.document.getElementById("document-type-filter");
    select.value = "id_card";
    select.fire("change", {});

    return settle()
        .then(function () {
            /* The first, now stale, read completes LAST. */
            resolveFirst(
                page({
                    items: [
                        item({ document_id: "stale", filename: "stale.jpg" })
                    ],
                    total: 999,
                    total_pages: 40
                })
            );
            return settle();
        })
        .then(function () {
            const table = win.document.getElementById("documents-table");
            return {
                request_count: win.requests.length,
                rendered: table.textContent,
                shows_stale: table.textContent.indexOf("stale.jpg") !== -1,
                shows_fresh: table.textContent.indexOf("fresh.jpg") !== -1,
                status: win.document.getElementById(
                    "documents-status"
                ).textContent
            };
        });
});


check("overlapping_read_is_aborted", function () {
    const signals = [];

    const win = boot({
        respond: function (index, requests, markAborted, signal) {
            signals.push(signal);
            if (index === 0) {
                return new Promise(function () {});
            }
            return Promise.resolve(page({ total: 1, total_pages: 1 }));
        }
    });

    const select = win.document.getElementById("expiry-status-filter");
    select.value = "EXPIRED";
    select.fire("change", {});

    return settle().then(function () {
        return {
            signal_count: signals.length,
            first_signal_aborted: Boolean(
                signals[0] && signals[0].aborted
            ),
            second_signal_aborted: Boolean(
                signals[1] && signals[1].aborted
            )
        };
    });
});


check("abort_is_not_reported_as_error", function () {
    const win = boot({
        respond: function (index) {
            if (index === 0) {
                return Promise.reject({
                    status: 0,
                    code: "REQUEST_ABORTED",
                    message: "The request was cancelled."
                });
            }
            return Promise.resolve(page({ total: 1, total_pages: 1 }));
        }
    });

    return settle().then(function () {
        return {
            error_hidden: win.document.getElementById("documents-error")
                .hidden,
            error_text: win.document.getElementById("documents-error")
                .textContent
        };
    });
});


/* ---------- states ---------- */

check("loading_state", function () {
    const win = boot({
        respond: function () {
            return new Promise(function () {});
        }
    });

    const loading = win.document.getElementById("documents-loading");

    return {
        loading_visible: loading.hidden === false,
        table_hidden: win.document.getElementById("documents-table")
            .hidden,
        error_hidden: win.document.getElementById("documents-error")
            .hidden,
        empty_hidden: win.document.getElementById("documents-empty")
            .hidden,
        skeleton_count: loading.querySelectorAll(".skeleton").length
    };
});


check("empty_database", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                page({ items: [], total: 0, total_pages: 0 })
            );
        }
    });

    return settle().then(function () {
        const empty = win.document.getElementById("documents-empty");
        return {
            empty_visible: empty.hidden === false,
            table_hidden: win.document.getElementById("documents-table")
                .hidden,
            text: empty.textContent,
            has_upload_cta: hrefs(win, "documents-empty").indexOf(
                "/upload"
            ) !== -1,
            status: win.document.getElementById("documents-status")
                .textContent,
            pagination_children: win.document.getElementById(
                "documents-pagination"
            ).childElementCount
        };
    });
});


check("empty_search", function () {
    const win = boot({
        search: "?search=nothingmatches",
        respond: function () {
            return Promise.resolve(
                page({ items: [], total: 0, total_pages: 0 })
            );
        }
    });

    return settle().then(function () {
        const empty = win.document.getElementById("documents-empty");
        return {
            text: empty.textContent,
            button_labels: empty
                .querySelectorAll("button")
                .map(function (b) {
                    return b.textContent;
                }),
            upload_cta: hrefs(win, "documents-empty")
        };
    });
});


check("empty_filtered", function () {
    const win = boot({
        search: "?final_state=REJECTED&document_type=id_card",
        respond: function () {
            return Promise.resolve(
                page({ items: [], total: 0, total_pages: 0 })
            );
        }
    });

    return settle().then(function () {
        const empty = win.document.getElementById("documents-empty");
        return {
            text: empty.textContent,
            button_labels: empty
                .querySelectorAll("button")
                .map(function (b) {
                    return b.textContent;
                })
        };
    });
});


check("empty_search_button_recovers", function () {
    let calls = 0;

    const win = boot({
        search: "?search=nothingmatches",
        respond: function () {
            calls += 1;
            if (calls === 1) {
                return Promise.resolve(
                    page({ items: [], total: 0, total_pages: 0 })
                );
            }
            return Promise.resolve(page());
        }
    });

    return settle()
        .then(function () {
            win.document
                .getElementById("documents-empty")
                .querySelector("button")
                .click();
            return settle();
        })
        .then(function () {
            return {
                calls: calls,
                search_after: win.requests[win.requests.length - 1].params
                    .search,
                table_visible: win.document.getElementById(
                    "documents-table"
                ).hidden === false
            };
        });
});


check("error_state", function () {
    const win = boot({
        respond: function () {
            return Promise.reject({
                status: 500,
                code: "DOCUMENT_LIST_LOAD_FAILED",
                message: "Failed to load documents.",
                requestId: "req-doc-77"
            });
        }
    });

    return settle().then(function () {
        const panel = win.document.getElementById("documents-error");
        const text = panel.textContent;
        return {
            error_visible: panel.hidden === false,
            table_hidden: win.document.getElementById("documents-table")
                .hidden,
            shows_code: text.indexOf("DOCUMENT_LIST_LOAD_FAILED") !== -1,
            shows_message:
                text.indexOf("Failed to load documents.") !== -1,
            shows_request_id: text.indexOf("req-doc-77") !== -1,
            mentions_traceback:
                text.toLowerCase().indexOf("traceback") !== -1,
            retry_buttons: panel.querySelectorAll("button").length,
            status_cleared: win.document.getElementById(
                "documents-status"
            ).textContent,
            pagination_cleared: win.document.getElementById(
                "documents-pagination"
            ).childElementCount
        };
    });
});


check("error_retry_recovers", function () {
    let calls = 0;

    const win = boot({
        respond: function () {
            calls += 1;
            if (calls === 1) {
                return Promise.reject({
                    status: 503,
                    code: "UNAVAILABLE",
                    message: "Try later.",
                    requestId: "r"
                });
            }
            return Promise.resolve(page());
        }
    });

    return settle()
        .then(function () {
            win.document
                .getElementById("documents-error")
                .querySelector("button")
                .click();
            return settle();
        })
        .then(function () {
            return {
                calls: calls,
                table_visible: win.document.getElementById(
                    "documents-table"
                ).hidden === false,
                error_hidden: win.document.getElementById(
                    "documents-error"
                ).hidden
            };
        });
});


/* ---------- safe links ---------- */

check("missing_document_id_is_safe", function () {
    const win = boot({
        respond: function () {
            const broken = item({ document_id: null, filename: "orphan.jpg" });
            delete broken.document_id;
            return Promise.resolve(
                page({ items: [broken], total: 1, total_pages: 1 })
            );
        }
    });

    return settle().then(function () {
        const links = hrefs(win, "documents-table");
        return {
            hrefs: links,
            builds_undefined: links.some(function (h) {
                return (
                    h.indexOf("undefined") !== -1 ||
                    h.indexOf("null") !== -1
                );
            }),
            text: win.document.getElementById("documents-table")
                .textContent
        };
    });
});


check("hostile_filename_is_text", function () {
    const hostile = '<script>alert(1)</script>.jpg';

    const win = boot({
        respond: function () {
            return Promise.resolve(
                page({
                    items: [item({ filename: hostile })],
                    total: 1,
                    total_pages: 1
                })
            );
        }
    });

    return settle().then(function () {
        const table = win.document.getElementById("documents-table");
        return {
            renders_literally: table.textContent.indexOf(hostile) !== -1,
            script_elements: table.querySelectorAll("script").length
        };
    });
});


/* ---------- keyboard reachable controls ---------- */

check("keyboard_controls", function () {
    const win = boot({});

    return settle().then(function () {
        const table = win.document.getElementById("documents-table");
        const pagination = win.document.getElementById(
            "documents-pagination"
        );

        /* Every interactive control is a real button or anchor,
           so it is focusable and announced without any
           tabindex or role patching. */
        const sortControls = table.querySelectorAll("thead button");
        const openControls = table.querySelectorAll("tbody a");

        return {
            sort_buttons: sortControls.length,
            sort_all_buttons: sortControls.every(function (n) {
                return n.tagName === "button";
            }),
            sort_button_types: sortControls.map(function (n) {
                return n.getAttribute("type");
            }),
            open_links: openControls.length,
            page_buttons: pagination.querySelectorAll("button").length,
            no_div_buttons:
                table.querySelectorAll('[role="button"]').length
        };
    });
});


/* ---------- submitting the toolbar does not reload ---------- */

check("form_submit_is_intercepted", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const before = win.requests.length;
            const form = win.document.getElementById("filter-form");
            const input = win.document.getElementById("search-input");

            input.value = "typed";

            let prevented = false;
            form.dispatchEvent({
                type: "submit",
                preventDefault: function () {
                    prevented = true;
                }
            });

            return settle().then(function () {
                return {
                    prevented: prevented,
                    new_requests: win.requests.length - before,
                    search_sent:
                        win.requests[win.requests.length - 1].params.search
                };
            });
        });
});


/* ==========================================================
   OUTPUT
   ========================================================== */

Promise.all(queue).then(function () {
    process.stdout.write(JSON.stringify(results, null, 1));
});
