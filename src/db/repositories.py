from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


# ==========================================================
# DOCUMENT REPOSITORY
# ==========================================================

class DocumentRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    def create_document(
        self,
        *,
        original_filename: str,
        content_type: str,
        document_type: str | None,
        processing_status: str = "PROCESSED",
    ) -> DocumentModel:

        document = DocumentModel(
            original_filename=original_filename,
            content_type=content_type,
            document_type=document_type,
            processing_status=processing_status,
        )

        self.session.add(
            document
        )

        self.session.flush()

        return document


    def get_document(
        self,
        document_id: str,
    ) -> DocumentModel | None:

        return self.session.get(
            DocumentModel,
            document_id,
        )


# ==========================================================
# DOCUMENT ANALYSIS REPOSITORY
# ==========================================================

class DocumentAnalysisRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    def create_analysis(
        self,
        *,
        document_id: str,
        pipeline_result: dict,
    ) -> DocumentAnalysisModel:

        analysis = DocumentAnalysisModel(
            document_id=document_id,

            extraction=(
                pipeline_result[
                    "extraction"
                ]
            ),

            ocr_lines=(
                pipeline_result[
                    "ocr_lines"
                ]
            ),

            evidence_flags=(
                pipeline_result[
                    "evidence_flags"
                ]
            ),

            field_confidence=(
                pipeline_result[
                    "field_confidence"
                ]
            ),

            date_validation=(
                pipeline_result[
                    "date_validation"
                ]
            ),

            anomaly_validation=(
                pipeline_result[
                    "anomaly_validation"
                ]
            ),

            review_decision=(
                pipeline_result[
                    "review_decision"
                ]
            ),
        )

        self.session.add(
            analysis
        )

        self.session.flush()

        return analysis


    def get_by_document_id(
        self,
        document_id: str,
    ) -> DocumentAnalysisModel | None:

        statement = (
            select(
                DocumentAnalysisModel
            )
            .where(
                DocumentAnalysisModel.document_id
                == document_id
            )
        )

        return (
            self.session
            .scalars(statement)
            .one_or_none()
        )


# ==========================================================
# HUMAN REVIEW REPOSITORY
# ==========================================================

class HumanReviewRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    def create_review(
        self,
        *,
        review_result: dict,
    ) -> HumanReviewModel:

        reviewed_at = (
            review_result[
                "reviewed_at"
            ]
        )

        if isinstance(
            reviewed_at,
            str,
        ):
            reviewed_at = (
                datetime.fromisoformat(
                    reviewed_at
                )
            )


        review = HumanReviewModel(
            id=review_result[
                "review_id"
            ],

            document_id=review_result[
                "document_id"
            ],

            reviewer_id=review_result[
                "reviewer_id"
            ],

            machine_decision=review_result[
                "machine_decision"
            ],

            machine_priority=review_result[
                "machine_priority"
            ],

            machine_reason_codes=(
                review_result.get(
                    "machine_reason_codes"
                )
                or []
            ),

            human_action=review_result[
                "human_action"
            ],

            corrections=(
                review_result.get(
                    "corrections"
                )
                or {}
            ),

            notes=review_result.get(
                "notes"
            ),

            reviewed_at=reviewed_at,
        )

        self.session.add(
            review
        )

        self.session.flush()

        return review


    def get_review(
        self,
        review_id: str,
    ) -> HumanReviewModel | None:

        return self.session.get(
            HumanReviewModel,
            review_id,
        )


    def get_by_document_id(
        self,
        document_id: str,
    ) -> list[HumanReviewModel]:

        statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel.document_id
                == document_id
            )
            .order_by(
                HumanReviewModel.reviewed_at
            )
        )

        return list(
            self.session.scalars(
                statement
            ).all()
        )


# ==========================================================
# AUDIT EVENT REPOSITORY
# ==========================================================

class AuditEventRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    def create_event(
        self,
        *,
        document_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        details: dict,
    ) -> AuditEventModel:

        event = AuditEventModel(
            document_id=document_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            details=details,
        )

        self.session.add(
            event
        )

        self.session.flush()

        return event


    def get_by_document_id(
        self,
        document_id: str,
    ) -> list[AuditEventModel]:

        statement = (
            select(
                AuditEventModel
            )
            .where(
                AuditEventModel.document_id
                == document_id
            )
            .order_by(
                AuditEventModel.created_at
            )
        )

        return list(
            self.session.scalars(
                statement
            ).all()
        )