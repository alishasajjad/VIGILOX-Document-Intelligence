/* ==========================================================
   VIGILOX EXTRACTED DATA / EVIDENCE / CONFIDENCE
   PHASE 8.11
   ==========================================================

   One row per extracted field, answering six questions at a
   glance:

       what field is this
       what value was read
       how confident was the OCR behind it
       did evidence validation accept it
       where in the document did it come from
       is this the machine's reading or a human's correction


   WHERE EACH PIECE COMES FROM
   ----------------------------------------------------------
   value            analysis.extraction[field].value
   source line ids  analysis.extraction[field].source_line_ids
   confidence       analysis.field_confidence[field].confidence
   evidence status  analysis.field_confidence[field].status
   evidence detail  analysis.evidence_flags
   OCR text         analysis.ocr_lines, looked up by line_id
   provenance       final_record.value_sources[field]

   Nothing on this screen is computed from anything else.


   NO OVERALL CONFIDENCE
   ----------------------------------------------------------
   There is a confidence per field and no authoritative
   definition of a document-level one. Averaging seven numbers
   and calling it "document confidence" would invent a
   statistic, so no such figure appears.


   CONFIDENCE BANDS
   ----------------------------------------------------------
   The numeric value is always shown. The band (high / medium /
   low) is presentation only, its thresholds live in common.js
   so the CSS colour and the JS label cannot drift, and the
   band never replaces the number.


   WHAT THE NUMBER DOES NOT MEAN
   ----------------------------------------------------------
   PHASE 10.5 measured field confidence against actual field
   correctness across all 63 evaluation documents. It does not
   predict correctness: incorrect fields carried a HIGHER mean
   confidence than correct ones, and the worst single error was
   a critical expiry date wrong at the 92nd percentile.

   That is structural. Confidence is OCR character confidence
   for the cited lines, so it measures whether the text was
   READ correctly, not whether it was ASSIGNED to the right
   field.

   The caveat is rendered on this screen rather than left in a
   comment, because the person who needs it is the reviewer
   looking at the number.
   ========================================================== */

(function (global) {
    "use strict";

    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* Field order. document_type first because it decides
       which of the others are required, then identity, then
       dates, then issuer. */
    var FIELD_ORDER = [
        "document_type",
        "full_name",
        "licence_number",
        "id_number",
        "date_of_birth",
        "issue_date",
        "expiry_date",
        "issuer"
    ];


    var container = null;
    var onHighlight = null;

    var model = {
        extraction: {},
        confidence: {},
        evidenceFlags: [],
        findings: null,
        ocrLines: [],
        valueSources: {},
        effectiveValues: null
    };


    /* ======================================================
       OCR LOOKUP
       ======================================================
       Keyed on the explicit line_id the OCR service writes.
       There is no positional fallback: guessing which line a
       value came from would be inventing evidence.
       ====================================================== */

    function buildOcrLookup(lines) {
        var lookup = {};

        (lines || []).forEach(function (line) {
            if (line && line.line_id !== undefined) {
                lookup[String(line.line_id)] = line;
            }
        });

        return lookup;
    }


    /* ======================================================
       EXTRACTION SHAPE
       ======================================================
       document_type is a bare string at the top level; every
       other field is { value, source_line_ids }.
       ====================================================== */

    function fieldData(name) {
        if (name === "document_type") {
            return {
                value: model.extraction
                    ? model.extraction.document_type
                    : null,
                source_line_ids: []
            };
        }

        var field =
            (model.extraction && model.extraction[name]) || null;

        return {
            value: field ? field.value : null,
            source_line_ids: field
                ? field.source_line_ids || []
                : []
        };
    }

    function confidenceFor(name) {
        var entry =
            (model.confidence && model.confidence[name]) || null;

        if (!entry) {
            return { confidence: null, status: null };
        }

        return {
            confidence:
                typeof entry.confidence === "number"
                    ? entry.confidence
                    : null,
            status: entry.status || null
        };
    }


    /* ======================================================
       DISPLAY VALUE
       ======================================================
       document_type is the one field with a friendly label.
       Every other value is shown exactly as extracted: an
       OCR-derived name or licence number must not be
       reformatted, or the reviewer would be checking the
       display against the image instead of the data.
       ====================================================== */

    function displayFieldValue(name, value) {
        if (ui.isBlank(value)) {
            return null;
        }
        if (name === "document_type") {
            return ui.formatDocumentType(value);
        }
        return String(value);
    }


    /* ======================================================
       EVIDENCE
       ====================================================== */

    function evidenceList(name, lookup) {
        var data = fieldData(name);
        var ids = data.source_line_ids || [];

        if (!ids.length) {
            return ui.el("p", {
                className: "field-hint",
                text:
                    name === "document_type"
                        ? "Document type is classified from the " +
                          "document as a whole rather than from " +
                          "one line."
                        : "No OCR line was cited for this value."
            });
        }

        var rows = ids.map(function (lineId) {
            var key = String(lineId);
            var line = lookup[key];

            return ui.el("li", {
                className: "evidence-line",
                children: [
                    ui.el("span", {
                        className: "evidence-id",
                        text: key
                    }),
                    ui.el("span", {
                        className: "evidence-text",
                        /* OCR text is untrusted document
                           content and is rendered as text. */
                        text: line
                            ? ui.displayValue(line.text)
                            : "This OCR line is not present in " +
                              "the stored output."
                    }),
                    line && typeof line.confidence === "number"
                        ? ui.el("span", {
                            className: "evidence-confidence",
                            text: ui.formatConfidence(line.confidence)
                        })
                        : null
                ]
            });
        });

        return ui.el("ul", {
            className: "evidence-lines",
            children: rows
        });
    }


    /* ======================================================
       EVIDENCE STATUS
       ====================================================== */

    function evidenceStatusBadge(status) {
        var described = vocabulary.describeConfidenceStatus(status);

        var modifier = {
            success: "badge-success",
            danger: "badge-danger",
            warning: "badge-warning",
            neutral: "badge-neutral"
        }[described.tone] || "badge-neutral";

        return ui.badge(described.label, modifier);
    }

    /* ======================================================
       EVIDENCE PROBLEMS FOR ONE FIELD
       ======================================================
       PHASE 10.6. Two sources, one preferred.

       PREFERRED: the normalized findings view. The backend
       has already worked out which field each evidence flag
       belongs to, so this groups a decided answer rather than
       recovering it from a string.

       FALLBACK: analysis.evidence_flags, parsed by
       vocabulary.evidenceFlagsByField. Still needed for a
       payload that carries no normalized view.

       Both render identically, because describeEvidenceFlag
       accepts either shape and
       test_phase10_finding_normalization asserts the two
       parsers agree on every flag the validator can emit.
       ====================================================== */

    function normalizedEvidenceByField() {
        var grouped = {};

        var all =
            (model.findings && model.findings.findings) || [];

        all.forEach(function (finding) {
            if (finding.category !== "EVIDENCE") {
                return;
            }

            var key = finding.field || "_unattributed";

            grouped[key] = grouped[key] || [];

            grouped[key].push(
                vocabulary.describeEvidenceFlag(finding.detail)
            );
        });

        return grouped;
    }

    function evidenceProblems(name) {
        var grouped = model.findings
            ? normalizedEvidenceByField()
            : vocabulary.evidenceFlagsByField(
                model.evidenceFlags
            );

        var problems = grouped[name] || [];

        if (!problems.length) {
            return null;
        }

        return ui.el("ul", {
            className: "evidence-problems",
            children: problems.map(function (problem) {
                return ui.el("li", {
                    children: [
                        ui.el("span", {
                            className: "evidence-problem-title",
                            text: problem.title
                        }),
                        problem.explanation
                            ? ui.el("span", {
                                className: "evidence-problem-detail",
                                text: problem.explanation
                            })
                            : null,
                        problem.detail
                            ? ui.el("span", {
                                className: "evidence-problem-ref",
                                text: "Line " + problem.detail
                            })
                            : null
                    ]
                });
            })
        });
    }


    /* ======================================================
       PROVENANCE
       ======================================================
       MACHINE and HUMAN_CORRECTION get distinct colour
       families, because a reviewer must never mistake one for
       the other.

       value_sources is only present once a final record exists
       with effective values. Before that, every value on this
       screen is a machine reading and is labelled so.
       ====================================================== */

    function provenanceBadge(name) {
        var source =
            (model.valueSources && model.valueSources[name]) || null;

        if (!source) {
            return ui.provenanceBadge("MACHINE");
        }

        return ui.provenanceBadge(source);
    }

    function isCorrected(name) {
        return (
            Boolean(model.valueSources) &&
            model.valueSources[name] === "HUMAN_CORRECTION"
        );
    }


    /* ======================================================
       ROW
       ====================================================== */

    function fieldRow(name, lookup) {
        var data = fieldData(name);
        var confidence = confidenceFor(name);
        var value = displayFieldValue(name, data.value);
        var corrected = isCorrected(name);

        var ids = (data.source_line_ids || []).map(String);

        /* Focusing or hovering a row highlights its evidence on
           the image. A real button, so it is keyboard
           reachable. */
        var locate = null;

        if (ids.length && typeof onHighlight === "function") {
            locate = ui.el("button", {
                className: "btn btn-ghost btn-sm",
                text:
                    ids.length === 1
                        ? "Show on document"
                        : "Show " + ids.length + " lines",
                attrs: { type: "button" }
            });

            locate.addEventListener("click", function () {
                onHighlight(ids);
            });
        }

        var valueNode = value
            ? ui.el("div", {
                className:
                    "field-value" +
                    (corrected ? " is-corrected" : ""),
                text: value
            })
            : ui.el("div", {
                className: "field-value is-empty",
                text: "Not detected"
            });

        return ui.el("article", {
            className:
                "field-row" + (corrected ? " is-corrected" : ""),
            children: [
                ui.el("div", {
                    className: "field-row-head",
                    children: [
                        ui.el("h3", {
                            className: "field-row-label",
                            text: vocabulary.fieldLabel(name)
                        }),
                        ui.el("div", {
                            className: "field-row-meta",
                            children: [
                                evidenceStatusBadge(confidence.status),
                                provenanceBadge(name)
                            ]
                        })
                    ]
                }),

                ui.el("div", {
                    className: "field-row-body",
                    children: [
                        valueNode,
                        ui.el("div", {
                            className: "field-row-confidence",
                            children: [
                                confidence.confidence !== null
                                    ? ui.confidenceIndicator(
                                        confidence.confidence
                                    )
                                    : ui.el("span", {
                                        className:
                                            "confidence-value is-unknown",
                                        text: "No confidence"
                                    })
                            ]
                        })
                    ]
                }),

                evidenceProblems(name),

                ui.el("details", {
                    className: "field-evidence",
                    children: [
                        ui.el("summary", {
                            children: [
                                ui.el("span", {
                                    text:
                                        ids.length
                                            ? "Evidence · " +
                                              ids.join(", ")
                                            : "Evidence"
                                })
                            ]
                        }),
                        ui.el("div", {
                            className: "field-evidence-body",
                            children: [
                                evidenceList(name, lookup),
                                locate
                                    ? ui.el("div", {
                                        className:
                                            "field-evidence-actions",
                                        children: [locate]
                                    })
                                    : null
                            ]
                        })
                    ]
                })
            ]
        });
    }


    /* ======================================================
       RENDER
       ====================================================== */

    function render() {
        if (!container) {
            return;
        }

        if (!model.extraction) {
            ui.replaceChildren(container, [
                ui.emptyState({
                    title: "No extraction is stored",
                    description:
                        "This document has no analysis record, " +
                        "so there are no extracted fields to " +
                        "show."
                })
            ]);
            return;
        }

        var lookup = buildOcrLookup(model.ocrLines);

        var rows = FIELD_ORDER.map(function (name) {
            return fieldRow(name, lookup);
        });

        var meaning = vocabulary.CONFIDENCE_MEANING;

        ui.replaceChildren(container, [
            ui.el("p", {
                className: "field-hint",
                text:
                    meaning.label +
                    " is " +
                    meaning.summary.charAt(0).toLowerCase() +
                    meaning.summary.slice(1) +
                    " " +
                    meaning.no_document_score
            }),
            /* PHASE 10.5. The caveat is separated and given
               warning weight, because the number beside it
               reads as certainty and the measurement says it
               is not. */
            ui.el("p", {
                className: "field-hint is-caveat",
                text: meaning.caveat
            }),
            ui.el("div", {
                className: "field-rows",
                children: rows
            })
        ]);
    }


    function init(options) {
        var config = options || {};

        container = ui.byId("extraction-fields");
        onHighlight = config.onHighlight || null;

        return update(config);
    }

    function update(options) {
        var config = options || {};

        model = {
            extraction: config.extraction || null,
            confidence: config.confidence || {},
            evidenceFlags: config.evidenceFlags || [],
            /* PHASE 10.6. The normalized view, when the
               backend sent one. */
            findings: config.findings || null,
            ocrLines: config.ocrLines || [],
            valueSources: config.valueSources || null,
            effectiveValues: config.effectiveValues || null
        };

        render();
        return model;
    }


    global.VigiloxFieldsView = {
        init: init,
        update: update,
        render: render,
        FIELD_ORDER: FIELD_ORDER,
        buildOcrLookup: buildOcrLookup,
        displayFieldValue: displayFieldValue
    };

}(typeof window !== "undefined" ? window : globalThis));
