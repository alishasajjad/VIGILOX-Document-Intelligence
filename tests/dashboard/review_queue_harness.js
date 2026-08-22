/* ==========================================================
   VIGILOX REVIEW QUEUE HARNESS
   PHASE 8.9
   ==========================================================

   Executes frontend/static/dashboard.js (the Review Queue)
   under Node against the shared DOM stub.

   dashboard.js keeps its Phase 7B filename; the module it
   contains is the Review Queue, not the Dashboard.

   Prints one JSON object of results on stdout.
   ========================================================== */

"use strict";

const stub = require("./dom_stub.js");


/* ==========================================================
   FIXTURE
   ==========================================================
   Shaped exactly like GET /api/v1/reviews/queue.
   ========================================================== */

function queueItem(overrides) {
    return Object.assign(
        {
            document_id: "doc-high",
            analysis_id: "an-1",
            original_filename: "guard_front.jpg",
            content_type: "image/jpeg",
            document_type: "guard_license",
            processing_status: "PROCESSED",
            review_decision: "REVIEW_REQUIRED",
            review_priority: "HIGH",
            reason_codes: [
                "MISSING_CRITICAL_FIELD",
                "CRITICAL_FIELD_NOT_TRUSTED"
            ],
            review_issues: [
                {
                    code: "MISSING_CRITICAL_FIELD",
                    severity: "ERROR",
                    field: "licence_number",
                    message: "Required field is missing."
                }
            ],
            anomaly_issues: [
                {
                    code: "MISSING_CRITICAL_FIELD",
                    severity: "ERROR",
                    field: "licence_number",
                    message: "Required field is missing."
                },
                {
                    code: "DOCUMENT_EXPIRED",
                    severity: "WARNING",
                    field: "expiry_date",
                    message: "The document expiry date is in the past."
                }
            ],
            created_at: "2026-08-01T09:15:00",
            analysis_created_at: "2026-08-01T09:15:20"
        },
        overrides || {}
    );
}


function queue(overrides) {
    const documents =
        (overrides && overrides.documents) || [
            queueItem({}),
            queueItem({
                document_id: "doc-medium",
                analysis_id: "an-2",
                original_filename: "badge.png",
                document_type: "sia_badge",
                review_priority: "MEDIUM",
                reason_codes: ["DOCUMENT_EXPIRED"],
                anomaly_issues: [
                    {
                        code: "DOCUMENT_EXPIRED",
                        severity: "WARNING",
                        field: "expiry_date",
                        message: "Expired."
                    }
                ]
            }),
            queueItem({
                document_id: "doc-low",
                analysis_id: "an-3",
                original_filename: "card.jpg",
                document_type: "id_card",
                review_priority: "LOW",
                reason_codes: ["DOCUMENT_EXPIRING_SOON"],
                anomaly_issues: [
                    {
                        code: "DOCUMENT_EXPIRING_SOON",
                        severity: "WARNING",
                        field: "expiry_date",
                        message: "Expiring soon."
                    }
                ]
            })
        ];

    return Object.assign(
        {
            total: documents.length,
            filters: { priority: null, document_type: null },
            documents: documents
        },
        overrides || {},
        { documents: documents }
    );
}


/* ==========================================================
   BOOT
   ========================================================== */

function boot(options) {
    const config = options || {};
    const calls = { queue: [], reviewer: 0, health: 0 };

    const win = stub.createWindow({
        pathname: "/review",
    });

    /* The real shipped page, parsed into a real element
       tree. A renamed id or a moved element breaks the
       test rather than being papered over. */
    stub.loadPage(win, "index.html");

    stub.loadScript(win, "js/api.js");
    stub.loadScript(win, "js/common.js");
    stub.loadScript(win, "js/vocabulary.js");

    win.VigiloxApi.endpoints.getReviewQueue = function (filters) {
        const index = calls.queue.length;
        calls.queue.push(filters);

        const responder =
            config.respond ||
            function () {
                return Promise.resolve(queue());
            };

        return responder(index, filters);
    };

    win.VigiloxApi.endpoints.getHealth = function () {
        calls.health += 1;
        return Promise.resolve({ status: "ok" });
    };

    win.VigiloxApi.endpoints.getReviewerIdentity = function () {
        calls.reviewer += 1;
        return Promise.resolve({
            reviewer: {
                reviewer_id: config.reviewerId || "queue-reviewer",
                role: "REVIEWER",
                source: "LOCAL_ENV",
                can_review: config.canReview !== false
            }
        });
    };

    stub.loadScript(win, "dashboard.js");
    win.document.ready();

    win.calls = calls;

    return win;
}


function settle(rounds) {
    let chain = Promise.resolve();
    for (let i = 0; i < (rounds || 3); i += 1) {
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

function rows(win) {
    return win.document
        .getElementById("queue-table-container")
        .querySelectorAll("tbody tr");
}

function statCards(win) {
    return win.document
        .getElementById("queue-summary")
        .querySelectorAll(".stat-card")
        .map(function (card) {
            const label = card.querySelector(".stat-label");
            const value = card.querySelector(".stat-value");
            return {
                label: label ? label.textContent : null,
                value: value ? value.textContent : null,
                attention: card.classList.contains("is-attention"),
                critical: card.classList.contains("is-critical")
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
                            .slice(0, 4)
                            .join(" | ")
                    };
                }
            )
    );
}


/* ---------- module surface ---------- */

check("module_surface", function () {
    const win = boot({
        respond: function () {
            return new Promise(function () {});
        }
    });

    return {
        exposed: Boolean(win.VigiloxReviewQueue),
        /* The Dashboard module must NOT be what this file
           defines. Confusing the two would run the wrong page
           at /review. */
        is_not_dashboard: !win.VigiloxDashboard,
        priorities: win.VigiloxReviewQueue.PRIORITIES,
        document_types: win.VigiloxReviewQueue.DOCUMENT_TYPES,
        columns: win.VigiloxReviewQueue.COLUMNS,
        visible_reasons: win.VigiloxReviewQueue.VISIBLE_REASONS,
        vocabulary_loaded: Boolean(win.VigiloxVocabulary)
    };
});


/* ---------- one request per load ---------- */

check("single_request", function () {
    const win = boot({});

    return settle().then(function () {
        return {
            request_count: win.calls.queue.length,
            first_filters: win.calls.queue[0],
            reviewer_calls: win.calls.reviewer,
            health_calls: win.calls.health,
            intervals: win.record.intervals.length
        };
    });
});


/* ---------- rows preserve server order ---------- */

check("row_render", function () {
    const win = boot({});

    return settle().then(function () {
        const list = rows(win);

        return {
            row_count: list.length,
            priorities: list.map(function (row) {
                const badge = row.querySelector(
                    '[class*="badge-priority"]'
                );
                return badge ? badge.textContent : null;
            }),
            filenames: list.map(function (row) {
                const cell = row.querySelector(".table-primary-cell");
                return cell ? cell.textContent : null;
            }),
            open_hrefs: win.document
                .getElementById("queue-table-container")
                .querySelectorAll("tbody a")
                .map(function (a) {
                    return a.getAttribute("href");
                }),
            open_labels: win.document
                .getElementById("queue-table-container")
                .querySelectorAll("tbody a")
                .map(function (a) {
                    return a.textContent;
                }),
            headers: win.document
                .getElementById("queue-table-container")
                .querySelectorAll("thead th")
                .map(function (th) {
                    return th.textContent;
                }),
            /* The queue API supports no sorting, so no header
               may pretend to sort. */
            header_buttons: win.document
                .getElementById("queue-table-container")
                .querySelectorAll("thead button").length,
            status: win.document.getElementById("queue-status")
                .textContent
        };
    });
});


/* ---------- readable review reasons ---------- */

check("reason_presentation", function () {
    const win = boot({});

    return settle().then(function () {
        const first = rows(win)[0];
        const chips = first.querySelectorAll(".reason-chip");

        return {
            chip_labels: chips.map(function (chip) {
                return chip.textContent;
            }),
            chip_titles: chips.map(function (chip) {
                return chip.getAttribute("title");
            }),
            /* The raw code must survive somewhere, so the
               readable label and the contract stay connected. */
            code_available: chips.some(function (chip) {
                return (
                    (chip.getAttribute("title") || "").indexOf(
                        "MISSING_CRITICAL_FIELD"
                    ) !== -1
                );
            }),
            /* ... but the raw code is not the visible label. */
            raw_code_visible: chips.some(function (chip) {
                return (
                    chip.textContent === "MISSING_CRITICAL_FIELD"
                );
            })
        };
    });
});


check("reason_deduplicated_and_capped", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            reason_codes: [
                                "MISSING_CRITICAL_FIELD",
                                "MISSING_CRITICAL_FIELD",
                                "MISSING_CRITICAL_FIELD",
                                "CRITICAL_FIELD_NOT_TRUSTED",
                                "DOCUMENT_EXPIRED",
                                "FUTURE_ISSUE_DATE",
                                "DOB_AFTER_EXPIRY_DATE"
                            ]
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const chips = rows(win)[0].querySelectorAll(".reason-chip");
        const more = rows(win)[0].querySelector(".reason-chip.is-more");

        return {
            chip_count: chips.length,
            visible_limit: win.VigiloxReviewQueue.VISIBLE_REASONS,
            more_label: more ? more.textContent : null,
            more_title: more ? more.getAttribute("title") : null
        };
    });
});


check("unknown_reason_code_is_shown", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            reason_codes: [
                                "SOME_FUTURE_BACKEND_CODE"
                            ]
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const chip = rows(win)[0].querySelector(".reason-chip");
        return {
            label: chip ? chip.textContent : null,
            marked_unknown: chip
                ? chip.classList.contains("is-unknown")
                : false,
            title: chip ? chip.getAttribute("title") : null
        };
    });
});


check("no_reason_codes", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            reason_codes: [],
                            anomaly_issues: []
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const row = rows(win)[0];
        return {
            row_rendered: Boolean(row),
            text: row ? row.textContent : null
        };
    });
});


/* ---------- severities come from the backend only ---------- */

check("severity_presentation", function () {
    const win = boot({});

    return settle().then(function () {
        const badges = rows(win)[0]
            .querySelectorAll(".badge-stack .badge")
            .map(function (b) {
                return {
                    text: b.textContent,
                    className: b.className
                };
            });

        return { badges: badges };
    });
});


check("unknown_severity_is_not_relabelled", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            anomaly_issues: [
                                {
                                    code: "X",
                                    severity: "CATASTROPHIC",
                                    field: null,
                                    message: "m"
                                }
                            ]
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const badges = rows(win)[0]
            .querySelectorAll(".badge-stack .badge")
            .map(function (b) {
                return { text: b.textContent, className: b.className };
            });

        return {
            badges: badges,
            /* An unrecognised severity must not be presented
               as ERROR or WARNING. */
            claims_error: badges.some(function (b) {
                return b.className.indexOf("severity-error") !== -1;
            }),
            claims_warning: badges.some(function (b) {
                return b.className.indexOf("severity-warning") !== -1;
            })
        };
    });
});


/* ---------- priority is not recalculated ---------- */

check("priority_is_server_authoritative", function () {
    const win = boot({
        respond: function () {
            /* Deliberately out of "natural" order: LOW first,
               with a HIGH-severity error attached to it. If the
               client re-sorted or re-derived urgency, this row
               would move or change badge. */
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            document_id: "doc-a",
                            review_priority: "LOW",
                            anomaly_issues: [
                                {
                                    code: "MISSING_CRITICAL_FIELD",
                                    severity: "ERROR",
                                    field: "id_number",
                                    message: "m"
                                }
                            ]
                        }),
                        queueItem({
                            document_id: "doc-b",
                            review_priority: "HIGH",
                            anomaly_issues: []
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const list = rows(win);
        return {
            order: list.map(function (row) {
                const badge = row.querySelector(
                    '[class*="badge-priority"]'
                );
                return badge ? badge.textContent : null;
            }),
            ids: list.map(function (row) {
                const cell = row.querySelector(
                    ".table-secondary-text"
                );
                return cell ? cell.textContent : null;
            })
        };
    });
});


/* ---------- summary counts the returned rows ---------- */

check("summary", function () {
    const win = boot({});

    return settle().then(function () {
        return { cards: statCards(win) };
    });
});


/* ---------- filters ---------- */

check("priority_filter", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "priority-filter"
            );
            select.value = "HIGH";
            select.fire("change", {});
            return settle();
        })
        .then(function () {
            return {
                request_count: win.calls.queue.length,
                last_filters:
                    win.calls.queue[win.calls.queue.length - 1]
            };
        });
});


check("document_type_filter", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "document-type-filter"
            );
            select.value = "id_card";
            select.fire("change", {});
            return settle();
        })
        .then(function () {
            return {
                last_filters:
                    win.calls.queue[win.calls.queue.length - 1]
            };
        });
});


check("tampered_filter_is_refused", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const priority = win.document.getElementById(
                "priority-filter"
            );
            priority.value = "URGENT";
            priority.fire("change", {});

            const type = win.document.getElementById(
                "document-type-filter"
            );
            type.value = "passport";
            type.fire("change", {});

            return settle();
        })
        .then(function () {
            return {
                filters_sent: win.calls.queue.map(function (f) {
                    return {
                        priority: f.priority,
                        documentType: f.documentType
                    };
                })
            };
        });
});


check("reset_filters", function () {
    const win = boot({});

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "priority-filter"
            );
            select.value = "LOW";
            select.fire("change", {});
            return settle();
        })
        .then(function () {
            win.document
                .getElementById("reset-filters-button")
                .click();
            return settle();
        })
        .then(function () {
            return {
                last_filters:
                    win.calls.queue[win.calls.queue.length - 1],
                priority_control: win.document.getElementById(
                    "priority-filter"
                ).value,
                type_control: win.document.getElementById(
                    "document-type-filter"
                ).value
            };
        });
});


check("concurrent_refresh_guard", function () {
    const win = boot({
        respond: function () {
            return new Promise(function () {});
        }
    });

    const refresh = win.document.getElementById("refresh-button");
    refresh.click();
    refresh.click();
    refresh.click();

    return {
        request_count: win.calls.queue.length,
        refresh_disabled: refresh.disabled
    };
});


check("form_submit_is_intercepted", function () {
    const win = boot({});

    return settle()
        .then(function () {
            let prevented = false;
            win.document
                .getElementById("queue-filter-form")
                .dispatchEvent({
                    type: "submit",
                    preventDefault: function () {
                        prevented = true;
                    }
                });
            return settle().then(function () {
                return prevented;
            });
        })
        .then(function (prevented) {
            return {
                prevented: prevented,
                request_count: win.calls.queue.length
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

    const loading = win.document.getElementById("queue-loading");

    return {
        loading_visible: loading.hidden === false,
        table_hidden: win.document.getElementById(
            "queue-table-container"
        ).hidden,
        error_hidden: win.document.getElementById("queue-error")
            .hidden,
        empty_hidden: win.document.getElementById("queue-empty")
            .hidden,
        skeleton_count: loading.querySelectorAll(".skeleton").length
    };
});


check("empty_queue", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve({
                total: 0,
                filters: { priority: null, document_type: null },
                documents: []
            });
        }
    });

    return settle().then(function () {
        const empty = win.document.getElementById("queue-empty");
        return {
            empty_visible: empty.hidden === false,
            table_hidden: win.document.getElementById(
                "queue-table-container"
            ).hidden,
            text: empty.textContent,
            hrefs: empty.querySelectorAll("a").map(function (a) {
                return a.getAttribute("href");
            }),
            status: win.document.getElementById("queue-status")
                .textContent,
            /* Zeros are legitimate here: the read completed and
               the queue really is empty. */
            summary_cards: statCards(win).length
        };
    });
});


check("empty_filtered_queue", function () {
    const win = boot({
        respond: function (index) {
            if (index === 0) {
                return Promise.resolve(queue());
            }
            return Promise.resolve({
                total: 0,
                filters: { priority: "HIGH", document_type: null },
                documents: []
            });
        }
    });

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "priority-filter"
            );
            select.value = "HIGH";
            select.fire("change", {});
            return settle();
        })
        .then(function () {
            const empty = win.document.getElementById("queue-empty");
            return {
                text: empty.textContent,
                button_labels: empty
                    .querySelectorAll("button")
                    .map(function (b) {
                        return b.textContent;
                    }),
                status: win.document.getElementById("queue-status")
                    .textContent
            };
        });
});


check("filtered_empty_recovers", function () {
    const win = boot({
        respond: function (index) {
            if (index === 1) {
                return Promise.resolve({
                    total: 0,
                    filters: {
                        priority: "HIGH",
                        document_type: null
                    },
                    documents: []
                });
            }
            return Promise.resolve(queue());
        }
    });

    return settle()
        .then(function () {
            const select = win.document.getElementById(
                "priority-filter"
            );
            select.value = "HIGH";
            select.fire("change", {});
            return settle();
        })
        .then(function () {
            win.document
                .getElementById("queue-empty")
                .querySelector("button")
                .click();
            return settle();
        })
        .then(function () {
            return {
                request_count: win.calls.queue.length,
                last_filters:
                    win.calls.queue[win.calls.queue.length - 1],
                table_visible: win.document.getElementById(
                    "queue-table-container"
                ).hidden === false
            };
        });
});


check("error_state", function () {
    const win = boot({
        respond: function () {
            return Promise.reject({
                status: 500,
                code: "REVIEW_QUEUE_LOAD_FAILED",
                message: "Failed to load review queue.",
                requestId: "req-queue-12",
                /* Present so the test can prove the new code
                   does not fall back to it while a structured
                   error is available. */
                detail: "legacy detail string"
            });
        }
    });

    return settle().then(function () {
        const panel = win.document.getElementById("queue-error");
        const text = panel.textContent;

        return {
            error_visible: panel.hidden === false,
            table_hidden: win.document.getElementById(
                "queue-table-container"
            ).hidden,
            shows_code: text.indexOf("REVIEW_QUEUE_LOAD_FAILED") !== -1,
            shows_message:
                text.indexOf("Failed to load review queue.") !== -1,
            shows_request_id: text.indexOf("req-queue-12") !== -1,
            uses_legacy_detail:
                text.indexOf("legacy detail string") !== -1,
            mentions_traceback:
                text.toLowerCase().indexOf("traceback") !== -1,
            retry_buttons: panel.querySelectorAll("button").length,
            summary_cleared: win.document.getElementById(
                "queue-summary"
            ).childElementCount,
            status_cleared: win.document.getElementById("queue-status")
                .textContent
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
                    message: "later",
                    requestId: "r"
                });
            }
            return Promise.resolve(queue());
        }
    });

    return settle()
        .then(function () {
            win.document
                .getElementById("queue-error")
                .querySelector("button")
                .click();
            return settle();
        })
        .then(function () {
            return {
                calls: calls,
                table_visible: win.document.getElementById(
                    "queue-table-container"
                ).hidden === false,
                error_hidden: win.document.getElementById(
                    "queue-error"
                ).hidden
            };
        });
});


/* ---------- reviewer identity ---------- */

check("reviewer_identity", function () {
    const win = boot({ reviewerId: "queue-operator" });

    return settle().then(function () {
        return {
            calls: win.calls.reviewer,
            shell_name: win.document.getElementById(
                "shell-reviewer-name"
            ).textContent,
            shell_access: win.document.getElementById(
                "shell-reviewer-access"
            ).textContent,
            /* There must be no way for the browser to state who
               the reviewer is. */
            identity_inputs: win.document.body.querySelectorAll(
                "input"
            ).length
        };
    });
});


check("read_only_reviewer_still_sees_the_queue", function () {
    const win = boot({ canReview: false });

    return settle().then(function () {
        return {
            table_visible: win.document.getElementById(
                "queue-table-container"
            ).hidden === false,
            shell_access: win.document.getElementById(
                "shell-reviewer-access"
            ).textContent,
            open_links: win.document
                .getElementById("queue-table-container")
                .querySelectorAll("tbody a").length
        };
    });
});


/* ---------- safety ---------- */

check("missing_document_id_is_safe", function () {
    const win = boot({
        respond: function () {
            const broken = queueItem({});
            delete broken.document_id;
            return Promise.resolve(
                queue({ documents: [broken] })
            );
        }
    });

    return settle().then(function () {
        const links = win.document
            .getElementById("queue-table-container")
            .querySelectorAll("tbody a")
            .map(function (a) {
                return a.getAttribute("href");
            });

        return {
            hrefs: links,
            builds_undefined: links.some(function (h) {
                return (
                    h.indexOf("undefined") !== -1 ||
                    h.indexOf("null") !== -1
                );
            }),
            text: win.document.getElementById(
                "queue-table-container"
            ).textContent
        };
    });
});


check("hostile_values_are_text", function () {
    const filename = '<img src=x onerror="alert(1)">.jpg';
    const message = "<b>bold</b> message";

    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            original_filename: filename,
                            anomaly_issues: [
                                {
                                    code: "<script>x</script>",
                                    severity: "ERROR",
                                    field: "full_name",
                                    message: message
                                }
                            ]
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const container = win.document.getElementById(
            "queue-table-container"
        );

        return {
            filename_literal:
                container.textContent.indexOf(filename) !== -1,
            img_elements: container.querySelectorAll("img").length,
            script_elements: container.querySelectorAll("script")
                .length,
            b_elements: container.querySelectorAll("b").length
        };
    });
});


check("no_personal_data_in_queue", function () {
    const win = boot({
        respond: function () {
            return Promise.resolve(
                queue({
                    documents: [
                        queueItem({
                            /* Keys the queue schema does not
                               carry. Present only to prove the
                               renderer never echoes unknown
                               fields. */
                            extraction: {
                                full_name: { value: "SAMPLE,JANE" }
                            },
                            ocr_lines: [
                                { line_id: "L0", text: "TEXAS DPS" }
                            ],
                            field_confidence: {
                                full_name: { value: "SAMPLE,JANE" }
                            }
                        })
                    ]
                })
            );
        }
    });

    return settle().then(function () {
        const text = win.document.getElementById(
            "queue-table-container"
        ).textContent;

        return {
            leaks_name: text.indexOf("SAMPLE,JANE") !== -1,
            leaks_ocr: text.indexOf("TEXAS DPS") !== -1
        };
    });
});


/* ==========================================================
   OUTPUT
   ========================================================== */

Promise.all(jobs).then(function () {
    process.stdout.write(JSON.stringify(results, null, 1));
});
