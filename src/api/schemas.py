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
# ==========================================================

class HumanReviewRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    reviewer_id: str = Field(
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