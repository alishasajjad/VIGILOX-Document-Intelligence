// ==========================================================
// VIGILOX DOCUMENT REVIEW DETAIL
// PHASE 7B.7 + PHASE 7B.8
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


const anomalyList =
    document.getElementById(
        "anomaly-list"
    );


// ==========================================================
// HUMAN REVIEW DOM
// ==========================================================

const reviewerIdInput =
    document.getElementById(
        "reviewer-id"
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
            "ID Card"

    };


    return (
        labels[value]
        || value
        || "Unknown"
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

async function checkApiHealth() {

    try {

        const response =
            await fetch(
                "/health"
            );


        if (
            !response.ok
        ) {

            throw new Error(
                "Health check failed."
            );

        }


        statusIndicator
            .classList
            .remove(
                "offline"
            );


        statusIndicator
            .classList
            .add(
                "online"
            );


        statusText.textContent =
            "API Online";

    }

    catch {

        statusIndicator
            .classList
            .remove(
                "online"
            );


        statusIndicator
            .classList
            .add(
                "offline"
            );


        statusText.textContent =
            "API Offline";

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
// ZERO-BASED VIGILOX LINE IDS
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
// VALIDATE REVIEWER
// ==========================================================

function getReviewerId() {

    return (
        reviewerIdInput
            .value
            .trim()
    );

}


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


    input.dataset.originalWasNull =
        (
            originalValue === null
            || originalValue === undefined
        )
            ? "true"
            : "false";


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
        !getReviewerId()
    ) {

        showReviewMessage(
            "Reviewer ID is required before correcting the document."
        );


        reviewerIdInput.focus();


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


    reviewerIdInput.disabled =
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


    const reviewerId =
        getReviewerId();


    if (
        !reviewerId
    ) {

        showReviewMessage(
            "Reviewer ID is required."
        );


        reviewerIdInput.focus();


        return;

    }


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

        const payload = {

            reviewer_id:
                reviewerId,

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

            throw new Error(
                body.detail
                || "Human review submission failed."
            );

        }


        showReviewMessage(
            (
                `Review completed successfully: `
                + `${body.human_action}.`
            ),
            "success"
        );


        approveButton.hidden =
            true;


        rejectButton.hidden =
            true;


        correctButton.hidden =
            true;


        submitCorrectionButton.hidden =
            true;


        cancelCorrectionButton.hidden =
            true;


        setTimeout(
            () => {

                window.location.href =
                    "/review";

            },
            900
        );

    }

    catch (
        error
    ) {

        showReviewMessage(
            (
                error.message
                || "Human review submission failed."
            )
        );


        setReviewSubmitting(
            false
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


        loadedExtractionValues =
            buildExtractionValueMap(
                loadedAnalysis.extraction,
                loadedDocumentMetadata
            );


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


        renderMachineDecision(
            loadedAnalysis.review_decision
        );


        renderExtraction(
            loadedAnalysis.extraction,
            loadedAnalysis.field_confidence,
            loadedAnalysis.ocr_lines
        );


        renderAnomalies(
            loadedAnalysis.anomaly_validation
        );


        await loadOriginalImage(
            documentId
        );


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

        await checkApiHealth();

        await loadDocument();

    }
);