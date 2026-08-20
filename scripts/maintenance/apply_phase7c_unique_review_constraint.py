from datetime import (
    datetime,
    timezone,
)
from uuid import uuid4

from sqlalchemy import (
    inspect,
    select,
    text,
)

from sqlalchemy.exc import (
    IntegrityError,
)

from database.database import (
    SessionLocal,
    engine,
)

from database.models import (
    HumanReviewModel,
)


# ==========================================================
# CONFIGURATION
# ==========================================================

CONSTRAINT_NAME = (
    "uq_human_reviews_document_id"
)

TABLE_NAME = (
    "human_reviews"
)


# ==========================================================
# CHECK DATABASE CONSTRAINT
# ==========================================================

def constraint_exists() -> bool:

    inspector = inspect(
        engine
    )


    unique_constraints = (
        inspector
        .get_unique_constraints(
            TABLE_NAME
        )
    )


    for constraint in (
        unique_constraints
    ):

        if (
            constraint.get(
                "name"
            )
            == CONSTRAINT_NAME
            and constraint.get(
                "column_names"
            )
            == [
                "document_id"
            ]
        ):

            return True


    return False


# ==========================================================
# VERIFY DATABASE REJECTS DUPLICATE
# ==========================================================

def verify_database_enforcement():

    print()
    print("-" * 76)
    print(
        "DATABASE ENFORCEMENT TEST"
    )
    print("-" * 76)


    with SessionLocal() as session:

        statement = (
            select(
                HumanReviewModel
            )
            .order_by(
                HumanReviewModel
                .reviewed_at
                .asc()
            )
            .limit(
                1
            )
        )


        existing_review = (
            session
            .scalars(
                statement
            )
            .first()
        )


        if existing_review is None:

            raise RuntimeError(
                (
                    "No existing human review "
                    "is available for the "
                    "database uniqueness test."
                )
            )


        duplicate_review = (
            HumanReviewModel(

                id=str(
                    uuid4()
                ),

                document_id=(
                    existing_review
                    .document_id
                ),

                reviewer_id=(
                    "phase7c-constraint-test"
                ),

                machine_decision=(
                    existing_review
                    .machine_decision
                ),

                machine_priority=(
                    existing_review
                    .machine_priority
                ),

                machine_reason_codes=(
                    list(
                        existing_review
                        .machine_reason_codes
                        or []
                    )
                ),

                human_action=(
                    "APPROVE"
                ),

                corrections={},

                notes=(
                    "Phase 7C.1 database "
                    "constraint verification."
                ),

                reviewed_at=(
                    datetime.now(
                        timezone.utc
                    )
                ),
            )
        )


        session.add(
            duplicate_review
        )


        try:

            session.flush()

        except IntegrityError:

            session.rollback()

            print(
                "[PASS] PostgreSQL rejected "
                "a second human review for "
                "the same document."
            )

            return


        session.rollback()


        raise AssertionError(
            (
                "PostgreSQL accepted a "
                "duplicate human review. "
                "The UNIQUE constraint is "
                "not enforcing correctly."
            )
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.1 — APPLY UNIQUE "
        "HUMAN REVIEW CONSTRAINT"
    )
    print("=" * 76)


    # ======================================================
    # DATABASE MIGRATION TRANSACTION
    # ======================================================

    with engine.begin() as connection:

        # ==================================================
        # VERIFY TABLE EXISTS
        # ==================================================

        table_exists = (
            connection.execute(
                text(
                    """
                    SELECT
                        to_regclass(
                            current_schema()
                            || '.human_reviews'
                        )
                    """
                )
            )
            .scalar_one_or_none()
        )


        if table_exists is None:

            raise RuntimeError(
                (
                    "Table human_reviews "
                    "does not exist."
                )
            )


        print()
        print(
            "[PASS] human_reviews "
            "table found"
        )


        # ==================================================
        # LOCK TABLE DURING MIGRATION
        # ==================================================
        #
        # Prevent another transaction from inserting a new
        # human review between our duplicate check and
        # UNIQUE constraint creation.
        # ==================================================

        connection.execute(
            text(
                """
                LOCK TABLE human_reviews
                IN SHARE ROW EXCLUSIVE MODE
                """
            )
        )


        print(
            "[PASS] human_reviews table "
            "locked for migration"
        )


        # ==================================================
        # FINAL DUPLICATE SAFETY CHECK
        # ==================================================

        duplicate_rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        document_id,
                        COUNT(*) AS review_count

                    FROM human_reviews

                    GROUP BY
                        document_id

                    HAVING
                        COUNT(*) > 1
                    """
                )
            )
            .mappings()
            .all()
        )


        if duplicate_rows:

            print()
            print(
                "[BLOCKED] Duplicate "
                "human reviews still exist:"
            )


            for row in (
                duplicate_rows
            ):

                print(
                    (
                        f"{row['document_id']} "
                        f"→ "
                        f"{row['review_count']} reviews"
                    )
                )


            raise RuntimeError(
                (
                    "Cannot create UNIQUE "
                    "constraint while duplicate "
                    "human review rows exist."
                )
            )


        print(
            "[PASS] No duplicate "
            "human review rows found"
        )


        # ==================================================
        # CHECK WHETHER CONSTRAINT ALREADY EXISTS
        # ==================================================

        existing_constraint = (
            connection.execute(
                text(
                    """
                    SELECT
                        pg_get_constraintdef(
                            c.oid
                        ) AS definition

                    FROM pg_constraint AS c

                    JOIN pg_class AS t
                        ON t.oid = c.conrelid

                    JOIN pg_namespace AS n
                        ON n.oid = t.relnamespace

                    WHERE
                        t.relname = 'human_reviews'
                        AND
                        n.nspname = current_schema()
                        AND
                        c.conname = :constraint_name
                        AND
                        c.contype = 'u'
                    """
                ),

                {
                    "constraint_name":
                        CONSTRAINT_NAME
                },
            )
            .mappings()
            .first()
        )


        if existing_constraint is not None:

            print(
                "[INFO] UNIQUE constraint "
                "already exists."
            )

            print(
                (
                    "Definition: "
                    f"{existing_constraint['definition']}"
                )
            )

        else:

            # ==============================================
            # APPLY ACTUAL POSTGRESQL CONSTRAINT
            # ==============================================

            connection.execute(
                text(
                    """
                    ALTER TABLE human_reviews

                    ADD CONSTRAINT
                        uq_human_reviews_document_id

                    UNIQUE (
                        document_id
                    )
                    """
                )
            )


            print(
                "[PASS] PostgreSQL UNIQUE "
                "constraint created"
            )


    # ======================================================
    # TRANSACTION COMMITTED HERE
    # ======================================================

    print()
    print(
        "[PASS] Constraint migration "
        "transaction committed"
    )


    # ======================================================
    # VERIFY USING SQLALCHEMY INSPECTOR
    # ======================================================

    if not constraint_exists():

        raise AssertionError(
            (
                "Constraint migration completed "
                "but SQLAlchemy could not verify "
                "uq_human_reviews_document_id."
            )
        )


    print(
        "[PASS] SQLAlchemy verified "
        "uq_human_reviews_document_id"
    )


    # ======================================================
    # ACTUAL DATABASE ENFORCEMENT TEST
    # ======================================================

    verify_database_enforcement()


    # ======================================================
    # FINAL
    # ======================================================

    print()
    print("=" * 76)
    print(
        "[PASS] PHASE 7C.1 POSTGRESQL "
        "UNIQUE CONSTRAINT ACTIVE"
    )
    print("=" * 76)

    print()
    print(
        "Rule now enforced:"
    )

    print(
        "One document → maximum one "
        "human_reviews row."
    )


if __name__ == "__main__":

    main()