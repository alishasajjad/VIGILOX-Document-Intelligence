// ==========================================================
// VIGILOX DOCUMENT REVIEW DETAIL
// PHASE 7B.7 + 7B.8 + 7C.4 + 7C.5
// ==========================================================


// ==========================================================
// CORRECTABLE FIELDS
// MUST MATCH HumanReviewService.CORRECTABLE_FIELDS
// ==========================================================

const CORRECTABLE_FIELDS = [
    "document_type",
    "full_name",
    "licence_number",
    "id_number",
    "expiry_date",
    "date_of_birth",
    "issue_date",
    "issuer"
];


// ==========================================================
// DOCUMENT STATE
// ==========================================================

let loadedDocumentId = null;

let loadedDocumentMetadata = {};

let loadedAnalysis = {};

let loadedHumanReview = null;

let loadedFinalRecord = null;

let loadedReviewerIdentity = null;

let reviewerIdentityError = null;

let loadedExtractionValues = {};

let imageObjectUrl = null;

let reviewSubmitting = false;


// ==========================================================
// DOM
// ==========================================================

const statusIndicator =
    document.getElementById(
        "status-indicator"
    );


const statusText =
    document.getElementById(
        "status-text"
    );


const detailLoading =
    document.getElementById(
        "detail-loading"
    );


const detailError =
    document.getElementById(
        "detail-error"
    );


const detailErrorMessage =
    document.getElementById(
        "detail-error-message"
    );


const detailContent =
    document.getElementById(
        "detail-content"
    );


const documentTitle =
    document.getElementById(
        "document-title"
    );


const documentSubtitle =
    document.getElementById(
        "document-subtitle"
    );


const originalDocumentImage =
    document.getElementById(
        "original-document-image"
    );


const imageUnavailable =
    document.getElementById(
        "image-unavailable"
    );


const machineDecision =
    document.getElementById(
        "machine-decision"
    );


const machinePriority =
    document.getElementById(
        "machine-priority"
    );


const machineReasons =
    document.getElementById(
        "machine-reasons"
    );


const extractionFields =
    document.getElementById(
        "extraction-fields"
    );


const effectiveValues =
    document.getElementById(
        "effective-values"
    );


const anomalyList =
    document.getElementById(
        "anomaly-list"
    );


// ==========================================================
// FINAL RECORD DOM
// ==========================================================

const finalStatus =
    document.getElementById(
        "final-status"
    );


const finalIsFinal =
    document.getElementById(
        "final-is-final"
    );


const finalIsUsable =
    document.getElementById(
        "final-is-usable"
    );


const finalRecordNote =
    document.getElementById(
        "final-record-note"
    );


// ==========================================================
// HUMAN REVIEW DOM
// ==========================================================

const humanReviewForm =
    document.getElementById(
        "human-review-form"
    );


const completedReviewSummary =
    document.getElementById(
        "completed-review-summary"
    );


const completedReviewAction =
    document.getElementById(
        "completed-review-action"
    );


const completedReviewer =
    document.getElementById(
        "completed-reviewer"
    );


const completedReviewedAt =
    document.getElementById(
        "completed-reviewed-at"
    );


const completedReviewNotes =
    document.getElementById(
        "completed-review-notes"
    );


const completedReviewCorrections =
    document.getElementById(
        "completed-review-corrections"
    );


const reviewLockedMessage =
    document.getElementById(
        "review-locked-message"
    );


// ==========================================================
// AUTHENTICATED REVIEWER DOM
// PHASE 7C.5
// ==========================================================

const authenticatedReviewerSection =
    document.getElementById(
        "authenticated-reviewer-section"
    );


const authenticatedReviewerCard =
    document.getElementById(
        "authenticated-reviewer-card"
    );


const authenticatedReviewerLoading =
    document.getElementById(
        "authenticated-reviewer-loading"
    );


const authenticatedReviewerContent =
    document.getElementById(
        "authenticated-reviewer-content"
    );


const authenticatedReviewerName =
    document.getElementById(
        "authenticated-reviewer-name"
    );


const authenticatedReviewerRole =
    document.getElementById(
        "authenticated-reviewer-role"
    );


const authenticatedReviewerSource =
    document.getElementById(
        "authenticated-reviewer-source"
    );


const authenticatedReviewerAccess =
    document.getElementById(
        "authenticated-reviewer-access"
    );


const authenticatedReviewerError =
    document.getElementById(
        "authenticated-reviewer-error"
    );


const reviewNotesInput =
    document.getElementById(
        "review-notes"
    );


const correctionPanel =
    document.getElementById(
        "correction-panel"
    );


const correctionFields =
    document.getElementById(
        "correction-fields"
    );


const cancelCorrectionButton =
    document.getElementById(
        "cancel-correction-button"
    );


const reviewMessage =
    document.getElementById(
        "review-message"
    );


const approveButton =
    document.getElementById(
        "approve-button"
    );


const rejectButton =
    document.getElementById(
        "reject-button"
    );


const correctButton =
    document.getElementById(
        "correct-button"
    );


const submitCorrectionButton =
    document.getElementById(
        "submit-correction-button"
    );


const reviewHistoryList =
    document.getElementById(
        "review-history-list"
    );


// ==========================================================
// HELPERS
// ==========================================================

function escapeHtml(
    value
) {

    const div =
        document.createElement(
            "div"
        );


    div.textContent =
        value ?? "";


    return div.innerHTML;

}


function formatFieldName(
    fieldName
) {

    return (
        fieldName
            .replaceAll(
                "_",
                " "
            )
            .replace(
                /\b\w/g,
                character =>
                    character.toUpperCase()
            )
    );

}


function formatDocumentType(
    value
) {

    const labels = {

        guard_license:
            "Guard License",

        sia_badge:
            "SIA Badge",

        id_card:
            "ID Card",

        unknown:
            "Unknown"

    };


    return (
        labels[value]
        || value
        || "Unknown"
    );

}


function formatDateTime(
    value
) {

    if (
        !value
    ) {

        return "—";

    }


    const parsed =
        new Date(
            value
        );


    if (
        Number.isNaN(
            parsed.getTime()
        )
    ) {

        return value;

    }


    return parsed.toLocaleString();

}


function formatDisplayValue(
    fieldName,
    value
) {

    if (
        value === null
        || value === undefined
        || value === ""
    ) {

        return "NULL";

    }


    if (
        fieldName
        === "document_type"
    ) {

        return formatDocumentType(
            value
        );

    }


    return String(
        value
    );

}


function getPriorityClass(
    priority
) {

    switch (
        priority
    ) {

        case "HIGH":

            return "priority-high";


        case "MEDIUM":

            return "priority-medium";


        case "LOW":

            return "priority-low";


        default:

            return "";

    }

}


function getFinalStatusClass(
    status
) {

    switch (
        status
    ) {

        case "AUTO_ACCEPTED":
        case "APPROVED":

            return "final-status-success";


        case "CORRECTED":

            return "final-status-corrected";


        case "REJECTED":

            return "final-status-rejected";


        case "PENDING_REVIEW":

            return "final-status-pending";


        default:

            return "final-status-unknown";

    }

}


function getHumanActionClass(
    action
) {

    switch (
        action
    ) {

        case "APPROVE":

            return "human-action-approve";


        case "CORRECT":

            return "human-action-correct";


        case "REJECT":

            return "human-action-reject";


        default:

            return "";

    }

}


// ==========================================================
// DOCUMENT ID FROM URL
// ==========================================================

function getDocumentId() {

    const segments =
        window.location.pathname
            .split("/")
            .filter(Boolean);


    if (
        segments.length < 2
    ) {

        return null;

    }


    return (
        segments[
            segments.length - 1
        ]
    );

}


// ==========================================================
// HEALTH
// ==========================================================

// ==========================================================
// APPLICATION SHELL
// ==========================================================
//
// PHASE 8.5
//
// The local API health check was removed. Navigation state
// and the liveness indicator come from
// VigiloxUI.initShellChrome().
//
// The shell reviewer is populated by renderReviewerIdentity
// below via VigiloxUI.applyShellReviewer, reusing the
// identity this page already loads. That deliberately avoids
// a second GET /api/v1/reviewer/me.
// ==========================================================


// ==========================================================
// AUTHENTICATED REVIEWER IDENTITY
// PHASE 7C.5
// ==========================================================

function renderReviewerIdentity() {

    // ======================================================
    // SHELL SYNC
    // PHASE 8.5
    // ======================================================
    //
    // Reuses the identity already fetched by
    // loadReviewerIdentity(), so the sidebar shows the
    // reviewer without a second request.
    //
    // Identity remains server-resolved. This only displays
    // what the server returned.
    // ======================================================

    VigiloxUI.applyShellReviewer(
        loadedReviewerIdentity
    );


    authenticatedReviewerLoading.hidden =
        true;


    authenticatedReviewerContent.hidden =
        true;


    authenticatedReviewerError.hidden =
        true;


    authenticatedReviewerCard.classList.remove(
        "reviewer-card-authorized",
        "reviewer-card-readonly",
        "reviewer-card-error"
    );


    // ======================================================
    // IDENTITY NOT AVAILABLE
    // ======================================================

    if (
        !loadedReviewerIdentity
    ) {

        authenticatedReviewerError.hidden =
            false;


        authenticatedReviewerError.textContent =
            (
                reviewerIdentityError
                || (
                    "Authenticated reviewer "
                    + "identity is unavailable."
                )
            );


        authenticatedReviewerCard.classList.add(
            "reviewer-card-error"
        );


        return;

    }


    // ======================================================
    // IDENTITY AVAILABLE
    // ======================================================

    authenticatedReviewerContent.hidden =
        false;


    authenticatedReviewerName.textContent =
        (
            loadedReviewerIdentity.reviewer_id
            || "Unknown reviewer"
        );


    authenticatedReviewerRole.textContent =
        (
            loadedReviewerIdentity.role
            || "UNKNOWN"
        );


    authenticatedReviewerSource.textContent =
        (
            loadedReviewerIdentity.source
            || "UNKNOWN"
        );


    if (
        loadedReviewerIdentity.can_review
    ) {

        authenticatedReviewerAccess.textContent =
            "Review access granted";


        authenticatedReviewerAccess.className =
            (
                "reviewer-access-badge "
                + "reviewer-access-granted"
            );


        authenticatedReviewerCard.classList.add(
            "reviewer-card-authorized"
        );

    }

    else {

        authenticatedReviewerAccess.textContent =
            "Read-only access";


        authenticatedReviewerAccess.className =
            (
                "reviewer-access-badge "
                + "reviewer-access-readonly"
            );


        authenticatedReviewerCard.classList.add(
            "reviewer-card-readonly"
        );

    }

}


async function loadReviewerIdentity() {

    loadedReviewerIdentity =
        null;


    reviewerIdentityError =
        null;


    authenticatedReviewerLoading.hidden =
        false;


    authenticatedReviewerContent.hidden =
        true;


    authenticatedReviewerError.hidden =
        true;


    try {

        const response =
            await fetch(
                "/api/v1/reviewer/me"
            );


        let body = {};


        try {

            body =
                await response.json();

        }

        catch {

            body = {};

        }


        if (
            !response.ok
        ) {

            if (
                response.status
                === 401
            ) {

                reviewerIdentityError =
                    (
                        body.detail
                        || (
                            "Reviewer authentication "
                            + "is required."
                        )
                    );

            }

            else if (
                response.status
                === 403
            ) {

                reviewerIdentityError =
                    (
                        body.detail
                        || (
                            "Reviewer identity "
                            + "is not authorized."
                        )
                    );

            }

            else {

                reviewerIdentityError =
                    (
                        body.detail
                        || (
                            "Failed to load "
                            + "reviewer identity."
                        )
                    );

            }


            renderReviewerIdentity();


            return null;

        }


        loadedReviewerIdentity =
            (
                body.reviewer
                || null
            );


        if (
            !loadedReviewerIdentity
        ) {

            reviewerIdentityError =
                (
                    "Reviewer identity response "
                    + "is missing reviewer data."
                );

        }


        renderReviewerIdentity();


        return (
            loadedReviewerIdentity
        );

    }

    catch {

        reviewerIdentityError =
            (
                "Unable to contact the reviewer "
                + "identity service."
            );


        renderReviewerIdentity();


        return null;

    }

}


// ==========================================================
// IMAGE
// ==========================================================

async function loadOriginalImage(
    documentId
) {

    const imageUrl =
        (
            "/api/v1/documents/"
            + encodeURIComponent(
                documentId
            )
            + "/image"
        );


    try {

        const response =
            await fetch(
                imageUrl
            );


        if (
            !response.ok
        ) {

            originalDocumentImage.hidden =
                true;


            imageUnavailable.hidden =
                false;


            return;

        }


        const blob =
            await response.blob();


        if (
            imageObjectUrl
        ) {

            URL.revokeObjectURL(
                imageObjectUrl
            );

        }


        imageObjectUrl =
            URL.createObjectURL(
                blob
            );


        originalDocumentImage.src =
            imageObjectUrl;


        originalDocumentImage.hidden =
            false;


        imageUnavailable.hidden =
            true;

    }

    catch {

        originalDocumentImage.hidden =
            true;


        imageUnavailable.hidden =
            false;

    }

}


// ==========================================================
// FINAL RECORD
// PHASE 7C.4
// ==========================================================

function renderFinalRecord(
    finalRecord
) {

    if (
        !finalRecord
    ) {

        finalStatus.innerHTML = `
            <span class="
                final-status-badge
                final-status-unknown
            ">
                UNKNOWN
            </span>
        `;


        finalIsFinal.textContent =
            "—";


        finalIsUsable.textContent =
            "—";


        finalRecordNote.textContent =
            (
                "Final record information "
                + "is not available."
            );


        return;

    }


    const status =
        finalRecord.final_status
        || "UNKNOWN";


    finalStatus.innerHTML = `
        <span
            class="
                final-status-badge
                ${getFinalStatusClass(status)}
            "
        >
            ${
                escapeHtml(
                    status.replaceAll(
                        "_",
                        " "
                    )
                )
            }
        </span>
    `;


    finalIsFinal.textContent =
        (
            finalRecord.is_final
                ? "Yes"
                : "No"
        );


    finalIsUsable.textContent =
        (
            finalRecord.is_usable
                ? "Yes"
                : "No"
        );


    const notes = {

        AUTO_ACCEPTED:
            (
                "The machine result was "
                + "auto-accepted and is available "
                + "for downstream use."
            ),

        PENDING_REVIEW:
            (
                "Human review is required before "
                + "this document can produce final "
                + "usable values."
            ),

        APPROVED:
            (
                "A human reviewer approved the "
                + "machine extraction without changes."
            ),

        CORRECTED:
            (
                "A human reviewer corrected one or "
                + "more machine-extracted values."
            ),

        REJECTED:
            (
                "A human reviewer rejected this "
                + "document. No effective values "
                + "should be used downstream."
            )

    };


    finalRecordNote.textContent =
        (
            notes[
                status
            ]
            || (
                "Final record status is "
                + status
                + "."
            )
        );

}


// ==========================================================
// MACHINE DECISION
// ==========================================================

function renderMachineDecision(
    reviewDecision
) {

    const decision =
        reviewDecision?.decision
        || "UNKNOWN";


    const priority =
        reviewDecision?.priority
        || "UNKNOWN";


    machineDecision.textContent =
        decision;


    machinePriority.innerHTML = `
        <span
            class="
                priority-badge
                ${getPriorityClass(priority)}
            "
        >
            ${escapeHtml(priority)}
        </span>
    `;


    const reasonCodes =
        reviewDecision?.reason_codes
        || [];


    machineReasons.innerHTML =
        "";


    if (
        reasonCodes.length === 0
    ) {

        machineReasons.textContent =
            "No machine reason codes.";


        return;

    }


    for (
        const reason
        of reasonCodes
    ) {

        const badge =
            document.createElement(
                "span"
            );


        badge.className =
            "reason-code";


        badge.textContent =
            reason;


        machineReasons.appendChild(
            badge
        );

    }

}


// ==========================================================
// FIELD CONFIDENCE
// ==========================================================

function getFieldConfidence(
    confidenceMap,
    fieldName
) {

    if (
        !confidenceMap
        || typeof confidenceMap
            !== "object"
    ) {

        return null;

    }


    const raw =
        confidenceMap[
            fieldName
        ];


    if (
        raw === null
        || raw === undefined
    ) {

        return null;

    }


    if (
        typeof raw
        === "number"
    ) {

        return raw;

    }


    if (
        typeof raw
        === "object"
    ) {

        return (
            raw.confidence
            ?? raw.value
            ?? raw.score
            ?? null
        );

    }


    return null;

}


// ==========================================================
// OCR EVIDENCE LOOKUP
// EXPLICIT IDs FIRST, LEGACY POSITIONAL FALLBACK
// ==========================================================

function buildOcrLookup(
    ocrLines
) {

    const lookup =
        new Map();


    if (
        !Array.isArray(
            ocrLines
        )
    ) {

        return lookup;

    }


    ocrLines.forEach(
        (
            line,
            index
        ) => {

            const lineId =
                (
                    line?.line_id
                    ?? line?.id
                    ?? `L${index}`
                );


            lookup.set(
                String(
                    lineId
                ),
                line
            );

        }
    );


    return lookup;

}


// ==========================================================
// NORMALIZE EXTRACTION STRUCTURE
// ==========================================================

function getExtractionFields(
    extraction
) {

    if (
        !extraction
        || typeof extraction
            !== "object"
    ) {

        return {};

    }


    if (
        extraction.fields
        && typeof extraction.fields
            === "object"
    ) {

        return extraction.fields;

    }


    const fields = {};


    for (
        const [
            key,
            value
        ]
        of Object.entries(
            extraction
        )
    ) {

        if (
            key === "document_type"
        ) {

            continue;

        }


        if (
            value
            && typeof value
                === "object"
            && (
                "value"
                in value
                || "source_line_ids"
                in value
            )
        ) {

            fields[
                key
            ] = value;

        }

    }


    return fields;

}


// ==========================================================
// BUILD SIMPLE EXTRACTION VALUE MAP
// ==========================================================

function buildExtractionValueMap(
    extraction,
    documentMetadata
) {

    const fields =
        getExtractionFields(
            extraction
        );


    const values = {};


    for (
        const fieldName
        of CORRECTABLE_FIELDS
    ) {

        if (
            fieldName
            === "document_type"
        ) {

            values.document_type =
                (
                    extraction?.document_type
                    ?? documentMetadata?.document_type
                    ?? null
                );


            continue;

        }


        values[
            fieldName
        ] =
            (
                fields[
                    fieldName
                ]?.value
                ?? null
            );

    }


    return values;

}


// ==========================================================
// EXTRACTION RENDER
// ==========================================================

function renderExtraction(
    extraction,
    fieldConfidence,
    ocrLines
) {

    extractionFields.innerHTML =
        "";


    const fields =
        getExtractionFields(
            extraction
        );


    const entries =
        Object.entries(
            fields
        );


    if (
        entries.length === 0
    ) {

        extractionFields.innerHTML = `
            <div class="detail-empty">
                No extracted fields available.
            </div>
        `;


        return;

    }


    const ocrLookup =
        buildOcrLookup(
            ocrLines
        );


    for (
        const [
            fieldName,
            fieldData
        ]
        of entries
    ) {

        const value =
            fieldData?.value;


        const sourceIds =
            fieldData
                ?.source_line_ids
            || [];


        const confidence =
            getFieldConfidence(
                fieldConfidence,
                fieldName
            );


        const field =
            document.createElement(
                "div"
            );


        field.className =
            "extraction-field";


        const confidenceText =
            (
                typeof confidence
                === "number"
            )
                ? (
                    confidence
                    <= 1
                        ? `${(
                            confidence
                            * 100
                        ).toFixed(1)}%`
                        : `${confidence.toFixed(1)}%`
                )
                : "—";


        let evidenceHtml =
            "";


        if (
            sourceIds.length > 0
        ) {

            evidenceHtml =
                sourceIds
                    .map(
                        sourceId => {

                            const normalizedSourceId =
                                String(
                                    sourceId
                                );


                            const line =
                                ocrLookup.get(
                                    normalizedSourceId
                                );


                            const text =
                                (
                                    line?.text
                                    ?? "OCR line unavailable"
                                );


                            return `
                                <div class="evidence-line">

                                    <span class="evidence-id">
                                        ${
                                            escapeHtml(
                                                normalizedSourceId
                                            )
                                        }
                                    </span>

                                    <span>
                                        ${
                                            escapeHtml(
                                                text
                                            )
                                        }
                                    </span>

                                </div>
                            `;

                        }
                    )
                    .join("");

        }

        else {

            evidenceHtml = `
                <span class="muted-text">
                    No source evidence
                </span>
            `;

        }


        field.innerHTML = `
            <div class="field-header">

                <span class="field-name">
                    ${
                        escapeHtml(
                            formatFieldName(
                                fieldName
                            )
                        )
                    }
                </span>

                <span class="confidence-value">
                    Confidence:
                    ${
                        escapeHtml(
                            confidenceText
                        )
                    }
                </span>

            </div>


            <div class="field-value">

                ${
                    value === null
                    || value === undefined
                    || value === ""
                        ? `
                            <span class="null-value">
                                NULL
                            </span>
                        `
                        : escapeHtml(
                            String(
                                value
                            )
                        )
                }

            </div>


            <div class="field-evidence">

                <span class="detail-label">
                    Evidence
                </span>

                ${evidenceHtml}

            </div>
        `;


        extractionFields.appendChild(
            field
        );

    }

}


// ==========================================================
// EFFECTIVE VALUES
// PHASE 7C.4
// ==========================================================

function renderEffectiveValues(
    finalRecord
) {

    effectiveValues.innerHTML =
        "";


    if (
        !finalRecord
    ) {

        effectiveValues.innerHTML = `
            <div class="detail-empty">
                Final record is not available.
            </div>
        `;


        return;

    }


    const machineValues =
        finalRecord.machine_values
        || {};


    const finalValues =
        finalRecord.effective_values;


    const valueSources =
        finalRecord.value_sources
        || {};


    if (
        !finalValues
    ) {

        let message =
            "Effective values are not available.";


        if (
            finalRecord.final_status
            === "PENDING_REVIEW"
        ) {

            message =
                (
                    "Effective values are withheld "
                    + "until human review is completed."
                );

        }


        if (
            finalRecord.final_status
            === "REJECTED"
        ) {

            message =
                (
                    "This document was rejected. "
                    + "No values are published for "
                    + "downstream use."
                );

        }


        effectiveValues.innerHTML = `
            <div class="effective-empty-state">
                ${escapeHtml(message)}
            </div>
        `;


        return;

    }


    for (
        const fieldName
        of CORRECTABLE_FIELDS
    ) {

        const machineValue =
            (
                machineValues[
                    fieldName
                ]
                ?? null
            );


        const effectiveValue =
            (
                finalValues[
                    fieldName
                ]
                ?? null
            );


        const source =
            (
                valueSources[
                    fieldName
                ]
                || "MACHINE"
            );


        const corrected =
            (
                source
                === "HUMAN_CORRECTION"
            );


        const row =
            document.createElement(
                "div"
            );


        row.className =
            (
                "effective-value-row"
                + (
                    corrected
                        ? " effective-value-corrected"
                        : ""
                )
            );


        row.innerHTML = `
            <div class="effective-field-name">
                ${
                    escapeHtml(
                        formatFieldName(
                            fieldName
                        )
                    )
                }
            </div>


            <div class="effective-value-column">

                <span class="detail-label">
                    Machine
                </span>

                <div class="effective-machine-value">
                    ${
                        escapeHtml(
                            formatDisplayValue(
                                fieldName,
                                machineValue
                            )
                        )
                    }
                </div>

            </div>


            <div class="effective-value-column">

                <span class="detail-label">
                    Effective
                </span>

                <div class="effective-final-value">
                    ${
                        escapeHtml(
                            formatDisplayValue(
                                fieldName,
                                effectiveValue
                            )
                        )
                    }
                </div>

            </div>


            <div class="effective-source-column">

                <span
                    class="
                        value-source-badge
                        ${
                            corrected
                                ? "value-source-human"
                                : "value-source-machine"
                        }
                    "
                >
                    ${
                        corrected
                            ? "Human Correction"
                            : "Machine"
                    }
                </span>

            </div>
        `;


        effectiveValues.appendChild(
            row
        );

    }

}


// ==========================================================
// ANOMALIES
// ==========================================================

function renderAnomalies(
    anomalyValidation
) {

    anomalyList.innerHTML =
        "";


    const issues =
        anomalyValidation?.issues
        || [];


    if (
        issues.length === 0
    ) {

        anomalyList.innerHTML = `
            <div class="detail-empty">
                No validation issues reported.
            </div>
        `;


        return;

    }


    for (
        const issue
        of issues
    ) {

        const issueElement =
            document.createElement(
                "div"
            );


        issueElement.className =
            "validation-issue";


        issueElement.innerHTML = `
            <div class="issue-header">

                <strong>
                    ${
                        escapeHtml(
                            issue.code
                            || "VALIDATION_ISSUE"
                        )
                    }
                </strong>

                <span class="issue-severity">
                    ${
                        escapeHtml(
                            issue.severity
                            || "UNKNOWN"
                        )
                    }
                </span>

            </div>


            <p>
                ${
                    escapeHtml(
                        issue.message
                        || "Validation issue detected."
                    )
                }
            </p>


            ${
                issue.field
                    ? `
                        <div class="issue-field">
                            Field:
                            ${
                                escapeHtml(
                                    issue.field
                                )
                            }
                        </div>
                    `
                    : ""
            }
        `;


        anomalyList.appendChild(
            issueElement
        );

    }

}


// ==========================================================
// HUMAN REVIEW MESSAGE
// ==========================================================

function showReviewMessage(
    message,
    type = "error"
) {

    reviewMessage.hidden =
        false;


    reviewMessage.textContent =
        message;


    reviewMessage.classList.remove(
        "review-message-error",
        "review-message-success"
    );


    reviewMessage.classList.add(
        type === "success"
            ? "review-message-success"
            : "review-message-error"
    );

}


function clearReviewMessage() {

    reviewMessage.hidden =
        true;


    reviewMessage.textContent =
        "";


    reviewMessage.classList.remove(
        "review-message-error",
        "review-message-success"
    );

}


// ==========================================================
// COMPLETED / PENDING HUMAN REVIEW STATE
// PHASE 7C.4 / 7C.5
// ==========================================================

function renderHumanReviewState(
    humanReview,
    finalRecord
) {

    const status =
        finalRecord?.final_status
        || "UNKNOWN";


    // ======================================================
    // HUMAN REVIEW ALREADY EXISTS
    // ======================================================

    if (
        humanReview
    ) {

        humanReviewForm.hidden =
            true;


        authenticatedReviewerSection.hidden =
            true;


        reviewLockedMessage.hidden =
            true;


        completedReviewSummary.hidden =
            false;


        const action =
            humanReview.human_action
            || "UNKNOWN";


        completedReviewAction.innerHTML = `
            <span
                class="
                    human-action-badge
                    ${getHumanActionClass(action)}
                "
            >
                ${escapeHtml(action)}
            </span>
        `;


        completedReviewer.textContent =
            (
                humanReview.reviewer_id
                || "—"
            );


        completedReviewedAt.textContent =
            formatDateTime(
                humanReview.reviewed_at
            );


        completedReviewNotes.textContent =
            (
                humanReview.notes
                || "No reviewer notes."
            );


        const corrections =
            humanReview.corrections
            || {};


        const entries =
            Object.entries(
                corrections
            );


        completedReviewCorrections.innerHTML =
            "";


        if (
            entries.length === 0
        ) {

            completedReviewCorrections.innerHTML = `
                <div class="muted-text">
                    No field corrections.
                </div>
            `;

        }

        else {

            for (
                const [
                    fieldName,
                    correctedValue
                ]
                of entries
            ) {

                const correction =
                    document.createElement(
                        "div"
                    );


                correction.className =
                    "completed-correction-row";


                correction.innerHTML = `
                    <span class="completed-correction-field">
                        ${
                            escapeHtml(
                                formatFieldName(
                                    fieldName
                                )
                            )
                        }
                    </span>

                    <span class="completed-correction-value">
                        ${
                            escapeHtml(
                                formatDisplayValue(
                                    fieldName,
                                    correctedValue
                                )
                            )
                        }
                    </span>
                `;


                completedReviewCorrections.appendChild(
                    correction
                );

            }

        }


        return;

    }


    // ======================================================
    // PENDING HUMAN REVIEW
    // ======================================================

    if (
        status
        === "PENDING_REVIEW"
    ) {

        completedReviewSummary.hidden =
            true;


        authenticatedReviewerSection.hidden =
            false;


        correctionPanel.hidden =
            true;


        correctionFields.innerHTML =
            "";


        approveButton.hidden =
            false;


        rejectButton.hidden =
            false;


        correctButton.hidden =
            false;


        submitCorrectionButton.hidden =
            true;


        cancelCorrectionButton.hidden =
            false;


        setReviewSubmitting(
            false
        );


        // ==================================================
        // AUTHORIZED REVIEWER
        // ==================================================

        if (
            loadedReviewerIdentity
            && loadedReviewerIdentity.can_review
        ) {

            reviewLockedMessage.hidden =
                true;


            humanReviewForm.hidden =
                false;


            return;

        }


        // ==================================================
        // NO AUTHORIZED REVIEWER
        // ==================================================

        humanReviewForm.hidden =
            true;


        reviewLockedMessage.hidden =
            false;


        if (
            loadedReviewerIdentity
            && !loadedReviewerIdentity.can_review
        ) {

            reviewLockedMessage.textContent =
                (
                    "The authenticated user "
                    + `${loadedReviewerIdentity.reviewer_id} `
                    + "has read-only access and cannot "
                    + "submit human review decisions."
                );

        }

        else {

            reviewLockedMessage.textContent =
                (
                    reviewerIdentityError
                    || (
                        "Reviewer authentication "
                        + "is required before this "
                        + "document can be reviewed."
                    )
                );

        }


        return;

    }


    // ======================================================
    // FINAL MACHINE STATE / NO HUMAN REVIEW REQUIRED
    // ======================================================

    completedReviewSummary.hidden =
        true;


    authenticatedReviewerSection.hidden =
        true;


    humanReviewForm.hidden =
        true;


    reviewLockedMessage.hidden =
        false;


    if (
        status
        === "AUTO_ACCEPTED"
    ) {

        reviewLockedMessage.textContent =
            (
                "This document was auto-accepted "
                + "by the machine decision and does "
                + "not require human review."
            );

    }

    else {

        reviewLockedMessage.textContent =
            (
                "This document is not currently "
                + "available for a new human review."
            );

    }

}


// ==========================================================
// REVIEW NOTES
// ==========================================================

function getReviewNotes() {

    const notes =
        reviewNotesInput
            .value
            .trim();


    return (
        notes
        || null
    );

}


// ==========================================================
// CORRECTION INPUT
// ==========================================================

function createCorrectionInput(
    fieldName,
    originalValue
) {

    const wrapper =
        document.createElement(
            "div"
        );


    wrapper.className =
        "correction-field";


    const label =
        document.createElement(
            "label"
        );


    label.className =
        "form-label";


    label.htmlFor =
        `correction-${fieldName}`;


    label.textContent =
        formatFieldName(
            fieldName
        );


    wrapper.appendChild(
        label
    );


    if (
        fieldName
        === "document_type"
    ) {

        const select =
            document.createElement(
                "select"
            );


        select.id =
            `correction-${fieldName}`;


        select.className =
            "form-control correction-input";


        select.dataset.fieldName =
            fieldName;


        const options = [
            {
                value:
                    "guard_license",

                label:
                    "Guard License"
            },

            {
                value:
                    "sia_badge",

                label:
                    "SIA Badge"
            },

            {
                value:
                    "id_card",

                label:
                    "ID Card"
            }
        ];


        for (
            const optionData
            of options
        ) {

            const option =
                document.createElement(
                    "option"
                );


            option.value =
                optionData.value;


            option.textContent =
                optionData.label;


            if (
                optionData.value
                === originalValue
            ) {

                option.selected =
                    true;

            }


            select.appendChild(
                option
            );

        }


        wrapper.appendChild(
            select
        );


        return wrapper;

    }


    const input =
        document.createElement(
            "input"
        );


    input.id =
        `correction-${fieldName}`;


    input.type =
        "text";


    input.className =
        "form-control correction-input";


    input.dataset.fieldName =
        fieldName;


    input.value =
        (
            originalValue
            ?? ""
        );


    if (
        fieldName === "expiry_date"
        || fieldName === "date_of_birth"
        || fieldName === "issue_date"
    ) {

        input.placeholder =
            "YYYY-MM-DD";

    }


    wrapper.appendChild(
        input
    );


    return wrapper;

}


// ==========================================================
// RENDER CORRECTION FORM
// ==========================================================

function renderCorrectionFields() {

    correctionFields.innerHTML =
        "";


    for (
        const fieldName
        of CORRECTABLE_FIELDS
    ) {

        const originalValue =
            loadedExtractionValues[
                fieldName
            ];


        const field =
            createCorrectionInput(
                fieldName,
                originalValue
            );


        correctionFields.appendChild(
            field
        );

    }

}


// ==========================================================
// OPEN CORRECTION MODE
// ==========================================================

function openCorrectionMode() {

    clearReviewMessage();


    if (
        !loadedReviewerIdentity
        || !loadedReviewerIdentity.can_review
    ) {

        showReviewMessage(
            (
                reviewerIdentityError
                || (
                    "Authenticated reviewer does "
                    + "not have permission to "
                    + "correct this document."
                )
            )
        );


        return;

    }


    renderCorrectionFields();


    correctionPanel.hidden =
        false;


    approveButton.hidden =
        true;


    rejectButton.hidden =
        true;


    correctButton.hidden =
        true;


    submitCorrectionButton.hidden =
        false;


    correctionPanel.scrollIntoView({
        behavior:
            "smooth",

        block:
            "nearest"
    });

}


// ==========================================================
// CLOSE CORRECTION MODE
// ==========================================================

function closeCorrectionMode() {

    correctionPanel.hidden =
        true;


    correctionFields.innerHTML =
        "";


    approveButton.hidden =
        false;


    rejectButton.hidden =
        false;


    correctButton.hidden =
        false;


    submitCorrectionButton.hidden =
        true;


    clearReviewMessage();

}


// ==========================================================
// COLLECT CHANGED CORRECTIONS
// ==========================================================

function collectCorrections() {

    const corrections =
        {};


    const inputs =
        correctionFields
            .querySelectorAll(
                ".correction-input"
            );


    inputs.forEach(
        input => {

            const fieldName =
                input.dataset
                    .fieldName;


            const originalValue =
                loadedExtractionValues[
                    fieldName
                ];


            const rawValue =
                input.value.trim();


            let newValue =
                rawValue;


            if (
                fieldName
                !== "document_type"
                && rawValue === ""
            ) {

                newValue =
                    null;

            }


            const normalizedOriginal =
                (
                    originalValue
                    === undefined
                    ? null
                    : originalValue
                );


            if (
                newValue
                !== normalizedOriginal
            ) {

                corrections[
                    fieldName
                ] =
                    newValue;

            }

        }
    );


    return corrections;

}


// ==========================================================
// BUTTON STATE
// ==========================================================

function setReviewSubmitting(
    submitting
) {

    reviewSubmitting =
        submitting;


    reviewNotesInput.disabled =
        submitting;


    approveButton.disabled =
        submitting;


    rejectButton.disabled =
        submitting;


    correctButton.disabled =
        submitting;


    submitCorrectionButton.disabled =
        submitting;


    cancelCorrectionButton.disabled =
        submitting;


    const correctionInputs =
        correctionFields
            .querySelectorAll(
                ".correction-input"
            );


    correctionInputs.forEach(
        input => {

            input.disabled =
                submitting;

        }
    );

}


// ==========================================================
// POST HUMAN REVIEW
// PHASE 7C.5 — NO CLIENT REVIEWER_ID
// ==========================================================

async function submitHumanReview(
    action,
    corrections = null
) {

    if (
        reviewSubmitting
    ) {

        return;

    }


    clearReviewMessage();


    // ======================================================
    // AUTHENTICATED IDENTITY REQUIRED
    // ======================================================

    if (
        !loadedReviewerIdentity
    ) {

        showReviewMessage(
            (
                reviewerIdentityError
                || (
                    "Reviewer authentication "
                    + "is required."
                )
            )
        );


        return;

    }


    // ======================================================
    // REVIEW WRITE ACCESS REQUIRED
    // ======================================================

    if (
        !loadedReviewerIdentity.can_review
    ) {

        showReviewMessage(
            (
                "Authenticated user does not "
                + "have permission to submit "
                + "human review decisions."
            )
        );


        return;

    }


    // ======================================================
    // CORRECTION MUST ACTUALLY CHANGE SOMETHING
    // ======================================================

    if (
        action === "CORRECT"
        && (
            !corrections
            || Object.keys(
                corrections
            ).length === 0
        )
    ) {

        showReviewMessage(
            "Change at least one field before submitting corrections."
        );


        return;

    }


    const actionLabels = {

        APPROVE:
            "approve",

        REJECT:
            "reject",

        CORRECT:
            "submit corrections for"

    };


    const confirmed =
        window.confirm(
            (
                `Are you sure you want to `
                + `${actionLabels[action]} `
                + `this document?`
            )
        );


    if (
        !confirmed
    ) {

        return;

    }


    setReviewSubmitting(
        true
    );


    try {

        // ==================================================
        // SECURITY:
        //
        // reviewer_id is intentionally NOT included here.
        //
        // Backend ReviewerIdentityService determines the
        // authoritative reviewer identity.
        // ==================================================

        const payload = {

            action:
                action,

            notes:
                getReviewNotes()

        };


        if (
            action === "CORRECT"
        ) {

            payload.corrections =
                corrections;

        }


        const response =
            await fetch(
                (
                    "/api/v1/documents/"
                    + encodeURIComponent(
                        loadedDocumentId
                    )
                    + "/reviews"
                ),

                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify(
                            payload
                        )
                }
            );


        let body = {};


        try {

            body =
                await response.json();

        }

        catch {

            body = {};

        }


        if (
            !response.ok
        ) {

            const error =
                new Error(
                    body.detail
                    || "Human review submission failed."
                );


            error.status =
                response.status;


            throw error;

        }


        setReviewSubmitting(
            false
        );


        // ==================================================
        // RELOAD DOCUMENT TO SHOW FINAL AUTHORITATIVE STATE
        // ==================================================

        await loadDocument();


        showReviewMessage(
            (
                "Review completed successfully: "
                + `${body.human_action}.`
            ),
            "success"
        );

    }

    catch (
        error
    ) {

        setReviewSubmitting(
            false
        );


        // ==================================================
        // AUTHENTICATION / AUTHORIZATION CHANGED
        // ==================================================

        if (
            error.status === 401
            || error.status === 403
        ) {

            await loadReviewerIdentity();


            renderHumanReviewState(
                loadedHumanReview,
                loadedFinalRecord
            );


            showReviewMessage(
                (
                    error.message
                    || (
                        "Reviewer authentication "
                        + "or authorization failed."
                    )
                )
            );


            return;

        }


        // ==================================================
        // ANOTHER REVIEWER WON THE RACE
        // ==================================================

        if (
            error.status
            === 409
        ) {

            await loadDocument();


            showReviewMessage(
                (
                    error.message
                    || (
                        "This document has already "
                        + "been reviewed."
                    )
                )
            );


            return;

        }


        showReviewMessage(
            (
                error.message
                || "Human review submission failed."
            )
        );

    }

}


// ==========================================================
// APPROVE
// ==========================================================

approveButton.addEventListener(
    "click",
    async () => {

        await submitHumanReview(
            "APPROVE"
        );

    }
);


// ==========================================================
// REJECT
// ==========================================================

rejectButton.addEventListener(
    "click",
    async () => {

        await submitHumanReview(
            "REJECT"
        );

    }
);


// ==========================================================
// CORRECT
// ==========================================================

correctButton.addEventListener(
    "click",
    () => {

        openCorrectionMode();

    }
);


// ==========================================================
// CANCEL CORRECTION
// ==========================================================

cancelCorrectionButton.addEventListener(
    "click",
    () => {

        closeCorrectionMode();

    }
);


// ==========================================================
// SUBMIT CORRECTIONS
// ==========================================================

submitCorrectionButton.addEventListener(
    "click",
    async () => {

        const corrections =
            collectCorrections();


        await submitHumanReview(
            "CORRECT",
            corrections
        );

    }
);


// ==========================================================
// REVIEW HISTORY
// PHASE 7C.4
// ==========================================================

function renderReviewHistory(
    history
) {

    reviewHistoryList.innerHTML =
        "";


    const events =
        history?.events
        || [];


    if (
        events.length === 0
    ) {

        reviewHistoryList.innerHTML = `
            <div class="detail-empty">
                No audit history available.
            </div>
        `;


        return;

    }


    for (
        const event
        of events
    ) {

        const details =
            event.details
            || {};


        const eventElement =
            document.createElement(
                "div"
            );


        eventElement.className =
            "history-event";


        let eventTitle =
            event.event_type
            || "AUDIT EVENT";


        let summaryHtml =
            "";


        if (
            event.event_type
            === "MACHINE_REVIEW_DECISION"
        ) {

            eventTitle =
                "Machine Review Decision";


            const reasons =
                details.reason_codes
                || [];


            summaryHtml = `
                <div class="history-summary-row">
                    <span>Decision</span>
                    <strong>
                        ${
                            escapeHtml(
                                details.decision
                                || "UNKNOWN"
                            )
                        }
                    </strong>
                </div>

                <div class="history-summary-row">
                    <span>Priority</span>
                    <strong>
                        ${
                            escapeHtml(
                                details.priority
                                || "UNKNOWN"
                            )
                        }
                    </strong>
                </div>

                <div class="history-reason-list">
                    ${
                        reasons.length
                            ? reasons
                                .map(
                                    reason => `
                                        <span class="reason-code">
                                            ${
                                                escapeHtml(
                                                    reason
                                                )
                                            }
                                        </span>
                                    `
                                )
                                .join("")
                            : `
                                <span class="muted-text">
                                    No reason codes
                                </span>
                            `
                    }
                </div>
            `;

        }


        if (
            event.event_type
            === "HUMAN_REVIEW"
        ) {

            eventTitle =
                "Human Review";


            const corrections =
                details.corrections
                || {};


            const correctionEntries =
                Object.entries(
                    corrections
                );


            summaryHtml = `
                <div class="history-summary-row">
                    <span>Action</span>
                    <strong>
                        ${
                            escapeHtml(
                                details.human_action
                                || "UNKNOWN"
                            )
                        }
                    </strong>
                </div>

                ${
                    details.notes
                        ? `
                            <div class="history-notes">
                                ${
                                    escapeHtml(
                                        details.notes
                                    )
                                }
                            </div>
                        `
                        : ""
                }

                ${
                    correctionEntries.length
                        ? `
                            <div class="history-corrections">
                                ${
                                    correctionEntries
                                        .map(
                                            ([
                                                fieldName,
                                                value
                                            ]) => `
                                                <div class="
                                                    history-correction-row
                                                ">
                                                    <span>
                                                        ${
                                                            escapeHtml(
                                                                formatFieldName(
                                                                    fieldName
                                                                )
                                                            )
                                                        }
                                                    </span>

                                                    <strong>
                                                        ${
                                                            escapeHtml(
                                                                formatDisplayValue(
                                                                    fieldName,
                                                                    value
                                                                )
                                                            )
                                                        }
                                                    </strong>
                                                </div>
                                            `
                                        )
                                        .join("")
                                }
                            </div>
                        `
                        : ""
                }
            `;

        }


        eventElement.innerHTML = `
            <div class="history-marker"></div>

            <div class="history-event-content">

                <div class="history-event-header">

                    <div>

                        <strong class="history-event-title">
                            ${escapeHtml(eventTitle)}
                        </strong>

                        <div class="history-event-actor">
                            ${
                                escapeHtml(
                                    event.actor_id
                                    || event.actor_type
                                    || "Unknown actor"
                                )
                            }
                        </div>

                    </div>


                    <time class="history-event-time">
                        ${
                            escapeHtml(
                                formatDateTime(
                                    event.created_at
                                )
                            )
                        }
                    </time>

                </div>


                <div class="history-event-body">
                    ${summaryHtml}
                </div>

            </div>
        `;


        reviewHistoryList.appendChild(
            eventElement
        );

    }

}


async function loadReviewHistory(
    documentId
) {

    try {

        const response =
            await fetch(
                (
                    "/api/v1/documents/"
                    + encodeURIComponent(
                        documentId
                    )
                    + "/history"
                )
            );


        if (
            !response.ok
        ) {

            throw new Error(
                "Failed to load audit history."
            );

        }


        const history =
            await response.json();


        renderReviewHistory(
            history
        );

    }

    catch {

        reviewHistoryList.innerHTML = `
            <div class="detail-empty">
                Review history could not be loaded.
            </div>
        `;

    }

}


// ==========================================================
// LOAD DOCUMENT
// ==========================================================

async function loadDocument() {

    const documentId =
        getDocumentId();


    if (
        !documentId
    ) {

        showError(
            "Document ID is missing."
        );


        return;

    }


    loadedDocumentId =
        documentId;


    try {

        const response =
            await fetch(
                (
                    "/api/v1/documents/"
                    + encodeURIComponent(
                        documentId
                    )
                )
            );


        if (
            !response.ok
        ) {

            let message =
                "Failed to load document.";


            try {

                const error =
                    await response.json();


                if (
                    error.detail
                ) {

                    message =
                        error.detail;

                }

            }

            catch {

                // Keep default message.

            }


            throw new Error(
                message
            );

        }


        const data =
            await response.json();


        loadedDocumentMetadata =
            data.document
            || {};


        loadedAnalysis =
            data.analysis
            || {};


        loadedHumanReview =
            data.human_review
            || null;


        loadedFinalRecord =
            data.final_record
            || null;


        loadedExtractionValues =
            buildExtractionValueMap(
                loadedAnalysis.extraction,
                loadedDocumentMetadata
            );


        // ==================================================
        // LOAD SERVER-TRUSTED REVIEWER IDENTITY
        // BEFORE DECIDING WHETHER ACTIONS ARE AVAILABLE
        // ==================================================

        await loadReviewerIdentity();


        documentTitle.textContent =
            (
                loadedDocumentMetadata
                    .original_filename
                || "Document Review"
            );


        documentSubtitle.textContent =
            (
                formatDocumentType(
                    loadedDocumentMetadata
                        .document_type
                )
                + " • "
                + documentId
            );


        renderFinalRecord(
            loadedFinalRecord
        );


        renderMachineDecision(
            loadedAnalysis.review_decision
        );


        renderExtraction(
            loadedAnalysis.extraction,
            loadedAnalysis.field_confidence,
            loadedAnalysis.ocr_lines
        );


        renderEffectiveValues(
            loadedFinalRecord
        );


        renderAnomalies(
            loadedAnalysis.anomaly_validation
        );


        renderHumanReviewState(
            loadedHumanReview,
            loadedFinalRecord
        );


        await Promise.all([
            loadOriginalImage(
                documentId
            ),

            loadReviewHistory(
                documentId
            )
        ]);


        detailError.hidden =
            true;


        detailLoading.hidden =
            true;


        detailContent.hidden =
            false;

    }

    catch (
        error
    ) {

        showError(
            error.message
        );

    }

}


// ==========================================================
// ERROR
// ==========================================================

function showError(
    message
) {

    detailLoading.hidden =
        true;


    detailContent.hidden =
        true;


    detailErrorMessage.textContent =
        (
            message
            || "Unable to load document."
        );


    detailError.hidden =
        false;

}


// ==========================================================
// CLEAN OBJECT URL
// ==========================================================

window.addEventListener(
    "beforeunload",
    () => {

        if (
            imageObjectUrl
        ) {

            URL.revokeObjectURL(
                imageObjectUrl
            );

        }

    }
);


// ==========================================================
// INITIAL LOAD
// ==========================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        VigiloxUI.initShellChrome();

        await loadDocument();

    }
);