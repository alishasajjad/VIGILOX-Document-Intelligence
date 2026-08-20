from sqlalchemy import (
    func,
    select,
)

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    HumanReviewModel,
)


def main():

    print()
    print(
        "=" * 72
    )

    print(
        "PHASE 7C.1 — EXISTING "
        "DUPLICATE HUMAN REVIEW CHECK"
    )

    print(
        "=" * 72
    )


    with SessionLocal() as session:

        statement = (
            select(
                HumanReviewModel.document_id,
                func.count(
                    HumanReviewModel.id
                ).label(
                    "review_count"
                ),
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


        duplicates = (
            session
            .execute(
                statement
            )
            .all()
        )


        if not duplicates:

            print()
            print(
                "[PASS] No duplicate "
                "human reviews found."
            )

            print()
            print(
                "Database is safe for "
                "UNIQUE(document_id)."
            )

            return


        print()
        print(
            "[WARNING] Duplicate "
            "human reviews found:"
        )

        print()


        for (
            document_id,
            review_count,
        ) in duplicates:

            print(
                f"{document_id} "
                f"→ {review_count} reviews"
            )


        print()
        print(
            "[BLOCKED] Do not add the "
            "UNIQUE constraint yet."
        )


if __name__ == "__main__":

    main()