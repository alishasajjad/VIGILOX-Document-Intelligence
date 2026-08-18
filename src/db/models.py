from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)

from sqlalchemy.dialects.postgresql import (
    JSONB,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from src.db.database import Base


# ==========================================================
# DOCUMENT
# ==========================================================

class DocumentModel(Base):

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    original_filename: Mapped[str] = (
        mapped_column(
            String(255),
            nullable=False,
        )
    )

    content_type: Mapped[str] = (
        mapped_column(
            String(100),
            nullable=False,
        )
    )

    document_type: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    processing_status: Mapped[str] = (
        mapped_column(
            String(50),
            nullable=False,
            default="PROCESSED",
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )


# ==========================================================
# DOCUMENT ANALYSIS
# ==========================================================

class DocumentAnalysisModel(Base):

    __tablename__ = "document_analyses"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    extraction: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    ocr_lines: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    evidence_flags: Mapped[list] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    field_confidence: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    date_validation: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    anomaly_validation: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    review_decision: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# HUMAN REVIEW
# ==========================================================

class HumanReviewModel(Base):

    __tablename__ = "human_reviews"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    reviewer_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    machine_decision: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    machine_priority: Mapped[
        str | None
    ] = mapped_column(
        String(30),
        nullable=True,
    )

    machine_reason_codes: Mapped[list] = (
        mapped_column(
            JSONB,
            nullable=False,
            default=list,
        )
    )

    human_action: Mapped[str] = (
        mapped_column(
            String(30),
            nullable=False,
        )
    )

    corrections: Mapped[dict] = (
        mapped_column(
            JSONB,
            nullable=False,
            default=dict,
        )
    )

    notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    reviewed_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )


# ==========================================================
# AUDIT EVENT
# ==========================================================

class AuditEventModel(Base):

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    document_id: Mapped[str] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    actor_id: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )