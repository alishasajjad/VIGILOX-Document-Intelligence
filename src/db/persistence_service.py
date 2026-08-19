from pathlib import Path

from src.db.database import (
    SessionLocal,
)

from src.db.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
)

from src.document_storage_service import (
    DocumentStorageService,
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
    # SAVE PROCESSED DOCUMENT
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


        # Keep track of storage so that a later
        # database failure can clean the file.
        stored_document_id = None

        original_document_stored = False


        try:

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
                # PHASE 7B
                # ==========================================
                #
                # source_path remains optional for backward
                # compatibility with older tests/services.
                #
                # Real API uploads will provide it.
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


                    original_document_stored = True


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
                # RESULT
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


            return result


        except Exception:

            # ==============================================
            # FILESYSTEM COMPENSATING CLEANUP
            # ==============================================
            #
            # PostgreSQL rolls back automatically because
            # SessionLocal.begin() failed.
            #
            # Filesystem writes are not transactional, so
            # remove any file that was already stored.
            # ==============================================

            if (
                stored_document_id is not None
                and original_document_stored
            ):

                try:

                    self.storage_service.delete_document(
                        stored_document_id
                    )

                except Exception as cleanup_exc:

                    print(
                        "[DOCUMENT STORAGE CLEANUP ERROR]",
                        repr(
                            cleanup_exc
                        ),
                    )


            raise


    # ======================================================
    # SAVE HUMAN REVIEW + AUDIT
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