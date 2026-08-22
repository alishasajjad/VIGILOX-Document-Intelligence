/* ==========================================================
   VIGILOX DOCUMENT WORKSPACE
   PHASE 8.10
   ==========================================================

   Owns GET /review/{document_id}.

   WHAT THIS FILE IS
   ----------------------------------------------------------
   The page controller. It loads the document, resolves the
   reviewer identity, and hands the data to the view modules.

   It is no longer the whole screen. The Phase 7B version was
   one ~4,000 line file that rendered every panel with
   innerHTML string templates and carried its own fetch calls
   and its own HTML escaper. Phase 8.10 split it by
   responsibility:

       js/workspace/tabs.js           detail tab controller
       js/workspace/source_panel.js   image + OCR evidence
       js/workspace/fields_view.js    values, confidence,
                                      evidence, provenance
       js/workspace/validation_view.js  dates, expiry, findings
       js/workspace/result_view.js    final record, effective
                                      values, history, raw data
       js/workspace/review_actions.js approve / correct / reject

   The filename stays review_detail.js. Browsers have it
   cached and existing tests fetch it by URL; renaming it would
   break both for no benefit.


   REQUESTS
   ----------------------------------------------------------
   A page load issues four:

       GET /api/v1/documents/{id}
       GET /api/v1/reviewer/me
       GET /api/v1/documents/{id}/image
       GET /api/v1/documents/{id}/history

   All four go through the shared client. The reviewer identity
   is fetched once and pushed into the sidebar with
   applyShellReviewer, so the shell adds no second identity
   request.


   REVIEWER IDENTITY
   ----------------------------------------------------------
   Resolved by the server. The browser sends nothing and this
   page has no input through which it could.

   Identity is loaded BEFORE the review panel renders, because
   can_review decides whether a form is offered at all.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;
    var vocabulary = global.VigiloxVocabulary;

    var tabsModule = global.VigiloxTabs;
    var sourcePanel = global.VigiloxSourcePanel;
    var fieldsView = global.VigiloxFieldsView;
    var validationView = global.VigiloxValidationView;
    var resultView = global.VigiloxResultView;
    var reviewActions = global.VigiloxReviewActions;


    /* ======================================================
       LOADED DOCUMENT STATE
       ====================================================== */

    var loadedDocumentId = null;
    var loadedDocumentMetadata = {};
    var loadedAnalysis = {};
    var loadedHumanReview = null;
    var loadedFinalRecord = null;
    var loadedReviewerIdentity = null;
    var reviewerIdentityError = null;
    var loadedHistory = null;
    var loadedPayload = null;

    /* PHASE 10.2 / 10.1.

       classification is derived server-side and arrives at the
       top level of the payload, beside final_record, because
       both are conclusions about the document rather than
       things read off it.

       quality is null for any document analysed before image
       quality assessment existed. null is carried through
       unchanged and rendered as NOT ASSESSED. Defaulting it to
       an empty assessment here would turn "we did not look"
       into "we looked and found nothing", which are different
       statements. */
    var loadedClassification = null;

    /* PHASE 10.6. payload.findings, the normalized view
       over the anomaly, quality and evidence payloads.
       Derived server-side beside the raw payloads it is
       built from, so the panel and the raw record cannot
       disagree. null when there is no analysis to
       normalize. */
    var loadedFindings = null;

    var tabs = null;
    var loading = false;


    var nodes = {};

    function collectNodes() {
        nodes = {
            loading: ui.byId("detail-loading"),
            error: ui.byId("detail-error"),
            errorMessage: ui.byId("detail-error-message"),
            content: ui.byId("detail-content"),
            title: ui.byId("document-title"),
            subtitle: ui.byId("document-subtitle"),
            facts: ui.byId("document-facts"),
            status: ui.byId("workspace-status"),
            tablist: ui.byId("workspace-tablist"),
            copyJson: ui.byId("copy-json-button"),
            downloadJson: ui.byId("download-json-button"),

            reviewerLoading: ui.byId(
                "authenticated-reviewer-loading"
            ),
            reviewerContent: ui.byId(
                "authenticated-reviewer-content"
            ),
            reviewerCard: ui.byId("authenticated-reviewer-card"),
            reviewerName: ui.byId("authenticated-reviewer-name"),
            reviewerRole: ui.byId("authenticated-reviewer-role"),
            reviewerSource: ui.byId(
                "authenticated-reviewer-source"
            ),
            reviewerAccess: ui.byId(
                "authenticated-reviewer-access"
            ),
            reviewerError: ui.byId("authenticated-reviewer-error")
        };
    }


    /* ======================================================
       DOCUMENT ID
       ======================================================
       Read from the path the server served. The route ignores
       the id when choosing a file, so this is the only place
       it is interpreted.
       ====================================================== */

    function getDocumentId() {
        var segments = String(global.location.pathname || "")
            .split("/")
            .filter(Boolean);

        if (segments.length < 2) {
            return null;
        }

        return segments[segments.length - 1];
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
        if (nodes.content) {
            nodes.content.hidden = which !== "content";
        }
    }

    function renderSkeleton() {
        ui.replaceChildren(nodes.loading, [
            ui.el("div", {
                className: "workspace",
                children: [
                    ui.el("div", {
                        className: "card",
                        children: [
                            ui.el("div", {
                                className: "card-body",
                                children: [
                                    ui.el("div", {
                                        className:
                                            "skeleton skeleton-card"
                                    })
                                ]
                            })
                        ]
                    }),
                    ui.el("div", {
                        className: "card",
                        children: [
                            ui.el("div", {
                                className: "card-body",
                                children: [ui.skeletonRows(6, 3)]
                            })
                        ]
                    })
                ]
            })
        ]);
    }

    function showError(error) {
        ui.replaceChildren(nodes.errorMessage, [
            ui.retryableErrorState(error, {
                title: "This document could not be loaded",
                onRetry: loadDocument
            })
        ]);
        setPanels("error");
    }


    /* ======================================================
       REVIEWER IDENTITY
       PHASE 7C.5
       ======================================================
       Server-resolved. Rendered into the review panel card and
       reused for the sidebar so no second request is made.
       ====================================================== */

    function renderReviewerIdentity() {
        /* Reuses the identity this page already loaded. */
        ui.applyShellReviewer(loadedReviewerIdentity, {
            unauthenticated: Boolean(reviewerIdentityError)
        });

        if (!nodes.reviewerCard) {
            return loadedReviewerIdentity;
        }

        nodes.reviewerLoading.hidden = true;
        nodes.reviewerContent.hidden = true;
        nodes.reviewerError.hidden = true;

        nodes.reviewerCard.classList.remove(
            "reviewer-card-authorized",
            "reviewer-card-readonly",
            "reviewer-card-error"
        );

        if (!loadedReviewerIdentity) {
            nodes.reviewerError.hidden = false;
            nodes.reviewerError.textContent =
                reviewerIdentityError ||
                "The authenticated reviewer identity is not " +
                "available.";
            nodes.reviewerCard.classList.add(
                "reviewer-card-error"
            );
            return null;
        }

        nodes.reviewerContent.hidden = false;

        nodes.reviewerName.textContent = ui.displayValue(
            loadedReviewerIdentity.reviewer_id
        );

        nodes.reviewerRole.textContent = ui.displayValue(
            loadedReviewerIdentity.role
        );

        nodes.reviewerSource.textContent = ui.displayValue(
            loadedReviewerIdentity.source
        );

        /* can_review is the server's answer. This only shows
           it; the backend enforces it. */
        if (loadedReviewerIdentity.can_review) {
            nodes.reviewerAccess.textContent =
                "Review access granted";
            nodes.reviewerAccess.className =
                "reviewer-access-badge reviewer-access-granted";
            nodes.reviewerCard.classList.add(
                "reviewer-card-authorized"
            );
        } else {
            nodes.reviewerAccess.textContent = "Read-only access";
            nodes.reviewerAccess.className =
                "reviewer-access-badge reviewer-access-readonly";
            nodes.reviewerCard.classList.add(
                "reviewer-card-readonly"
            );
        }

        return loadedReviewerIdentity;
    }

    function loadReviewerIdentity() {
        loadedReviewerIdentity = null;
        reviewerIdentityError = null;

        if (nodes.reviewerLoading) {
            nodes.reviewerLoading.hidden = false;
            nodes.reviewerContent.hidden = true;
            nodes.reviewerError.hidden = true;
        }

        return api.endpoints.getReviewerIdentity().then(
            function (payload) {
                loadedReviewerIdentity =
                    (payload && payload.reviewer) || null;

                if (!loadedReviewerIdentity) {
                    reviewerIdentityError =
                        "The identity response carried no " +
                        "reviewer.";
                }

                renderReviewerIdentity();
                return loadedReviewerIdentity;
            },
            function (error) {
                /* An unauthenticated or unauthorised reviewer
                   is a legitimate state, not a page failure.
                   The stable code is surfaced without leaking
                   anything internal. */
                reviewerIdentityError =
                    (error && error.message) ||
                    "The reviewer identity service could not be " +
                    "reached.";

                renderReviewerIdentity();
                return null;
            }
        );
    }

    /** Re-resolve identity and re-render the review panel. */
    function refreshIdentity() {
        return loadReviewerIdentity().then(function () {
            applyReviewState();
            return loadedReviewerIdentity;
        });
    }


    /* ======================================================
       HEADER AND FACTS
       ====================================================== */

    function renderHeader() {
        if (nodes.title) {
            /* A filename comes from an uploaded file and is
               untrusted. textContent, always. */
            nodes.title.textContent = ui.displayValue(
                loadedDocumentMetadata.original_filename
            );
        }

        if (nodes.subtitle) {
            nodes.subtitle.textContent = ui.displayValue(
                loadedDocumentMetadata.document_id
            );
        }
    }

    function renderFacts() {
        if (!nodes.facts) {
            return;
        }

        var rows = [
            ["Document type", ui.formatDocumentType(
                loadedDocumentMetadata.document_type
            )],
            ["Processing status", ui.humanizeEnum(
                loadedDocumentMetadata.processing_status
            )],
            ["File type", ui.displayValue(
                loadedDocumentMetadata.content_type
            )],
            ["Uploaded", ui.formatDateTime(
                loadedDocumentMetadata.created_at
            )],
            ["Analysed", ui.formatDateTime(
                loadedAnalysis ? loadedAnalysis.created_at : null
            )],
            ["Document ID", ui.displayValue(
                loadedDocumentMetadata.document_id
            )],
            ["Analysis ID", ui.displayValue(
                loadedAnalysis ? loadedAnalysis.analysis_id : null
            )]
        ];

        ui.replaceChildren(
            nodes.facts,
            rows.map(function (row) {
                return ui.el("div", {
                    className: "detail-row",
                    children: [
                        ui.el("span", {
                            className: "detail-label",
                            text: row[0]
                        }),
                        ui.el("span", {
                            className: "detail-value text-mono",
                            text: row[1]
                        })
                    ]
                });
            })
        );
    }


    /* ======================================================
       MACHINE VALUES
       ======================================================
       Taken from the final record when one exists, because
       FinalRecordService already flattened them there. Falls
       back to reading the extraction directly for a document
       with no analysis.
       ====================================================== */

    function machineValues() {
        if (loadedFinalRecord && loadedFinalRecord.machine_values) {
            return loadedFinalRecord.machine_values;
        }

        var extraction =
            (loadedAnalysis && loadedAnalysis.extraction) || {};

        var values = {
            document_type: extraction.document_type || null
        };

        reviewActions.CORRECTABLE_FIELDS.forEach(function (name) {
            if (name === "document_type") {
                return;
            }
            var field = extraction[name] || {};
            values[name] =
                field.value === undefined ? null : field.value;
        });

        return values;
    }


    /* ======================================================
       VIEW WIRING
       ====================================================== */

    function documentContext() {
        return {
            documentType: loadedDocumentMetadata.document_type,
            finalRecord: loadedFinalRecord,
            humanReview: loadedHumanReview,
            reviewDecision: loadedAnalysis
                ? loadedAnalysis.review_decision
                : null,
            dateValidation: loadedAnalysis
                ? loadedAnalysis.date_validation
                : null,
            anomalyValidation: loadedAnalysis
                ? loadedAnalysis.anomaly_validation
                : null,
            classification: loadedClassification,
            raw: loadedPayload
        };
    }

    function applyReviewState() {
        return reviewActions.update({
            documentId: loadedDocumentId,
            machineValues: machineValues(),
            humanReview: loadedHumanReview,
            finalRecord: loadedFinalRecord,
            reviewer: loadedReviewerIdentity,
            reviewerError: reviewerIdentityError,
            classification: loadedClassification
        });
    }

    function renderAll() {
        renderHeader();
        renderFacts();

        resultView.update(documentContext());

        fieldsView.update({
            extraction: loadedAnalysis
                ? loadedAnalysis.extraction
                : null,
            confidence: loadedAnalysis
                ? loadedAnalysis.field_confidence
                : {},
            evidenceFlags: loadedAnalysis
                ? loadedAnalysis.evidence_flags
                : [],
            findings: loadedFindings,
            ocrLines: loadedAnalysis
                ? loadedAnalysis.ocr_lines
                : [],
            valueSources: loadedFinalRecord
                ? loadedFinalRecord.value_sources
                : null,
            effectiveValues: loadedFinalRecord
                ? loadedFinalRecord.effective_values
                : null
        });

        validationView.update({
            dateValidation: loadedAnalysis
                ? loadedAnalysis.date_validation
                : null,
            anomalyValidation: loadedAnalysis
                ? loadedAnalysis.anomaly_validation
                : null,
            reviewDecision: loadedAnalysis
                ? loadedAnalysis.review_decision
                : null,
            quality: loadedAnalysis
                ? loadedAnalysis.quality
                : null,
            findings: loadedFindings
        });

        applyReviewState();
    }


    /* ======================================================
       HISTORY
       ====================================================== */

    function loadReviewHistory(documentId) {
        return api.endpoints.getDocumentHistory(documentId).then(
            function (history) {
                loadedHistory = history;
                resultView.renderReviewHistory(history);
                return history;
            },
            function (error) {
                loadedHistory = null;

                var container = ui.byId("review-history-list");

                ui.replaceChildren(container, [
                    ui.retryableErrorState(error, {
                        title: "The audit history could not be loaded",
                        onRetry: function () {
                            return loadReviewHistory(documentId);
                        }
                    })
                ]);

                return null;
            }
        );
    }


    /* ======================================================
       TECHNICAL DATA ACTIONS
       ======================================================
       Copy and Download operate on data already in the page.
       No new request, and nothing is generated server-side.
       ====================================================== */

    function jsonFilename() {
        return (
            "vigilox-" +
            String(loadedDocumentId || "document").replace(
                /[^A-Za-z0-9_-]/g,
                "-"
            ) +
            ".json"
        );
    }

    function announce(text, kind) {
        ui.setStatusMessage(nodes.status, text, kind || "info");
    }

    function copyJson() {
        var text = resultView.jsonText();

        if (!text) {
            announce(
                "There is nothing to copy yet.",
                "error"
            );
            return Promise.resolve(false);
        }

        var clipboard =
            global.navigator && global.navigator.clipboard;

        if (!clipboard || !clipboard.writeText) {
            announce(
                "This browser did not allow copying. Use the " +
                "Technical Data tab and copy manually.",
                "error"
            );
            return Promise.resolve(false);
        }

        return clipboard.writeText(text).then(
            function () {
                announce(
                    "The document JSON was copied to your " +
                    "clipboard.",
                    "success"
                );
                return true;
            },
            function () {
                announce(
                    "The copy was blocked by the browser.",
                    "error"
                );
                return false;
            }
        );
    }

    function downloadJson() {
        var text = resultView.jsonText();

        if (!text) {
            announce(
                "There is nothing to download yet.",
                "error"
            );
            return false;
        }

        var blob = new global.Blob([text], {
            type: "application/json"
        });

        var url = global.URL.createObjectURL(blob);

        var link = ui.el("a", {
            attrs: { href: url, download: jsonFilename() }
        });

        global.document.body.appendChild(link);
        link.click();
        global.document.body.removeChild(link);

        /* Released immediately: the browser has already taken
           the bytes it needs, and holding a blob of document
           data alive serves nothing. */
        global.URL.revokeObjectURL(url);

        announce(
            "The document JSON was downloaded.",
            "success"
        );

        return true;
    }


    /* ======================================================
       LOAD
       ====================================================== */

    function loadDocument() {
        if (loading) {
            return Promise.resolve(null);
        }

        var documentId = getDocumentId();

        if (!documentId) {
            showError({
                code: "MISSING_DOCUMENT_ID",
                message:
                    "This URL does not contain a document ID.",
                requestId: null
            });
            return Promise.resolve(null);
        }

        loading = true;
        loadedDocumentId = documentId;

        renderSkeleton();
        setPanels("loading");

        return api.endpoints
            .getDocument(documentId)
            .then(function (payload) {
                loadedPayload = payload;
                loadedDocumentMetadata = payload.document || {};
                loadedAnalysis = payload.analysis || null;
                loadedClassification =
                    payload.classification || null;
                loadedFindings = payload.findings || null;
                loadedHumanReview = payload.human_review || null;
                loadedFinalRecord = payload.final_record || null;

                /* Identity BEFORE the review panel renders:
                   can_review decides whether a form appears. */
                return loadReviewerIdentity();
            })
            .then(function () {
                renderAll();
                setPanels("content");
                loading = false;

                /* The image and the history are independent of
                   the panels above and load in parallel. */
                return Promise.all([
                    sourcePanel.init({
                        documentId: documentId,
                        ocrLines: loadedAnalysis
                            ? loadedAnalysis.ocr_lines
                            : []
                    }),
                    loadReviewHistory(documentId)
                ]);
            })
            .then(function () {
                return loadedPayload;
            })
            .catch(function (error) {
                loading = false;
                showError(error);
                return null;
            });
    }


    /* ======================================================
       INIT
       ====================================================== */

    function init() {
        collectNodes();

        ui.initShellChrome();

        tabs = tabsModule.createTabs(nodes.tablist, {});

        fieldsView.init({
            onHighlight: function (lineIds) {
                sourcePanel.highlight(lineIds);
            }
        });

        validationView.init({});
        resultView.init();

        reviewActions.init({
            /* A completed review reloads from the server. The
               final record is the backend's to compute, and
               only a reload proves what was stored. */
            onReviewed: function () {
                loading = false;
                return loadDocument();
            },
            onIdentityChanged: refreshIdentity
        });

        if (nodes.copyJson) {
            nodes.copyJson.addEventListener("click", copyJson);
        }

        if (nodes.downloadJson) {
            nodes.downloadJson.addEventListener(
                "click",
                downloadJson
            );
        }

        return loadDocument();
    }

    if (global.document) {
        global.document.addEventListener(
            "DOMContentLoaded",
            init
        );
    }


    global.VigiloxWorkspace = {
        init: init,
        loadDocument: loadDocument,
        loadReviewerIdentity: loadReviewerIdentity,
        renderReviewerIdentity: renderReviewerIdentity,
        loadReviewHistory: loadReviewHistory,
        refreshIdentity: refreshIdentity,
        copyJson: copyJson,
        downloadJson: downloadJson,
        getDocumentId: getDocumentId,
        machineValues: machineValues,

        getReviewer: function () {
            return loadedReviewerIdentity;
        },
        getFinalRecord: function () {
            return loadedFinalRecord;
        },
        getHumanReview: function () {
            return loadedHumanReview;
        },
        getHistory: function () {
            return loadedHistory;
        },
        getTabs: function () {
            return tabs;
        }
    };

}(typeof window !== "undefined" ? window : globalThis));
