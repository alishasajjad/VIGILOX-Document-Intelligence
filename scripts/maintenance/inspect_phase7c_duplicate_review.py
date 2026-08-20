# ==========================================================
# PROJECT ROOT BOOTSTRAP
# PHASE 8.2
# ==========================================================
#
# This block exists so the script can be run directly:
#
#     python scripts\<area>\<script>.py
#
# Direct execution sets sys.path[0] to the script's OWN
# directory, so the backend and database packages would not
# be importable and the script would fail with:
#
#     ModuleNotFoundError: No module named 'backend'
#
# The canonical invocation is module form, which resolves the
# project root itself and needs no bootstrap:
#
#     python -m scripts.<area>.<script>
#
# Both forms are supported. This is the single sanctioned
# bootstrap pattern for scripts/ and it is documented in
# scripts/README.md. It is deliberately absent from
# backend/, database/ and tests/, which must never manipulate
# sys.path.
# ==========================================================

import sys

from pathlib import Path

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from sqlalchemy import (
    select,
)

from database.database import (  # noqa: E402
    SessionLocal,
)

from database.models import (  # noqa: E402
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


# ==========================================================
# TARGET DUPLICATE DOCUMENT
# ==========================================================

DOCUMENT_ID = (
    "792cda00-be58-4c91-a26e-6f5778750a74"
)


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.1 — DUPLICATE HUMAN REVIEW INSPECTION"
    )
    print("=" * 76)

    print()
    print(
        f"Document ID: {DOCUMENT_ID}"
    )


    with SessionLocal() as session:

        # ==================================================
        # DOCUMENT
        # ==================================================

        document = (
            session.get(
                DocumentModel,
                DOCUMENT_ID,
            )
        )


        if document is None:

            print()
            print(
                "[ERROR] Document does not exist."
            )

            return


        print()
        print("-" * 76)
        print("DOCUMENT")
        print("-" * 76)

        print(
            f"Filename:           "
            f"{document.original_filename}"
        )

        print(
            f"Content Type:       "
            f"{document.content_type}"
        )

        print(
            f"Document Type:      "
            f"{document.document_type}"
        )

        print(
            f"Processing Status:  "
            f"{document.processing_status}"
        )

        print(
            f"Created At:         "
            f"{document.created_at}"
        )


        # ==================================================
        # MACHINE ANALYSIS
        # ==================================================

        analysis_statement = (
            select(
                DocumentAnalysisModel
            )
            .where(
                DocumentAnalysisModel.document_id
                == DOCUMENT_ID
            )
        )


        analysis = (
            session
            .scalars(
                analysis_statement
            )
            .one_or_none()
        )


        print()
        print("-" * 76)
        print("MACHINE REVIEW")
        print("-" * 76)


        if analysis is None:

            print(
                "No document analysis found."
            )

        else:

            review_decision = (
                analysis.review_decision
                or {}
            )

            print(
                f"Decision:      "
                f"{review_decision.get('decision')}"
            )

            print(
                f"Priority:      "
                f"{review_decision.get('priority')}"
            )

            print(
                f"Reason Codes:  "
                f"{review_decision.get('reason_codes')}"
            )


        # ==================================================
        # HUMAN REVIEWS
        # ==================================================

        review_statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel.document_id
                == DOCUMENT_ID
            )
            .order_by(
                HumanReviewModel.reviewed_at.asc()
            )
        )


        reviews = (
            session
            .scalars(
                review_statement
            )
            .all()
        )


        print()
        print("-" * 76)
        print(
            f"HUMAN REVIEWS ({len(reviews)})"
        )
        print("-" * 76)


        for (
            index,
            review,
        ) in enumerate(
            reviews,
            start=1,
        ):

            print()
            print(
                f"Review #{index}"
            )

            print(
                f"Review ID:        "
                f"{review.id}"
            )

            print(
                f"Reviewer ID:      "
                f"{review.reviewer_id}"
            )

            print(
                f"Human Action:     "
                f"{review.human_action}"
            )

            print(
                f"Machine Decision: "
                f"{review.machine_decision}"
            )

            print(
                f"Machine Priority: "
                f"{review.machine_priority}"
            )

            print(
                f"Reason Codes:     "
                f"{review.machine_reason_codes}"
            )

            print(
                f"Corrections:      "
                f"{review.corrections}"
            )

            print(
                f"Notes:            "
                f"{review.notes}"
            )

            print(
                f"Reviewed At:      "
                f"{review.reviewed_at}"
            )


        # ==================================================
        # AUDIT EVENTS
        # ==================================================

        audit_statement = (
            select(
                AuditEventModel
            )
            .where(
                AuditEventModel.document_id
                == DOCUMENT_ID
            )
            .order_by(
                AuditEventModel.created_at.asc()
            )
        )


        audits = (
            session
            .scalars(
                audit_statement
            )
            .all()
        )


        print()
        print("-" * 76)
        print(
            f"AUDIT EVENTS ({len(audits)})"
        )
        print("-" * 76)


        for (
            index,
            event,
        ) in enumerate(
            audits,
            start=1,
        ):

            print()
            print(
                f"Audit #{index}"
            )

            print(
                f"Event ID:    "
                f"{event.id}"
            )

            print(
                f"Event Type:  "
                f"{event.event_type}"
            )

            print(
                f"Actor Type:  "
                f"{event.actor_type}"
            )

            print(
                f"Actor ID:    "
                f"{event.actor_id}"
            )

            print(
                f"Created At:  "
                f"{event.created_at}"
            )

            print(
                f"Details:     "
                f"{event.details}"
            )


        # ==================================================
        # SUMMARY
        # ==================================================

        human_audits = [
            event
            for event
            in audits
            if (
                event.event_type
                == "HUMAN_REVIEW"
            )
        ]


        print()
        print("=" * 76)
        print("SUMMARY")
        print("=" * 76)

        print(
            f"Human review rows:   "
            f"{len(reviews)}"
        )

        print(
            f"HUMAN_REVIEW audits: "
            f"{len(human_audits)}"
        )

        print()
        print(
            "[INFO] No records were modified."
        )


if __name__ == "__main__":

    main()