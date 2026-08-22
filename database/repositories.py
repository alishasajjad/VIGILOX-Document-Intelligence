from datetime import datetime

from sqlalchemy import (
    case,
    exists,
    select,
)
from sqlalchemy.orm import Session

from database.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


# ==========================================================
# HUMAN REVIEW EXCEPTIONS
# PHASE 7C.1
# ==========================================================

class DuplicateHumanReviewError(
    RuntimeError
):
    """
    Raised when a completed human review already exists
    for the supplied document.

    Phase 7C.1 rule:

        One document can have only one completed
        human review.

    This is the application-level protection layer.

    A PostgreSQL UNIQUE constraint on
    human_reviews.document_id will provide the final
    database-level concurrency protection.
    """

    def __init__(
        self,
        document_id: str,
    ):

        self.document_id = (
            document_id
        )

        super().__init__(
            (
                "A human review already exists "
                f"for document {document_id}."
            )
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
        source_sha256: str | None = None,
    ) -> DocumentModel:

        document = DocumentModel(
            original_filename=(
                original_filename
            ),

            content_type=(
                content_type
            ),

            document_type=(
                document_type
            ),

            processing_status=(
                processing_status
            ),

            # PHASE 10.3. Keyword-only with a default, so
            # every existing caller keeps working and stores
            # null -- which is the honest value for a
            # document whose source was never fingerprinted.
            source_sha256=(
                source_sha256
            ),
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


    # ======================================================
    # SOURCE FINGERPRINT LOOKUP
    # PHASE 10.3
    # ======================================================

    def documents_for_source(
        self,
        source_sha256: str | None,
    ) -> list[DocumentModel]:

        """
        Every document made from these exact bytes, OLDEST
        FIRST.

        Oldest first because position in this list is the
        answer to "is this the original or a repeat", and the
        first element is the original.

        A null or blank fingerprint returns nothing rather
        than matching every unfingerprinted document. SQL
        would not match NULL against NULL anyway, but
        returning early makes the intent explicit and skips
        the query: "not known" is not a source that can be
        duplicated.
        """

        if not source_sha256:
            return []


        return list(
            self.session.execute(
                select(
                    DocumentModel
                )
                .where(
                    DocumentModel.source_sha256
                    == source_sha256
                )
                .order_by(
                    DocumentModel.created_at.asc(),
                    DocumentModel.id.asc(),
                )
            )
            .scalars()
            .all()
        )
    
    # ======================================================
    # DELETE DOCUMENT
    # PHASE 7C.6
    # ======================================================

    def delete_document(
        self,
        document: DocumentModel,
    ) -> None:

        self.session.delete(
            document
        )


        # Execute DELETE inside the current transaction.
        #
        # PostgreSQL foreign-key ON DELETE CASCADE removes:
        #
        #   document_analyses
        #   human_reviews
        #   audit_events
        #
        # Commit remains controlled by the service-level
        # SessionLocal.begin() transaction.

        self.session.flush()


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

        analysis = (
            DocumentAnalysisModel(

                document_id=(
                    document_id
                ),

                extraction=(
                    pipeline_result[
                        "extraction"
                    ]
                ),

                # PHASE 10.1. .get() rather than [], so a
                # pipeline result produced before quality
                # assessment existed still persists.
                quality=(
                    pipeline_result.get(
                        "quality"
                    )
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
                DocumentAnalysisModel
                .document_id
                == document_id
            )
        )


        return (
            self.session
            .scalars(
                statement
            )
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


    # ======================================================
    # PHASE 7C.1
    # CHECK WHETHER DOCUMENT ALREADY HAS A HUMAN REVIEW
    # ======================================================

    def has_review_for_document(
        self,
        document_id: str,
    ) -> bool:

        statement = (
            select(
                exists()
                .where(
                    HumanReviewModel
                    .document_id
                    == document_id
                )
            )
        )


        return bool(
            self.session.scalar(
                statement
            )
        )


    # ======================================================
    # PHASE 7C.1
    # GET THE SINGLE HUMAN REVIEW FOR A DOCUMENT
    # ======================================================

    def get_single_by_document_id(
        self,
        document_id: str,
    ) -> HumanReviewModel | None:

        statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel
                .document_id
                == document_id
            )
            .order_by(
                HumanReviewModel
                .reviewed_at
            )
            .limit(
                1
            )
        )


        return (
            self.session
            .scalars(
                statement
            )
            .first()
        )


    # ======================================================
    # CREATE HUMAN REVIEW
    # PHASE 7C.1 APPLICATION DUPLICATE GUARD
    # ======================================================

    def create_review(
        self,
        *,
        review_result: dict,
    ) -> HumanReviewModel:

        document_id = (
            review_result[
                "document_id"
            ]
        )


        # ==================================================
        # DUPLICATE REVIEW PRE-CHECK
        # ==================================================
        #
        # This blocks ordinary sequential duplicate
        # submissions at the application layer.
        #
        # Example:
        #
        # Reviewer A:
        #   APPROVE → accepted
        #
        # Reviewer B later:
        #   REJECT → DuplicateHumanReviewError
        #
        # NOTE:
        # This check alone cannot eliminate a true race
        # condition where two transactions execute the
        # check simultaneously.
        #
        # PostgreSQL UNIQUE(document_id) will provide the
        # final concurrency guarantee in the next 7C.1 step.
        # ==================================================

        if self.has_review_for_document(
            document_id
        ):

            raise DuplicateHumanReviewError(
                document_id
            )


        # ==================================================
        # REVIEW TIMESTAMP
        # ==================================================

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


        # ==================================================
        # CREATE RECORD
        # ==================================================

        review = (
            HumanReviewModel(

                id=(
                    review_result[
                        "review_id"
                    ]
                ),

                document_id=(
                    document_id
                ),

                reviewer_id=(
                    review_result[
                        "reviewer_id"
                    ]
                ),

                machine_decision=(
                    review_result[
                        "machine_decision"
                    ]
                ),

                machine_priority=(
                    review_result[
                        "machine_priority"
                    ]
                ),

                machine_reason_codes=(
                    review_result.get(
                        "machine_reason_codes"
                    )
                    or []
                ),

                human_action=(
                    review_result[
                        "human_action"
                    ]
                ),

                corrections=(
                    review_result.get(
                        "corrections"
                    )
                    or {}
                ),

                notes=(
                    review_result.get(
                        "notes"
                    )
                ),

                reviewed_at=(
                    reviewed_at
                ),
            )
        )


        self.session.add(
            review
        )


        self.session.flush()


        return review


    # ======================================================
    # GET REVIEW BY REVIEW ID
    # ======================================================

    def get_review(
        self,
        review_id: str,
    ) -> HumanReviewModel | None:

        return self.session.get(
            HumanReviewModel,
            review_id,
        )


    # ======================================================
    # GET REVIEWS BY DOCUMENT ID
    # ======================================================
    #
    # This legacy/list method is intentionally preserved
    # for backward compatibility with existing query,
    # audit and test code.
    #
    # After Phase 7C.1 is fully implemented, normal
    # production state should contain at most one review
    # per document.
    # ======================================================

    def get_by_document_id(
        self,
        document_id: str,
    ) -> list[
        HumanReviewModel
    ]:

        statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel
                .document_id
                == document_id
            )
            .order_by(
                HumanReviewModel
                .reviewed_at
            )
        )


        return list(
            self.session
            .scalars(
                statement
            )
            .all()
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

        event = (
            AuditEventModel(

                document_id=(
                    document_id
                ),

                event_type=(
                    event_type
                ),

                actor_type=(
                    actor_type
                ),

                actor_id=(
                    actor_id
                ),

                details=(
                    details
                ),
            )
        )


        self.session.add(
            event
        )


        self.session.flush()


        return event


    def get_by_document_id(
        self,
        document_id: str,
    ) -> list[
        AuditEventModel
    ]:

        statement = (
            select(
                AuditEventModel
            )
            .where(
                AuditEventModel
                .document_id
                == document_id
            )
            .order_by(
                AuditEventModel
                .created_at
            )
        )


        return list(
            self.session
            .scalars(
                statement
            )
            .all()
        )


# ==========================================================
# REVIEW QUEUE REPOSITORY
# PHASE 7A
# ==========================================================

class ReviewQueueRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    def get_review_queue(
        self,
        *,
        priority: str | None = None,
        document_type: str | None = None,
    ) -> list[
        tuple[
            DocumentModel,
            DocumentAnalysisModel,
        ]
    ]:

        # ==================================================
        # JSONB EXPRESSIONS
        # ==================================================

        decision_expression = (
            DocumentAnalysisModel
            .review_decision[
                "decision"
            ]
            .as_string()
        )


        priority_expression = (
            DocumentAnalysisModel
            .review_decision[
                "priority"
            ]
            .as_string()
        )


        # ==================================================
        # HUMAN REVIEW EXISTS
        # ==================================================
        #
        # A document must disappear from the pending
        # review queue once any human review has been
        # submitted for that document.
        # ==================================================

        human_review_exists = (
            exists()
            .where(
                HumanReviewModel
                .document_id
                == DocumentModel.id
            )
        )


        # ==================================================
        # PRIORITY ORDER
        # ==================================================

        priority_order = (
            case(

                (
                    priority_expression
                    == "HIGH",
                    1,
                ),

                (
                    priority_expression
                    == "MEDIUM",
                    2,
                ),

                (
                    priority_expression
                    == "LOW",
                    3,
                ),

                else_=4,
            )
        )


        # ==================================================
        # BASE QUERY
        # ==================================================

        statement = (
            select(
                DocumentModel,
                DocumentAnalysisModel,
            )

            .join(
                DocumentAnalysisModel,
                DocumentAnalysisModel
                    .document_id
                == DocumentModel.id,
            )

            .where(
                decision_expression
                == "REVIEW_REQUIRED"
            )

            # Exclude documents that have already
            # received a human review.
            .where(
                ~human_review_exists
            )
        )


        # ==================================================
        # OPTIONAL PRIORITY FILTER
        # ==================================================

        if priority is not None:

            statement = (
                statement.where(
                    priority_expression
                    == priority
                )
            )


        # ==================================================
        # OPTIONAL DOCUMENT TYPE FILTER
        # ==================================================

        if document_type is not None:

            statement = (
                statement.where(
                    DocumentModel
                        .document_type
                    == document_type
                )
            )


        # ==================================================
        # ORDERING
        # ==================================================
        #
        # HIGH first
        # MEDIUM second
        # LOW third
        #
        # Within the same priority:
        # oldest document first.
        # ==================================================

        statement = (
            statement.order_by(
                priority_order.asc(),
                DocumentModel
                    .created_at
                    .asc(),
            )
        )


        # ==================================================
        # EXECUTE QUERY
        # ==================================================

        rows = (
            self.session
            .execute(
                statement
            )
            .all()
        )


        return [
            (
                row[
                    0
                ],
                row[
                    1
                ],
            )

            for row
            in rows
        ]