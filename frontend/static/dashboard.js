// ==========================================================
// VIGILOX REVIEW DASHBOARD
// PHASE 7B.6
// ==========================================================


// ==========================================================
// DOM ELEMENTS
// ==========================================================

const statusIndicator =
    document.getElementById(
        "status-indicator"
    );


const statusText =
    document.getElementById(
        "status-text"
    );


const refreshButton =
    document.getElementById(
        "refresh-button"
    );


const pendingCount =
    document.getElementById(
        "pending-count"
    );


const highCount =
    document.getElementById(
        "high-count"
    );


const mediumCount =
    document.getElementById(
        "medium-count"
    );


const lowCount =
    document.getElementById(
        "low-count"
    );


const priorityFilter =
    document.getElementById(
        "priority-filter"
    );


const documentTypeFilter =
    document.getElementById(
        "document-type-filter"
    );


const queueLoading =
    document.getElementById(
        "queue-loading"
    );


const queueError =
    document.getElementById(
        "queue-error"
    );


const queueErrorMessage =
    document.getElementById(
        "queue-error-message"
    );


const queueEmpty =
    document.getElementById(
        "queue-empty"
    );


const queueTableContainer =
    document.getElementById(
        "queue-table-container"
    );


const queueTableBody =
    document.getElementById(
        "queue-table-body"
    );


// ==========================================================
// HTML ESCAPING
// ==========================================================

function escapeHtml(value) {

    const element =
        document.createElement(
            "div"
        );


    element.textContent =
        value ?? "";


    return element.innerHTML;

}


// ==========================================================
// API HEALTH CHECK
// ==========================================================

async function checkApiHealth() {

    try {

        const response =
            await fetch(
                "/health"
            );


        if (!response.ok) {

            throw new Error(
                "Health endpoint failed."
            );

        }


        const data =
            await response.json();


        if (
            data.status
            !== "ok"
        ) {

            throw new Error(
                "API is not healthy."
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


        return true;

    }

    catch (error) {

        console.error(
            "API health check failed:",
            error
        );


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


        return false;

    }

}


// ==========================================================
// RESET QUEUE STATES
// ==========================================================

function hideQueueStates() {

    queueLoading.hidden = true;

    queueError.hidden = true;

    queueEmpty.hidden = true;

    queueTableContainer.hidden = true;

}


// ==========================================================
// BUILD QUERY URL
// ==========================================================

function buildQueueUrl() {

    const params =
        new URLSearchParams();


    const selectedPriority =
        priorityFilter.value;


    const selectedDocumentType =
        documentTypeFilter.value;


    if (selectedPriority) {

        params.set(
            "priority",
            selectedPriority
        );

    }


    if (selectedDocumentType) {

        params.set(
            "document_type",
            selectedDocumentType
        );

    }


    const query =
        params.toString();


    if (query) {

        return (
            "/api/v1/reviews/queue"
            + "?"
            + query
        );

    }


    return "/api/v1/reviews/queue";

}


// ==========================================================
// FORMAT DOCUMENT TYPE
// ==========================================================

function formatDocumentType(
    documentType
) {

    const names = {
        "guard_license":
            "Guard License",

        "sia_badge":
            "SIA Badge",

        "id_card":
            "ID Card"
    };


    return (
        names[
            documentType
        ]
        || documentType
        || "Unknown"
    );

}


// ==========================================================
// FORMAT DATE
// ==========================================================

function formatDate(
    value
) {

    if (!value) {

        return "—";

    }


    const date =
        new Date(
            value
        );


    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return value;

    }


    return (
        date.toLocaleString(
            undefined,
            {
                year:
                    "numeric",

                month:
                    "short",

                day:
                    "2-digit",

                hour:
                    "2-digit",

                minute:
                    "2-digit"
            }
        )
    );

}


// ==========================================================
// PRIORITY CLASS
// ==========================================================

function getPriorityClass(
    priority
) {

    switch (priority) {

        case "HIGH":

            return (
                "priority-high"
            );


        case "MEDIUM":

            return (
                "priority-medium"
            );


        case "LOW":

            return (
                "priority-low"
            );


        default:

            return "";

    }

}


// ==========================================================
// UPDATE SUMMARY COUNTS
// ==========================================================

function updateSummaryCounts(
    documents
) {

    const total =
        documents.length;


    const high =
        documents.filter(
            document =>
                document.review_priority
                === "HIGH"
        ).length;


    const medium =
        documents.filter(
            document =>
                document.review_priority
                === "MEDIUM"
        ).length;


    const low =
        documents.filter(
            document =>
                document.review_priority
                === "LOW"
        ).length;


    pendingCount.textContent =
        total;


    highCount.textContent =
        high;


    mediumCount.textContent =
        medium;


    lowCount.textContent =
        low;

}


// ==========================================================
// RENDER REASON CODES
// ==========================================================

function renderReasonCodes(
    reasonCodes
) {

    if (
        !Array.isArray(
            reasonCodes
        )
        || reasonCodes.length === 0
    ) {

        return "—";

    }


    return (
        `<div class="reason-list">`
        +
        reasonCodes
            .map(
                code => (
                    `
                    <span class="reason-code">
                        ${escapeHtml(code)}
                    </span>
                    `
                )
            )
            .join("")
        +
        `</div>`
    );

}


// ==========================================================
// RENDER QUEUE
// ==========================================================

function renderQueue(
    documents
) {

    queueTableBody.innerHTML =
        "";


    if (
        !Array.isArray(
            documents
        )
        || documents.length === 0
    ) {

        queueEmpty.hidden =
            false;


        return;

    }


    for (
        const document
        of documents
    ) {

        const row =
            document.createElement
                ? null
                : window.document
                    .createElement(
                        "tr"
                    );


        const priorityClass =
            getPriorityClass(
                document.review_priority
            );


        const filename =
            escapeHtml(
                document.original_filename
            );


        const documentId =
            escapeHtml(
                document.document_id
            );


        const documentType =
            escapeHtml(
                formatDocumentType(
                    document.document_type
                )
            );


        const priority =
            escapeHtml(
                document.review_priority
                || "UNKNOWN"
            );


        const createdAt =
            escapeHtml(
                formatDate(
                    document.created_at
                )
            );


        row.innerHTML = `
            <td>

                <div class="document-name">
                    ${filename}
                </div>

                <div
                    class="document-id"
                    title="${documentId}"
                >
                    ${documentId}
                </div>

            </td>


            <td>

                <span class="type-badge">
                    ${documentType}
                </span>

            </td>


            <td>

                <span
                    class="
                        priority-badge
                        ${priorityClass}
                    "
                >
                    ${priority}
                </span>

            </td>


            <td>
                ${
                    renderReasonCodes(
                        document.reason_codes
                    )
                }
            </td>


            <td>
                ${createdAt}
            </td>


            <td>

                <button
                    type="button"
                    class="review-button"
                    data-document-id="${documentId}"
                >
                    Review
                </button>

            </td>
        `;


        queueTableBody
            .appendChild(
                row
            );

    }


    queueTableContainer.hidden =
        false;


    bindReviewButtons();

}


// ==========================================================
// REVIEW BUTTONS
// ==========================================================

function bindReviewButtons() {

    const buttons =
        document.querySelectorAll(
            ".review-button"
        );


    buttons.forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    const documentId =
                        button.dataset
                            .documentId;


                    // Phase 7B.7 will replace this
                    // with the full review detail UI.

                    window.location.href =
                        (
                            "/review/"
                            + encodeURIComponent(
                                documentId
                            )
                        );

                }
            );

        }
    );

}


// ==========================================================
// LOAD REVIEW QUEUE
// ==========================================================

async function loadReviewQueue() {

    hideQueueStates();


    queueLoading.hidden =
        false;


    try {

        const url =
            buildQueueUrl();


        const response =
            await fetch(
                url
            );


        if (!response.ok) {

            let message =
                "Review queue request failed.";


            try {

                const errorBody =
                    await response.json();


                if (
                    errorBody.detail
                ) {

                    message =
                        errorBody.detail;

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


        const documents =
            Array.isArray(
                data.documents
            )
                ? data.documents
                : [];


        queueLoading.hidden =
            true;


        updateSummaryCounts(
            documents
        );


        renderQueue(
            documents
        );

    }

    catch (error) {

        console.error(
            "Review queue load failed:",
            error
        );


        queueLoading.hidden =
            true;


        queueErrorMessage.textContent =
            (
                error.message
                || "Please try again."
            );


        queueError.hidden =
            false;


        pendingCount.textContent =
            "—";


        highCount.textContent =
            "—";


        mediumCount.textContent =
            "—";


        lowCount.textContent =
            "—";

    }

}


// ==========================================================
// REFRESH DASHBOARD
// ==========================================================

async function refreshDashboard() {

    refreshButton.disabled =
        true;


    refreshButton.textContent =
        "Refreshing...";


    try {

        await checkApiHealth();

        await loadReviewQueue();

    }

    finally {

        refreshButton.disabled =
            false;


        refreshButton.textContent =
            "Refresh";

    }

}


// ==========================================================
// FILTER EVENTS
// ==========================================================

priorityFilter.addEventListener(
    "change",
    async () => {

        await loadReviewQueue();

    }
);


documentTypeFilter.addEventListener(
    "change",
    async () => {

        await loadReviewQueue();

    }
);


// ==========================================================
// REFRESH EVENT
// ==========================================================

refreshButton.addEventListener(
    "click",
    refreshDashboard
);


// ==========================================================
// INITIAL LOAD
// ==========================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        await checkApiHealth();

        await loadReviewQueue();

    }
);