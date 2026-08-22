/* ==========================================================
   VIGILOX FINAL RESULT / HISTORY / TECHNICAL DATA
   PHASE 8.14
   ==========================================================

   Three things, all driven by what FinalRecordService already
   resolved:

       the final record and whether it is usable
       machine value / human correction / effective value
       the audit timeline, plus raw JSON behind a tab


   THE FIVE FINAL STATES ARE THE BACKEND'S
   ----------------------------------------------------------
   AUTO_ACCEPTED, PENDING_REVIEW, APPROVED, CORRECTED and
   REJECTED come from FinalRecordService. No sixth state is
   invented here, and "usable" is read from the record's own
   is_usable rather than re-derived from the status, so the
   wording and the record can never disagree.

       PENDING_REVIEW  not final, not usable, and the service
                       publishes no effective values at all
       REJECTED        final, but not usable, and again no
                       effective values

   Both are presented as exactly that. Neither is dressed up as
   a usable result.


   THE MACHINE READING IS NEVER HIDDEN
   ----------------------------------------------------------
   A corrected field shows the machine value, the corrected
   value and the effective value together, with the provenance
   beside them. Hiding the original would destroy the reviewer's
   only way to see what was changed.


   RAW JSON IS SECONDARY
   ----------------------------------------------------------
   It is the last tab, never the default. It is kept because
   developers and reviewers genuinely need it, and Copy and
   Download are offered because both are trivial and safe from
   data already in the page.
   ========================================================== */

(function (global) {
    "use strict";

    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* Matches FinalRecordService.FIELD_NAMES. */
    var FIELD_NAMES = [
        "document_type",
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer"
    ];


    var nodes = {};

    var model = {
        finalRecord: null,
        humanReview: null,
        history: null,
        raw: null
    };


    function collectNodes() {
        nodes = {
            finalRecord: ui.byId("final-record"),
            effectiveValues: ui.byId("effective-values"),
            history: ui.byId("review-history-list"),
            raw: ui.byId("raw-data"),
            overview: ui.byId("overview-panel"),
            badges: ui.byId("document-badges")
        };
    }


    /* ======================================================
       FINAL RECORD
       ====================================================== */

    function usabilityBadge(record) {
        /* is_usable is the service's own answer. */
        if (!record) {
            return ui.badge("Unknown", "badge-neutral");
        }
        return record.is_usable
            ? ui.badge("Usable", "badge-success")
            : ui.badge("Not usable", "badge-danger");
    }

    function finalityBadge(record) {
        if (!record) {
            return ui.badge("Unknown", "badge-neutral");
        }
        return record.is_final
            ? ui.badge("Final", "badge-info")
            : ui.badge("Not final", "badge-warning");
    }

    function renderFinalRecord(finalRecord) {
        model.finalRecord = finalRecord || null;

        if (!nodes.finalRecord) {
            return;
        }

        if (!finalRecord) {
            ui.replaceChildren(nodes.finalRecord, [
                ui.emptyState({
                    title: "No final record",
                    description:
                        "A final record is built once an " +
                        "analysis exists for this document."
                })
            ]);
            return;
        }

        var described = vocabulary.describeFinalStatus(
            finalRecord.final_status
        );

        ui.replaceChildren(nodes.finalRecord, [
            ui.el("section", {
                className:
                    "final-record final-record-" +
                    String(described.status || "unknown")
                        .toLowerCase()
                        .replace(/_/g, "-"),
                children: [
                    ui.el("div", {
                        className: "final-record-head",
                        children: [
                            ui.el("h3", {
                                className: "final-record-status",
                                text: described.label
                            }),
                            ui.el("div", {
                                className: "badge-stack",
                                children: [
                                    finalityBadge(finalRecord),
                                    usabilityBadge(finalRecord)
                                ]
                            })
                        ]
                    }),
                    described.note
                        ? ui.el("p", {
                            className: "final-record-note",
                            text: described.note
                        })
                        : null,
                    finalRecord.human_action
                        ? ui.el("p", {
                            className: "final-record-action",
                            children: [
                                ui.el("span", {
                                    text: "Reviewer decision: "
                                }),
                                ui.badge(
                                    vocabulary.describeHumanAction(
                                        finalRecord.human_action
                                    ).pastLabel,
                                    "badge-info"
                                )
                            ]
                        })
                        : null
                ]
            })
        ]);
    }


    /* ======================================================
       EFFECTIVE VALUES
       ======================================================
       Machine, correction and effective side by side.
       ====================================================== */

    function valueCell(label, value, className) {
        return ui.el("div", {
            className: "value-cell " + (className || ""),
            children: [
                ui.el("span", {
                    className: "value-cell-label",
                    text: label
                }),
                ui.el("span", {
                    className:
                        "value-cell-value" +
                        (ui.isBlank(value) ? " is-empty" : ""),
                    /* Extracted content, rendered as text. */
                    text: ui.isBlank(value)
                        ? "Not set"
                        : String(value)
                })
            ]
        });
    }

    function renderEffectiveValues(finalRecord) {
        if (!nodes.effectiveValues) {
            return;
        }

        if (!finalRecord) {
            ui.clear(nodes.effectiveValues);
            return;
        }

        var machine = finalRecord.machine_values || {};
        var effective = finalRecord.effective_values;
        var sources = finalRecord.value_sources || {};

        var described = vocabulary.describeFinalStatus(
            finalRecord.final_status
        );

        /* ==================================================
           NO EFFECTIVE VALUES
           ==================================================
           PENDING_REVIEW and REJECTED both publish none. Say
           which, and say plainly that nothing here is usable
           downstream. The machine reading is still shown,
           clearly labelled as not effective.
           ================================================== */

        if (!effective) {
            ui.replaceChildren(nodes.effectiveValues, [
                ui.el("div", {
                    className: "alert alert-warning",
                    attrs: { role: "note" },
                    children: [
                        ui.el("div", {
                            className: "alert-body",
                            children: [
                                ui.el("p", {
                                    className: "alert-title",
                                    text:
                                        "No effective values are " +
                                        "published"
                                }),
                                ui.el("p", {
                                    text:
                                        described.note ||
                                        "This document publishes no " +
                                        "effective values."
                                })
                            ]
                        })
                    ]
                }),
                ui.el("h3", {
                    className: "value-table-title",
                    text: "Machine reading"
                }),
                ui.el("p", {
                    className: "field-hint",
                    text:
                        "Shown for reference only. These values " +
                        "are not the document's effective " +
                        "record and must not be used " +
                        "downstream."
                }),
                ui.el("div", {
                    className: "value-rows",
                    children: FIELD_NAMES.map(function (name) {
                        return ui.el("div", {
                            className: "value-row",
                            children: [
                                ui.el("div", {
                                    className: "value-row-label",
                                    text: vocabulary.fieldLabel(name)
                                }),
                                valueCell(
                                    "Machine",
                                    machine[name],
                                    "is-machine"
                                ),
                                ui.el("div", {
                                    className: "value-row-source",
                                    children: [
                                        ui.badge(
                                            "Withheld",
                                            "badge-neutral"
                                        )
                                    ]
                                })
                            ]
                        });
                    })
                })
            ]);
            return;
        }

        /* ==================================================
           EFFECTIVE VALUES EXIST
           ================================================== */

        var correctedCount = 0;

        var rows = FIELD_NAMES.map(function (name) {
            var source = sources[name] || "MACHINE";
            var corrected = source === "HUMAN_CORRECTION";

            if (corrected) {
                correctedCount += 1;
            }

            var cells = [
                ui.el("div", {
                    className: "value-row-label",
                    text: vocabulary.fieldLabel(name)
                }),
                valueCell("Machine", machine[name], "is-machine")
            ];

            /* The correction column only exists where a human
               actually changed something, so an approved
               document is not padded with empty columns. */
            if (corrected) {
                cells.push(
                    valueCell(
                        "Human correction",
                        effective[name],
                        "is-human"
                    )
                );
            }

            cells.push(
                valueCell(
                    "Effective",
                    effective[name],
                    "is-effective"
                )
            );

            cells.push(
                ui.el("div", {
                    className: "value-row-source",
                    children: [ui.provenanceBadge(source)]
                })
            );

            return ui.el("div", {
                className:
                    "value-row" + (corrected ? " is-corrected" : ""),
                children: cells
            });
        });

        ui.replaceChildren(nodes.effectiveValues, [
            ui.el("h3", {
                className: "value-table-title",
                text: "Effective record"
            }),
            ui.el("p", {
                className: "field-hint",
                text:
                    correctedCount > 0
                        ? correctedCount +
                          (correctedCount === 1
                              ? " field was corrected by a reviewer. "
                              : " fields were corrected by a reviewer. ") +
                          "The machine reading is preserved beside " +
                          "each correction."
                        : "No field was corrected. Every effective " +
                          "value is the machine reading."
            }),
            ui.el("div", {
                className: "value-rows",
                children: rows
            })
        ]);
    }


    /* ======================================================
       OVERVIEW
       ======================================================
       The always-visible summary. Answers "where does this
       document stand" without opening a tab or reading JSON.
       ====================================================== */

    /* ======================================================
       CLASSIFICATION
       PHASE 10.2
       ======================================================
       Whether this file is a supported document type. A
       separate question from image quality, and from whether
       the extracted values are trustworthy.

       The row is only added when the answer is not SUPPORTED.
       On a Guard Licence that classified correctly, a row
       reading "Supported document" states the obvious once per
       document and pushes the rows that matter further down.
       ====================================================== */

    function classificationRow(context) {
        var classification = context.classification || null;

        if (!classification) {
            return null;
        }

        var described = vocabulary.describeClassification(
            classification.outcome
        );

        if (described.outcome === "SUPPORTED") {
            return null;
        }

        return ui.el("div", {
            className: "detail-row",
            children: [
                ui.el("span", {
                    className: "detail-label",
                    text: "Classification"
                }),
                ui.el("span", {
                    className: "detail-value",
                    children: [
                        ui.badge(
                            described.label,
                            described.tone === "warning"
                                ? "badge-warning"
                                : "badge-neutral"
                        )
                    ]
                })
            ]
        });
    }

    /* The callout above the overview rows. Carries the
       server-authored sentence and the supported-type list, so
       the three type names are not typed out a second time in
       the frontend. */
    function unsupportedCallout(context) {
        var classification = context.classification || null;

        if (
            !classification ||
            classification.supported !== false
        ) {
            return null;
        }

        var described = vocabulary.describeClassification(
            classification.outcome
        );

        var types =
            classification.supported_document_types || [];

        return ui.el("div", {
            className:
                "alert " +
                (described.tone === "warning"
                    ? "alert-warning"
                    : "alert-info"),
            children: [
                ui.el("p", {
                    className: "alert-title",
                    text: described.label
                }),
                ui.el("p", {
                    /* Server-authored. */
                    text: ui.displayValue(
                        classification.message
                    )
                }),
                types.length
                    ? ui.el("p", {
                        className: "field-hint",
                        text:
                            "Supported document types: " +
                            types.join(", ") +
                            "."
                    })
                    : null
            ]
        });
    }

    function renderOverview(context) {
        if (!nodes.overview) {
            return;
        }

        var finalRecord = context.finalRecord || null;
        var decision = context.reviewDecision || {};
        var expiry =
            (context.dateValidation &&
                context.dateValidation.expiry) ||
            null;
        var anomaly = context.anomalyValidation || {};

        var described = vocabulary.describeFinalStatus(
            finalRecord ? finalRecord.final_status : null
        );

        var errors = anomaly.error_count;
        var warnings = anomaly.warning_count;

        var rows = [
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Final status"
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [
                            ui.finalStateBadge(
                                finalRecord
                                    ? finalRecord.final_status
                                    : null
                            ),
                            usabilityBadge(finalRecord)
                        ]
                    })
                ]
            }),
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Machine decision"
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [
                            /* PHASE 10.2. Was humanizeEnum,
                               which turned the two old values
                               into readable labels by rule.
                               UNSUPPORTED_DOCUMENT needs
                               explaining rather than
                               capitalising, so the vocabulary
                               owns all three. */
                            ui.el("span", {
                                text: vocabulary
                                    .describeMachineDecision(
                                        decision.decision
                                    ).label
                            }),
                            decision.priority &&
                            decision.priority !== "NONE"
                                ? ui.priorityBadge(decision.priority)
                                : null
                        ]
                    })
                ]
            }),
            classificationRow(context),
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Validity"
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [
                            ui.expiryBadge(
                                expiry ? expiry.status : null
                            ),
                            expiry && expiry.value
                                ? ui.el("span", {
                                    text: ui.formatDate(expiry.value)
                                })
                                : null
                        ]
                    })
                ]
            }),
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Findings"
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [
                            typeof errors === "number" ||
                            typeof warnings === "number"
                                ? ui.el("span", {
                                    text:
                                        (errors || 0) +
                                        ((errors || 0) === 1
                                            ? " error, "
                                            : " errors, ") +
                                        (warnings || 0) +
                                        ((warnings || 0) === 1
                                            ? " warning"
                                            : " warnings")
                                })
                                : ui.el("span", {
                                    className: "is-empty",
                                    text: "Not recorded"
                                })
                        ]
                    })
                ]
            })
        ];

        ui.replaceChildren(nodes.overview, [
            unsupportedCallout(context),
            described.note
                ? ui.el("p", {
                    className: "overview-note",
                    text: described.note
                })
                : null,
            ui.el("div", {
                className: "detail-rows",
                children: rows
            })
        ]);
    }


    /* ======================================================
       HEADER BADGES
       ====================================================== */

    function renderBadges(context) {
        if (!nodes.badges) {
            return;
        }

        var finalRecord = context.finalRecord || null;
        var decision = context.reviewDecision || {};
        var expiry =
            (context.dateValidation &&
                context.dateValidation.expiry) ||
            null;

        var children = [
            ui.badge(
                ui.formatDocumentType(context.documentType),
                "badge-info"
            ),
            ui.finalStateBadge(
                finalRecord ? finalRecord.final_status : null
            ),
            ui.expiryBadge(expiry ? expiry.status : null)
        ];

        if (decision.priority && decision.priority !== "NONE") {
            children.push(ui.priorityBadge(decision.priority));
        }

        /* PHASE 10.2. Only when it is not a supported document.
           A badge saying "Supported document" on every correctly
           classified document is noise in a header that already
           carries the type. */
        if (
            context.classification &&
            context.classification.supported === false
        ) {
            children.push(
                ui.badge(
                    vocabulary.describeClassification(
                        context.classification.outcome
                    ).label,
                    "badge-neutral"
                )
            );
        }

        if (context.humanReview) {
            children.push(
                ui.badge(
                    "Reviewed by " +
                        ui.displayValue(
                            context.humanReview.reviewer_id
                        ),
                    "badge-neutral"
                )
            );
        }

        ui.replaceChildren(nodes.badges, children);
    }


    /* ======================================================
       HISTORY
       ======================================================
       A timeline, not an audit JSON dump. Each event type gets
       the fields it actually carries.
       ====================================================== */

    var EVENT_TITLES = {
        DOCUMENT_UPLOADED: "Document uploaded",
        MACHINE_REVIEW_DECISION: "Machine review decision",
        HUMAN_REVIEW: "Human review",
        DOCUMENT_DELETED: "Document deleted"
    };

    function eventTitle(type) {
        var key = String(type || "").toUpperCase();
        if (
            Object.prototype.hasOwnProperty.call(EVENT_TITLES, key)
        ) {
            return EVENT_TITLES[key];
        }
        return vocabulary.humanize(key) || "Audit event";
    }

    function machineEventBody(details) {
        var codes = details.reason_codes || [];

        return [
            ui.el("div", {
                className: "timeline-facts",
                children: [
                    ui.el("span", {
                        text:
                            "Decision: " +
                            ui.humanizeEnum(details.decision)
                    }),
                    details.priority
                        ? ui.el("span", {
                            text:
                                "Priority: " +
                                ui.humanizeEnum(details.priority)
                        })
                        : null
                ]
            }),
            codes.length
                ? ui.el("div", {
                    className: "reason-chips",
                    children: codes.map(function (code) {
                        var described =
                            vocabulary.describeReasonCode(code);
                        return ui.el("span", {
                            className: "reason-chip",
                            text: described.title,
                            attrs: { title: described.code }
                        });
                    })
                })
                : ui.el("p", {
                    className: "field-hint",
                    text: "No reason codes were recorded."
                })
        ];
    }

    function humanEventBody(details) {
        var corrections = details.corrections || {};
        var names = Object.keys(corrections);

        return [
            ui.el("div", {
                className: "timeline-facts",
                children: [
                    ui.el("span", {
                        text:
                            "Action: " +
                            vocabulary.describeHumanAction(
                                details.human_action
                            ).pastLabel
                    })
                ]
            }),
            details.notes
                ? ui.el("blockquote", {
                    className: "timeline-notes",
                    /* Reviewer notes are free text and are
                       rendered as text. */
                    text: String(details.notes)
                })
                : null,
            names.length
                ? ui.el("div", {
                    className: "timeline-corrections",
                    children: names.map(function (name) {
                        return ui.el("div", {
                            className: "timeline-correction",
                            children: [
                                ui.el("span", {
                                    className:
                                        "timeline-correction-field",
                                    text: vocabulary.fieldLabel(name)
                                }),
                                ui.el("span", {
                                    className:
                                        "timeline-correction-value",
                                    text: ui.isBlank(
                                        corrections[name]
                                    )
                                        ? "Cleared"
                                        : String(corrections[name])
                                })
                            ]
                        });
                    })
                })
                : null
        ];
    }

    function historyEvent(event) {
        var details = event.details || {};
        var type = String(event.event_type || "").toUpperCase();

        var body;

        if (type === "MACHINE_REVIEW_DECISION") {
            body = machineEventBody(details);
        } else if (type === "HUMAN_REVIEW") {
            body = humanEventBody(details);
        } else {
            body = [];
        }

        return ui.el("li", {
            className: "timeline-item",
            children: [
                ui.el("span", {
                    className: "timeline-marker",
                    attrs: { "aria-hidden": "true" }
                }),
                ui.el("div", {
                    className: "timeline-body",
                    children: [
                        ui.el("div", {
                            className: "timeline-head",
                            children: [
                                ui.el("h3", {
                                    className: "timeline-title",
                                    text: eventTitle(event.event_type)
                                }),
                                ui.el("time", {
                                    className: "timeline-time",
                                    text: ui.formatDateTime(
                                        event.created_at
                                    ),
                                    attrs: {
                                        datetime: event.created_at || ""
                                    }
                                })
                            ]
                        }),
                        ui.el("p", {
                            className: "timeline-actor",
                            text:
                                ui.humanizeEnum(event.actor_type) +
                                (event.actor_id
                                    ? " · " + String(event.actor_id)
                                    : "")
                        })
                    ].concat(body)
                })
            ]
        });
    }

    function renderReviewHistory(history) {
        model.history = history || null;

        if (!nodes.history) {
            return;
        }

        var events = (history && history.events) || [];

        if (!events.length) {
            ui.replaceChildren(nodes.history, [
                ui.emptyState({
                    title: "No audit history",
                    description:
                        "No audit events are recorded against " +
                        "this document."
                })
            ]);
            return;
        }

        ui.replaceChildren(nodes.history, [
            ui.el("p", {
                className: "field-hint",
                text:
                    events.length +
                    (events.length === 1
                        ? " audit event, oldest first."
                        : " audit events, oldest first.")
            }),
            ui.el("ol", {
                className: "timeline",
                children: events.map(historyEvent)
            })
        ]);
    }


    /* ======================================================
       TECHNICAL DATA
       ======================================================
       The last tab. Kept because it is genuinely needed, and
       never the landing view.
       ====================================================== */

    function renderRaw(payload) {
        model.raw = payload || null;

        if (!nodes.raw) {
            return;
        }

        var text = "";

        try {
            text = JSON.stringify(payload, null, 2);
        } catch (error) {
            text = "This payload could not be serialised.";
        }

        ui.replaceChildren(nodes.raw, [
            ui.el("p", {
                className: "field-hint",
                text:
                    "The stored analysis exactly as the API " +
                    "returned it. Useful for debugging; the " +
                    "panels above are the product."
            }),
            ui.el("pre", {
                className: "raw-json",
                attrs: { tabindex: "0" },
                /* textContent. A pre element does not make
                   innerHTML safe. */
                text: text
            })
        ]);
    }

    function jsonText() {
        try {
            return JSON.stringify(model.raw, null, 2);
        } catch (error) {
            return null;
        }
    }


    /* ======================================================
       UPDATE
       ====================================================== */

    function init() {
        collectNodes();
    }

    function update(context) {
        var config = context || {};

        model.humanReview = config.humanReview || null;

        renderBadges(config);
        renderOverview(config);
        renderFinalRecord(config.finalRecord);
        renderEffectiveValues(config.finalRecord);
        renderRaw(config.raw);

        return model;
    }


    global.VigiloxResultView = {
        init: init,
        update: update,

        /* Named for what they do. The Phase 7C dashboard tests
           guarded these responsibilities by name and they are
           still exactly these responsibilities. */
        renderFinalRecord: renderFinalRecord,
        renderEffectiveValues: renderEffectiveValues,
        renderReviewHistory: renderReviewHistory,
        renderOverview: renderOverview,
        renderRaw: renderRaw,

        jsonText: jsonText,
        FIELD_NAMES: FIELD_NAMES,
        EVENT_TITLES: EVENT_TITLES
    };

}(typeof window !== "undefined" ? window : globalThis));
