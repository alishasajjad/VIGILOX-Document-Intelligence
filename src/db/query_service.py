from src.db.database import (
    SessionLocal,
)

from src.db.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    ReviewQueueRepository,
)


class DocumentQueryService:

    # ======================================================
    # GET COMPLETE STORED DOCUMENT
    # ======================================================

    def get_document(
        self,
        document_id: str,
    ) -> dict | None:

        with SessionLocal() as session:

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


            # ==============================================
            # DOCUMENT METADATA
            # ==============================================

            document = (
                document_repository
                .get_document(
                    document_id
                )
            )


            if document is None:

                return None


            # ==============================================
            # STORED ANALYSIS
            # ==============================================

            analysis = (
                analysis_repository
                .get_by_document_id(
                    document_id
                )
            )


            # ==============================================
            # BUILD DOCUMENT RESPONSE
            # ==============================================

            result = {

                "document": {
                    "document_id":
                        document.id,

                    "original_filename":
                        document.original_filename,

                    "content_type":
                        document.content_type,

                    "document_type":
                        document.document_type,

                    "processing_status":
                        document.processing_status,

                    "created_at":
                        (
                            document.created_at
                            .isoformat()
                            if document.created_at
                            else None
                        ),

                    "updated_at":
                        (
                            document.updated_at
                            .isoformat()
                            if document.updated_at
                            else None
                        ),
                },

                "analysis":
                    None,
            }


            # ==============================================
            # INCLUDE ANALYSIS
            # ==============================================

            if analysis is not None:

                result["analysis"] = {

                    "analysis_id":
                        analysis.id,

                    "extraction":
                        analysis.extraction,

                    "ocr_lines":
                        analysis.ocr_lines,

                    "evidence_flags":
                        analysis.evidence_flags,

                    "field_confidence":
                        analysis.field_confidence,

                    "date_validation":
                        analysis.date_validation,

                    "anomaly_validation":
                        analysis.anomaly_validation,

                    "review_decision":
                        analysis.review_decision,

                    "created_at":
                        (
                            analysis.created_at
                            .isoformat()
                            if analysis.created_at
                            else None
                        ),
                }


            return result


    # ======================================================
    # GET DOCUMENT AUDIT HISTORY
    # ======================================================

    def get_document_history(
        self,
        document_id: str,
    ) -> dict | None:

        with SessionLocal() as session:

            document_repository = (
                DocumentRepository(
                    session
                )
            )

            audit_repository = (
                AuditEventRepository(
                    session
                )
            )


            # ==============================================
            # VERIFY DOCUMENT EXISTS
            # ==============================================

            document = (
                document_repository
                .get_document(
                    document_id
                )
            )


            if document is None:

                return None


            # ==============================================
            # LOAD AUDIT EVENTS
            # ==============================================

            audit_events = (
                audit_repository
                .get_by_document_id(
                    document_id
                )
            )


            # ==============================================
            # SERIALIZE EVENTS
            # ==============================================

            events = []


            for event in audit_events:

                events.append(
                    {
                        "audit_id":
                            event.id,

                        "document_id":
                            event.document_id,

                        "event_type":
                            event.event_type,

                        "actor_type":
                            event.actor_type,

                        "actor_id":
                            event.actor_id,

                        "details":
                            event.details,

                        "created_at":
                            (
                                event.created_at
                                .isoformat()
                                if event.created_at
                                else None
                            ),
                    }
                )


            return {
                "document_id":
                    document_id,

                "event_count":
                    len(events),

                "events":
                    events,
            }


    # ======================================================
    # GET REVIEW QUEUE
    # PHASE 7A
    # ======================================================

    def get_review_queue(
        self,
        *,
        priority: str | None = None,
        document_type: str | None = None,
    ) -> dict:

        # ==================================================
        # NORMALIZE OPTIONAL FILTERS
        # ==================================================

        normalized_priority = (
            priority.upper().strip()
            if priority is not None
            else None
        )


        normalized_document_type = (
            document_type.lower().strip()
            if document_type is not None
            else None
        )


        # ==================================================
        # DATABASE SESSION
        # ==================================================

        with SessionLocal() as session:

            review_queue_repository = (
                ReviewQueueRepository(
                    session
                )
            )


            # ==============================================
            # LOAD PENDING REVIEW DOCUMENTS
            # ==============================================

            queue_rows = (
                review_queue_repository
                .get_review_queue(
                    priority=(
                        normalized_priority
                    ),
                    document_type=(
                        normalized_document_type
                    ),
                )
            )


            # ==============================================
            # SERIALIZE QUEUE ITEMS
            # ==============================================

            documents = []


            for (
                document,
                analysis,
            ) in queue_rows:

                review_decision = (
                    analysis.review_decision
                    or {}
                )


                anomaly_validation = (
                    analysis.anomaly_validation
                    or {}
                )


                reason_codes = (
                    review_decision.get(
                        "reason_codes"
                    )
                    or []
                )


                issues = (
                    review_decision.get(
                        "issues"
                    )
                    or []
                )


                anomaly_issues = (
                    anomaly_validation.get(
                        "issues"
                    )
                    or []
                )


                documents.append(
                    {
                        "document_id":
                            document.id,

                        "analysis_id":
                            analysis.id,

                        "original_filename":
                            document.original_filename,

                        "content_type":
                            document.content_type,

                        "document_type":
                            document.document_type,

                        "processing_status":
                            document.processing_status,

                        "review_decision":
                            review_decision.get(
                                "decision"
                            ),

                        "review_priority":
                            review_decision.get(
                                "priority"
                            ),

                        "reason_codes":
                            reason_codes,

                        "review_issues":
                            issues,

                        "anomaly_issues":
                            anomaly_issues,

                        "created_at":
                            (
                                document.created_at
                                .isoformat()
                                if document.created_at
                                else None
                            ),

                        "analysis_created_at":
                            (
                                analysis.created_at
                                .isoformat()
                                if analysis.created_at
                                else None
                            ),
                    }
                )


            # ==============================================
            # API-READY RESPONSE
            # ==============================================

            return {
                "total":
                    len(documents),

                "filters": {
                    "priority":
                        normalized_priority,

                    "document_type":
                        normalized_document_type,
                },

                "documents":
                    documents,
            }