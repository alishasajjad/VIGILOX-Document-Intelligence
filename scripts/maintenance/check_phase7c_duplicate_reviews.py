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
    func,
    select,
)

from database.database import (  # noqa: E402
    SessionLocal,
)

from database.models import (  # noqa: E402
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