from datetime import datetime
from typing import (
    Any,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


# ==========================================================
# HUMAN REVIEW REQUEST
# PHASE 7C.5
# ==========================================================

class HumanReviewRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    # ------------------------------------------------------
    # DEPRECATED CLIENT FIELD
    # ------------------------------------------------------
    #
    # Kept temporarily so the existing Phase 7B dashboard
    # does not receive HTTP 422 while Phase 7C.5 is being
    # rolled out.
    #
    # IMPORTANT:
    # The backend MUST NOT use this value as the
    # authoritative reviewer identity.
    #
    # ReviewerIdentityService resolves the trusted
    # identity server-side.
    # ------------------------------------------------------

    reviewer_id: (
        str
        | None
    ) = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    action: Literal[
        "APPROVE",
        "REJECT",
        "CORRECT",
    ]

    notes: str | None = None

    corrections: (
        dict[str, str | None]
        | None
    ) = None


# ==========================================================
# REVIEW QUEUE FILTERS
# PHASE 7A
# ==========================================================

class ReviewQueueFilters(BaseModel):

    priority: (
        Literal[
            "HIGH",
            "MEDIUM",
            "LOW",
        ]
        | None
    ) = None

    document_type: (
        str
        | None
    ) = None


# ==========================================================
# REVIEW QUEUE ITEM
# PHASE 7A
# ==========================================================

class ReviewQueueItem(BaseModel):

    document_id: str

    analysis_id: str

    original_filename: str

    content_type: str

    document_type: (
        str
        | None
    )

    processing_status: str

    review_decision: Literal[
        "REVIEW_REQUIRED"
    ]

    review_priority: Literal[
        "HIGH",
        "MEDIUM",
        "LOW",
    ]

    reason_codes: list[str] = Field(
        default_factory=list
    )

    review_issues: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    anomaly_issues: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    created_at: (
        datetime
        | None
    )

    analysis_created_at: (
        datetime
        | None
    )


# ==========================================================
# REVIEW QUEUE RESPONSE
# PHASE 7A
# ==========================================================

class ReviewQueueResponse(BaseModel):

    total: int = Field(
        ge=0
    )

    filters: ReviewQueueFilters

    documents: list[
        ReviewQueueItem
    ] = Field(
        default_factory=list
    )


# ==========================================================
# DOCUMENTS LIST
# PHASE 8.8A
# ==========================================================
#
# A SUMMARY schema.
#
# Deliberately absent: extraction, ocr_lines, field
# confidence, evidence flags, anomaly detail, audit history
# and image bytes. Those belong to the detail endpoints. A
# list screen that carried them would leak document content
# into a browsable index.
#
# Overall confidence is also absent. field_confidence is
# per-field only and this codebase has no authoritative
# overall-confidence definition, so exposing one here would
# be an invented statistic.
# ==========================================================

class DocumentListItem(BaseModel):

    document_id: str

    filename: str

    content_type: str

    document_type: (
        str
        | None
    ) = None

    processing_status: str

    # From review_decision.decision
    machine_decision: (
        str
        | None
    ) = None

    # From review_decision.priority
    priority: (
        str
        | None
    ) = None

    # Resolved by FinalRecordService, the same authority the
    # detail read path uses.
    final_state: (
        str
        | None
    ) = None

    # PHASE 10.2. SUPPORTED, UNSUPPORTED or
    # UNCLASSIFIED_NEEDS_REVIEW, derived by the same domain
    # function the detail read path uses.
    classification_outcome: (
        str
        | None
    ) = None

    human_review_action: (
        str
        | None
    ) = None

    is_reviewed: bool = False

    # From date_validation.expiry
    expiry_date: (
        str
        | None
    ) = None

    expiry_status: (
        str
        | None
    ) = None

    reviewer_id: (
        str
        | None
    ) = None

    created_at: (
        str
        | None
    ) = None

    processed_at: (
        str
        | None
    ) = None

    reviewed_at: (
        str
        | None
    ) = None


class DocumentListResponse(BaseModel):

    status: str = "success"

    items: list[
        DocumentListItem
    ] = Field(
        default_factory=list
    )

    total: int = Field(
        ge=0
    )

    page: int = Field(
        ge=1
    )

    page_size: int = Field(
        ge=1
    )

    total_pages: int = Field(
        ge=0
    )


# ==========================================================
# DASHBOARD SUMMARY
# PHASE 8.6A
# ==========================================================
#
# Every field is a count of persisted rows.
#
# There is no accuracy, success rate, risk score, SLA or
# average confidence, because this codebase defines none of
# those and inventing them would misrepresent the system.
# ==========================================================

class DashboardReviewCounts(BaseModel):

    # decision = REVIEW_REQUIRED and no human review exists.
    # Identical definition to GET /api/v1/reviews/queue.
    pending_review: int = Field(
        ge=0
    )

    auto_accepted: int = Field(
        ge=0
    )

    review_required: int = Field(
        ge=0
    )

    # PHASE 10.2. decision = UNSUPPORTED_DOCUMENT.
    #
    # Counted separately and NOT included in pending_review or
    # review_required, because no reviewer is queued for these.
    # Folding them into either number would overstate the
    # outstanding human workload.
    unsupported: int = Field(
        ge=0
    )

    approved: int = Field(
        ge=0
    )

    corrected: int = Field(
        ge=0
    )

    rejected: int = Field(
        ge=0
    )


class DashboardExpiryCounts(BaseModel):

    # Mirrors date_validation.expiry.status exactly. No new
    # threshold is defined here.
    expired: int = Field(
        ge=0
    )

    expires_today: int = Field(
        ge=0
    )

    expiring_soon: int = Field(
        ge=0
    )

    active: int = Field(
        ge=0
    )

    not_available: int = Field(
        ge=0
    )


class DashboardPriorityCounts(BaseModel):

    high: int = Field(
        ge=0
    )

    medium: int = Field(
        ge=0
    )

    low: int = Field(
        ge=0
    )


class DashboardSummaryResponse(BaseModel):

    status: str = "success"

    total_documents: int = Field(
        ge=0
    )

    review: DashboardReviewCounts

    expiry: DashboardExpiryCounts

    pending_review_priority: DashboardPriorityCounts

    # Bounded. Reuses the Documents list item shape so the
    # dashboard and the list cannot describe a document
    # differently.
    recent_documents: list[
        DocumentListItem
    ] = Field(
        default_factory=list
    )
