import json

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

from sqlalchemy import (
    func,
    select,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    HumanReviewModel,
)


# ==========================================================
# BACKUP
# ==========================================================

BACKUP_DIRECTORY = Path(
    "output"
) / "phase7c_migrations"


# ==========================================================
# SERIALIZE REVIEW
# ==========================================================

def serialize_review(
    review: HumanReviewModel,
) -> dict:

    return {
        "id":
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
            review.machine_reason_codes,

        "human_action":
            review.human_action,

        "corrections":
            review.corrections,

        "notes":
            review.notes,

        "reviewed_at":
            (
                review.reviewed_at.isoformat()
                if review.reviewed_at
                else None
            ),
    }


# ==========================================================
# FIND DUPLICATE DOCUMENT IDS
# ==========================================================

def find_duplicate_document_ids(
    session,
) -> list[str]:

    statement = (
        select(
            HumanReviewModel.document_id,
        )
        .group_by(
            HumanReviewModel.document_id
        )
        .having(
            func.count(
                HumanReviewModel.id
            )
            > 1
        )
    )


    return list(
        session.scalars(
            statement
        ).all()
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.1 — DUPLICATE HUMAN "
        "REVIEW MIGRATION"
    )
    print("=" * 76)


    BACKUP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )


    with SessionLocal() as session:

        duplicate_document_ids = (
            find_duplicate_document_ids(
                session
            )
        )


        if not duplicate_document_ids:

            print()
            print(
                "[PASS] No duplicate human "
                "reviews require migration."
            )

            return


        # ==================================================
        # COLLECT BACKUP BEFORE MODIFYING DATABASE
        # ==================================================

        backup_data = {
            "migration":
                "phase_7c_1_duplicate_reviews",

            "created_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "policy":
                (
                    "Latest reviewed_at record retained. "
                    "Older human_reviews rows removed. "
                    "Audit events are not modified."
                ),

            "documents":
                [],
        }


        migration_plan = []


        for document_id in (
            duplicate_document_ids
        ):

            statement = (
                select(
                    HumanReviewModel
                )
                .where(
                    HumanReviewModel.document_id
                    == document_id
                )
                .order_by(
                    HumanReviewModel
                    .reviewed_at
                    .asc(),

                    HumanReviewModel
                    .id
                    .asc(),
                )
            )


            reviews = list(
                session.scalars(
                    statement
                ).all()
            )


            # Latest review becomes canonical.
            keep_review = (
                reviews[
                    -1
                ]
            )


            remove_reviews = (
                reviews[
                    :-1
                ]
            )


            backup_data[
                "documents"
            ].append(
                {
                    "document_id":
                        document_id,

                    "all_reviews": [
                        serialize_review(
                            review
                        )
                        for review
                        in reviews
                    ],

                    "retained_review_id":
                        keep_review.id,

                    "removed_review_ids": [
                        review.id
                        for review
                        in remove_reviews
                    ],
                }
            )


            migration_plan.append(
                (
                    document_id,
                    keep_review,
                    remove_reviews,
                )
            )


        # ==================================================
        # WRITE BACKUP BEFORE DELETE
        # ==================================================

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )


        backup_path = (
            BACKUP_DIRECTORY
            / (
                "human_review_duplicates_"
                f"{timestamp}.json"
            )
        )


        backup_path.write_text(
            json.dumps(
                backup_data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


        print()
        print(
            "[PASS] Backup created:"
        )

        print(
            backup_path
        )


        # ==================================================
        # DISPLAY MIGRATION PLAN
        # ==================================================

        print()
        print("-" * 76)
        print(
            "MIGRATION PLAN"
        )
        print("-" * 76)


        for (
            document_id,
            keep_review,
            remove_reviews,
        ) in migration_plan:

            print()
            print(
                f"Document: {document_id}"
            )

            print(
                "KEEP:"
            )

            print(
                f"  Review ID: "
                f"{keep_review.id}"
            )

            print(
                f"  Reviewer:  "
                f"{keep_review.reviewer_id}"
            )

            print(
                f"  Action:    "
                f"{keep_review.human_action}"
            )

            print(
                f"  Reviewed:  "
                f"{keep_review.reviewed_at}"
            )


            print(
                "REMOVE:"
            )


            for review in (
                remove_reviews
            ):

                print(
                    f"  {review.id} "
                    f"| {review.reviewer_id} "
                    f"| {review.human_action} "
                    f"| {review.reviewed_at}"
                )


        # ==================================================
        # DELETE ONLY SUPERSEDED HUMAN_REVIEW ROWS
        # ==================================================
        #
        # IMPORTANT:
        #
        # AuditEventModel is intentionally untouched.
        #
        # Therefore previous review actions remain visible
        # in the immutable audit trail.
        # ==================================================

        removed_count = 0


        for (
            _document_id,
            _keep_review,
            remove_reviews,
        ) in migration_plan:

            for review in (
                remove_reviews
            ):

                session.delete(
                    review
                )


                removed_count += 1


        session.commit()


        # ==================================================
        # VERIFY
        # ==================================================

        remaining_duplicates = (
            find_duplicate_document_ids(
                session
            )
        )


        if remaining_duplicates:

            raise RuntimeError(
                (
                    "Migration committed but duplicate "
                    "human review rows still exist: "
                    f"{remaining_duplicates}"
                )
            )


        print()
        print("=" * 76)
        print(
            "[PASS] DUPLICATE HUMAN REVIEW "
            "MIGRATION COMPLETED"
        )
        print("=" * 76)

        print()
        print(
            f"Removed superseded rows: "
            f"{removed_count}"
        )

        print(
            "Historical audit events: untouched"
        )

        print(
            "Current human review state: "
            "one canonical review per document"
        )


if __name__ == "__main__":

    main()