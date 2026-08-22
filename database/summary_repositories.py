from sqlalchemy import (
    case,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from database.models import (
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


# ==========================================================
# DOCUMENT SUMMARY REPOSITORY
# PHASE 8.6A / 8.8A
# ==========================================================
#
# Powers the Documents list and the Dashboard summary.
#
# It lives beside repositories.py rather than inside it
# because that file is already ~850 lines and owns the write
# path. This module owns read-only summary and aggregate
# queries.
#
#
# SCOPE RULE
# ----------------------------------------------------------
#
# Summary columns ONLY. This repository never selects
# extraction, ocr_lines, evidence_flags, field_confidence or
# anomaly_validation. Those are large JSONB payloads and a
# list screen has no use for them. Detail endpoints remain
# responsible for that data.
#
#
# NO BUSINESS RULES HERE
# ----------------------------------------------------------
#
# Final-state semantics are owned by FinalRecordService. This
# repository accepts neutral primitives:
#
#     machine_decision / machine_decision_not
#     human_action / human_action_isnull
#
# and turns them into SQL. It does not know what "CORRECTED"
# means, so the list view and the detail view cannot drift
# apart.
#
#
# QUERY SHAPE
# ----------------------------------------------------------
#
# One bounded list query plus one count query. Two LEFT OUTER
# JOINs, so a document with no analysis or no review still
# appears, and there is no per-row follow-up query.
# ==========================================================


class DocumentSummaryRepository:

    # ======================================================
    # SORT WHITELIST
    # ======================================================
    #
    # Client sort keys never reach SQL. They are looked up
    # here, so an arbitrary column name cannot be injected
    # through the URL.
    # ======================================================

    SORTABLE = (
        "created_at",
        "filename",
        "document_type",
        "expiry_date",
        "priority",
    )


    def __init__(
        self,
        session: Session,
    ):
        self.session = session


    # ======================================================
    # JSONB EXPRESSIONS
    # ======================================================

    @staticmethod
    def decision_expression():

        return (
            DocumentAnalysisModel
            .review_decision[
                "decision"
            ]
            .as_string()
        )


    @staticmethod
    def priority_expression():

        return (
            DocumentAnalysisModel
            .review_decision[
                "priority"
            ]
            .as_string()
        )


    @staticmethod
    def expiry_status_expression():

        return (
            DocumentAnalysisModel
            .date_validation[
                "expiry"
            ][
                "status"
            ]
            .as_string()
        )


    @staticmethod
    def expiry_value_expression():

        return (
            DocumentAnalysisModel
            .date_validation[
                "expiry"
            ][
                "value"
            ]
            .as_string()
        )


    @classmethod
    def priority_order_expression(
        cls,
    ):

        # ==================================================
        # Identical ordering to ReviewQueueRepository:
        # HIGH, MEDIUM, LOW, then anything else.
        #
        # Deliberately consistent, so sorting Documents by
        # priority matches the Review Queue.
        # ==================================================

        priority = (
            cls.priority_expression()
        )


        return case(

            (
                priority == "HIGH",
                1,
            ),

            (
                priority == "MEDIUM",
                2,
            ),

            (
                priority == "LOW",
                3,
            ),

            else_=4,
        )


    # ======================================================
    # JOINS
    # ======================================================

    @staticmethod
    def _base_joins(
        statement,
    ):

        # ==================================================
        # LEFT OUTER JOINs.
        #
        # A document must still be listed when it has no
        # analysis row, or no human review yet.
        # ==================================================

        return (
            statement
            .outerjoin(
                DocumentAnalysisModel,
                DocumentAnalysisModel.document_id
                == DocumentModel.id,
            )
            .outerjoin(
                HumanReviewModel,
                HumanReviewModel.document_id
                == DocumentModel.id,
            )
        )


    # ======================================================
    # FILTERS
    # ======================================================

    @classmethod
    def _apply_filters(
        cls,
        statement,
        *,
        document_type=None,
        machine_decision=None,
        machine_decision_not=None,
        expiry_status=None,
        human_action=None,
        human_action_isnull=None,
        search=None,
    ):

        if document_type is not None:

            statement = (
                statement.where(
                    DocumentModel.document_type
                    == document_type
                )
            )


        if machine_decision is not None:

            statement = (
                statement.where(
                    cls.decision_expression()
                    == machine_decision
                )
            )


        if machine_decision_not is not None:

            # ==============================================
            # "Everything except these decisions."
            #
            # A document with no analysis row, or with no
            # recorded decision, is not auto accepted and so
            # belongs in this set. A bare != would silently
            # drop those rows, because a NULL comparison is
            # unknown rather than true.
            #
            # PHASE 10.2 made this accept a COLLECTION as well
            # as a single value, because PENDING_REVIEW now
            # excludes two decisions: AUTO_ACCEPT and
            # UNSUPPORTED_DOCUMENT.
            #
            # A bare string is still accepted, and is treated
            # as a one-element set rather than iterated as
            # characters -- a str is iterable, so accepting one
            # without this check would build a NOT IN over the
            # letters of the decision name and match nothing.
            # ==============================================

            if isinstance(
                machine_decision_not,
                str,
            ):

                excluded = (
                    machine_decision_not,
                )

            else:

                excluded = tuple(
                    machine_decision_not
                )


            decision = (
                cls.decision_expression()
            )


            if excluded:

                statement = (
                    statement.where(
                        or_(
                            decision.not_in(
                                excluded
                            ),

                            decision.is_(
                                None
                            ),
                        )
                    )
                )


        if expiry_status is not None:

            statement = (
                statement.where(
                    cls.expiry_status_expression()
                    == expiry_status
                )
            )


        if human_action is not None:

            statement = (
                statement.where(
                    HumanReviewModel.human_action
                    == human_action
                )
            )


        if human_action_isnull is True:

            statement = (
                statement.where(
                    HumanReviewModel.human_action
                    .is_(
                        None
                    )
                )
            )


        if human_action_isnull is False:

            statement = (
                statement.where(
                    HumanReviewModel.human_action
                    .is_not(
                        None
                    )
                )
            )


        # ==================================================
        # SEARCH
        # ==================================================
        #
        # Deliberately narrow: filename and document id only.
        #
        # OCR text and extracted values are NOT searched.
        # They are personal data, an unbounded ILIKE over
        # JSONB would not use an index, and it would turn a
        # summary endpoint into a content-disclosure surface.
        #
        # Bound through SQLAlchemy. Never string-concatenated.
        # ==================================================

        if search:

            pattern = (
                "%"
                + str(
                    search
                ).strip()
                + "%"
            )


            statement = (
                statement.where(
                    or_(
                        DocumentModel
                        .original_filename
                        .ilike(
                            pattern
                        ),

                        DocumentModel
                        .id
                        .ilike(
                            pattern
                        ),
                    )
                )
            )


        return statement


    # ======================================================
    # COUNT
    # ======================================================

    def count_documents(
        self,
        **filters,
    ) -> int:

        statement = (
            self._base_joins(
                select(
                    func.count(
                        DocumentModel.id
                    )
                )
                .select_from(
                    DocumentModel
                )
            )
        )


        statement = (
            self._apply_filters(
                statement,
                **filters,
            )
        )


        return (
            self.session.scalar(
                statement
            )
            or 0
        )


    # ======================================================
    # LIST
    # ======================================================

    def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        sort: str = "created_at",
        descending: bool = True,
        **filters,
    ) -> list[dict]:

        if sort not in self.SORTABLE:

            raise ValueError(
                (
                    "Unsupported sort field: "
                    f"{sort}"
                )
            )


        expiry_status = (
            self.expiry_status_expression()
        )


        expiry_value = (
            self.expiry_value_expression()
        )


        # ==================================================
        # SUMMARY COLUMNS ONLY
        # ==================================================

        statement = (
            self._base_joins(
                select(
                    DocumentModel.id,
                    DocumentModel.original_filename,
                    DocumentModel.content_type,
                    DocumentModel.document_type,
                    DocumentModel.processing_status,
                    DocumentModel.created_at,

                    DocumentAnalysisModel.id
                    .label(
                        "analysis_id"
                    ),

                    DocumentAnalysisModel.created_at
                    .label(
                        "processed_at"
                    ),

                    self.decision_expression()
                    .label(
                        "machine_decision"
                    ),

                    self.priority_expression()
                    .label(
                        "priority"
                    ),

                    expiry_status
                    .label(
                        "expiry_status"
                    ),

                    expiry_value
                    .label(
                        "expiry_date"
                    ),

                    HumanReviewModel.human_action
                    .label(
                        "human_action"
                    ),

                    HumanReviewModel.reviewed_at
                    .label(
                        "reviewed_at"
                    ),

                    HumanReviewModel.reviewer_id
                    .label(
                        "reviewer_id"
                    ),
                )
                .select_from(
                    DocumentModel
                )
            )
        )


        statement = (
            self._apply_filters(
                statement,
                **filters,
            )
        )


        # ==================================================
        # ORDERING
        # ==================================================

        sort_expressions = {
            "created_at":
                DocumentModel.created_at,

            "filename":
                DocumentModel.original_filename,

            "document_type":
                DocumentModel.document_type,

            "expiry_date":
                expiry_value,

            "priority":
                self.priority_order_expression(),
        }


        primary = (
            sort_expressions[
                sort
            ]
        )


        # ==================================================
        # DETERMINISTIC ORDERING
        # ==================================================
        #
        # The primary key is always the final tiebreak, so a
        # page boundary can never duplicate or skip a row when
        # the sorted column holds duplicate values.
        # ==================================================

        statement = (
            statement
            .order_by(
                primary.desc()
                if descending
                else primary.asc(),

                DocumentModel.id.asc(),
            )
            .limit(
                limit
            )
            .offset(
                offset
            )
        )


        rows = (
            self.session
            .execute(
                statement
            )
            .mappings()
            .all()
        )


        return [
            dict(
                row
            )
            for row in rows
        ]


    # ======================================================
    # DASHBOARD AGGREGATES
    # ======================================================
    #
    # Every count below is computed by PostgreSQL. Rows are
    # never pulled into Python to be counted.
    # ======================================================

    def count_all_documents(
        self,
    ) -> int:

        return (
            self.session.scalar(
                select(
                    func.count(
                        DocumentModel.id
                    )
                )
            )
            or 0
        )


    def count_by_machine_decision(
        self,
    ) -> dict:

        decision = (
            self.decision_expression()
        )


        rows = (
            self.session
            .execute(
                select(
                    decision,
                    func.count(
                        DocumentAnalysisModel.id
                    ),
                )
                .group_by(
                    decision
                )
            )
            .all()
        )


        return {
            (
                row[0]
                or "UNKNOWN"
            ): row[1]
            for row in rows
        }


    def count_by_human_action(
        self,
    ) -> dict:

        rows = (
            self.session
            .execute(
                select(
                    HumanReviewModel.human_action,
                    func.count(
                        HumanReviewModel.id
                    ),
                )
                .group_by(
                    HumanReviewModel.human_action
                )
            )
            .all()
        )


        return {
            (
                row[0]
                or "UNKNOWN"
            ): row[1]
            for row in rows
        }


    def count_by_expiry_status(
        self,
    ) -> dict:

        status = (
            self.expiry_status_expression()
        )


        rows = (
            self.session
            .execute(
                select(
                    status,
                    func.count(
                        DocumentAnalysisModel.id
                    ),
                )
                .group_by(
                    status
                )
            )
            .all()
        )


        return {
            (
                row[0]
                or "UNKNOWN"
            ): row[1]
            for row in rows
        }


    def count_pending_review_by_priority(
        self,
    ) -> dict:

        # ==================================================
        # PENDING REVIEW
        # ==================================================
        #
        # Uses exactly the ReviewQueueRepository definition:
        #
        #     decision = REVIEW_REQUIRED
        #     AND no human review exists
        #
        # so a dashboard count cannot disagree with
        # GET /api/v1/reviews/queue.
        # ==================================================

        priority = (
            self.priority_expression()
        )


        human_review_exists = (
            exists()
            .where(
                HumanReviewModel.document_id
                == DocumentModel.id
            )
        )


        rows = (
            self.session
            .execute(
                select(
                    priority,
                    func.count(
                        DocumentModel.id
                    ),
                )
                .select_from(
                    DocumentModel
                )
                .join(
                    DocumentAnalysisModel,
                    DocumentAnalysisModel.document_id
                    == DocumentModel.id,
                )
                .where(
                    self.decision_expression()
                    == "REVIEW_REQUIRED"
                )
                .where(
                    ~human_review_exists
                )
                .group_by(
                    priority
                )
            )
            .all()
        )


        return {
            (
                row[0]
                or "UNKNOWN"
            ): row[1]
            for row in rows
        }
