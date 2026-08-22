from database.database import (
    SessionLocal,
)

from database.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
    ReviewQueueRepository,
)

from database.summary_repositories import (
    DocumentSummaryRepository,
)

from backend.app.services.final_record_service import (
    FinalRecordService,
)

from backend.app.domain.classification import (
    describe_classification,
)

from backend.app.domain.duplicates import (
    describe_duplicate_source,
)

from backend.app.domain.findings import (
    normalize_findings,
)


class DocumentQueryService:

    # ======================================================
    # INITIALIZATION
    # PHASE 7C.3
    # ======================================================

    def __init__(
        self,
    ):

        self.final_record_service = (
            FinalRecordService()
        )


    # ======================================================
    # SERIALIZE HUMAN REVIEW
    # PHASE 7C.3
    # ======================================================

    def _serialize_human_review(
        self,
        review,
    ) -> dict | None:

        if review is None:

            return None


        return {
            "review_id":
                review.id,

            "document_id":
                review.document_id,

            "reviewer_id":
                review.reviewer_id,

            "machine_decision":
                review.machine_decision,

            "machine_priority":
                review.machine_priority,

            "machine_reason_codes":
                (
                    review.machine_reason_codes
                    or []
                ),

            "human_action":
                review.human_action,

            "corrections":
                (
                    review.corrections
                    or {}
                ),

            "notes":
                review.notes,

            "reviewed_at":
                (
                    review.reviewed_at
                    .isoformat()

                    if review.reviewed_at
                    else None
                ),
        }


    # ======================================================
    # GET COMPLETE STORED DOCUMENT
    # PHASE 7C.3
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

            human_review_repository = (
                HumanReviewRepository(
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
            # HUMAN REVIEW
            # PHASE 7C.3
            # ==============================================

            human_review = (
                human_review_repository
                .get_single_by_document_id(
                    document_id
                )
            )


            serialized_human_review = (
                self._serialize_human_review(
                    human_review
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

                "human_review":
                    serialized_human_review,

                # PHASE 10.2. Declared here so the key is
                # always present. A document with no analysis
                # row has not been classified at all, which
                # null says and an invented outcome would not.
                "classification":
                    None,

                # PHASE 10.3. Always present, so a caller
                # never has to distinguish "no duplicate
                # information" from "key missing".
                "duplicate":
                    None,

                # PHASE 10.6. The normalized findings view.
                # Always present. None means there is no
                # analysis to normalize, which is a different
                # statement from an empty findings list.
                "findings":
                    None,

                "final_record":
                    None,
            }


            # ==============================================
            # INCLUDE ANALYSIS
            # ==============================================

            if analysis is not None:

                result[
                    "analysis"
                ] = {

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

                    # PHASE 10.1. None means NOT ASSESSED,
                    # which is a different statement from
                    # "no problems found". The interface has
                    # to be able to tell them apart, so the
                    # null is passed through rather than
                    # defaulted to an empty assessment.
                    "quality":
                        analysis.quality,

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


                # ==========================================
                # CLASSIFICATION OUTCOME
                # PHASE 10.2
                # ==========================================
                #
                # Derived, not stored, from the two values
                # already in hand. The same function serves
                # the document list, so the list and the
                # detail page cannot disagree about whether a
                # document is supported.
                # ==========================================

                result[
                    "classification"
                ] = (
                    describe_classification(
                        document_type=(
                            (
                                analysis.extraction
                                or {}
                            ).get(
                                "document_type"
                            )
                        ),

                        machine_decision=(
                            (
                                analysis.review_decision
                                or {}
                            ).get(
                                "decision"
                            )
                        ),
                    )
                )


                # ==========================================
                # DUPLICATE SOURCE
                # PHASE 10.3
                # ==========================================
                #
                # One indexed lookup, on the detail path only.
                #
                # NOT on the documents list: that would be a
                # correlated query per row to answer a
                # question nobody asks of a table. The list
                # stays as it was.
                #
                # Derived rather than stored, because the
                # answer changes when a LATER upload of the
                # same bytes arrives. A stored copy would be
                # correct at write time and wrong afterwards,
                # and would need every sibling row rewritten
                # to fix.
                #
                # The fingerprint itself is not in the result.
                # ==========================================

                same_source = [
                    row.id
                    for row in (
                        document_repository
                        .documents_for_source(
                            document.source_sha256
                        )
                    )
                ]

                result[
                    "duplicate"
                ] = (
                    describe_duplicate_source(
                        document_id=(
                            document.id
                        ),
                        same_source_document_ids=(
                            same_source
                        ),
                    )
                )


                # ==========================================
                # NORMALIZED FINDINGS
                # PHASE 10.6
                # ==========================================
                #
                # Derived from payloads already loaded on the
                # analysis row. No extra query, no stored
                # column, and therefore no way for this view
                # to disagree with the raw payloads sitting
                # beside it in the same response.
                #
                # ADDED, NOT SUBSTITUTED. anomaly_validation,
                # evidence_flags, date_validation and quality
                # are all still returned exactly as before,
                # because existing consumers and tests read
                # them and a cleaner interface is not a reason
                # to break a working contract.
                #
                # classification and duplicate are NOT passed
                # in. An unsupported document is a
                # classification outcome and an exact
                # duplicate is a source-identity outcome;
                # neither is an anomaly, and flattening either
                # into this list would say something about the
                # document that is not true.
                # ==========================================

                result[
                    "findings"
                ] = (
                    normalize_findings(
                        anomaly_validation=(
                            analysis.anomaly_validation
                        ),

                        quality=(
                            analysis.quality
                        ),

                        evidence_flags=(
                            analysis.evidence_flags
                        ),

                        date_validation=(
                            analysis.date_validation
                        ),

                        review_decision=(
                            analysis.review_decision
                        ),
                    )
                )


                # ==========================================
                # FINAL / EFFECTIVE RECORD
                # PHASE 7C.3
                # ==========================================

                result[
                    "final_record"
                ] = (
                    self.final_record_service
                    .build(
                        extraction=(
                            analysis.extraction
                            or {}
                        ),

                        machine_review_decision=(
                            analysis.review_decision
                        ),

                        human_review=(
                            serialized_human_review
                        ),
                    )
                )


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
                    len(
                        events
                    ),

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
                    len(
                        documents
                    ),

                "filters": {
                    "priority":
                        normalized_priority,

                    "document_type":
                        normalized_document_type,
                },

                "documents":
                    documents,
            }


    # ======================================================
    # DOCUMENT SUMMARY MAPPING
    # PHASE 8.8A
    # ======================================================
    #
    # ONE mapping used by both the Documents list and the
    # Dashboard recent-documents section, so the two screens
    # can never describe the same document differently.
    #
    # final_state comes from FinalRecordService, the same
    # authority the document detail read path uses. It is not
    # recomputed here and not encoded in SQL.
    # ======================================================

    def _map_document_summary(
        self,
        row: dict,
    ) -> dict:

        machine_decision = (
            row.get(
                "machine_decision"
            )
        )


        human_action = (
            row.get(
                "human_action"
            )
        )


        # ==================================================
        # FINAL STATE
        # ==================================================
        #
        # A row can only fail here if the database holds an
        # unrecognised human action, which would be a data
        # integrity problem rather than a request problem.
        # The list degrades to None for that row instead of
        # failing the whole page.
        # ==================================================

        try:

            final_state = (
                FinalRecordService
                .resolve_final_status(
                    machine_decision=(
                        machine_decision
                    ),

                    human_action=(
                        human_action
                    ),
                )
            )


        except ValueError:

            final_state = None


        def isoformat(
            value,
        ):

            return (
                value.isoformat()
                if value is not None
                else None
            )


        return {
            "document_id":
                row.get(
                    "id"
                ),

            "filename":
                row.get(
                    "original_filename"
                ),

            "content_type":
                row.get(
                    "content_type"
                ),

            "document_type":
                row.get(
                    "document_type"
                ),

            "processing_status":
                row.get(
                    "processing_status"
                ),

            "machine_decision":
                machine_decision,

            "priority":
                row.get(
                    "priority"
                ),

            "final_state":
                final_state,

            # PHASE 10.2. Derived by the same function the
            # detail path uses. The list carries the outcome
            # rather than the whole block, because a row needs
            # to be filterable and badge-able, not to restate
            # the supported-type list once per row.
            "classification_outcome":
                (
                    describe_classification(
                        document_type=(
                            row.get(
                                "document_type"
                            )
                        ),

                        machine_decision=(
                            machine_decision
                        ),
                    )["outcome"]
                ),

            "human_review_action":
                human_action,

            "is_reviewed":
                human_action is not None,

            "expiry_date":
                row.get(
                    "expiry_date"
                ),

            "expiry_status":
                row.get(
                    "expiry_status"
                ),

            "reviewer_id":
                row.get(
                    "reviewer_id"
                ),

            "created_at":
                isoformat(
                    row.get(
                        "created_at"
                    )
                ),

            "processed_at":
                isoformat(
                    row.get(
                        "processed_at"
                    )
                ),

            "reviewed_at":
                isoformat(
                    row.get(
                        "reviewed_at"
                    )
                ),
        }


    # ======================================================
    # FINAL STATE FILTER TRANSLATION
    # ======================================================
    #
    # Turns a final_state into the neutral primitives the
    # repository understands, using FinalRecordService as the
    # authority. The repository never learns what a final
    # state means.
    # ======================================================

    @staticmethod
    def _final_state_filters(
        final_state: str | None,
    ) -> dict:

        if final_state is None:

            return {}


        spec = (
            FinalRecordService
            .final_status_query_spec(
                final_state
            )
        )


        filters = {}


        if spec["human_action"] is not None:

            filters[
                "human_action"
            ] = spec[
                "human_action"
            ]


        if spec["human_action_isnull"] is True:

            filters[
                "human_action_isnull"
            ] = True


        if spec["machine_decision"] is not None:

            filters[
                "machine_decision"
            ] = spec[
                "machine_decision"
            ]


        # PHASE 10.2. Passed through as-is, which is now a
        # tuple for PENDING_REVIEW. The repository turns a
        # collection into NOT IN; see _apply_filters.
        if spec["machine_decision_not"] is not None:

            filters[
                "machine_decision_not"
            ] = spec[
                "machine_decision_not"
            ]


        return filters


    # ======================================================
    # DOCUMENTS LIST
    # PHASE 8.8A
    # ======================================================

    def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        document_type: str | None = None,
        final_state: str | None = None,
        machine_decision: str | None = None,
        expiry_status: str | None = None,
        search: str | None = None,
        sort: str = "created_at",
        descending: bool = True,
    ) -> dict:

        filters = {
            "document_type":
                document_type,

            "expiry_status":
                expiry_status,

            "search":
                search,
        }


        # ==================================================
        # MACHINE DECISION
        # ==================================================
        #
        # An explicit machine_decision filter is combined
        # with any final_state filter rather than replacing
        # it, so the two remain independent controls.
        # ==================================================

        if machine_decision is not None:

            filters[
                "machine_decision"
            ] = machine_decision


        filters.update(
            self._final_state_filters(
                final_state
            )
        )


        offset = (
            (
                page - 1
            )
            * page_size
        )


        with SessionLocal() as session:

            repository = (
                DocumentSummaryRepository(
                    session
                )
            )


            # ==========================================
            # Two queries total: one count, one bounded
            # page. No per-row follow-up query.
            # ==========================================

            total = (
                repository.count_documents(
                    **filters
                )
            )


            rows = (
                repository.list_documents(
                    limit=(
                        page_size
                    ),

                    offset=(
                        offset
                    ),

                    sort=(
                        sort
                    ),

                    descending=(
                        descending
                    ),

                    **filters,
                )
            )


        items = [
            self._map_document_summary(
                row
            )
            for row in rows
        ]


        total_pages = (
            (
                total
                + page_size
                - 1
            )
            // page_size
            if page_size
            else 0
        )


        return {
            "items":
                items,

            "total":
                total,

            "page":
                page,

            "page_size":
                page_size,

            "total_pages":
                total_pages,
        }


    # ======================================================
    # DASHBOARD SUMMARY
    # PHASE 8.6A
    # ======================================================
    #
    # Every number here is a SQL aggregate over persisted
    # data. Nothing is estimated, averaged or scored.
    #
    # Deliberately NOT included, because no authoritative
    # definition exists in this codebase:
    #
    #     overall / average confidence
    #     accuracy or success rate
    #     risk score
    #     processing SLA or throughput
    #
    # field_confidence is per-field only, so an "overall
    # confidence" would be an invented statistic.
    # ======================================================

    def get_dashboard_summary(
        self,
        *,
        recent_limit: int = 5,
    ) -> dict:

        with SessionLocal() as session:

            repository = (
                DocumentSummaryRepository(
                    session
                )
            )


            total_documents = (
                repository.count_all_documents()
            )


            by_decision = (
                repository
                .count_by_machine_decision()
            )


            by_action = (
                repository
                .count_by_human_action()
            )


            by_expiry = (
                repository
                .count_by_expiry_status()
            )


            pending_by_priority = (
                repository
                .count_pending_review_by_priority()
            )


            recent_rows = (
                repository.list_documents(
                    limit=(
                        recent_limit
                    ),

                    offset=0,

                    sort="created_at",

                    descending=True,
                )
            )


        # ==================================================
        # REVIEW STATE COUNTS
        # ==================================================
        #
        # pending_review is the sum of the per-priority
        # pending counts, which come from exactly the
        # ReviewQueueRepository definition. It therefore
        # agrees with GET /api/v1/reviews/queue by
        # construction rather than by coincidence.
        # ==================================================

        pending_review = (
            sum(
                pending_by_priority.values()
            )
        )


        return {
            "total_documents":
                total_documents,

            "review": {
                "pending_review":
                    pending_review,

                "auto_accepted":
                    by_decision.get(
                        "AUTO_ACCEPT",
                        0,
                    ),

                "review_required":
                    by_decision.get(
                        "REVIEW_REQUIRED",
                        0,
                    ),

                # PHASE 10.2. Deliberately not added into
                # pending_review or review_required: nothing
                # is queued for a reviewer here, and rolling
                # it in would overstate outstanding work.
                "unsupported":
                    by_decision.get(
                        "UNSUPPORTED_DOCUMENT",
                        0,
                    ),

                "approved":
                    by_action.get(
                        "APPROVE",
                        0,
                    ),

                "corrected":
                    by_action.get(
                        "CORRECT",
                        0,
                    ),

                "rejected":
                    by_action.get(
                        "REJECT",
                        0,
                    ),
            },

            # Keys mirror date_validation.expiry.status
            # exactly. No new threshold is introduced.
            "expiry": {
                "expired":
                    by_expiry.get(
                        "EXPIRED",
                        0,
                    ),

                "expires_today":
                    by_expiry.get(
                        "EXPIRES_TODAY",
                        0,
                    ),

                "expiring_soon":
                    by_expiry.get(
                        "EXPIRING_SOON",
                        0,
                    ),

                "active":
                    by_expiry.get(
                        "ACTIVE",
                        0,
                    ),

                "not_available":
                    by_expiry.get(
                        "NOT_AVAILABLE",
                        0,
                    ),
            },

            "pending_review_priority": {
                "high":
                    pending_by_priority.get(
                        "HIGH",
                        0,
                    ),

                "medium":
                    pending_by_priority.get(
                        "MEDIUM",
                        0,
                    ),

                "low":
                    pending_by_priority.get(
                        "LOW",
                        0,
                    ),
            },

            "recent_documents": [
                self._map_document_summary(
                    row
                )
                for row in recent_rows
            ],
        }
