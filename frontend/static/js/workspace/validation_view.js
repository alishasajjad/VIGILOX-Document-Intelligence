/* ==========================================================
   VIGILOX VALIDATION / EXPIRY / FINDINGS
   PHASE 8.12
   ==========================================================

   Two panels.

   VALIDATION
       expiry status and date, per-date-field parse status, and
       the date validator's logical issues.

   FINDINGS
       everything the pipeline raised, from the normalized
       view -- see PHASE 10.6 below.


   NO RISK SCORE
   ----------------------------------------------------------
   There is no document risk number here and none is computed.
   The backend produces severities and a machine review
   decision; a percentage risk would be an invention.

   PHASE 10.6 settled this rather than deferring it. The only
   derived value on the whole panel is highest_severity, which
   is the maximum of the severities the producers assigned. It
   is a severity, not a number, and it cannot be mistaken for
   a probability -- which matters, because PHASE 10.5 measured
   what happens when a number on this screen looks more
   certain than it is.


   NORMALIZED FINDINGS
   PHASE 10.6
   ----------------------------------------------------------
   payload.findings, built by
   backend/app/domain/findings.py, is the source for the
   findings panel. Severity, category, field attribution,
   ordering and routing effect all arrive decided; this file
   chooses only how strongly each finding is drawn.

   The raw-anomaly path below it is still live, for a payload
   that carries no normalized view.


   DAYS UNTIL EXPIRY
   ----------------------------------------------------------
   Shown, and taken straight from
   date_validation.expiry.days_until_expiry. The validator
   already computes it against its own reference_date, so this
   introduces no new threshold and no second definition of
   "soon". If the backend did not send it, nothing is
   displayed rather than a locally computed substitute, which
   could disagree with the status beside it.


   SEVERITIES
   ----------------------------------------------------------
   ERROR and WARNING are what DocumentAnomalyValidator emits.
   An unrecognised severity is counted and shown as itself and
   is never promoted into one of those two.
   ========================================================== */

(function (global) {
    "use strict";

    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    var DATE_FIELDS = [
        "date_of_birth",
        "issue_date",
        "expiry_date"
    ];


    var validationContainer = null;
    var findingsContainer = null;

    var model = {
        dateValidation: null,
        anomalyValidation: null,
        reviewDecision: null,
        quality: null,
        /* PHASE 10.6. payload.findings, the normalized view.
           null means the backend sent none, which is why the
           raw anomaly path is still here. */
        findings: null
    };


    /* ======================================================
       EXPIRY
       ====================================================== */

    function expiryBlock() {
        var expiry =
            (model.dateValidation && model.dateValidation.expiry) ||
            null;

        var status = expiry ? expiry.status : "NOT_AVAILABLE";
        var days = expiry ? expiry.days_until_expiry : null;

        var rows = [
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Status"
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [ui.expiryBadge(status)]
                    })
                ]
            }),
            ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: "Expiry date"
                    }),
                    ui.el("span", {
                        className:
                            "detail-value" +
                            (expiry && expiry.value
                                ? ""
                                : " is-empty"),
                        text:
                            expiry && expiry.value
                                ? ui.formatDate(expiry.value)
                                : "No usable expiry date was read"
                    })
                ]
            })
        ];

        /* Only when the validator supplied it. */
        if (typeof days === "number") {
            rows.push(
                ui.el("div", {
                    className: "detail-row",
                    children: [
                        ui.el("span", {
                            className: "detail-label",
                            text: "Days remaining"
                        }),
                        ui.el("span", {
                            className: "detail-value numeric",
                            text:
                                days < 0
                                    ? "Expired " +
                                      Math.abs(days) +
                                      (Math.abs(days) === 1
                                          ? " day ago"
                                          : " days ago")
                                    : days === 0
                                        ? "Expires today"
                                        : days +
                                          (days === 1
                                              ? " day"
                                              : " days")
                        })
                    ]
                })
            );
        }

        if (
            model.dateValidation &&
            model.dateValidation.reference_date
        ) {
            rows.push(
                ui.el("div", {
                    className: "detail-row",
                    children: [
                        ui.el("span", {
                            className: "detail-label",
                            text: "Checked against"
                        }),
                        ui.el("span", {
                            className: "detail-value",
                            text: ui.formatDate(
                                model.dateValidation.reference_date
                            )
                        })
                    ]
                })
            );
        }

        return ui.el("section", {
            className: "validation-block",
            children: [
                ui.el("h3", {
                    className: "validation-block-title",
                    text: "Validity"
                }),
                ui.el("div", {
                    className: "detail-rows",
                    children: rows
                })
            ]
        });
    }


    /* ======================================================
       DATE FIELDS
       ====================================================== */

    function dateFieldsBlock() {
        var fields =
            (model.dateValidation &&
                model.dateValidation.date_fields) ||
            {};

        var rows = DATE_FIELDS.map(function (name) {
            var entry = fields[name] || {};
            var described = vocabulary.describeDateStatus(
                entry.status
            );

            var modifier = {
                success: "badge-success",
                danger: "badge-danger",
                warning: "badge-warning",
                neutral: "badge-neutral"
            }[described.tone] || "badge-neutral";

            return ui.el("div", {
                className: "detail-row",
                children: [
                    ui.el("span", {
                        className: "detail-label",
                        text: vocabulary.fieldLabel(name)
                    }),
                    ui.el("span", {
                        className: "detail-value",
                        children: [
                            ui.el("span", {
                                className: "date-field-value",
                                /* The raw extracted string, not
                                   a reformatted one: an
                                   unparseable value must be
                                   visible exactly as read. */
                                text: ui.isBlank(entry.value)
                                    ? "Not detected"
                                    : String(entry.value)
                            }),
                            ui.badge(described.label, modifier)
                        ]
                    })
                ]
            });
        });

        return ui.el("section", {
            className: "validation-block",
            children: [
                ui.el("h3", {
                    className: "validation-block-title",
                    text: "Date fields"
                }),
                ui.el("div", {
                    className: "detail-rows",
                    children: rows
                })
            ]
        });
    }


    /* ======================================================
       LOGICAL ISSUES
       ====================================================== */

    function logicalIssuesBlock() {
        var issues =
            (model.dateValidation &&
                model.dateValidation.logical_issues) ||
            [];

        var body;

        if (!issues.length) {
            body = ui.el("p", {
                className: "validation-clear",
                children: [
                    ui.badge("No conflicts", "badge-success"),
                    ui.el("span", {
                        text:
                            "The extracted dates are consistent " +
                            "with each other."
                    })
                ]
            });
        } else {
            body = ui.el("ul", {
                className: "issue-list",
                children: issues.map(function (issue) {
                    var described = vocabulary.describeReasonCode(
                        issue.code
                    );

                    return ui.el("li", {
                        className: "issue-item",
                        children: [
                            ui.el("div", {
                                className: "issue-item-head",
                                children: [
                                    ui.el("span", {
                                        className: "issue-item-title",
                                        text: described.title
                                    }),
                                    issue.field
                                        ? ui.badge(
                                            vocabulary.fieldLabel(
                                                issue.field
                                            ),
                                            "badge-neutral"
                                        )
                                        : null
                                ]
                            }),
                            /* The validator's own message, as
                               text. It can contain an extracted
                               value. */
                            ui.el("p", {
                                className: "issue-item-message",
                                text: ui.displayValue(issue.message)
                            }),
                            ui.el("p", {
                                className: "issue-item-code",
                                text: described.code
                            })
                        ]
                    });
                })
            });
        }

        return ui.el("section", {
            className: "validation-block",
            children: [
                ui.el("h3", {
                    className: "validation-block-title",
                    text: "Date consistency"
                }),
                body
            ]
        });
    }


    /* ======================================================
       FINDINGS
       ====================================================== */

    function severityCounts(issues) {
        var counts = { ERROR: 0, WARNING: 0, OTHER: 0 };

        issues.forEach(function (issue) {
            var severity = String(issue.severity || "").toUpperCase();
            if (severity === "ERROR") {
                counts.ERROR += 1;
            } else if (severity === "WARNING") {
                counts.WARNING += 1;
            } else {
                counts.OTHER += 1;
            }
        });

        return counts;
    }

    function findingRow(issue) {
        var described = vocabulary.describeReasonCode(issue.code);

        return ui.el("li", {
            className: "finding-item",
            children: [
                ui.el("div", {
                    className: "finding-head",
                    children: [
                        /* Only severities the backend sent. An
                           unknown one falls back to neutral
                           rather than being relabelled. */
                        ui.severityBadge(issue.severity),
                        ui.el("span", {
                            className: "finding-title",
                            text: described.title
                        }),
                        issue.field
                            ? ui.badge(
                                vocabulary.fieldLabel(issue.field),
                                "badge-neutral"
                            )
                            : null
                    ]
                }),
                ui.el("p", {
                    className: "finding-message",
                    text: ui.displayValue(issue.message)
                }),
                described.explanation
                    ? ui.el("p", {
                        className: "finding-explanation",
                        text: described.explanation
                    })
                    : null,
                ui.el("p", {
                    className: "finding-code",
                    text: described.code
                })
            ]
        });
    }


    /* ======================================================
       NORMALIZED FINDINGS
       PHASE 10.6
       ======================================================
       payload.findings, from
       backend/app/domain/findings.py.

       WHAT THIS VIEW DOES AND DOES NOT DECIDE
       ------------------------------------------------------
       Does not: assign a severity, order the list, work out
       which field a finding belongs to, or judge whether a
       finding drove the machine decision. All four arrive
       decided.

       Does: choose how strongly each one is drawn.


       HIERARCHY
       ------------------------------------------------------
       The backend already sorted worst-first, so the reading
       order is correct without this file sorting anything.
       Weight is then applied by severity:

         ERROR     a coloured left edge. Strongest thing on
                   the panel.
         WARNING   a muted left edge. Visible, not alarming.
         INFO      no edge.
         ungraded  no edge, muted text, and its own section
                   below the graded ones.

       Nothing pulses, nothing is red-on-red, and no finding
       is presented as an emergency. A reviewer who is
       alarmed by every document stops reading carefully, and
       that is worse than a plain list.


       THREE SECTIONS, NOT ONE
       ------------------------------------------------------
       Record findings, then evidence, then image quality.
       The categories answer different questions -- see
       vocabulary.FINDING_CATEGORIES -- and merging them
       would lose the distinction that makes any of them
       actionable.

       Evidence findings are ungraded by the backend on
       purpose: the validator assigns them no severity, and
       their graded consequence is already in the record
       section as CRITICAL_FIELD_NOT_TRUSTED or
       EXTRACTED_FIELD_INVALID_EVIDENCE. So they are shown as
       supporting detail, which is what they are.
       ====================================================== */

    var SEVERITY_WEIGHT = {
        CRITICAL: "is-error",
        ERROR: "is-error",
        WARNING: "is-warning"
    };

    function weightClass(severity) {
        var key = String(severity || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                SEVERITY_WEIGHT,
                key
            )
        ) {
            return " " + SEVERITY_WEIGHT[key];
        }

        return severity ? "" : " is-detail";
    }

    /* The domain detail an expiry finding carries. Taken from
       the finding, which the backend enriched from the date
       validator -- so "soon" is not defined a second time
       here and cannot disagree with the status above. */
    function expiryDetailLine(detail) {
        if (!detail) {
            return null;
        }

        var parts = [];

        if (detail.expiry_date) {
            parts.push(ui.formatDate(detail.expiry_date));
        }

        if (typeof detail.days_until_expiry === "number") {
            var days = detail.days_until_expiry;

            parts.push(
                days < 0
                    ? Math.abs(days) + " day(s) ago"
                    : "in " + days + " day(s)"
            );
        }

        if (!parts.length) {
            return null;
        }

        return ui.el("p", {
            className: "finding-explanation",
            text: parts.join(" · ")
        });
    }

    /* The measurement a quality finding carries. Reported as
       measured against threshold, with nothing derived from
       it. */
    function measurementLine(detail) {
        if (
            !detail ||
            typeof detail.measured_value !== "number" ||
            typeof detail.threshold !== "number"
        ) {
            return null;
        }

        return ui.el("p", {
            className: "finding-code",
            text:
                String(detail.metric_name || "") +
                " measured " +
                ui.formatNumber(detail.measured_value) +
                " against a threshold of " +
                ui.formatNumber(detail.threshold)
        });
    }

    function normalizedRow(finding) {
        var category = finding.category;

        var described =
            category === "EVIDENCE"
                ? vocabulary.describeEvidenceFlag(finding.detail)
                : category === "QUALITY"
                ? vocabulary.describeQualityCode(finding.code)
                : vocabulary.describeReasonCode(finding.code);

        var heads = [];

        /* An ungraded finding gets no severity badge at all.
           A neutral "Notice" chip would read as a grade the
           validator never gave it. */
        if (finding.severity) {
            heads.push(ui.severityBadge(finding.severity));
        }

        heads.push(
            ui.el("span", {
                className: "finding-title",
                text: described.title
            })
        );

        if (finding.field) {
            heads.push(
                ui.badge(
                    vocabulary.fieldLabel(finding.field),
                    "badge-neutral"
                )
            );
        }

        /* Shown only where it is known to be true. The
           backend sends null when no machine decision is
           stored, and null is not a no. */
        if (finding.affects_routing === true) {
            heads.push(
                ui.badge("Drove the decision", "badge-neutral")
            );
        }

        var cited =
            finding.detail && finding.detail.source_line_id
                ? finding.detail.source_line_id
                : null;

        return ui.el("li", {
            className: "finding-item" + weightClass(finding.severity),
            children: [
                ui.el("div", {
                    className: "finding-head",
                    children: heads
                }),
                finding.message
                    ? ui.el("p", {
                        className: "finding-message",
                        text: finding.message
                    })
                    : null,
                described.explanation
                    ? ui.el("p", {
                        className: "finding-explanation",
                        text: described.explanation
                    })
                    : null,
                category === "EXPIRY"
                    ? expiryDetailLine(finding.detail)
                    : null,
                category === "QUALITY"
                    ? measurementLine(finding.detail)
                    : null,
                cited
                    ? ui.el("p", {
                        className: "finding-code",
                        text: "Cited OCR line " + cited
                    })
                    : null,
                ui.el("p", {
                    className: "finding-code",
                    text: ui.displayValue(finding.code)
                })
            ]
        });
    }

    function normalizedSummary(view) {
        var badges = [];

        [
            ["ERROR", "error", "errors", "badge-severity-error"],
            [
                "WARNING",
                "warning",
                "warnings",
                "badge-severity-warning"
            ],
            ["INFO", "notice", "notices", "badge-severity-info"]
        ].forEach(function (entry) {
            var count = (view.counts || {})[entry[0]] || 0;

            if (!count) {
                return;
            }

            badges.push(
                ui.badge(
                    count +
                        " " +
                        (count === 1 ? entry[1] : entry[2]),
                    entry[3]
                )
            );
        });

        if (view.unrated_count) {
            badges.push(
                ui.badge(
                    view.unrated_count +
                        " supporting detail" +
                        (view.unrated_count === 1 ? "" : "s"),
                    "badge-neutral"
                )
            );
        }

        var decision = model.reviewDecision || {};

        var notes = [];

        if (decision.decision) {
            notes.push(
                ui.el("p", {
                    className: "field-hint",
                    text:
                        "These findings produced the machine " +
                        "decision " +
                        ui.humanizeEnum(decision.decision) +
                        (decision.priority &&
                        decision.priority !== "NONE"
                            ? " at " +
                              ui.humanizeEnum(decision.priority) +
                              " priority."
                            : ".")
                })
            );
        }

        /* A severity the interface does not recognise. Named
           rather than quietly folded into a count, because
           whoever introduced it needs to see that it
           arrived. */
        if (
            view.unrecognised_severities &&
            view.unrecognised_severities.length
        ) {
            notes.push(
                ui.el("p", {
                    className: "field-hint is-caveat",
                    text:
                        view.unrecognised_severities.length +
                        " finding severity value" +
                        (view.unrecognised_severities.length === 1
                            ? " is"
                            : "s are") +
                        " not recognised (" +
                        view.unrecognised_severities.join(", ") +
                        ") and " +
                        (view.unrecognised_severities.length === 1
                            ? "is"
                            : "are") +
                        " not included in the counts above."
                })
            );
        }

        return ui.el("div", {
            className: "finding-summary",
            children: [
                ui.el("div", {
                    className: "badge-stack",
                    children: badges.length
                        ? badges
                        : [
                            ui.badge(
                                "No graded findings",
                                "badge-neutral"
                            )
                        ]
                })
            ].concat(notes)
        });
    }

    /* ======================================================
       IMAGE QUALITY, FROM THE NORMALIZED VIEW
       ======================================================
       The same three states as qualityBlock() below, read
       from the normalized view instead of the raw quality
       payload.

       WHY THIS EXISTS AT ALL
       ------------------------------------------------------
       The first version of this panel rendered the record and
       evidence findings from the normalized view and the
       quality findings from analysis.quality. Two sources for
       one panel, which is the thing normalization was supposed
       to remove -- and it had a real failure mode: a view
       carrying a QUALITY finding whose raw payload was absent
       rendered five findings out of six, silently. The
       workspace harness caught it.

       So on the normalized path, every finding on this panel
       comes from the view. quality_assessed and quality_error
       travel with it, which is what keeps NOT ASSESSED
       distinguishable from ASSESSED AND CLEAN without needing
       the raw payload as well.
       ====================================================== */

    function normalizedQualityBlock(view, rows) {
        var title = ui.el("h3", {
            className: "validation-block-title",
            text: "Image quality"
        });

        /* NOT ASSESSED. Nobody measured this image, which is
           not the same statement as "no problems were
           found". */
        if (!view.quality_assessed) {
            return ui.el("section", {
                className: "validation-block",
                children: [
                    title,
                    ui.el("p", {
                        className: "field-hint",
                        text:
                            "Not assessed. This document was " +
                            "processed before image quality " +
                            "assessment was available, so " +
                            "nothing is known about the image " +
                            "either way."
                    })
                ]
            });
        }

        /* The assessment ran and failed. Reported as a
           failure, never as a clean result. */
        if (view.quality_error) {
            return ui.el("section", {
                className: "validation-block",
                children: [
                    title,
                    ui.el("p", {
                        className: "field-hint",
                        text:
                            "The image could not be measured, " +
                            "so no quality findings are " +
                            "available for it."
                    })
                ]
            });
        }

        return ui.el("section", {
            className: "validation-block",
            children: [
                title,
                rows.length
                    ? ui.el("ul", {
                        className: "finding-list",
                        children: rows.map(normalizedRow)
                    })
                    : ui.el("p", {
                        className: "field-hint",
                        text:
                            "Assessed. No image quality " +
                            "problems were measured."
                    }),
                /* Stated on every document that carries an
                   assessment. The thresholds were derived
                   from this project benchmark plus controlled
                   degradations, and presenting them as
                   universal would overstate what was
                   measured. */
                ui.el("p", {
                    className: "field-hint",
                    text:
                        "Image quality is a measurement of " +
                        "the photograph, not a verdict on the " +
                        "document. Thresholds were calibrated " +
                        "on the VIGILOX evaluation set and " +
                        "controlled degradations of it."
                })
            ]
        });
    }

    function normalizedSection(title, question, rows) {
        return ui.el("section", {
            className: "validation-block",
            children: [
                ui.el("h3", {
                    className: "validation-block-title",
                    text: title
                }),
                question
                    ? ui.el("p", {
                        className: "field-hint",
                        text: question
                    })
                    : null,
                ui.el("ul", {
                    className: "finding-list",
                    children: rows.map(normalizedRow)
                })
            ]
        });
    }

    /* ======================================================
       IMAGE QUALITY
       PHASE 10.1 / 10.2
       ======================================================
       Rendered as its own block inside Findings, not merged
       into the anomaly list.

       Two reasons. Quality findings answer a different
       question -- can the image be read, rather than is the
       extracted data consistent -- and each one carries a
       measured value against a measured threshold, which the
       anomaly issues do not have.

       THE NULL CASE IS THE POINT
       ------------------------------------------------------
       quality is null for every document analysed before
       Phase 10.1. That renders as "Not assessed", never as
       "no problems found". Showing an empty findings list for
       a document nobody measured would be the interface
       asserting something it does not know.
       ====================================================== */

    function qualityFindingRow(finding) {
        var described = vocabulary.describeQualityCode(
            finding.code
        );

        var measured = finding.measured_value;
        var threshold = finding.threshold;

        return ui.el("li", {
            className: "finding-item",
            children: [
                ui.el("div", {
                    className: "finding-head",
                    children: [
                        /* Backend severity, as sent. */
                        ui.severityBadge(finding.severity),
                        ui.el("span", {
                            className: "finding-title",
                            text: described.title
                        })
                    ]
                }),
                ui.el("p", {
                    className: "finding-message",
                    text: ui.displayValue(finding.message)
                }),
                described.explanation
                    ? ui.el("p", {
                        className: "finding-explanation",
                        text: described.explanation
                    })
                    : null,
                /* The measurement, shown because it is what
                   makes the finding checkable rather than an
                   opinion. Reported as measured against
                   threshold, with no score derived from it. */
                typeof measured === "number" &&
                typeof threshold === "number"
                    ? ui.el("p", {
                        className: "finding-code",
                        text:
                            String(finding.metric_name || "") +
                            " measured " +
                            ui.formatNumber(measured) +
                            " against a threshold of " +
                            ui.formatNumber(threshold)
                    })
                    : null,
                ui.el("p", {
                    className: "finding-code",
                    text: described.code
                })
            ]
        });
    }

    function qualityBlock() {
        var quality = model.quality;

        if (!quality) {
            return ui.el("section", {
                className: "validation-block",
                children: [
                    ui.el("h3", {
                        className: "validation-block-title",
                        text: "Image quality"
                    }),
                    ui.el("p", {
                        className: "field-hint",
                        text:
                            "Not assessed. This document was " +
                            "processed before image quality " +
                            "assessment was available, so " +
                            "nothing is known about the image " +
                            "either way."
                    })
                ]
            });
        }

        var findings = quality.findings || [];

        /* An assessment that could not read the file at all.
           Reported as an error rather than as a clean result. */
        if (quality.error) {
            return ui.el("section", {
                className: "validation-block",
                children: [
                    ui.el("h3", {
                        className: "validation-block-title",
                        text: "Image quality"
                    }),
                    ui.el("p", {
                        className: "field-hint",
                        text:
                            "The image could not be measured, " +
                            "so no quality findings are " +
                            "available for it."
                    })
                ]
            });
        }

        return ui.el("section", {
            className: "validation-block",
            children: [
                ui.el("h3", {
                    className: "validation-block-title",
                    text: "Image quality"
                }),
                findings.length
                    ? ui.el("ul", {
                        className: "finding-list",
                        children: findings.map(
                            qualityFindingRow
                        )
                    })
                    : ui.el("p", {
                        className: "field-hint",
                        text:
                            "Assessed. No image quality " +
                            "problems were measured."
                    }),
                /* Stated on every document that carries an
                   assessment. The thresholds were derived from
                   this project benchmark plus controlled
                   degradations, and presenting them as
                   universal would overstate what was
                   measured. */
                ui.el("p", {
                    className: "field-hint",
                    text:
                        "Image quality is a measurement of the " +
                        "photograph, not a verdict on the " +
                        "document. Thresholds were calibrated " +
                        "on the VIGILOX evaluation set and " +
                        "controlled degradations of it."
                })
            ]
        });
    }

    function renderNormalizedFindings(view) {
        var all = view.findings || [];

        var record = all.filter(function (finding) {
            return (
                finding.category !== "EVIDENCE" &&
                finding.category !== "QUALITY"
            );
        });

        var evidence = all.filter(function (finding) {
            return finding.category === "EVIDENCE";
        });

        var quality = all.filter(function (finding) {
            return finding.category === "QUALITY";
        });

        if (!all.length) {
            ui.replaceChildren(findingsContainer, [
                ui.el("div", {
                    className: "empty-state",
                    children: [
                        ui.el("p", {
                            className: "empty-title",
                            text: "No findings"
                        }),
                        ui.el("p", {
                            className: "empty-description",
                            text:
                                "Nothing was raised against " +
                                "this document's record or " +
                                "its evidence."
                        })
                    ]
                }),
                /* Image quality is reported even when nothing
                   else was, because NOT ASSESSED is itself
                   something the reviewer needs to know. */
                normalizedQualityBlock(view, [])
            ]);
            return;
        }

        var sections = [normalizedSummary(view)];

        if (record.length) {
            var anomalyCategory =
                vocabulary.describeFindingCategory("ANOMALY");

            sections.push(
                normalizedSection(
                    "Record findings",
                    anomalyCategory.question,
                    record
                )
            );
        }

        /* Image quality before evidence, because quality
           findings are GRADED and evidence findings are not.
           Both graded sections therefore come first and the
           ungraded supporting detail comes last, which is the
           same hierarchy the backend's sort applies inside
           each section. */
        sections.push(normalizedQualityBlock(view, quality));

        if (evidence.length) {
            var evidenceCategory =
                vocabulary.describeFindingCategory("EVIDENCE");

            sections.push(
                normalizedSection(
                    "Evidence",
                    evidenceCategory.question +
                        " These carry no severity of their " +
                        "own: where an evidence problem " +
                        "mattered to the decision, it appears " +
                        "above as a graded finding.",
                    evidence
                )
            );
        }

        ui.replaceChildren(findingsContainer, sections);
    }

    function renderFindings() {
        if (!findingsContainer) {
            return;
        }

        /* PHASE 10.6. The normalized view when the backend
           sent one.

           The path below it is not dead code: a document with
           no analysis row has no normalized view, and an older
           cached payload may not carry the key. Falling back
           to the raw anomaly issues renders the same findings
           it always did rather than an empty panel. */
        if (model.findings) {
            renderNormalizedFindings(model.findings);
            return;
        }

        var anomaly = model.anomalyValidation || {};
        var issues = anomaly.issues || [];

        if (!issues.length) {
            ui.replaceChildren(findingsContainer, [
                ui.el("div", {
                    className: "empty-state",
                    children: [
                        ui.el("p", {
                            className: "empty-title",
                            text: "No findings"
                        }),
                        ui.el("p", {
                            className: "empty-description",
                            text:
                                "The anomaly validator raised " +
                                "nothing against this document."
                        })
                    ]
                })
            ]);
            return;
        }

        var counts = severityCounts(issues);

        var summary = [];

        if (counts.ERROR) {
            summary.push(
                ui.badge(
                    counts.ERROR +
                        (counts.ERROR === 1
                            ? " error"
                            : " errors"),
                    "badge-severity-error"
                )
            );
        }

        if (counts.WARNING) {
            summary.push(
                ui.badge(
                    counts.WARNING +
                        (counts.WARNING === 1
                            ? " warning"
                            : " warnings"),
                    "badge-severity-warning"
                )
            );
        }

        if (counts.OTHER) {
            summary.push(
                ui.badge(counts.OTHER + " other", "badge-neutral")
            );
        }

        var decision = model.reviewDecision || {};

        ui.replaceChildren(findingsContainer, [
            ui.el("div", {
                className: "finding-summary",
                children: [
                    ui.el("div", {
                        className: "badge-stack",
                        children: summary
                    }),
                    decision.decision
                        ? ui.el("p", {
                            className: "field-hint",
                            text:
                                "These findings produced the " +
                                "machine decision " +
                                ui.humanizeEnum(decision.decision) +
                                (decision.priority &&
                                decision.priority !== "NONE"
                                    ? " at " +
                                      ui.humanizeEnum(
                                          decision.priority
                                      ) +
                                      " priority."
                                    : ".")
                        })
                        : null
                ]
            }),
            ui.el("ul", {
                className: "finding-list",
                children: issues.map(findingRow)
            }),
            qualityBlock()
        ]);
    }


    /* ======================================================
       RENDER
       ====================================================== */

    function renderValidation() {
        if (!validationContainer) {
            return;
        }

        if (!model.dateValidation) {
            ui.replaceChildren(validationContainer, [
                ui.emptyState({
                    title: "No validation record",
                    description:
                        "This document has no stored date or " +
                        "logical validation."
                })
            ]);
            return;
        }

        ui.replaceChildren(validationContainer, [
            expiryBlock(),
            dateFieldsBlock(),
            logicalIssuesBlock()
        ]);
    }

    function render() {
        renderValidation();
        renderFindings();
    }

    function init(options) {
        validationContainer = ui.byId("validation-content");
        findingsContainer = ui.byId("anomaly-list");
        return update(options);
    }

    function update(options) {
        var config = options || {};

        model = {
            dateValidation: config.dateValidation || null,
            anomalyValidation: config.anomalyValidation || null,
            reviewDecision: config.reviewDecision || null,
            /* PHASE 10.1. null is meaningful here and is kept
               as null: it means NOT ASSESSED. */
            quality:
                config.quality === undefined
                    ? null
                    : config.quality,

            /* PHASE 10.6. */
            findings: config.findings || null
        };

        render();
        return model;
    }


    global.VigiloxValidationView = {
        init: init,
        update: update,
        render: render,
        DATE_FIELDS: DATE_FIELDS,
        severityCounts: severityCounts
    };

}(typeof window !== "undefined" ? window : globalThis));
