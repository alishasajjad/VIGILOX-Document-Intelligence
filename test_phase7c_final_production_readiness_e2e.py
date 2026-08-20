import io
import json
import logging
import tempfile

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    func,
    select,
)

from src.api.main import (
    app,
)

from src.api.request_context import (
    REQUEST_ID_HEADER,
)

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.query_service import (
    DocumentQueryService,
)

from src.document_deletion_service import (
    DocumentDeletionService,
)

from src.document_storage_service import (
    DocumentStorageService,
)

from src.human_review_service import (
    HumanReviewService,
)

from src.operational_logging import (
    LOGGER_ROOT_NAME,
    StructuredJSONFormatter,
)

from src.readiness_service import (
    REASON_DATABASE_UNAVAILABLE,
    ReadinessCheckFailed,
    ReadinessService,
)

from src.reviewer_identity_service import (
    ReviewerIdentityService,
)

from src.storage_integrity_service import (
    StorageIntegrityService,
)

from src.storage_reconciliation_service import (
    StorageReconciliationService,
)


# ==========================================================
# PHASE 7C.8
# FINAL PRODUCTION-READINESS END-TO-END TEST
# ==========================================================
#
# PURPOSE
# ----------------------------------------------------------
#
# This is the final gate of Phase 7C.
#
# It does NOT reimplement the unit and component tests that
# already cover each service in isolation. It proves that the
# already-tested parts work together as one production
# system:
#
#     liveness / readiness
#     bounded upload handling
#     temporary file lifecycle
#     pipeline integration
#     PostgreSQL persistence
#     permanent source storage
#     explicit OCR evidence provenance
#     review queue
#     trusted reviewer identity
#     human CORRECT + final effective record
#     machine extraction immutability
#     duplicate review protection
#     request correlation IDs
#     structured operational logging
#     safe error contracts
#     storage integrity, deletion and reconciliation
#
#
# PIPELINE CHOICE
# ----------------------------------------------------------
#
# This gate uses a DETERMINISTIC pipeline double rather than
# real PaddleOCR + Groq.
#
# Reason:
#
# A final production gate must be reliable and repeatable.
# Real LLM output is nondeterministic. During Phase 7C.7g the
# same real document produced three different values for
# full_name across runs, which is exactly the kind of
# flakiness a final gate must not inherit.
#
# Real OCR / LLM / PostgreSQL coverage is preserved
# separately and still runs in the regression gate through:
#
#     test_real_pipeline_persistence.py
#     test_phase7c_real_provenance_e2e.py
#
#
# ISOLATION
# ----------------------------------------------------------
#
# All storage operations use an isolated temporary storage
# root. Real user document storage is never touched.
#
# Only PostgreSQL rows created by this test are removed.
# ==========================================================

TEST_BYTES = (
    b"VIGILOX-PHASE-7C8-FINAL-"
    b"PRODUCTION-READINESS-SOURCE-BYTES"
)


REVIEWER_ID = (
    "phase7c8-trusted-reviewer"
)


SPOOFED_REVIEWER_ID = (
    "phase7c8-spoofed-attacker"
)


PRIVATE_QUEUE_FAILURE = (
    "PHASE7C8_PRIVATE_DATABASE_"
    "FAILURE_MUST_NOT_LEAK"
)


PRIVATE_DATABASE_SECRET = (
    "postgresql://vigilox:"
    "PHASE7C8_SECRET_PASSWORD@"
    "db.internal:5432/vigilox"
)


CORRECTED_FULL_NAME = (
    "CORRECTED,PHASE7C8"
)


CORRECTED_LICENCE_NUMBER = (
    "P7C8-CORRECTED-001"
)


# ==========================================================
# ASSERT HELPERS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
):

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


def assert_not_equal(
    actual,
    forbidden,
    message: str,
):

    if actual == forbidden:

        raise AssertionError(
            f"{message}\n"
            f"Forbidden value: {forbidden}"
        )


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


def assert_false(
    condition: bool,
    message: str,
):

    if condition:

        raise AssertionError(
            message
        )


# ==========================================================
# TRUSTED REVIEWER HEADERS
# ==========================================================

def reviewer_headers() -> dict[str, str]:

    return {
        "X-VIGILOX-REVIEWER-ID":
            REVIEWER_ID,

        "X-VIGILOX-REVIEWER-ROLE":
            "REVIEWER",
    }


# ==========================================================
# DETERMINISTIC PIPELINE RESULT
# ==========================================================
#
# The machine decision is intentionally REVIEW_REQUIRED so
# the gate exercises the full human-review and final-record
# path rather than the AUTO_ACCEPT shortcut.
# ==========================================================

def build_pipeline_result() -> dict:

    issue = {
        "code":
            "DOCUMENT_EXPIRED",

        "severity":
            "WARNING",

        "field":
            "expiry_date",

        "message":
            "Document is expired.",
    }


    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "SAMPLE,PHASE7C8",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C8001",

                "source_line_ids": [
                    "L1"
                ],
            },

            "id_number": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "expiry_date": {
                "value":
                    "2025-01-01",

                "source_line_ids": [
                    "L2"
                ],
            },

            "date_of_birth": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "issue_date": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "issuer": {
                "value":
                    "VIGILOX TEST AUTHORITY",

                "source_line_ids": [
                    "L3"
                ],
            },
        },

        "ocr_lines": [
            {
                "line_id":
                    "L0",

                "text":
                    "SAMPLE,PHASE7C8",

                "confidence":
                    0.991,

                "bbox":
                    [10, 10, 200, 30],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "P7C8001",

                "confidence":
                    0.992,

                "bbox":
                    [10, 40, 150, 60],
            },

            {
                "line_id":
                    "L2",

                "text":
                    "01/01/2025",

                "confidence":
                    0.993,

                "bbox":
                    [10, 70, 150, 90],
            },

            {
                "line_id":
                    "L3",

                "text":
                    "VIGILOX TEST AUTHORITY",

                "confidence":
                    0.994,

                "bbox":
                    [10, 100, 250, 120],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name":
                0.991,

            "licence_number":
                0.992,

            "id_number":
                None,

            "expiry_date":
                0.993,

            "date_of_birth":
                None,

            "issue_date":
                None,

            "issuer":
                0.994,
        },

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2025-01-01",

                "status":
                    "EXPIRED",

                "days_until_expiry":
                    -595,
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {
            "document_type":
                "guard_license",

            "valid":
                True,

            "has_anomalies":
                True,

            "error_count":
                0,

            "warning_count":
                1,

            "issues": [
                issue
            ],
        },

        "review_decision": {
            "decision":
                "REVIEW_REQUIRED",

            "review_required":
                True,

            "priority":
                "MEDIUM",

            "reason_codes": [
                "DOCUMENT_EXPIRED"
            ],

            "issues": [
                issue
            ],
        },
    }


# ==========================================================
# TEMP-FILE TRACKING PIPELINE DOUBLE
# ==========================================================

class TrackingFakePipeline:
    """
    Deterministic pipeline double.

    Also asserts the temporary upload lifecycle from inside
    the request, which is the only place the temporary file
    is supposed to exist.
    """

    def __init__(
        self,
    ):

        self.received_temp_paths = []


    def process(
        self,
        image_path: str,
    ) -> dict:

        self.received_temp_paths.append(
            image_path
        )


        path = Path(
            image_path
        )


        assert_true(
            path.exists(),
            (
                "Temporary upload must exist "
                "while the pipeline is "
                "processing."
            ),
        )


        assert_equal(
            path.read_bytes(),
            TEST_BYTES,
            (
                "Temporary upload bytes do not "
                "match the uploaded request "
                "bytes."
            ),
        )


        return (
            build_pipeline_result()
        )


# ==========================================================
# FAILING QUERY SERVICE DOUBLE
# ==========================================================

class FailingDocumentQueryService:
    """
    Forces a controlled internal dependency failure so the
    gate can prove the sanitized 500 contract and the
    structured operational log share one request ID.
    """

    def get_review_queue(
        self,
        *,
        priority=None,
        document_type=None,
    ):

        raise RuntimeError(
            PRIVATE_QUEUE_FAILURE
        )


# ==========================================================
# FAILING READINESS DEPENDENCY
# ==========================================================

class FakeDatabaseUnavailable(
    RuntimeError
):
    pass


def failing_database_check(
    app_state=None,
):

    raise ReadinessCheckFailed(
        reason=(
            REASON_DATABASE_UNAVAILABLE
        ),

        exc=(
            FakeDatabaseUnavailable(
                "could not connect to "
                f"{PRIVATE_DATABASE_SECRET}"
            )
        ),
    )


# ==========================================================
# STRUCTURED LOG CAPTURE
# ==========================================================

class StructuredLogCapture:
    """
    Focused capture of the real vigilox logger hierarchy
    using the real production formatter.

    A focused handler is used rather than parsing unrelated
    global log output.
    """

    def __init__(
        self,
    ):

        self.stream = (
            io.StringIO()
        )


        self.handler = (
            logging.StreamHandler(
                self.stream
            )
        )


        self.handler.setFormatter(
            StructuredJSONFormatter()
        )


        self.root_logger = (
            logging.getLogger(
                LOGGER_ROOT_NAME
            )
        )


        self.previous_level = (
            self.root_logger.level
        )


    def __enter__(
        self,
    ):

        self.root_logger.addHandler(
            self.handler
        )


        self.root_logger.setLevel(
            logging.DEBUG
        )


        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):

        self.root_logger.removeHandler(
            self.handler
        )


        self.root_logger.setLevel(
            self.previous_level
        )


        return False


    def find_event(
        self,
        event: str,
    ) -> dict | None:

        for line in (
            self.stream
            .getvalue()
            .splitlines()
        ):

            stripped = (
                line.strip()
            )


            if not stripped:

                continue


            record = (
                json.loads(
                    stripped
                )
            )


            if (
                record.get(
                    "event"
                )
                == event
            ):

                return record


        return None


# ==========================================================
# DATABASE COUNT HELPERS
# ==========================================================

def count_documents(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        return (
            session.scalar(
                select(
                    func.count(
                        DocumentModel.id
                    )
                )
                .where(
                    DocumentModel.id
                    == document_id
                )
            )
            or 0
        )


def count_analyses(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        return (
            session.scalar(
                select(
                    func.count(
                        DocumentAnalysisModel.id
                    )
                )
                .where(
                    DocumentAnalysisModel
                    .document_id
                    == document_id
                )
            )
            or 0
        )


def count_reviews(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        return (
            session.scalar(
                select(
                    func.count(
                        HumanReviewModel.id
                    )
                )
                .where(
                    HumanReviewModel.document_id
                    == document_id
                )
            )
            or 0
        )


def count_audits(
    document_id: str,
    event_type: str | None = None,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    AuditEventModel.id
                )
            )
            .where(
                AuditEventModel.document_id
                == document_id
            )
        )


        if event_type is not None:

            statement = (
                statement.where(
                    AuditEventModel.event_type
                    == event_type
                )
            )


        return (
            session.scalar(
                statement
            )
            or 0
        )


# ==========================================================
# RAW STORED EXTRACTION
# ==========================================================

def load_stored_extraction(
    document_id: str,
) -> dict | None:

    with SessionLocal() as session:

        analysis = (
            session.scalar(
                select(
                    DocumentAnalysisModel
                )
                .where(
                    DocumentAnalysisModel
                    .document_id
                    == document_id
                )
            )
        )


        if analysis is None:

            return None


        return analysis.extraction


# ==========================================================
# AUDIT ACTORS
# ==========================================================

def load_audit_actors(
    document_id: str,
    event_type: str,
) -> list[str | None]:

    with SessionLocal() as session:

        rows = (
            session.scalars(
                select(
                    AuditEventModel
                )
                .where(
                    AuditEventModel.document_id
                    == document_id
                )
                .where(
                    AuditEventModel.event_type
                    == event_type
                )
            )
            .all()
        )


        return [
            row.actor_id
            for row in rows
        ]


# ==========================================================
# STORED REVIEWER
# ==========================================================

def load_review_reviewer(
    document_id: str,
) -> str | None:

    with SessionLocal() as session:

        review = (
            session.scalar(
                select(
                    HumanReviewModel
                )
                .where(
                    HumanReviewModel.document_id
                    == document_id
                )
            )
        )


        if review is None:

            return None


        return review.reviewer_id


# ==========================================================
# REVIEW QUEUE MEMBERSHIP
# ==========================================================

def queue_contains_document(
    client,
    document_id: str,
) -> bool:

    response = (
        client.get(
            "/api/v1/reviews/queue"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Review queue should return "
            "HTTP 200."
        ),
    )


    for item in (
        response.json()[
            "documents"
        ]
    ):

        if (
            item[
                "document_id"
            ]
            == document_id
        ):

            return True


    return False


# ==========================================================
# INTEGRITY REPORT LOOKUP
# ==========================================================

def report_contains(
    report: dict,
    category: str,
    document_id: str,
) -> bool:

    for item in report.get(
        category,
        [],
    ):

        if (
            item.get(
                "document_id"
            )
            == document_id
        ):

            return True


    return False


# ==========================================================
# DATABASE CLEANUP
# ==========================================================

def remove_test_documents(
    document_ids,
) -> None:

    for document_id in document_ids:

        with SessionLocal.begin() as session:

            document = (
                session.get(
                    DocumentModel,
                    document_id,
                )
            )


            if document is not None:

                session.delete(
                    document
                )


# ==========================================================
# SECTION 1 — LIVENESS AND READINESS
# ==========================================================

def section_liveness_and_readiness(
    client,
):

    print()
    print("-" * 76)
    print(
        "SECTION 1 - LIVENESS AND "
        "READINESS"
    )
    print("-" * 76)


    # ======================================================
    # LIVENESS
    # ======================================================

    response = (
        client.get(
            "/health"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Liveness should return HTTP 200."
        ),
    )


    assert_equal(
        response.json(),
        {
            "status":
                "ok",

            "service":
                "vigilox-document-intelligence",

            "version":
                "0.1.0",
        },
        (
            "Lightweight liveness payload "
            "must remain unchanged."
        ),
    )


    print(
        "[PASS] Liveness healthy and "
        "lightweight"
    )


    # ======================================================
    # READINESS
    # ======================================================

    response = (
        client.get(
            "/health/ready"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Readiness should return HTTP 200 "
            "with healthy dependencies."
        ),
    )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "status"
        ],
        "ready",
        (
            "Readiness should report ready."
        ),
    )


    for check_name in (
        "database",
        "storage",
        "services",
    ):

        assert_equal(
            body[
                "checks"
            ][
                check_name
            ][
                "status"
            ],
            "ok",
            (
                "Readiness dependency should "
                f"be ok: {check_name}"
            ),
        )


    print(
        "[PASS] Readiness healthy "
        "(real PostgreSQL + managed storage)"
    )


    assert_true(
        response.headers.get(
            REQUEST_ID_HEADER
        )
        is not None,
        (
            "Readiness response should carry "
            "a correlation ID."
        ),
    )


    print(
        "[PASS] Readiness response carries "
        "a request ID"
    )


# ==========================================================
# SECTION 2 — UPLOAD, PIPELINE, PERSISTENCE, STORAGE
# ==========================================================

def section_upload_and_persistence(
    client,
    pipeline,
    storage_service,
    integrity_service,
    managed_ids,
) -> str:

    print()
    print("-" * 76)
    print(
        "SECTION 2 - UPLOAD, PIPELINE, "
        "PERSISTENCE AND SOURCE STORAGE"
    )
    print("-" * 76)


    response = (
        client.post(
            "/api/v1/documents/analyze",

            files={
                "file": (
                    "phase7c8_final.jpg",
                    TEST_BYTES,
                    "image/jpeg",
                )
            },
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Analyze endpoint should return "
            "HTTP 200."
        ),
    )


    body = (
        response.json()
    )


    document_id = (
        body[
            "document_id"
        ]
    )


    managed_ids.add(
        document_id
    )


    print(
        "[PASS] Document uploaded and "
        "processed through the pipeline"
    )


    # ======================================================
    # REQUEST ID ON SUCCESS
    # ======================================================

    assert_true(
        response.headers.get(
            REQUEST_ID_HEADER
        )
        is not None,
        (
            "Successful analyze response "
            "should carry a correlation ID."
        ),
    )


    print(
        "[PASS] Successful upload carries "
        "a request ID"
    )


    # ======================================================
    # TEMPORARY UPLOAD LIFECYCLE
    # ======================================================
    #
    # Existence DURING processing is asserted inside the
    # pipeline double. Here we prove removal AFTER the
    # request completed.
    # ======================================================

    assert_equal(
        len(
            pipeline
            .received_temp_paths
        ),
        1,
        (
            "The pipeline should have been "
            "invoked exactly once."
        ),
    )


    temp_path = Path(
        pipeline
        .received_temp_paths[
            0
        ]
    )


    assert_false(
        temp_path.exists(),
        (
            "Temporary upload must be removed "
            "after the request completes."
        ),
    )


    print(
        "[PASS] Temporary upload existed "
        "during processing and was cleaned"
    )


    # ======================================================
    # POSTGRESQL PERSISTENCE
    # ======================================================

    assert_equal(
        count_documents(
            document_id
        ),
        1,
        (
            "Exactly one document row should "
            "be persisted."
        ),
    )


    assert_equal(
        count_analyses(
            document_id
        ),
        1,
        (
            "Exactly one analysis row should "
            "be persisted."
        ),
    )


    assert_equal(
        count_audits(
            document_id,
            "MACHINE_REVIEW_DECISION",
        ),
        1,
        (
            "Exactly one machine review audit "
            "event should be persisted."
        ),
    )


    print(
        "[PASS] Document, analysis and "
        "machine audit persisted"
    )


    # ======================================================
    # PERMANENT SOURCE STORAGE
    # ======================================================

    assert_true(
        body[
            "original_document_stored"
        ],
        (
            "Analyze response should report "
            "the original as stored."
        ),
    )


    assert_true(
        storage_service.original_exists(
            document_id=(
                document_id
            ),

            content_type=(
                "image/jpeg"
            ),
        ),
        (
            "Original source document should "
            "exist in managed storage."
        ),
    )


    print(
        "[PASS] Original source permanently "
        "stored"
    )


    # ======================================================
    # READ PATH
    # ======================================================

    response = (
        client.get(
            f"/api/v1/documents/{document_id}"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Stored document should be "
            "retrievable."
        ),
    )


    stored = (
        response.json()
    )


    assert_equal(
        stored[
            "document"
        ][
            "processing_status"
        ],
        "PROCESSED",
        (
            "Document processing status "
            "should be PROCESSED."
        ),
    )


    print(
        "[PASS] Stored document retrievable "
        "through the API"
    )


    # ======================================================
    # EXPLICIT OCR EVIDENCE PROVENANCE
    # ======================================================

    analysis = (
        stored[
            "analysis"
        ]
    )


    ocr_lookup = {
        line[
            "line_id"
        ]: line

        for line
        in analysis[
            "ocr_lines"
        ]
    }


    assert_equal(
        sorted(
            ocr_lookup
        ),
        [
            "L0",
            "L1",
            "L2",
            "L3",
        ],
        (
            "Persisted OCR lines should keep "
            "their explicit line IDs."
        ),
    )


    extraction = (
        analysis[
            "extraction"
        ]
    )


    for field_name in (
        "full_name",
        "licence_number",
        "expiry_date",
        "issuer",
    ):

        source_line_ids = (
            extraction[
                field_name
            ][
                "source_line_ids"
            ]
        )


        assert_true(
            len(
                source_line_ids
            )
            > 0,
            (
                "Extracted field should retain "
                f"evidence: {field_name}"
            ),
        )


        for line_id in source_line_ids:

            assert_true(
                line_id
                in ocr_lookup,
                (
                    f"{field_name} references a "
                    "missing OCR line: "
                    f"{line_id}"
                ),
            )


    print(
        "[PASS] Explicit OCR evidence IDs "
        "retained and resolvable"
    )


    assert_true(
        analysis[
            "field_confidence"
        ]
        is not None,
        (
            "Field confidence data should be "
            "persisted."
        ),
    )


    print(
        "[PASS] Confidence / evidence data "
        "preserved"
    )


    # ======================================================
    # EXACT ORIGINAL BYTES
    # ======================================================

    response = (
        client.get(
            f"/api/v1/documents/{document_id}"
            "/image"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Original document image should "
            "be retrievable."
        ),
    )


    assert_equal(
        response.content,
        TEST_BYTES,
        (
            "Returned original bytes must "
            "match the uploaded source "
            "exactly."
        ),
    )


    print(
        "[PASS] Exact original source bytes "
        "retrievable"
    )


    # ======================================================
    # STORAGE INTEGRITY
    # ======================================================

    report = (
        integrity_service.scan()
    )


    assert_true(
        report_contains(
            report,
            "healthy_documents",
            document_id,
        ),
        (
            "Stored document should be "
            "reported HEALTHY."
        ),
    )


    assert_false(
        report_contains(
            report,
            "missing_storage",
            document_id,
        ),
        (
            "Stored document must not be "
            "reported as missing storage."
        ),
    )


    print(
        "[PASS] Storage integrity reports "
        "document HEALTHY"
    )


    return document_id


# ==========================================================
# SECTION 3 — REVIEW, FINAL RECORD, PROVENANCE
# ==========================================================

def section_review_and_final_record(
    client,
    document_id: str,
):

    print()
    print("-" * 76)
    print(
        "SECTION 3 - REVIEW, FINAL RECORD "
        "AND PROVENANCE"
    )
    print("-" * 76)


    # ======================================================
    # REVIEW QUEUE
    # ======================================================

    assert_true(
        queue_contains_document(
            client,
            document_id,
        ),
        (
            "A REVIEW_REQUIRED document should "
            "appear in the review queue."
        ),
    )


    print(
        "[PASS] Document appears in the "
        "review queue"
    )


    # ======================================================
    # PRE-REVIEW FINAL RECORD
    # ======================================================

    stored = (
        client.get(
            f"/api/v1/documents/{document_id}"
        )
        .json()
    )


    final_record = (
        stored[
            "final_record"
        ]
    )


    assert_equal(
        final_record[
            "final_status"
        ],
        "PENDING_REVIEW",
        (
            "An unreviewed REVIEW_REQUIRED "
            "document should be "
            "PENDING_REVIEW."
        ),
    )


    assert_false(
        final_record[
            "is_final"
        ],
        (
            "PENDING_REVIEW must not be final."
        ),
    )


    assert_false(
        final_record[
            "is_usable"
        ],
        (
            "PENDING_REVIEW must not be "
            "usable."
        ),
    )


    assert_equal(
        final_record[
            "effective_values"
        ],
        None,
        (
            "PENDING_REVIEW must expose no "
            "effective values."
        ),
    )


    print(
        "[PASS] Pre-review final record is "
        "PENDING_REVIEW and unusable"
    )


    machine_extraction_before = (
        load_stored_extraction(
            document_id
        )
    )


    # ======================================================
    # TRUSTED REVIEWER IDENTITY
    # ======================================================

    response = (
        client.get(
            "/api/v1/reviewer/me",
            headers=(
                reviewer_headers()
            ),
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Trusted reviewer identity should "
            "resolve."
        ),
    )


    reviewer = (
        response.json()[
            "reviewer"
        ]
    )


    assert_equal(
        reviewer[
            "reviewer_id"
        ],
        REVIEWER_ID,
        (
            "Trusted header identity should be "
            "authoritative."
        ),
    )


    assert_true(
        reviewer[
            "can_review"
        ],
        (
            "A REVIEWER role should be allowed "
            "to review."
        ),
    )


    print(
        "[PASS] Trusted reviewer identity "
        "endpoint authoritative"
    )


    # ======================================================
    # UNAUTHENTICATED WRITE IS REJECTED
    # ======================================================

    response = (
        client.post(
            f"/api/v1/documents/{document_id}"
            "/reviews",

            json={
                "action":
                    "APPROVE",
            },
        )
    )


    assert_equal(
        response.status_code,
        401,
        (
            "A review without trusted identity "
            "headers must be rejected."
        ),
    )


    assert_equal(
        response.json()[
            "error"
        ][
            "code"
        ],
        "REVIEWER_AUTHENTICATION_REQUIRED",
        (
            "Unauthenticated review should use "
            "the reviewer authentication "
            "code."
        ),
    )


    print(
        "[PASS] Unauthenticated review "
        "rejected with 401"
    )


    # ======================================================
    # SUBMIT HUMAN CORRECTION
    # ======================================================
    #
    # The request body deliberately carries a spoofed
    # reviewer_id. The backend must ignore it and use the
    # trusted server-side identity instead.
    # ======================================================

    response = (
        client.post(
            f"/api/v1/documents/{document_id}"
            "/reviews",

            headers=(
                reviewer_headers()
            ),

            json={
                "reviewer_id":
                    SPOOFED_REVIEWER_ID,

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Phase 7C.8 final "
                        "production readiness "
                        "correction."
                    ),

                "corrections": {
                    "full_name":
                        CORRECTED_FULL_NAME,

                    "licence_number":
                        CORRECTED_LICENCE_NUMBER,
                },
            },
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "A trusted human correction should "
            "be accepted."
        ),
    )


    review_body = (
        response.json()
    )


    print(
        "[PASS] Human CORRECT accepted with "
        "trusted identity"
    )


    # ======================================================
    # CLIENT SPOOFING INEFFECTIVE
    # ======================================================

    assert_equal(
        review_body[
            "authenticated_reviewer"
        ][
            "reviewer_id"
        ],
        REVIEWER_ID,
        (
            "The response must report the "
            "trusted reviewer, not the "
            "client-supplied value."
        ),
    )


    assert_equal(
        load_review_reviewer(
            document_id
        ),
        REVIEWER_ID,
        (
            "human_reviews.reviewer_id must "
            "come from the trusted identity."
        ),
    )


    assert_not_equal(
        load_review_reviewer(
            document_id
        ),
        SPOOFED_REVIEWER_ID,
        (
            "A client-supplied reviewer_id "
            "must never be persisted as the "
            "reviewer."
        ),
    )


    audit_actors = (
        load_audit_actors(
            document_id,
            "HUMAN_REVIEW",
        )
    )


    assert_equal(
        audit_actors,
        [
            REVIEWER_ID
        ],
        (
            "audit_events.actor_id must come "
            "from the trusted identity."
        ),
    )


    print(
        "[PASS] Client reviewer spoofing "
        "ineffective in DB and audit"
    )


    # ======================================================
    # FINAL RECORD AFTER CORRECTION
    # ======================================================

    stored = (
        client.get(
            f"/api/v1/documents/{document_id}"
        )
        .json()
    )


    final_record = (
        stored[
            "final_record"
        ]
    )


    assert_equal(
        final_record[
            "final_status"
        ],
        "CORRECTED",
        (
            "A human CORRECT should produce "
            "final status CORRECTED."
        ),
    )


    assert_true(
        final_record[
            "is_final"
        ],
        (
            "CORRECTED must be final."
        ),
    )


    assert_true(
        final_record[
            "is_usable"
        ],
        (
            "CORRECTED must be usable."
        ),
    )


    print(
        "[PASS] Final record is CORRECTED, "
        "final and usable"
    )


    # ======================================================
    # EFFECTIVE VALUES
    # ======================================================

    effective_values = (
        final_record[
            "effective_values"
        ]
    )


    assert_equal(
        effective_values[
            "full_name"
        ],
        CORRECTED_FULL_NAME,
        (
            "Corrected full_name should "
            "appear in effective values."
        ),
    )


    assert_equal(
        effective_values[
            "licence_number"
        ],
        CORRECTED_LICENCE_NUMBER,
        (
            "Corrected licence_number should "
            "appear in effective values."
        ),
    )


    assert_equal(
        effective_values[
            "issuer"
        ],
        "VIGILOX TEST AUTHORITY",
        (
            "Uncorrected fields should retain "
            "their machine value."
        ),
    )


    print(
        "[PASS] Effective values overlay "
        "corrections onto machine values"
    )


    # ======================================================
    # PROVENANCE
    # ======================================================

    value_sources = (
        final_record[
            "value_sources"
        ]
    )


    for corrected_field in (
        "full_name",
        "licence_number",
    ):

        assert_equal(
            value_sources[
                corrected_field
            ],
            "HUMAN_CORRECTION",
            (
                "Corrected field provenance "
                "should be HUMAN_CORRECTION: "
                f"{corrected_field}"
            ),
        )


    for machine_field in (
        "issuer",
        "expiry_date",
        "document_type",
    ):

        assert_equal(
            value_sources[
                machine_field
            ],
            "MACHINE",
            (
                "Uncorrected field provenance "
                "should remain machine "
                f"provenance: {machine_field}"
            ),
        )


    print(
        "[PASS] HUMAN_CORRECTION and MACHINE "
        "provenance correct"
    )


    # ======================================================
    # MACHINE EXTRACTION IMMUTABILITY
    # ======================================================

    machine_extraction_after = (
        load_stored_extraction(
            document_id
        )
    )


    assert_equal(
        machine_extraction_after,
        machine_extraction_before,
        (
            "The stored machine extraction "
            "must never be mutated by a human "
            "correction."
        ),
    )


    assert_equal(
        machine_extraction_after[
            "full_name"
        ][
            "value"
        ],
        "SAMPLE,PHASE7C8",
        (
            "The original machine full_name "
            "must remain unchanged."
        ),
    )


    assert_equal(
        final_record[
            "machine_values"
        ][
            "full_name"
        ],
        "SAMPLE,PHASE7C8",
        (
            "The final record should still "
            "expose the original machine "
            "value."
        ),
    )


    print(
        "[PASS] Original machine extraction "
        "remains immutable"
    )


    # ======================================================
    # MACHINE DECISION UNCHANGED
    # ======================================================

    assert_equal(
        stored[
            "analysis"
        ][
            "review_decision"
        ][
            "decision"
        ],
        "REVIEW_REQUIRED",
        (
            "The machine review decision must "
            "remain unchanged after human "
            "review."
        ),
    )


    print(
        "[PASS] Machine review decision "
        "unchanged"
    )


    # ======================================================
    # QUEUE REMOVAL
    # ======================================================

    assert_false(
        queue_contains_document(
            client,
            document_id,
        ),
        (
            "A reviewed document should leave "
            "the review queue."
        ),
    )


    print(
        "[PASS] Reviewed document removed "
        "from the review queue"
    )


    # ======================================================
    # DUPLICATE REVIEW BLOCKED
    # ======================================================

    response = (
        client.post(
            f"/api/v1/documents/{document_id}"
            "/reviews",

            headers=(
                reviewer_headers()
            ),

            json={
                "action":
                    "APPROVE",
            },
        )
    )


    assert_equal(
        response.status_code,
        409,
        (
            "A second human review must be "
            "rejected with HTTP 409."
        ),
    )


    assert_equal(
        response.json()[
            "error"
        ][
            "code"
        ],
        "DOCUMENT_ALREADY_REVIEWED",
        (
            "Duplicate review should use the "
            "stable conflict code."
        ),
    )


    print(
        "[PASS] Duplicate review blocked "
        "with 409"
    )


    # ======================================================
    # EXACTLY ONE REVIEW AND ONE AUDIT
    # ======================================================

    assert_equal(
        count_reviews(
            document_id
        ),
        1,
        (
            "Exactly one human review must "
            "exist."
        ),
    )


    assert_equal(
        count_audits(
            document_id,
            "HUMAN_REVIEW",
        ),
        1,
        (
            "Exactly one human review audit "
            "event must exist."
        ),
    )


    print(
        "[PASS] Exactly one human review and "
        "one human audit event"
    )


    # ======================================================
    # AUDIT HISTORY
    # ======================================================

    response = (
        client.get(
            f"/api/v1/documents/{document_id}"
            "/history"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Document history should be "
            "retrievable."
        ),
    )


    event_types = {
        event[
            "event_type"
        ]

        for event
        in response.json()[
            "events"
        ]
    }


    assert_true(
        "MACHINE_REVIEW_DECISION"
        in event_types,
        (
            "History should include the "
            "machine decision event."
        ),
    )


    assert_true(
        "HUMAN_REVIEW"
        in event_types,
        (
            "History should include the human "
            "review event."
        ),
    )


    print(
        "[PASS] Audit history contains "
        "machine and human events"
    )


# ==========================================================
# SECTION 4 — ERROR CONTRACT, REQUEST ID, LOGGING
# ==========================================================

def section_errors_and_logging(
    client,
    real_document_query,
):

    print()
    print("-" * 76)
    print(
        "SECTION 4 - ERROR CONTRACT, "
        "REQUEST ID AND LOGGING"
    )
    print("-" * 76)


    # ======================================================
    # SAFE CONTROLLED 404
    # ======================================================

    unknown_id = str(
        uuid4()
    )


    response = (
        client.get(
            f"/api/v1/documents/{unknown_id}"
        )
    )


    assert_equal(
        response.status_code,
        404,
        (
            "An unknown document should return "
            "HTTP 404."
        ),
    )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "error"
        ][
            "code"
        ],
        "DOCUMENT_NOT_FOUND",
        (
            "Unknown document should use the "
            "stable not-found code."
        ),
    )


    header_request_id = (
        response.headers.get(
            REQUEST_ID_HEADER
        )
    )


    assert_true(
        header_request_id is not None,
        (
            "HTTP 404 should carry a "
            "correlation ID header."
        ),
    )


    assert_equal(
        body[
            "error"
        ][
            "request_id"
        ],
        header_request_id,
        (
            "HTTP 404 header and "
            "error.request_id must match."
        ),
    )


    print(
        "[PASS] 404 DOCUMENT_NOT_FOUND with "
        "matching request ID"
    )


    # ======================================================
    # CONTROLLED INTERNAL FAILURE
    # ======================================================

    try:

        app.state.document_query = (
            FailingDocumentQueryService()
        )


        with StructuredLogCapture() as capture:

            response = (
                client.get(
                    "/api/v1/reviews/queue"
                )
            )


            log_record = (
                capture.find_event(
                    "review_queue_load_failed"
                )
            )


        assert_equal(
            response.status_code,
            500,
            (
                "A failing dependency should "
                "return HTTP 500."
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body[
                "error"
            ][
                "code"
            ],
            "REVIEW_QUEUE_LOAD_FAILED",
            (
                "Internal failure should use "
                "the stable domain code."
            ),
        )


        print(
            "[PASS] Internal failure mapped to "
            "a stable 500 error code"
        )


        # ==============================================
        # NO PRIVATE LEAK
        # ==============================================

        serialized_body = (
            json.dumps(
                body
            )
        )


        assert_true(
            PRIVATE_QUEUE_FAILURE
            not in serialized_body,
            (
                "The private exception string "
                "must not reach the client."
            ),
        )


        assert_true(
            "Traceback"
            not in serialized_body,
            (
                "A stack trace must not reach "
                "the client."
            ),
        )


        print(
            "[PASS] Private exception detail "
            "not exposed to the client"
        )


        # ==============================================
        # STRUCTURED LOG
        # ==============================================

        assert_true(
            log_record is not None,
            (
                "A structured "
                "review_queue_load_failed "
                "event should be emitted."
            ),
        )


        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_equal(
            log_record[
                "request_id"
            ],
            header_request_id,
            (
                "The structured log must share "
                "the response request ID."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "request_id"
            ],
            header_request_id,
            (
                "The error payload must share "
                "the response request ID."
            ),
        )


        assert_equal(
            log_record[
                "error_code"
            ],
            "REVIEW_QUEUE_LOAD_FAILED",
            (
                "The structured log should "
                "carry the stable error code."
            ),
        )


        assert_equal(
            log_record[
                "error_type"
            ],
            "RuntimeError",
            (
                "The structured log should "
                "carry the exception type."
            ),
        )


        print(
            "[PASS] Structured log shares the "
            "request ID, event and error code"
        )


        # ==============================================
        # SERVER-SIDE TRACE RETAINED
        # ==============================================

        assert_true(
            PRIVATE_QUEUE_FAILURE
            in log_record[
                "exception"
            ],
            (
                "The server-side log should "
                "retain the real exception for "
                "operators."
            ),
        )


        print(
            "[PASS] Real failure detail kept "
            "server-side only"
        )


        # ==============================================
        # NO SECRETS OR REQUEST BODIES
        # ==============================================

        serialized_log = (
            json.dumps(
                log_record
            )
        )


        for forbidden in (
            "GROQ_API_KEY",
            "DATABASE_URL",
            "authorization",
            "X-VIGILOX-REVIEWER-ID",
        ):

            assert_true(
                forbidden
                not in serialized_log,
                (
                    "Structured logs must not "
                    "contain sensitive context: "
                    f"{forbidden}"
                ),
            )


        print(
            "[PASS] Structured log contains no "
            "secrets or request bodies"
        )


    finally:

        app.state.document_query = (
            real_document_query
        )


    # ======================================================
    # RECOVERY
    # ======================================================

    response = (
        client.get(
            "/api/v1/reviews/queue"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "The review queue should recover "
            "after the injected failure is "
            "removed."
        ),
    )


    print(
        "[PASS] Review queue recovers after "
        "the injected failure"
    )


# ==========================================================
# SECTION 5 — READINESS FAILURE PATH
# ==========================================================

def section_readiness_failure(
    client,
    real_readiness,
):

    print()
    print("-" * 76)
    print(
        "SECTION 5 - SAFE READINESS "
        "FAILURE PATH"
    )
    print("-" * 76)


    try:

        app.state.readiness = (
            ReadinessService(
                database_check=(
                    failing_database_check
                )
            )
        )


        with StructuredLogCapture() as capture:

            response = (
                client.get(
                    "/health/ready"
                )
            )


            log_record = (
                capture.find_event(
                    "readiness_dependency"
                    "_failed"
                )
            )


        assert_equal(
            response.status_code,
            503,
            (
                "A failing readiness dependency "
                "should return HTTP 503."
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body[
                "error"
            ][
                "code"
            ],
            "SERVICE_NOT_READY",
            (
                "Readiness failure should use "
                "the stable not-ready code."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "details"
            ][
                "checks"
            ][
                "database"
            ][
                "reason"
            ],
            REASON_DATABASE_UNAVAILABLE,
            (
                "Readiness failure should "
                "expose a stable reason code."
            ),
        )


        print(
            "[PASS] Readiness failure returns "
            "a safe HTTP 503"
        )


        # ==============================================
        # NO PRIVATE LEAK
        # ==============================================

        serialized_body = (
            json.dumps(
                body
            )
        )


        for forbidden in (
            PRIVATE_DATABASE_SECRET,
            "PHASE7C8_SECRET_PASSWORD",
            "postgresql://",
            "Traceback",
        ):

            assert_true(
                forbidden
                not in serialized_body,
                (
                    "Readiness failure leaked "
                    "private information: "
                    f"{forbidden}"
                ),
            )


        print(
            "[PASS] Readiness failure exposes "
            "no credentials or traces"
        )


        # ==============================================
        # REQUEST ID
        # ==============================================

        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_true(
            header_request_id is not None,
            (
                "Readiness failure should carry "
                "a correlation ID header."
            ),
        )


        assert_equal(
            body[
                "error"
            ][
                "request_id"
            ],
            header_request_id,
            (
                "Readiness failure header and "
                "error.request_id must match."
            ),
        )


        assert_true(
            log_record is not None,
            (
                "Readiness failure should emit "
                "a structured event."
            ),
        )


        assert_equal(
            log_record[
                "request_id"
            ],
            header_request_id,
            (
                "The readiness failure log must "
                "share the response request ID."
            ),
        )


        print(
            "[PASS] Readiness failure shares "
            "one request ID across all outputs"
        )


    finally:

        app.state.readiness = (
            real_readiness
        )


    # ======================================================
    # RECOVERY
    # ======================================================

    response = (
        client.get(
            "/health/ready"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Readiness should recover once the "
            "dependency is healthy again."
        ),
    )


    print(
        "[PASS] Readiness recovers after the "
        "injected dependency failure"
    )


# ==========================================================
# SECTION 6 — DELETION, ORPHANS, RECONCILIATION
# ==========================================================

def section_storage_lifecycle(
    client,
    storage_service,
    persistence_service,
    integrity_service,
    reconciliation_service,
    deletion_service,
    source_path,
    reviewed_document_id,
    managed_ids,
):

    print()
    print("-" * 76)
    print(
        "SECTION 6 - DELETION, ORPHAN "
        "DETECTION AND RECONCILIATION"
    )
    print("-" * 76)


    # ======================================================
    # SAFE DB-FIRST DELETION
    # ======================================================

    result = (
        deletion_service
        .delete_document(
            reviewed_document_id
        )
    )


    assert_equal(
        result[
            "status"
        ],
        "DELETED",
        (
            "Business deletion should report "
            "DELETED."
        ),
    )


    assert_true(
        result[
            "database_deleted"
        ],
        (
            "The database row should be "
            "deleted."
        ),
    )


    assert_equal(
        result[
            "storage_status"
        ],
        "DELETED",
        (
            "Managed storage should be "
            "deleted."
        ),
    )


    print(
        "[PASS] DB-first deletion completed"
    )


    # ======================================================
    # CASCADES
    # ======================================================

    assert_equal(
        count_documents(
            reviewed_document_id
        ),
        0,
        (
            "The document row should be gone."
        ),
    )


    assert_equal(
        count_analyses(
            reviewed_document_id
        ),
        0,
        (
            "The analysis row should cascade "
            "delete."
        ),
    )


    assert_equal(
        count_reviews(
            reviewed_document_id
        ),
        0,
        (
            "The human review should cascade "
            "delete."
        ),
    )


    assert_equal(
        count_audits(
            reviewed_document_id
        ),
        0,
        (
            "Audit events should cascade "
            "delete."
        ),
    )


    print(
        "[PASS] Analysis, review and audit "
        "cascades deleted"
    )


    # ======================================================
    # SOURCE STORAGE REMOVED
    # ======================================================

    assert_false(
        storage_service
        .get_document_directory(
            reviewed_document_id
        )
        .exists(),
        (
            "The managed source directory "
            "should be removed."
        ),
    )


    print(
        "[PASS] Permanent source storage "
        "removed"
    )


    # ======================================================
    # API NO LONGER EXPOSES THE DOCUMENT
    # ======================================================

    assert_equal(
        client.get(
            "/api/v1/documents/"
            f"{reviewed_document_id}"
        )
        .status_code,
        404,
        (
            "A deleted document should return "
            "HTTP 404."
        ),
    )


    assert_equal(
        client.get(
            "/api/v1/documents/"
            f"{reviewed_document_id}"
            "/image"
        )
        .status_code,
        404,
        (
            "A deleted document image should "
            "return HTTP 404."
        ),
    )


    print(
        "[PASS] Deleted document returns 404 "
        "for record and image"
    )


    managed_ids.discard(
        reviewed_document_id
    )


    # ======================================================
    # INTEGRITY AFTER DELETION
    # ======================================================

    report = (
        integrity_service.scan()
    )


    for category in (
        "healthy_documents",
        "missing_storage",
        "orphan_storage",
    ):

        assert_false(
            report_contains(
                report,
                category,
                reviewed_document_id,
            ),
            (
                "A fully deleted document must "
                "not appear in integrity "
                f"category: {category}"
            ),
        )


    print(
        "[PASS] Integrity scan shows no trace "
        "of the deleted document"
    )


    # ======================================================
    # DELIBERATE ORPHAN
    # ======================================================

    orphan_id = str(
        uuid4()
    )


    orphan_path = (
        storage_service
        .save_original(
            document_id=(
                orphan_id
            ),

            source_path=(
                source_path
            ),

            content_type=(
                "image/jpeg"
            ),
        )
    )


    assert_true(
        orphan_path.exists(),
        (
            "Orphan setup failed."
        ),
    )


    report = (
        integrity_service.scan()
    )


    assert_true(
        report_contains(
            report,
            "orphan_storage",
            orphan_id,
        ),
        (
            "A storage directory without a "
            "database row should be reported "
            "as ORPHAN_STORAGE."
        ),
    )


    print(
        "[PASS] Orphan storage detected"
    )


    # ======================================================
    # DRY RUN IS NON-DESTRUCTIVE
    # ======================================================

    dry_run = (
        reconciliation_service
        .reconcile_orphans(
            dry_run=True
        )
    )


    assert_equal(
        dry_run[
            "mode"
        ],
        "DRY_RUN",
        (
            "Reconciliation should report "
            "DRY_RUN mode."
        ),
    )


    dry_run_statuses = {
        item[
            "document_id"
        ]: item[
            "status"
        ]

        for item
        in dry_run[
            "results"
        ]
    }


    assert_equal(
        dry_run_statuses.get(
            orphan_id
        ),
        "WOULD_DELETE",
        (
            "A dry run should report "
            "WOULD_DELETE for the orphan."
        ),
    )


    assert_equal(
        dry_run[
            "deleted_count"
        ],
        0,
        (
            "A dry run must not delete "
            "anything."
        ),
    )


    assert_true(
        orphan_path.exists(),
        (
            "A dry run must not mutate the "
            "filesystem."
        ),
    )


    print(
        "[PASS] Dry-run reconciliation is "
        "non-destructive"
    )


    # ======================================================
    # EXECUTE RECONCILIATION
    # ======================================================

    executed = (
        reconciliation_service
        .reconcile_orphans(
            dry_run=False
        )
    )


    assert_equal(
        executed[
            "mode"
        ],
        "EXECUTE",
        (
            "Reconciliation should report "
            "EXECUTE mode."
        ),
    )


    executed_statuses = {
        item[
            "document_id"
        ]: item[
            "status"
        ]

        for item
        in executed[
            "results"
        ]
    }


    assert_equal(
        executed_statuses.get(
            orphan_id
        ),
        "DELETED",
        (
            "Executed reconciliation should "
            "delete the orphan."
        ),
    )


    assert_false(
        orphan_path.exists(),
        (
            "The orphan file should be "
            "removed."
        ),
    )


    final_report = (
        integrity_service.scan()
    )


    assert_false(
        report_contains(
            final_report,
            "orphan_storage",
            orphan_id,
        ),
        (
            "The reconciled orphan should no "
            "longer be reported."
        ),
    )


    print(
        "[PASS] Orphan reconciliation removed "
        "only the orphan"
    )


    # ======================================================
    # MISSING STORAGE IS PROTECTED
    # ======================================================
    #
    # A database record whose managed source file has
    # disappeared must be DETECTED but never automatically
    # deleted by reconciliation.
    # ======================================================

    stored = (
        persistence_service
        .save_processed_document(
            original_filename=(
                "phase7c8_missing.jpg"
            ),

            content_type=(
                "image/jpeg"
            ),

            pipeline_result=(
                build_pipeline_result()
            ),

            source_path=(
                str(
                    source_path
                )
            ),
        )
    )


    missing_id = (
        stored[
            "document_id"
        ]
    )


    managed_ids.add(
        missing_id
    )


    # Remove ONLY the managed storage, leaving the
    # authoritative database record in place.

    assert_true(
        storage_service
        .delete_document(
            missing_id
        ),
        (
            "Managed storage removal for the "
            "missing-storage scenario failed."
        ),
    )


    report = (
        integrity_service.scan()
    )


    assert_true(
        report_contains(
            report,
            "missing_storage",
            missing_id,
        ),
        (
            "A database record without managed "
            "storage should be reported as "
            "MISSING_STORAGE."
        ),
    )


    print(
        "[PASS] Missing storage detected"
    )


    # ======================================================
    # RECONCILIATION MUST NOT TOUCH IT
    # ======================================================

    protected_run = (
        reconciliation_service
        .reconcile_orphans(
            dry_run=False
        )
    )


    protected_ids = {
        item[
            "document_id"
        ]

        for item
        in protected_run[
            "results"
        ]
    }


    assert_false(
        missing_id
        in protected_ids,
        (
            "Reconciliation must never process "
            "a MISSING_STORAGE database "
            "record."
        ),
    )


    assert_true(
        protected_run[
            "protected"
        ][
            "missing_storage"
        ]
        >= 1,
        (
            "Reconciliation should explicitly "
            "report protected missing-storage "
            "records."
        ),
    )


    assert_equal(
        count_documents(
            missing_id
        ),
        1,
        (
            "A MISSING_STORAGE database record "
            "must survive reconciliation."
        ),
    )


    print(
        "[PASS] Reconciliation protected the "
        "missing-storage DB record"
    )


    # ======================================================
    # EXPLICIT DELETION STILL SAFE
    # ======================================================

    result = (
        deletion_service
        .delete_document(
            missing_id
        )
    )


    assert_equal(
        result[
            "status"
        ],
        "DELETED",
        (
            "Explicit deletion should still "
            "succeed."
        ),
    )


    assert_equal(
        result[
            "storage_status"
        ],
        "MISSING",
        (
            "Explicit deletion should report "
            "MISSING storage status."
        ),
    )


    assert_equal(
        count_documents(
            missing_id
        ),
        0,
        (
            "Explicit deletion should remove "
            "the database record."
        ),
    )


    managed_ids.discard(
        missing_id
    )


    print(
        "[PASS] Explicit deletion safely "
        "removed the missing-storage record"
    )


    # ======================================================
    # FINAL MANAGED STORAGE IS CLEAN
    # ======================================================

    remaining = sorted(
        entry.name
        for entry
        in storage_service
        .storage_root
        .iterdir()
    )


    assert_equal(
        remaining,
        [],
        (
            "The isolated managed storage root "
            "should be empty at the end of the "
            "gate."
        ),
    )


    final_report = (
        integrity_service.scan()
    )


    assert_equal(
        final_report[
            "summary"
        ][
            "orphan_storage"
        ],
        0,
        (
            "No orphan storage should remain."
        ),
    )


    print(
        "[PASS] Final managed storage is "
        "clean"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.8 - FINAL PRODUCTION "
        "READINESS END-TO-END TEST"
    )
    print("=" * 76)


    client = None


    managed_ids: set[str] = (
        set()
    )


    # ======================================================
    # SNAPSHOT APPLICATION STATE
    # ======================================================

    state_attributes = (
        "pipeline",
        "persistence",
        "document_query",
        "human_review",
        "reviewer_identity",
        "readiness",
    )


    original_state = {
        attribute:
            getattr(
                app.state,
                attribute,
                None,
            )

        for attribute
        in state_attributes
    }


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_root = (
            temp_root
            / "documents"
        )


        # ==================================================
        # ISOLATED SERVICES
        # ==================================================

        storage_service = (
            DocumentStorageService(
                storage_root=(
                    storage_root
                )
            )
        )


        persistence_service = (
            PersistenceService(
                storage_service=(
                    storage_service
                )
            )
        )


        integrity_service = (
            StorageIntegrityService(
                storage_service=(
                    storage_service
                )
            )
        )


        reconciliation_service = (
            StorageReconciliationService(
                storage_service=(
                    storage_service
                ),

                integrity_service=(
                    integrity_service
                ),
            )
        )


        deletion_service = (
            DocumentDeletionService(
                storage_service=(
                    storage_service
                )
            )
        )


        pipeline = (
            TrackingFakePipeline()
        )


        document_query = (
            DocumentQueryService()
        )


        readiness_service = (
            ReadinessService()
        )


        source_path = (
            temp_root
            / "source.jpg"
        )


        source_path.write_bytes(
            TEST_BYTES
        )


        try:

            # ==============================================
            # WIRE APPLICATION STATE
            # ==============================================

            app.state.pipeline = (
                pipeline
            )


            app.state.persistence = (
                persistence_service
            )


            app.state.document_query = (
                document_query
            )


            app.state.human_review = (
                HumanReviewService()
            )


            app.state.reviewer_identity = (
                ReviewerIdentityService(
                    mode="trusted_headers"
                )
            )


            app.state.readiness = (
                readiness_service
            )


            client = TestClient(
                app,
                raise_server_exceptions=False,
            )


            print()
            print(
                "[OK] Final production "
                "readiness services "
                "initialized"
            )


            # ==============================================
            # SECTIONS
            # ==============================================

            section_liveness_and_readiness(
                client
            )


            document_id = (
                section_upload_and_persistence(
                    client,
                    pipeline,
                    storage_service,
                    integrity_service,
                    managed_ids,
                )
            )


            section_review_and_final_record(
                client,
                document_id,
            )


            section_errors_and_logging(
                client,
                document_query,
            )


            section_readiness_failure(
                client,
                readiness_service,
            )


            section_storage_lifecycle(
                client,
                storage_service,
                persistence_service,
                integrity_service,
                reconciliation_service,
                deletion_service,
                source_path,
                document_id,
                managed_ids,
            )


            # ==============================================
            # FINAL GATE
            # ==============================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.8 FINAL "
                "PRODUCTION READINESS "
                "END-TO-END TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==============================================
            # CLIENT CLEANUP
            # ==============================================

            if client is not None:

                client.close()


            # ==============================================
            # DATABASE CLEANUP
            # ==============================================
            #
            # Only documents created by this test are
            # removed.
            # ==============================================

            remove_test_documents(
                managed_ids
            )


            # ==============================================
            # RESTORE APPLICATION STATE
            # ==============================================

            for (
                attribute,
                original_value,
            ) in original_state.items():

                if original_value is not None:

                    setattr(
                        app.state,
                        attribute,
                        original_value,
                    )


                elif hasattr(
                    app.state,
                    attribute,
                ):

                    delattr(
                        app.state,
                        attribute,
                    )


            print()
            print(
                "[CLEANUP] Phase 7C.8 "
                "temporary documents, storage "
                "and API state removed."
            )


if __name__ == "__main__":

    main()
