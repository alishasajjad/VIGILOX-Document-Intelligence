from src.db.database import (
    SessionLocal,
)

from src.db.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
)


class PersistenceService:

    # ======================================================
    # SAVE PROCESSED DOCUMENT
    # ======================================================

    def save_processed_document(
        self,
        *,
        original_filename: str,
        content_type: str,
        pipeline_result: dict,
    ) -> dict:

        document_type = (
            pipeline_result[
                "extraction"
            ]
            .get(
                "document_type"
            )
        )


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


            # ==============================================
            # DOCUMENT
            # ==============================================

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


            # ==============================================
            # ANALYSIS
            # ==============================================

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


            # ==============================================
            # MACHINE DECISION AUDIT
            # ==============================================

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
            }


        return result


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