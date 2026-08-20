from sqlalchemy import (
    inspect,
    text,
)

from database.database import (
    Base,
    engine,
)

# Import models so that SQLAlchemy
# registers all tables in Base.metadata.
from database.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


print()
print("=" * 70)
print(
    "PHASE 6B — DATABASE FOUNDATION TEST"
)
print("=" * 70)


# ==========================================================
# TEST 1 — DATABASE CONNECTION
# ==========================================================

with engine.connect() as connection:

    result = connection.execute(
        text("SELECT 1")
    )

    value = result.scalar_one()


assert value == 1

print(
    "Database connection: OK"
)


# ==========================================================
# TEST 2 — CREATE TABLES
# ==========================================================

Base.metadata.create_all(
    bind=engine
)

print(
    "Table creation: OK"
)


# ==========================================================
# TEST 3 — VERIFY TABLES IN POSTGRESQL
# ==========================================================

inspector = inspect(
    engine
)

actual_tables = set(
    inspector.get_table_names()
)


expected_tables = {
    "documents",
    "document_analyses",
    "human_reviews",
    "audit_events",
}


print(
    "Database tables:",
    sorted(actual_tables),
)


missing_tables = (
    expected_tables
    - actual_tables
)


assert not missing_tables, (
    f"Missing tables: "
    f"{sorted(missing_tables)}"
)


# ==========================================================
# SUCCESS
# ==========================================================

print()
print(
    "[PASS] PostgreSQL database "
    "foundation is working."
)