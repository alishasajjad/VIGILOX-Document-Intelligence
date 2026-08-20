from pathlib import Path

from sqlalchemy.exc import (
    IntegrityError,
)

from database.database import (
    SessionLocal,
)

from database.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    DuplicateHumanReviewError,
    HumanReviewRepository,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)

from backend.app.core.logging import (
    get_operational_logger,
    log_exception,
)


# ==========================================================
# STRUCTURED OPERATIONAL LOGGER
# PHASE 7C.7d
# ==========================================================

logger = (
    get_operational_logger(
        "persistence"
    )
)


# ==========================================================
# PHASE 7C.1
# DATABASE CONSTRAINT NAME
# ==========================================================

HUMAN_REVIEW_UNIQUE_CONSTRAINT = (
    "uq_human_reviews_document_id"
)


class PersistenceService:

    # ======================================================
    # INITIALIZATION
    # PHASE 7B
    # ======================================================

    def __init__(
        self,
        storage_service: (
            DocumentStorageService
            | None
        ) = None,
    ):

        self.storage_service = (
            storage_service
            or DocumentStorageService()
        )


    # ======================================================
    # PHASE 7C.1
    # IDENTIFY DUPLICATE HUMAN REVIEW DB VIOLATION
    # ======================================================

    @staticmethod
    def _is_duplicate_human_review_integrity_error(
        exc: IntegrityError,
    ) -> bool:

        original_error = (
            exc.orig
        )


        # ==================================================
        # PREFERRED PSYCOPG / POSTGRESQL DIAGNOSTIC
        # ==================================================

        diagnostic = (
            getattr(
                original_error,
                "diag",
                None,
            )
        )


        constraint_name = (
            getattr(
                diagnostic,
                "constraint_name",
                None,
            )
            if diagnostic is not None
            else None
        )


        if (
            constraint_name
            == HUMAN_REVIEW_UNIQUE_CONSTRAINT
        ):

            return True


        # ==================================================
        # SAFE FALLBACK
        # ==================================================
        #
        # Some database driver/error combinations may not
        # expose diag.constraint_name directly.
        #
        # Only translate the error if our exact constraint
        # name is present.
        # ==================================================

        return (
            HUMAN_REVIEW_UNIQUE_CONSTRAINT
            in str(
                original_error
            )
        )


    # ======================================================
    # SAVE PROCESSED DOCUMENT
    # PHASE 7B / PHASE 7C.6c
    # ======================================================

    def save_processed_document(
        self,
        *,
        original_filename: str,
        content_type: str,
        pipeline_result: dict,
        source_path: str | Path | None = None,
    ) -> dict:

        document_type = (
            pipeline_result[
                "extraction"
            ]
            .get(
                "document_type"
            )
        )


        # ==================================================
        # STORAGE LIFECYCLE TRACKING
        # PHASE 7C.6c
        # ==================================================
        #
        # stored_document_id:
        #
        #     Becomes available once PostgreSQL creates the
        #     document row inside the current transaction.
        #
        # original_document_stored:
        #
        #     Used for the successful API result.
        #
        # IMPORTANT:
        #
        # Failure cleanup must NOT depend on
        # original_document_stored because save_original()
        # could physically create storage and then fail
        # before returning.
        # ==================================================

        stored_document_id = None

        original_document_stored = False


        try:

            # ==================================================
            # DATABASE TRANSACTION
            # ==================================================
            #
            # PostgreSQL operations below share one transaction:
            #
            #   document
            #   analysis
            #   machine audit
            #
            # Any exception rolls all database operations back.
            #
            # Filesystem writes are not transactional and need
            # compensating cleanup in the outer exception block.
            # ==================================================

            with SessionLocal.begin() as session:

                document_repository = (
                    DocumentRepository(
                        session
                    )
                )

                analysis_repository = (
                    DocumentAnalysisRepository(
                        session
                    )
                )

                audit_repository = (
                    AuditEventRepository(
                        session
                    )
                )


                # ==========================================
                # DOCUMENT
                # ==========================================

                document = (
                    document_repository
                    .create_document(
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
                            "PROCESSED"
                        ),
                    )
                )


                stored_document_id = (
                    document.id
                )


                # ==========================================
                # ORIGINAL DOCUMENT STORAGE
                # PHASE 7B / 7C.6
                # ==========================================
                #
                # The physical source is stored while the
                # PostgreSQL transaction is still open.
                #
                # If anything after this point fails:
                #
                #   PostgreSQL → rollback
                #   filesystem → compensating cleanup
                #
                # ==========================================

                if source_path is not None:

                    self.storage_service.save_original(
                        document_id=(
                            document.id
                        ),

                        source_path=(
                            source_path
                        ),

                        content_type=(
                            content_type
                        ),
                    )


                    original_document_stored = (
                        True
                    )


                # ==========================================
                # ANALYSIS
                # ==========================================

                analysis = (
                    analysis_repository
                    .create_analysis(
                        document_id=(
                            document.id
                        ),

                        pipeline_result=(
                            pipeline_result
                        ),
                    )
                )


                # ==========================================
                # MACHINE DECISION AUDIT
                # ==========================================

                review_decision = (
                    pipeline_result[
                        "review_decision"
                    ]
                )


                machine_audit = (
                    audit_repository
                    .create_event(
                        document_id=(
                            document.id
                        ),

                        event_type=(
                            "MACHINE_REVIEW_DECISION"
                        ),

                        actor_type=(
                            "SYSTEM"
                        ),

                        actor_id=(
                            "vigilox-system"
                        ),

                        details={
                            "decision":
                                review_decision.get(
                                    "decision"
                                ),

                            "review_required":
                                review_decision.get(
                                    "review_required"
                                ),

                            "priority":
                                review_decision.get(
                                    "priority"
                                ),

                            "reason_codes":
                                review_decision.get(
                                    "reason_codes",
                                    [],
                                ),
                        },
                    )
                )


                # ==========================================
                # SUCCESS RESULT
                # ==========================================

                result = {
                    "document_id":
                        document.id,

                    "analysis_id":
                        analysis.id,

                    "machine_audit_id":
                        machine_audit.id,

                    "document_type":
                        document.document_type,

                    "processing_status":
                        document.processing_status,

                    "original_document_stored":
                        original_document_stored,
                }


            # ==================================================
            # TRANSACTION COMMITTED SUCCESSFULLY
            # ==================================================

            return result


        except Exception:

            # ==============================================
            # FILESYSTEM COMPENSATING CLEANUP
            # PHASE 7C.6c
            # ==============================================
            #
            # SessionLocal.begin() automatically rolls back
            # the PostgreSQL transaction.
            #
            # The filesystem is different:
            #
            #     storage writes are not transactional.
            #
            # Therefore any managed document directory that
            # may have been created during this failed
            # persistence operation must be removed.
            #
            #
            # IMPORTANT CHANGE FROM PHASE 7B
            # ----------------------------------------------
            #
            # OLD CONDITION:
            #
            #     stored_document_id is not None
            #     AND
            #     original_document_stored is True
            #
            #
            # Problem:
            #
            # save_original() could theoretically:
            #
            #     1. physically write original.jpg
            #     2. encounter an exception
            #     3. never return to this service
            #
            # In that situation:
            #
            #     original_document_stored == False
            #
            # but physical storage may exist.
            #
            #
            # NEW RULE:
            #
            # If:
            #
            #     a document ID was allocated
            #     AND
            #     source storage was part of this operation
            #
            # always perform an idempotent cleanup attempt.
            #
            # DocumentStorageService.delete_document()
            # safely returns False if nothing exists.
            # ==============================================

            if (
                stored_document_id is not None
                and source_path is not None
            ):

                try:

                    self.storage_service.delete_document(
                        stored_document_id
                    )


                except Exception as cleanup_exc:

                    # ======================================
                    # CLEANUP FAILURE OBSERVABILITY
                    # ======================================
                    #
                    # The original processing / persistence
                    # exception remains the authoritative
                    # failure and must be re-raised.
                    #
                    # Do not replace it with the secondary
                    # cleanup exception.
                    #
                    # A cleanup failure can leave an orphan
                    # storage directory. Phase 7C.6d / 7C.6e
                    # will detect and reconcile such orphans.
                    # ======================================

                    log_exception(
                        logger,

                        event=(
                            "document_storage"
                            "_compensation_failed"
                        ),

                        message=(
                            "Compensating storage "
                            "cleanup failed after a "
                            "persistence failure."
                        ),

                        exc=cleanup_exc,

                        document_id=(
                            stored_document_id
                        ),
                    )


            # Preserve original traceback.

            raise


    # ======================================================
    # SAVE HUMAN REVIEW + AUDIT
    # PHASE 7B / PHASE 7C.1
    # ======================================================

    def save_human_review(
        self,
        *,
        review_result: dict,
    ) -> dict:

        document_id = (
            review_result[
                "document_id"
            ]
        )


        try:

            # ==================================================
            # TRANSACTION BOUNDARY
            # ==================================================
            #
            # Human review and HUMAN_REVIEW audit event are
            # intentionally persisted in the SAME transaction.
            #
            # If the human-review insert fails because another
            # reviewer already completed the document:
            #
            #   human_reviews insert → rollback
            #   audit event          → rollback / never created
            #
            # This prevents duplicate audit events.
            # ==================================================

            with SessionLocal.begin() as session:

                document_repository = (
                    DocumentRepository(
                        session
                    )
                )

                human_review_repository = (
                    HumanReviewRepository(
                        session
                    )
                )

                audit_repository = (
                    AuditEventRepository(
                        session
                    )
                )


                # ==============================================
                # ENSURE DOCUMENT EXISTS
                # ==============================================

                document = (
                    document_repository
                    .get_document(
                        document_id
                    )
                )


                if document is None:

                    raise ValueError(
                        "Cannot persist human "
                        "review because the "
                        "document does not exist."
                    )


                # ==============================================
                # HUMAN REVIEW
                # ==============================================
                #
                # Repository performs the normal application
                # pre-check.
                #
                # PostgreSQL UNIQUE(document_id) remains the
                # final concurrency protection.
                # ==============================================

                review = (
                    human_review_repository
                    .create_review(
                        review_result=(
                            review_result
                        )
                    )
                )


                # ==============================================
                # HUMAN REVIEW AUDIT
                # ==============================================

                audit_event = (
                    audit_repository
                    .create_event(
                        document_id=(
                            document_id
                        ),

                        event_type=(
                            "HUMAN_REVIEW"
                        ),

                        actor_type=(
                            "HUMAN"
                        ),

                        actor_id=(
                            review_result[
                                "reviewer_id"
                            ]
                        ),

                        details={
                            "review_id":
                                review.id,

                            "human_action":
                                review_result[
                                    "human_action"
                                ],

                            "machine_decision":
                                review_result[
                                    "machine_decision"
                                ],

                            "machine_priority":
                                review_result[
                                    "machine_priority"
                                ],

                            "machine_reason_codes":
                                review_result.get(
                                    "machine_reason_codes",
                                    [],
                                ),

                            "corrections":
                                review_result.get(
                                    "corrections"
                                )
                                or {},

                            "notes":
                                review_result.get(
                                    "notes"
                                ),

                            "reviewed_at":
                                review_result[
                                    "reviewed_at"
                                ],
                        },
                    )
                )


                # ==============================================
                # RESULT
                # ==============================================

                result = {
                    "review_id":
                        review.id,

                    "document_id":
                        document_id,

                    "human_action":
                        review.human_action,

                    "audit_event_id":
                        audit_event.id,
                }


            return result


        # ======================================================
        # APPLICATION-LEVEL DUPLICATE
        # ======================================================
        #
        # Repository has already detected an existing review.
        # SessionLocal.begin() automatically rolls back.
        # ======================================================

        except DuplicateHumanReviewError:

            raise


        # ======================================================
        # DATABASE-LEVEL CONCURRENT DUPLICATE
        # PHASE 7C.1
        # ======================================================
        #
        # Example:
        #
        # Transaction A:
        #   existence check → no review
        #
        # Transaction B:
        #   existence check → no review
        #
        # Both attempt INSERT.
        #
        # PostgreSQL UNIQUE(document_id) allows only one.
        #
        # Translate only our known UNIQUE constraint into
        # the domain-level DuplicateHumanReviewError.
        # Other IntegrityError cases must remain visible as
        # real persistence failures.
        # ======================================================

        except IntegrityError as exc:

            if (
                self
                ._is_duplicate_human_review_integrity_error(
                    exc
                )
            ):

                raise DuplicateHumanReviewError(
                    document_id
                ) from exc


            raise