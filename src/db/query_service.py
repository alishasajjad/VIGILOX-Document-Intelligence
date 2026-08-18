from src.db.database import (
    SessionLocal,
)

from src.db.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
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