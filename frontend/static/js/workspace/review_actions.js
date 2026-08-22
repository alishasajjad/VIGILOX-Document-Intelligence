/* ==========================================================
   VIGILOX HUMAN REVIEW ACTIONS
   PHASE 8.13
   ==========================================================

   The three decisions a reviewer can record, unchanged:

       APPROVE   accept every machine value as read
       CORRECT   replace one or more values
       REJECT    mark the document unusable

   No fourth action is added.


   THE TRUST BOUNDARY
   ----------------------------------------------------------
   The request body carries action, notes and, for a
   correction, corrections. It carries NO reviewer id. The
   backend resolves the reviewer itself through
   ReviewerIdentityService and ignores anything a client sends,
   so putting an id in the payload would be, at best,
   misleading about where authority lives.

   There is no input anywhere on the page through which the
   browser could state who the reviewer is.

   can_review comes from the server. The UI uses it to decide
   whether to show the form at all, which is a convenience, not
   a control: the backend enforces authorisation regardless.


   MACHINE VALUES ARE IMMUTABLE
   ----------------------------------------------------------
   A correction never edits the stored extraction. It is sent
   as an overlay, and FinalRecordService keeps machine_values
   intact while computing effective_values. The correction form
   reflects that: it shows the machine value beside every input
   and never claims to be editing it.

   Only the eight fields HumanReviewService accepts are
   editable. There is no free-form JSON editor.


   DUPLICATE SUBMISSION
   ----------------------------------------------------------
   One review per document is enforced by the database. The UI
   still disables every control for the duration of a submit,
   because a duplicate click produces an HTTP 409 that reads
   like a failure to the user when it was really a double tap.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;


    /* Must match HumanReviewService.CORRECTABLE_FIELDS. */
    var CORRECTABLE_FIELDS = [
        "document_type",
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer"
    ];


    var DATE_FIELDS = [
        "expiry_date",
        "date_of_birth",
        "issue_date"
    ];


    var DOCUMENT_TYPE_OPTIONS = [
        { value: "guard_license", label: "Guard Licence" },
        { value: "sia_badge", label: "SIA Badge" },
        { value: "id_card", label: "ID Card" }
    ];


    /* ==================================================
       ERROR CODES THIS SCREEN HANDLES BY NAME
       ==================================================
       Each maps to what the reviewer should do next, rather
       than restating the code at them.
       ================================================== */

    var ERROR_GUIDANCE = {

        DOCUMENT_ALREADY_REVIEWED: {
            title: "This document has already been reviewed",
            guidance:
                "Another reviewer recorded a decision first. " +
                "The completed review is now shown below.",
            reload: true
        },

        INVALID_HUMAN_REVIEW: {
            title: "The review could not be accepted",
            guidance:
                "Check the corrected values and try again.",
            reload: false
        },

        REVIEWER_NOT_AUTHORIZED: {
            title: "You are not authorised to review",
            guidance:
                "Your account has read-only access. Nothing " +
                "was changed.",
            reload: false,
            refreshIdentity: true
        },

        REVIEWER_AUTHENTICATION_REQUIRED: {
            title: "Reviewer authentication is required",
            guidance:
                "Your identity could not be confirmed. Nothing " +
                "was changed.",
            reload: false,
            refreshIdentity: true
        }
    };


    var nodes = {};

    var context = {
        documentId: null,
        machineValues: {},
        humanReview: null,
        finalRecord: null,
        reviewer: null,
        reviewerError: null
    };

    var submitting = false;
    var callbacks = {};


    function collectNodes() {
        nodes = {
            panel: ui.byId("human-review-panel"),
            message: ui.byId("review-message"),

            completed: ui.byId("completed-review-summary"),
            completedAction: ui.byId("completed-review-action"),
            completedReviewer: ui.byId("completed-reviewer"),
            completedAt: ui.byId("completed-reviewed-at"),
            completedNotes: ui.byId("completed-review-notes"),
            completedCorrections: ui.byId(
                "completed-review-corrections"
            ),

            locked: ui.byId("review-locked-message"),

            reviewerSection: ui.byId(
                "authenticated-reviewer-section"
            ),

            form: ui.byId("human-review-form"),
            notes: ui.byId("review-notes"),

            correctionPanel: ui.byId("correction-panel"),
            correctionFields: ui.byId("correction-fields"),
            cancelCorrection: ui.byId("cancel-correction-button"),

            approve: ui.byId("approve-button"),
            correct: ui.byId("correct-button"),
            reject: ui.byId("reject-button"),
            submitCorrection: ui.byId("submit-correction-button"),

            dialog: ui.byId("confirm-dialog"),
            dialogTitle: ui.byId("confirm-title"),
            dialogBody: ui.byId("confirm-body"),
            dialogCancel: ui.byId("confirm-cancel"),
            dialogAccept: ui.byId("confirm-accept")
        };
    }


    /* ======================================================
       MESSAGES
       ====================================================== */

    function showMessage(text, kind) {
        ui.setStatusMessage(nodes.message, text, kind || "error");
    }

    function clearMessage() {
        ui.setStatusMessage(nodes.message, "", "info");
    }


    /* ======================================================
       CONFIRMATION DIALOG
       ======================================================
       A native <dialog>. Focus containment, Escape and the
       backdrop come from the platform, and focus returns to
       the control that opened it.
       ====================================================== */

    var lastFocused = null;

    function confirmAction(options) {
        var config = options || {};

        if (!nodes.dialog || !nodes.dialog.showModal) {
            /* No dialog element: proceed rather than blocking
               the reviewer. The backend is still the
               authority. */
            return Promise.resolve(true);
        }

        lastFocused = global.document.activeElement || null;

        nodes.dialogTitle.textContent = config.title || "Confirm";

        ui.replaceChildren(nodes.dialogBody, [
            ui.el("p", { text: config.body || "" }),
            config.consequence
                ? ui.el("p", {
                    className: "dialog-consequence",
                    text: config.consequence
                })
                : null
        ]);

        nodes.dialogAccept.textContent =
            config.acceptLabel || "Confirm";

        nodes.dialogAccept.className =
            "btn " + (config.danger ? "btn-danger" : "btn-primary");

        return new Promise(function (resolve) {
            function finish(accepted) {
                nodes.dialogAccept.removeEventListener(
                    "click",
                    onAccept
                );
                nodes.dialogCancel.removeEventListener(
                    "click",
                    onCancel
                );

                if (nodes.dialog.open) {
                    nodes.dialog.close();
                }

                /* Focus goes back where it came from. */
                if (lastFocused && lastFocused.focus) {
                    lastFocused.focus();
                }

                resolve(accepted);
            }

            function onAccept() {
                finish(true);
            }

            function onCancel() {
                finish(false);
            }

            nodes.dialogAccept.addEventListener("click", onAccept);
            nodes.dialogCancel.addEventListener("click", onCancel);

            nodes.dialog.showModal();

            /* Cancel is focused first, so Enter on an
               accidental keypress does not record a decision. */
            if (nodes.dialogCancel.focus) {
                nodes.dialogCancel.focus();
            }
        });
    }


    /* ======================================================
       CORRECTION INPUTS
       ====================================================== */

    function machineValue(name) {
        var value = context.machineValues
            ? context.machineValues[name]
            : null;
        return value === undefined ? null : value;
    }

    function correctionInput(name) {
        var original = machineValue(name);
        var inputId = "correction-" + name;

        var control;

        if (name === "document_type") {
            /* A closed set, so a select. A typed document type
               would be rejected by the schema. */
            control = ui.el("select", {
                className: "select correction-input",
                attrs: { id: inputId, "data-field-name": name }
            });

            DOCUMENT_TYPE_OPTIONS.forEach(function (option) {
                var node = ui.el("option", {
                    text: option.label,
                    attrs: { value: option.value }
                });
                if (option.value === original) {
                    node.setAttribute("selected", "selected");
                }
                control.appendChild(node);
            });

            control.value = original || "";
        } else {
            control = ui.el("input", {
                className: "input correction-input",
                attrs: {
                    id: inputId,
                    type: "text",
                    "data-field-name": name,
                    autocomplete: "off"
                }
            });

            if (DATE_FIELDS.indexOf(name) !== -1) {
                control.setAttribute("placeholder", "YYYY-MM-DD");
                control.setAttribute(
                    "aria-describedby",
                    inputId + "-hint"
                );
            }

            control.value = original === null ? "" : String(original);
        }

        return ui.el("div", {
            className: "correction-field",
            children: [
                ui.el("label", {
                    className: "field-label",
                    text: vocabulary.fieldLabel(name),
                    attrs: { for: inputId }
                }),

                /* The machine reading stays visible beside the
                   input, so a reviewer always sees what they
                   are changing. */
                ui.el("p", {
                    className: "correction-machine-value",
                    children: [
                        ui.el("span", {
                            className: "correction-machine-label",
                            text: "Machine read"
                        }),
                        ui.el("span", {
                            className:
                                "correction-machine-text" +
                                (original === null
                                    ? " is-empty"
                                    : ""),
                            text:
                                original === null
                                    ? "Nothing"
                                    : String(original)
                        })
                    ]
                }),

                control,

                DATE_FIELDS.indexOf(name) !== -1
                    ? ui.el("p", {
                        className: "field-hint",
                        text: "Use YYYY-MM-DD. Leave blank to clear.",
                        attrs: { id: inputId + "-hint" }
                    })
                    : null
            ]
        });
    }

    function renderCorrectionFields() {
        ui.replaceChildren(
            nodes.correctionFields,
            CORRECTABLE_FIELDS.map(correctionInput)
        );
    }

    /**
     * Only fields the reviewer actually changed.
     *
     * Key presence matters, not truthiness: clearing a value
     * to null is a legitimate correction and must be sent.
     */
    function collectCorrections() {
        var corrections = {};

        var inputs = nodes.correctionFields.querySelectorAll(
            ".correction-input"
        );

        Array.prototype.forEach.call(inputs, function (input) {
            var name =
                input.getAttribute("data-field-name") ||
                (input.dataset ? input.dataset.fieldName : null);

            if (!name) {
                return;
            }

            var raw = String(input.value === undefined ? "" : input.value)
                .trim();

            var next = raw;

            /* document_type is a select and always has a value.
               Every other field can be cleared to null. */
            if (name !== "document_type" && raw === "") {
                next = null;
            }

            var original = machineValue(name);
            var normalised = original === undefined ? null : original;

            if (next !== normalised) {
                corrections[name] = next;
            }
        });

        return corrections;
    }


    /* ======================================================
       CORRECTION MODE
       ====================================================== */

    var correctionMode = false;

    function openCorrectionMode() {
        clearMessage();

        if (!canReview()) {
            showMessage(
                context.reviewerError ||
                    "Your account does not have permission to " +
                    "correct this document."
            );
            return false;
        }

        correctionMode = true;
        renderCorrectionFields();

        nodes.correctionPanel.hidden = false;
        nodes.approve.hidden = true;
        nodes.reject.hidden = true;
        nodes.correct.hidden = true;
        nodes.submitCorrection.hidden = false;

        /* Focus the first input, so a keyboard user is put
           where the work is. */
        var first = nodes.correctionFields.querySelector(
            ".correction-input"
        );
        if (first && first.focus) {
            first.focus();
        }

        return true;
    }

    function closeCorrectionMode() {
        /* Whether correction mode was actually open decides
           whether focus should move.

           This function also runs on every re-render to reset
           the panel, and an unconditional focus() there stole
           focus from whatever the reviewer was doing. It moved
           focus onto the Correct button after a successful
           Approve, which is both wrong and disorienting. */
        var wasOpen = correctionMode;

        correctionMode = false;
        ui.clear(nodes.correctionFields);

        nodes.correctionPanel.hidden = true;
        nodes.approve.hidden = false;
        nodes.reject.hidden = false;
        nodes.correct.hidden = false;
        nodes.submitCorrection.hidden = true;

        /* Only a real cancel clears the message.
           This function also runs on every re-render, and an
           unconditional clear there wiped the explanation of
           the failure that caused the re-render. An
           authorisation error left the reviewer with an empty
           panel and no idea why nothing happened. */
        if (wasOpen) {
            clearMessage();
        }

        /* Only a real cancel returns focus, and only to a
           control that is actually visible. */
        if (
            wasOpen &&
            nodes.correct &&
            nodes.correct.focus &&
            !nodes.correct.hidden
        ) {
            nodes.correct.focus();
        }
    }


    /* ======================================================
       SUBMIT STATE
       ====================================================== */

    function setSubmitting(value) {
        submitting = value;

        [
            nodes.notes,
            nodes.approve,
            nodes.correct,
            nodes.reject,
            nodes.submitCorrection,
            nodes.cancelCorrection
        ].forEach(function (node) {
            if (node) {
                node.disabled = value;
            }
        });

        var inputs = nodes.correctionFields.querySelectorAll(
            ".correction-input"
        );

        Array.prototype.forEach.call(inputs, function (input) {
            input.disabled = value;
        });

        /* aria-busy on the panel, so the state is announced
           rather than only visible. */
        if (nodes.panel) {
            if (value) {
                nodes.panel.setAttribute("aria-busy", "true");
            } else {
                nodes.panel.removeAttribute("aria-busy");
            }
        }
    }

    function isSubmitting() {
        return submitting;
    }


    /* ======================================================
       SUBMIT
       ====================================================== */

    function canReview() {
        return Boolean(context.reviewer && context.reviewer.can_review);
    }

    function notes() {
        if (!nodes.notes) {
            return null;
        }
        var text = String(nodes.notes.value || "").trim();
        return text ? text : null;
    }

    function confirmCopy(action, corrections) {
        var described = vocabulary.describeHumanAction(action);
        var count = corrections
            ? Object.keys(corrections).length
            : 0;

        if (action === "APPROVE") {
            return {
                title: "Approve this document?",
                body: described.summary,
                consequence:
                    "The document becomes final and its machine " +
                    "values become the effective record.",
                acceptLabel: "Approve"
            };
        }

        if (action === "REJECT") {
            return {
                title: "Reject this document?",
                body: described.summary,
                consequence:
                    "The document becomes final and NOT usable. " +
                    "No effective values will be published.",
                acceptLabel: "Reject",
                danger: true
            };
        }

        return {
            title:
                count === 1
                    ? "Submit 1 correction?"
                    : "Submit " + count + " corrections?",
            body: described.summary,
            consequence:
                "The document becomes final. The machine " +
                "reading is preserved and your correction " +
                "becomes the effective value.",
            acceptLabel: "Submit Corrections"
        };
    }

    function submitReview(action, corrections) {
        /* Guard before anything else. The database rejects a
           duplicate review with HTTP 409, and a double click
           should not surface as a failure. */
        if (submitting) {
            return Promise.resolve(null);
        }

        clearMessage();

        if (!context.reviewer) {
            showMessage(
                context.reviewerError ||
                    "Reviewer authentication is required."
            );
            return Promise.resolve(null);
        }

        if (!canReview()) {
            showMessage(
                "Your account has read-only access and cannot " +
                "record review decisions."
            );
            return Promise.resolve(null);
        }

        if (
            action === "CORRECT" &&
            (!corrections || !Object.keys(corrections).length)
        ) {
            showMessage(
                "Change at least one value before submitting a " +
                "correction."
            );
            return Promise.resolve(null);
        }

        return confirmAction(
            confirmCopy(action, corrections)
        ).then(function (accepted) {
            if (!accepted) {
                return null;
            }

            setSubmitting(true);

            /* ==========================================
               SECURITY

               reviewer_id is deliberately absent. The
               backend resolves the reviewer itself and
               ignores any client-supplied identity.
               ========================================== */

            const payload = {
                action: action,
                notes: notes()
            };

            if (action === "CORRECT") {
                payload.corrections = corrections;
            }

            return api.endpoints
                .submitReview(context.documentId, payload)
                .then(
                    function (result) {
                        setSubmitting(false);
                        return onSubmitted(result);
                    },
                    function (error) {
                        setSubmitting(false);
                        return onSubmitFailed(error);
                    }
                );
        });
    }

    function onSubmitted(result) {
        var described = vocabulary.describeHumanAction(
            result && result.human_action
        );

        if (typeof callbacks.onReviewed === "function") {
            /* Reload from the server rather than patching local
               state. The final record is the backend's to
               compute, and only a reload proves what was
               stored. */
            return Promise.resolve(callbacks.onReviewed()).then(
                function () {
                    showMessage(
                        "Review recorded: " +
                            described.pastLabel +
                            ".",
                        "success"
                    );
                    return result;
                }
            );
        }

        showMessage(
            "Review recorded: " + described.pastLabel + ".",
            "success"
        );

        return result;
    }

    function onSubmitFailed(error) {
        var code = error && error.code ? error.code : null;

        var guidance =
            code &&
            Object.prototype.hasOwnProperty.call(
                ERROR_GUIDANCE,
                code
            )
                ? ERROR_GUIDANCE[code]
                : null;

        var parts = [];

        if (guidance) {
            parts.push(guidance.title);
            parts.push(guidance.guidance);
        } else {
            parts.push(
                (error && error.message) ||
                    "The review could not be submitted."
            );
        }

        /* The stable code and the request id are appended so a
           reviewer can quote them, without making them the
           message. */
        if (code) {
            parts.push("Code: " + code);
        }

        if (error && error.requestId) {
            parts.push("Support Request ID: " + error.requestId);
        }

        showMessage(parts.join(" "));

        if (
            guidance &&
            guidance.refreshIdentity &&
            typeof callbacks.onIdentityChanged === "function"
        ) {
            return Promise.resolve(
                callbacks.onIdentityChanged()
            ).then(function () {
                /* Re-stated after the refresh, because
                   re-resolving identity re-renders this panel.
                   Without this the reviewer saw the panel
                   change and no explanation of why. */
                showMessage(parts.join(" "));
                return null;
            });
        }

        if (
            guidance &&
            guidance.reload &&
            typeof callbacks.onReviewed === "function"
        ) {
            return Promise.resolve(callbacks.onReviewed()).then(
                function () {
                    /* Re-state the message: the reload above
                       re-renders the panel. */
                    showMessage(parts.join(" "));
                    return null;
                }
            );
        }

        return null;
    }


    /* ======================================================
       COMPLETED REVIEW
       ====================================================== */

    function renderCompleted(humanReview) {
        var described = vocabulary.describeHumanAction(
            humanReview.human_action
        );

        ui.replaceChildren(nodes.completedAction, [
            ui.badge(
                described.pastLabel,
                humanReview.human_action === "REJECT"
                    ? "badge-danger"
                    : humanReview.human_action === "CORRECT"
                        ? "badge-info"
                        : "badge-success"
            )
        ]);

        nodes.completedReviewer.textContent = ui.displayValue(
            humanReview.reviewer_id
        );

        nodes.completedAt.textContent = ui.formatDateTime(
            humanReview.reviewed_at
        );

        nodes.completedNotes.textContent = humanReview.notes
            ? String(humanReview.notes)
            : "No notes were recorded.";

        var corrections = humanReview.corrections || {};
        var names = Object.keys(corrections);

        if (!names.length) {
            ui.replaceChildren(nodes.completedCorrections, [
                ui.el("p", {
                    className: "field-hint",
                    text: "No values were corrected."
                })
            ]);
            return;
        }

        ui.replaceChildren(nodes.completedCorrections, [
            ui.el("h3", {
                className: "completed-corrections-title",
                text:
                    names.length === 1
                        ? "1 corrected value"
                        : names.length + " corrected values"
            }),
            ui.el("div", {
                className: "value-rows",
                children: names.map(function (name) {
                    return ui.el("div", {
                        className: "value-row is-corrected",
                        children: [
                            ui.el("div", {
                                className: "value-row-label",
                                text: vocabulary.fieldLabel(name)
                            }),
                            ui.el("div", {
                                className: "value-cell is-machine",
                                children: [
                                    ui.el("span", {
                                        className: "value-cell-label",
                                        text: "Machine"
                                    }),
                                    ui.el("span", {
                                        className: "value-cell-value",
                                        text: ui.isBlank(
                                            machineValue(name)
                                        )
                                            ? "Nothing"
                                            : String(
                                                machineValue(name)
                                            )
                                    })
                                ]
                            }),
                            ui.el("div", {
                                className: "value-cell is-human",
                                children: [
                                    ui.el("span", {
                                        className: "value-cell-label",
                                        text: "Corrected to"
                                    }),
                                    ui.el("span", {
                                        className: "value-cell-value",
                                        text: ui.isBlank(
                                            corrections[name]
                                        )
                                            ? "Cleared"
                                            : String(corrections[name])
                                    })
                                ]
                            }),
                            ui.el("div", {
                                className: "value-row-source",
                                children: [
                                    ui.provenanceBadge(
                                        "HUMAN_CORRECTION"
                                    )
                                ]
                            })
                        ]
                    });
                })
            })
        ]);
    }


    /* ======================================================
       LOCKED
       ====================================================== */

    function renderLocked(title, description) {
        ui.replaceChildren(nodes.locked, [
            ui.el("div", {
                className: "alert alert-info",
                attrs: { role: "note" },
                children: [
                    ui.el("div", {
                        className: "alert-body",
                        children: [
                            ui.el("p", {
                                className: "alert-title",
                                text: title
                            }),
                            description
                                ? ui.el("p", { text: description })
                                : null
                        ]
                    })
                ]
            })
        ]);
    }


    /* ======================================================
       STATE
       ======================================================
       Exactly one of: completed review, review form, or a
       locked explanation.
       ====================================================== */

    function renderHumanReviewState(humanReview, finalRecord) {
        context.humanReview = humanReview || null;
        context.finalRecord = finalRecord || null;

        var status = finalRecord
            ? finalRecord.final_status
            : null;

        nodes.completed.hidden = true;
        nodes.locked.hidden = true;
        nodes.reviewerSection.hidden = true;
        nodes.form.hidden = true;

        /* ==================================================
           ALREADY REVIEWED — LOCKED
           ==================================================
           One human review per document. The record is shown;
           no form is offered.
           ================================================== */

        if (humanReview) {
            nodes.completed.hidden = false;
            renderCompleted(humanReview);
            return "COMPLETED";
        }

        /* ==================================================
           PENDING REVIEW — ACTIONABLE
           ================================================== */

        if (status === "PENDING_REVIEW") {
            nodes.reviewerSection.hidden = false;
            closeCorrectionMode();
            setSubmitting(false);

            if (canReview()) {
                nodes.form.hidden = false;
                return "ACTIONABLE";
            }

            nodes.locked.hidden = false;

            if (context.reviewer) {
                renderLocked(
                    "Read-only access",
                    "The authenticated user " +
                        ui.displayValue(
                            context.reviewer.reviewer_id
                        ) +
                        " cannot record review decisions."
                );
            } else {
                renderLocked(
                    "Reviewer authentication is required",
                    context.reviewerError ||
                        "Your identity could not be confirmed, so " +
                        "no decision can be recorded."
                );
            }

            return "READ_ONLY";
        }

        /* ==================================================
           AUTO_ACCEPTED — NOT A REVIEW TARGET
           ==================================================
           Consistent with the final-record rules: an
           auto-accepted document is already final and usable
           and does not take a human review.
           ================================================== */

        nodes.locked.hidden = false;

        if (status === "AUTO_ACCEPTED") {
            renderLocked(
                "No review required",
                "VIGILOX confirmed every required field against " +
                "its own OCR evidence, so this document was " +
                "auto-accepted and is already final."
            );
            return "AUTO_ACCEPTED";
        }

        /* ==================================================
           UNSUPPORTED — NOT A REVIEW TARGET
           PHASE 10.2
           ==================================================
           This branch existed already and caught the status as
           an unrecognised one, which failed safe: no form, no
           Approve button, nothing publishable. The only thing
           missing was saying why.

           Approve deliberately stays unavailable. Approving an
           unsupported document would publish an effective
           record whose document type is unknown and whose
           fields are empty, which is exactly the outcome the
           unsupported policy exists to prevent.
           ================================================== */

        if (status === "UNSUPPORTED") {
            renderLocked(
                "Unsupported document",
                "VIGILOX could not identify this file as one " +
                "of the supported document types, so there " +
                "is nothing here for a reviewer to confirm " +
                "or correct. No review is pending and no " +
                "usable record was produced."
            );
            return "UNSUPPORTED";
        }

        renderLocked(
            "Not available for review",
            "This document is not currently in a state that " +
            "accepts a human review decision."
        );

        return "UNAVAILABLE";
    }


    /* ======================================================
       INIT
       ====================================================== */

    function bind() {
        if (nodes.approve) {
            nodes.approve.addEventListener("click", function () {
                submitReview("APPROVE", null);
            });
        }

        if (nodes.reject) {
            nodes.reject.addEventListener("click", function () {
                submitReview("REJECT", null);
            });
        }

        if (nodes.correct) {
            nodes.correct.addEventListener("click", function () {
                openCorrectionMode();
            });
        }

        if (nodes.cancelCorrection) {
            nodes.cancelCorrection.addEventListener(
                "click",
                function () {
                    closeCorrectionMode();
                }
            );
        }

        if (nodes.submitCorrection) {
            nodes.submitCorrection.addEventListener(
                "click",
                function () {
                    submitReview("CORRECT", collectCorrections());
                }
            );
        }
    }

    function init(options) {
        var config = options || {};

        collectNodes();
        bind();

        callbacks = {
            onReviewed: config.onReviewed || null,
            onIdentityChanged: config.onIdentityChanged || null
        };
    }

    function update(config) {
        context.documentId = config.documentId || null;
        context.machineValues = config.machineValues || {};
        context.reviewer = config.reviewer || null;
        context.reviewerError = config.reviewerError || null;

        return renderHumanReviewState(
            config.humanReview,
            config.finalRecord
        );
    }


    global.VigiloxReviewActions = {
        init: init,
        update: update,
        renderHumanReviewState: renderHumanReviewState,
        submitReview: submitReview,
        collectCorrections: collectCorrections,
        openCorrectionMode: openCorrectionMode,
        closeCorrectionMode: closeCorrectionMode,
        isSubmitting: isSubmitting,
        isCorrectionMode: function () {
            return correctionMode;
        },
        CORRECTABLE_FIELDS: CORRECTABLE_FIELDS,
        DOCUMENT_TYPE_OPTIONS: DOCUMENT_TYPE_OPTIONS,
        ERROR_GUIDANCE: ERROR_GUIDANCE
    };

}(typeof window !== "undefined" ? window : globalThis));
