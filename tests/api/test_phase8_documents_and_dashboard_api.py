import json
import tempfile

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    select,
)

from backend.app.main import (
    app,
)

from backend.app.api.request_context import (
    REQUEST_ID_HEADER,
)

from backend.app.services.final_record_service import (
    FinalRecordService,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from database.summary_repositories import (
    DocumentSummaryRepository,
)


# ==========================================================
# PHASE 8.6A / 8.8A
# DOCUMENTS LIST + DASHBOARD SUMMARY API TEST
# ==========================================================
#
# Fixtures are created through PersistenceService, so the
# persisted JSONB has exactly the shape production writes.
# Nothing is hand-inserted.
#
# Every assertion is scoped to this test's own documents by
# filename prefix or by document id, because the development
# database contains unrelated rows. A test that asserted a
# global total would be measuring residue.
#
# Storage uses an isolated temporary root. Only rows this
# test created are removed.
# ==========================================================

MARKER = "phase8api"


TEST_BYTES = (
    b"VIGILOX-PHASE8-DOCUMENTS-API-FIXTURE"
)


REVIEWER_ID = (
    "phase8-api-reviewer"
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
# FIXTURE PIPELINE RESULT
# ==========================================================

def build_pipeline_result(
    *,
    decision: str,
    priority: str,
    expiry_status: str,
    expiry_value,
    document_type: str,
):

    return {
        "extraction": {
            "document_type":
                document_type,

            "full_name": {
                "value":
                    "SAMPLE,PHASE8",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P8-0001",

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
                    expiry_value,

                "source_line_ids": (
                    [
                        "L2"
                    ]
                    if expiry_value
                    else []
                ),
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
                    "SAMPLE,PHASE8",

                "confidence":
                    0.99,

                "bbox":
                    [1, 1, 2, 2],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "P8-0001",

                "confidence":
                    0.99,

                "bbox":
                    [1, 1, 2, 2],
            },

            {
                "line_id":
                    "L2",

                "text":
                    "EXPIRY",

                "confidence":
                    0.99,

                "bbox":
                    [1, 1, 2, 2],
            },

            {
                "line_id":
                    "L3",

                "text":
                    "VIGILOX TEST AUTHORITY",

                "confidence":
                    0.99,

                "bbox":
                    [1, 1, 2, 2],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name": {
                "value":
                    "SAMPLE,PHASE8",

                "status":
                    "VALID",

                "confidence":
                    0.99,
            },
        },

        "date_validation": {
            "reference_date":
                "2026-08-20",

            "date_fields":
                {},

            "expiry": {
                "value":
                    expiry_value,

                "status":
                    expiry_status,

                "days_until_expiry":
                    None,
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {
            "document_type":
                document_type,

            "valid":
                True,

            "has_anomalies":
                False,

            "error_count":
                0,

            "warning_count":
                0,

            "issues":
                [],
        },

        "review_decision": {
            "decision":
                decision,

            "review_required":
                decision == "REVIEW_REQUIRED",

            "priority":
                priority,

            "reason_codes":
                [],

            "issues":
                [],
        },
    }


# ==========================================================
# FIXTURE SET
# ==========================================================
#
# Six documents covering every final state the system can
# produce, plus a variety of document types, priorities and
# expiry statuses.
# ==========================================================

FIXTURES = (
    {
        "label": "auto",
        "document_type": "guard_license",
        "decision": "AUTO_ACCEPT",
        "priority": "LOW",
        "expiry_status": "ACTIVE",
        "expiry_value": "2030-01-01",
        "human_action": None,
        "expected_final_state": "AUTO_ACCEPTED",
    },
    {
        "label": "pending_high",
        "document_type": "guard_license",
        "decision": "REVIEW_REQUIRED",
        "priority": "HIGH",
        "expiry_status": "EXPIRED",
        "expiry_value": "2020-01-01",
        "human_action": None,
        "expected_final_state": "PENDING_REVIEW",
    },
    {
        "label": "pending_medium",
        "document_type": "sia_badge",
        "decision": "REVIEW_REQUIRED",
        "priority": "MEDIUM",
        "expiry_status": "EXPIRING_SOON",
        "expiry_value": "2026-09-01",
        "human_action": None,
        "expected_final_state": "PENDING_REVIEW",
    },
    {
        "label": "approved",
        "document_type": "id_card",
        "decision": "REVIEW_REQUIRED",
        "priority": "LOW",
        "expiry_status": "NOT_AVAILABLE",
        "expiry_value": None,
        "human_action": "APPROVE",
        "expected_final_state": "APPROVED",
    },
    {
        "label": "corrected",
        "document_type": "guard_license",
        "decision": "REVIEW_REQUIRED",
        "priority": "HIGH",
        "expiry_status": "EXPIRED",
        "expiry_value": "2019-05-05",
        "human_action": "CORRECT",
        "expected_final_state": "CORRECTED",
    },
    {
        "label": "rejected",
        "document_type": "sia_badge",
        "decision": "REVIEW_REQUIRED",
        "priority": "MEDIUM",
        "expiry_status": "EXPIRES_TODAY",
        "expiry_value": "2026-08-20",
        "human_action": "REJECT",
        "expected_final_state": "REJECTED",
    },
)


def create_fixtures(
    persistence,
    source_path,
) -> dict:

    created = {}


    for fixture in FIXTURES:

        filename = (
            f"{MARKER}_{fixture['label']}.jpg"
        )


        stored = (
            persistence
            .save_processed_document(
                original_filename=(
                    filename
                ),

                content_type=(
                    "image/jpeg"
                ),

                pipeline_result=(
                    build_pipeline_result(
                        decision=(
                            fixture["decision"]
                        ),

                        priority=(
                            fixture["priority"]
                        ),

                        expiry_status=(
                            fixture["expiry_status"]
                        ),

                        expiry_value=(
                            fixture["expiry_value"]
                        ),

                        document_type=(
                            fixture["document_type"]
                        ),
                    )
                ),

                source_path=(
                    str(
                        source_path
                    )
                ),
            )
        )


        document_id = (
            stored[
                "document_id"
            ]
        )


        created[
            fixture["label"]
        ] = document_id


        # ==============================================
        # HUMAN REVIEW
        # ==============================================
        #
        # Persisted through PersistenceService so the
        # human_reviews row and its audit event are written
        # exactly as production writes them.
        # ==============================================

        if fixture["human_action"]:

            # ==========================================
            # Built by HumanReviewService, not by hand.
            #
            # That service owns the review_result shape,
            # including reviewed_at and the machine-decision
            # snapshot, so the fixture cannot drift from what
            # production persists.
            # ==========================================

            review_result = (
                HumanReviewService()
                .submit_review(
                    document_id=(
                        document_id
                    ),

                    reviewer_id=(
                        REVIEWER_ID
                    ),

                    review_result=(
                        build_pipeline_result(
                            decision=(
                                fixture["decision"]
                            ),

                            priority=(
                                fixture["priority"]
                            ),

                            expiry_status=(
                                fixture[
                                    "expiry_status"
                                ]
                            ),

                            expiry_value=(
                                fixture[
                                    "expiry_value"
                                ]
                            ),

                            document_type=(
                                fixture[
                                    "document_type"
                                ]
                            ),
                        )["review_decision"]
                    ),

                    action=(
                        fixture["human_action"]
                    ),

                    notes=(
                        "phase8 api fixture"
                    ),

                    corrections=(
                        {
                            "full_name":
                                "CORRECTED,PHASE8"
                        }
                        if fixture["human_action"]
                        == "CORRECT"
                        else None
                    ),
                )
            )


            persistence.save_human_review(
                review_result=(
                    review_result
                )
            )


    return created


def remove_fixtures(
    document_ids,
):

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
# SCOPING HELPERS
# ==========================================================

def own_items(
    payload,
    created,
):

    """Only the documents this test created."""

    ids = set(
        created.values()
    )


    return [
        item
        for item in payload[
            "items"
        ]
        if item["document_id"] in ids
    ]


def fetch_all_own(
    client,
    created,
    query: str = "",
):

    """
    Fetch every page and return this test's own items.

    Uses search=MARKER so the filter happens in SQL rather
    than by pulling the whole table into the test.
    """

    collected = []
    page = 1


    while True:

        response = (
            client.get(
                "/api/v1/documents"
                f"?search={MARKER}"
                f"&page={page}"
                "&page_size=100"
                + query
            )
        )


        assert_equal(
            response.status_code,
            200,
            "Document list should return 200.",
        )


        payload = (
            response.json()
        )


        collected.extend(
            own_items(
                payload,
                created,
            )
        )


        if page >= payload["total_pages"]:
            break

        page += 1


    return collected


# ==========================================================
# TEST 1 — LIST SHAPE AND SUMMARY-ONLY PAYLOAD
# ==========================================================

def test_list_shape_and_no_detail_leak(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - LIST SHAPE AND "
        "SUMMARY-ONLY PAYLOAD"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/documents"
            f"?search={MARKER}"
        )
    )


    assert_equal(
        response.status_code,
        200,
        "Document list should return 200.",
    )


    payload = (
        response.json()
    )


    for key in (
        "status",
        "items",
        "total",
        "page",
        "page_size",
        "total_pages",
    ):

        assert_true(
            key in payload,
            (
                "Pagination metadata is missing "
                f"{key}."
            ),
        )


    print(
        "[PASS] Response exposes items and "
        "pagination metadata"
    )


    mine = (
        own_items(
            payload,
            created,
        )
    )


    assert_equal(
        len(
            mine
        ),
        len(
            FIXTURES
        ),
        (
            "Search should return every fixture "
            "document."
        ),
    )


    print(
        f"[PASS] All {len(FIXTURES)} fixture "
        "documents returned"
    )


    # ======================================================
    # NO DETAIL PAYLOAD
    # ======================================================
    #
    # A summary index must not carry document contents.
    # ======================================================

    forbidden_keys = (
        "extraction",
        "ocr_lines",
        "field_confidence",
        "evidence_flags",
        "anomaly_validation",
        "date_validation",
        "review_decision",
        "audit_events",
        "corrections",
        "notes",
    )


    item = (
        mine[
            0
        ]
    )


    for key in forbidden_keys:

        assert_false(
            key in item,
            (
                "The document summary must not "
                f"expose detail payload: {key}"
            ),
        )


    print(
        f"[PASS] None of {len(forbidden_keys)} "
        "detail payloads exposed"
    )


    # ======================================================
    # NO DOCUMENT CONTENT ANYWHERE IN THE RESPONSE
    # ======================================================

    serialized = (
        json.dumps(
            payload
        )
    )


    for leaked in (
        "SAMPLE,PHASE8",
        "VIGILOX TEST AUTHORITY",
        "L0",
        "phase8 api fixture",
    ):

        assert_false(
            leaked in serialized,
            (
                "Extracted document content "
                "leaked into the summary list: "
                f"{leaked}"
            ),
        )


    print(
        "[PASS] No OCR or extracted content in "
        "the summary response"
    )


    # ======================================================
    # NO OVERALL CONFIDENCE INVENTED
    # ======================================================

    for key in item.keys():

        assert_false(
            "confidence" in key.lower(),
            (
                "An overall confidence field "
                "appeared. field_confidence is "
                "per-field only and this codebase "
                "defines no authoritative overall "
                f"value: {key}"
            ),
        )


    print(
        "[PASS] No invented overall-confidence "
        "field"
    )


    # ======================================================
    # REQUEST ID
    # ======================================================

    assert_true(
        response.headers.get(
            REQUEST_ID_HEADER
        )
        is not None,
        (
            "Response should carry a correlation "
            "ID header."
        ),
    )


    print(
        "[PASS] Correlation ID header present"
    )


# ==========================================================
# TEST 2 — FINAL STATE CONSISTENCY
# ==========================================================

def test_final_state_consistency(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - FINAL STATE CONSISTENCY"
    )
    print("-" * 76)


    mine = (
        fetch_all_own(
            client,
            created,
        )
    )


    by_id = {
        item["document_id"]: item
        for item in mine
    }


    for fixture in FIXTURES:

        document_id = (
            created[
                fixture["label"]
            ]
        )


        item = (
            by_id[
                document_id
            ]
        )


        assert_equal(
            item["final_state"],
            fixture["expected_final_state"],
            (
                "Unexpected final_state for "
                f"fixture {fixture['label']}."
            ),
        )


    print(
        "[PASS] All 5 final states resolve "
        "correctly in the list"
    )


    # ======================================================
    # AGREES WITH THE DETAIL READ PATH
    # ======================================================
    #
    # The list must never contradict the document detail
    # endpoint, which builds the final record through
    # FinalRecordService.
    # ======================================================

    for fixture in FIXTURES:

        document_id = (
            created[
                fixture["label"]
            ]
        )


        detail = (
            client.get(
                f"/api/v1/documents/{document_id}"
            )
            .json()
        )


        detail_state = (
            detail[
                "final_record"
            ][
                "final_status"
            ]
        )


        assert_equal(
            by_id[
                document_id
            ][
                "final_state"
            ],
            detail_state,
            (
                "The list and the detail read "
                "path disagree about final state "
                f"for {fixture['label']}."
            ),
        )


    print(
        "[PASS] List final_state matches the "
        "document detail read path exactly"
    )


    # ======================================================
    # REVIEWED FLAGS
    # ======================================================

    for fixture in FIXTURES:

        item = (
            by_id[
                created[
                    fixture["label"]
                ]
            ]
        )


        expected_reviewed = (
            fixture["human_action"]
            is not None
        )


        assert_equal(
            item["is_reviewed"],
            expected_reviewed,
            (
                "Unexpected is_reviewed for "
                f"{fixture['label']}."
            ),
        )


        assert_equal(
            item["human_review_action"],
            fixture["human_action"],
            (
                "Unexpected human_review_action "
                f"for {fixture['label']}."
            ),
        )


        if expected_reviewed:

            assert_equal(
                item["reviewer_id"],
                REVIEWER_ID,
                (
                    "Reviewed document should "
                    "report its reviewer."
                ),
            )


            assert_true(
                item["reviewed_at"]
                is not None,
                (
                    "Reviewed document should "
                    "report a review timestamp."
                ),
            )


    print(
        "[PASS] Reviewed and unreviewed "
        "documents map correctly"
    )


# ==========================================================
# TEST 3 — FILTERS
# ==========================================================

def test_filters(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - FILTERS"
    )
    print("-" * 76)


    # ======================================================
    # FINAL STATE
    # ======================================================

    for fixture in FIXTURES:

        state = (
            fixture["expected_final_state"]
        )


        items = (
            fetch_all_own(
                client,
                created,
                f"&final_state={state}",
            )
        )


        for item in items:

            assert_equal(
                item["final_state"],
                state,
                (
                    "final_state filter returned "
                    "a document in a different "
                    "state."
                ),
            )


        expected_ids = {
            created[f["label"]]
            for f in FIXTURES
            if f["expected_final_state"] == state
        }


        assert_equal(
            {
                i["document_id"]
                for i in items
            },
            expected_ids,
            (
                "final_state filter returned the "
                f"wrong set for {state}."
            ),
        )


    print(
        "[PASS] final_state filter correct for "
        "all 5 states"
    )


    # ======================================================
    # DOCUMENT TYPE
    # ======================================================

    for document_type in (
        "guard_license",
        "sia_badge",
        "id_card",
    ):

        items = (
            fetch_all_own(
                client,
                created,
                f"&document_type={document_type}",
            )
        )


        expected = {
            created[f["label"]]
            for f in FIXTURES
            if f["document_type"] == document_type
        }


        assert_equal(
            {
                i["document_id"]
                for i in items
            },
            expected,
            (
                "document_type filter returned "
                f"the wrong set for "
                f"{document_type}."
            ),
        )


    print(
        "[PASS] document_type filter correct"
    )


    # ======================================================
    # MACHINE DECISION
    # ======================================================

    items = (
        fetch_all_own(
            client,
            created,
            "&machine_decision=AUTO_ACCEPT",
        )
    )


    assert_equal(
        {
            i["document_id"]
            for i in items
        },
        {
            created["auto"]
        },
        (
            "machine_decision filter returned "
            "the wrong set."
        ),
    )


    print(
        "[PASS] machine_decision filter correct"
    )


    # ======================================================
    # EXPIRY STATUS
    # ======================================================
    #
    # Uses the real validator vocabulary. ACTIVE and
    # NOT_AVAILABLE exist; VALID and UNKNOWN do not.
    # ======================================================

    for expiry_status in (
        "EXPIRED",
        "EXPIRES_TODAY",
        "EXPIRING_SOON",
        "ACTIVE",
        "NOT_AVAILABLE",
    ):

        items = (
            fetch_all_own(
                client,
                created,
                f"&expiry_status={expiry_status}",
            )
        )


        expected = {
            created[f["label"]]
            for f in FIXTURES
            if f["expiry_status"] == expiry_status
        }


        assert_equal(
            {
                i["document_id"]
                for i in items
            },
            expected,
            (
                "expiry_status filter returned "
                f"the wrong set for "
                f"{expiry_status}."
            ),
        )


    print(
        "[PASS] expiry_status filter correct for "
        "all 5 real statuses"
    )


# ==========================================================
# TEST 4 — SEARCH
# ==========================================================

def test_search(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - SEARCH"
    )
    print("-" * 76)


    # ======================================================
    # FILENAME
    # ======================================================

    response = (
        client.get(
            "/api/v1/documents"
            f"?search={MARKER}_corrected"
        )
    )


    items = (
        own_items(
            response.json(),
            created,
        )
    )


    assert_equal(
        {
            i["document_id"]
            for i in items
        },
        {
            created["corrected"]
        },
        (
            "Filename search returned the wrong "
            "set."
        ),
    )


    print(
        "[PASS] Search matches filename"
    )


    # ======================================================
    # DOCUMENT ID
    # ======================================================

    target = (
        created["approved"]
    )


    response = (
        client.get(
            "/api/v1/documents"
            f"?search={target}"
        )
    )


    items = (
        own_items(
            response.json(),
            created,
        )
    )


    assert_equal(
        {
            i["document_id"]
            for i in items
        },
        {
            target
        },
        (
            "Document id search returned the "
            "wrong set."
        ),
    )


    print(
        "[PASS] Search matches document id"
    )


    # ======================================================
    # DOCUMENT CONTENT IS NOT SEARCHABLE
    # ======================================================
    #
    # Searching an extracted value must not find anything.
    # OCR and extracted values are personal data and the
    # summary index deliberately does not index them.
    # ======================================================

    response = (
        client.get(
            "/api/v1/documents"
            "?search=SAMPLE,PHASE8"
        )
    )


    items = (
        own_items(
            response.json(),
            created,
        )
    )


    assert_equal(
        items,
        [],
        (
            "Search reached extracted document "
            "content. Search must be limited to "
            "filename and document id."
        ),
    )


    print(
        "[PASS] Search does not reach OCR or "
        "extracted values"
    )


    # ======================================================
    # NO RESULTS
    # ======================================================

    response = (
        client.get(
            "/api/v1/documents"
            "?search=zzz-no-such-document-zzz"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "A search with no matches is not an "
            "error."
        ),
    )


    assert_equal(
        response.json()["items"],
        [],
        (
            "A search with no matches should "
            "return an empty list."
        ),
    )


    print(
        "[PASS] Empty search result is a clean "
        "empty list"
    )


    # ======================================================
    # SQL INJECTION ATTEMPT
    # ======================================================

    for hostile in (
        "'; DROP TABLE documents; --",
        "%' OR '1'='1",
        "100%",
    ):

        response = (
            client.get(
                "/api/v1/documents",
                params={
                    "search": hostile,
                },
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "A hostile search term should be "
                "bound as a parameter, not "
                "executed: "
                f"{hostile}"
            ),
        )


    with SessionLocal() as session:

        surviving = (
            session.scalars(
                select(
                    DocumentModel
                )
                .limit(
                    1
                )
            )
            .first()
        )


    assert_true(
        surviving is not None,
        (
            "The documents table did not survive "
            "the injection attempt."
        ),
    )


    print(
        "[PASS] Hostile search terms are bound "
        "safely, not executed"
    )


# ==========================================================
# TEST 5 — PAGINATION AND ORDERING
# ==========================================================

def test_pagination_and_ordering(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - PAGINATION AND ORDERING"
    )
    print("-" * 76)


    # ======================================================
    # PAGE WALK
    # ======================================================
    #
    # Walking one item at a time must visit every fixture
    # exactly once. A missing tiebreak in the ORDER BY would
    # show up here as a duplicate or a gap.
    # ======================================================

    seen = []
    page = 1


    while True:

        payload = (
            client.get(
                "/api/v1/documents"
                f"?search={MARKER}"
                f"&page={page}"
                "&page_size=1"
            )
            .json()
        )


        assert_equal(
            payload["page_size"],
            1,
            "page_size should be echoed back.",
        )


        seen.extend(
            item["document_id"]
            for item in payload["items"]
        )


        if page >= payload["total_pages"]:
            break


        page += 1


    own = [
        d
        for d in seen
        if d in set(
            created.values()
        )
    ]


    assert_equal(
        len(
            own
        ),
        len(
            set(
                own
            )
        ),
        (
            "Paging returned a duplicate "
            "document. Ordering is not "
            "deterministic."
        ),
    )


    assert_equal(
        set(
            own
        ),
        set(
            created.values()
        ),
        (
            "Paging did not visit every document "
            "exactly once."
        ),
    )


    print(
        f"[PASS] Page walk visited all "
        f"{len(FIXTURES)} documents once, no "
        "duplicates or gaps"
    )


    # ======================================================
    # total_pages ARITHMETIC
    # ======================================================

    payload = (
        client.get(
            "/api/v1/documents"
            f"?search={MARKER}"
            "&page_size=4"
        )
        .json()
    )


    expected_pages = (
        (
            payload["total"]
            + 4
            - 1
        )
        // 4
    )


    assert_equal(
        payload["total_pages"],
        expected_pages,
        (
            "total_pages arithmetic is wrong."
        ),
    )


    print(
        "[PASS] total_pages arithmetic correct"
    )


    # ======================================================
    # BEYOND THE LAST PAGE
    # ======================================================

    payload = (
        client.get(
            "/api/v1/documents"
            f"?search={MARKER}"
            "&page=9999"
        )
        .json()
    )


    assert_equal(
        payload["items"],
        [],
        (
            "A page beyond the end should be "
            "empty, not an error."
        ),
    )


    print(
        "[PASS] Page beyond the end returns an "
        "empty page"
    )


    # ======================================================
    # SORTING
    # ======================================================

    for sort_field in (
        DocumentSummaryRepository.SORTABLE
    ):

        for direction in (
            "asc",
            "desc",
        ):

            response = (
                client.get(
                    "/api/v1/documents"
                    f"?search={MARKER}"
                    f"&sort={sort_field}"
                    f"&direction={direction}"
                    "&page_size=100"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Whitelisted sort should be "
                    f"accepted: {sort_field} "
                    f"{direction}"
                ),
            )


    print(
        f"[PASS] All "
        f"{len(DocumentSummaryRepository.SORTABLE)} "
        "whitelisted sort fields work in both "
        "directions"
    )


    # ======================================================
    # FILENAME SORT IS ACTUALLY SORTED
    # ======================================================

    items = (
        client.get(
            "/api/v1/documents"
            f"?search={MARKER}"
            "&sort=filename"
            "&direction=asc"
            "&page_size=100"
        )
        .json()["items"]
    )


    names = [
        i["filename"]
        for i in items
    ]


    assert_equal(
        names,
        sorted(
            names
        ),
        (
            "Ascending filename sort did not "
            "return sorted filenames."
        ),
    )


    print(
        "[PASS] Sort direction is actually "
        "applied"
    )


# ==========================================================
# TEST 6 — NO N+1 QUERIES
# ==========================================================

def test_no_n_plus_one(
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - QUERY COUNT"
    )
    print("-" * 76)


    # ======================================================
    # Counts real statements via a SQLAlchemy event hook.
    #
    # A page of N documents must not cost O(N) queries.
    # ======================================================

    from sqlalchemy import event
    from database.database import engine

    executed = []


    def record(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):

        executed.append(
            statement
        )


    event.listen(
        engine,
        "before_cursor_execute",
        record,
    )


    try:

        service = (
            DocumentQueryService()
        )


        executed.clear()


        result = (
            service.list_documents(
                page=1,
                page_size=100,
                search=MARKER,
            )
        )


        query_count = (
            len(
                executed
            )
        )


        row_count = (
            len(
                result["items"]
            )
        )


    finally:

        event.remove(
            engine,
            "before_cursor_execute",
            record,
        )


    print(
        f"       {row_count} documents returned "
        f"in {query_count} SQL statements"
    )


    # One count query plus one list query. A small constant
    # allowance covers connection-level statements.
    assert_true(
        query_count <= 4,
        (
            f"{row_count} documents cost "
            f"{query_count} SQL statements. The "
            "list must not issue a query per "
            "document."
        ),
    )


    assert_true(
        row_count >= len(
            FIXTURES
        ),
        (
            "The query-count check did not "
            "actually return the fixtures."
        ),
    )


    print(
        "[PASS] Constant query count, no N+1"
    )


# ==========================================================
# TEST 7 — DASHBOARD SUMMARY
# ==========================================================

def test_dashboard_summary(
    client,
    created,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - DASHBOARD SUMMARY"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/dashboard/summary"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Dashboard summary should return "
            "200."
        ),
    )


    payload = (
        response.json()
    )


    for key in (
        "total_documents",
        "review",
        "expiry",
        "pending_review_priority",
        "recent_documents",
    ):

        assert_true(
            key in payload,
            (
                "Dashboard summary is missing "
                f"{key}."
            ),
        )


    print(
        "[PASS] Dashboard exposes all summary "
        "sections"
    )


    # ======================================================
    # COUNTS INCLUDE THE FIXTURES
    # ======================================================
    #
    # Asserted as lower bounds, because the development
    # database holds unrelated rows. An exact equality here
    # would be asserting on residue.
    # ======================================================

    assert_true(
        payload["total_documents"]
        >= len(
            FIXTURES
        ),
        (
            "total_documents should count at "
            "least the fixture documents."
        ),
    )


    review = (
        payload["review"]
    )


    assert_true(
        review["auto_accepted"] >= 1,
        (
            "The AUTO_ACCEPT fixture should be "
            "counted."
        ),
    )


    assert_true(
        review["approved"] >= 1,
        "The APPROVE fixture should be counted.",
    )


    assert_true(
        review["corrected"] >= 1,
        "The CORRECT fixture should be counted.",
    )


    assert_true(
        review["rejected"] >= 1,
        "The REJECT fixture should be counted.",
    )


    print(
        "[PASS] Machine decision and human "
        "action counts reflect real rows"
    )


    # ======================================================
    # PENDING REVIEW AGREES WITH THE REVIEW QUEUE
    # ======================================================
    #
    # This is the important consistency check. The dashboard
    # must not invent its own definition of pending.
    # ======================================================

    queue_total = (
        client.get(
            "/api/v1/reviews/queue"
        )
        .json()["total"]
    )


    assert_equal(
        review["pending_review"],
        queue_total,
        (
            "Dashboard pending_review disagrees "
            "with GET /api/v1/reviews/queue. The "
            "two must share one definition."
        ),
    )


    print(
        f"[PASS] pending_review ({queue_total}) "
        "matches the review queue exactly"
    )


    # ======================================================
    # PRIORITY BREAKDOWN SUMS TO PENDING
    # ======================================================

    priorities = (
        payload["pending_review_priority"]
    )


    assert_equal(
        priorities["high"]
        + priorities["medium"]
        + priorities["low"],
        review["pending_review"],
        (
            "The pending priority breakdown does "
            "not sum to pending_review."
        ),
    )


    print(
        "[PASS] Priority breakdown sums to "
        "pending_review"
    )


    # ======================================================
    # EXPIRY KEYS MIRROR THE VALIDATOR
    # ======================================================

    expiry = (
        payload["expiry"]
    )


    assert_equal(
        set(
            expiry.keys()
        ),
        {
            "expired",
            "expires_today",
            "expiring_soon",
            "active",
            "not_available",
        },
        (
            "Expiry keys must mirror the five "
            "statuses date_logical_validator "
            "produces."
        ),
    )


    for label in (
        "expired",
        "expires_today",
        "expiring_soon",
        "active",
        "not_available",
    ):

        assert_true(
            expiry[label] >= 1,
            (
                "Each expiry status has a fixture "
                f"and should be counted: {label}"
            ),
        )


    print(
        "[PASS] All 5 real expiry statuses "
        "counted"
    )


    # ======================================================
    # RECENT DOCUMENTS ARE BOUNDED
    # ======================================================

    recent = (
        payload["recent_documents"]
    )


    assert_true(
        len(
            recent
        )
        <= 10,
        (
            "recent_documents must be bounded. "
            f"Got {len(recent)}."
        ),
    )


    print(
        f"[PASS] recent_documents bounded at "
        f"{len(recent)}"
    )


    # ======================================================
    # RECENT REUSES THE LIST ITEM SHAPE
    # ======================================================

    if recent:

        list_item = (
            client.get(
                "/api/v1/documents"
                "?page_size=1"
            )
            .json()["items"][0]
        )


        assert_equal(
            set(
                recent[0].keys()
            ),
            set(
                list_item.keys()
            ),
            (
                "recent_documents must reuse the "
                "Documents list item shape so the "
                "two screens cannot describe a "
                "document differently."
            ),
        )


    print(
        "[PASS] recent_documents reuses the "
        "list item shape"
    )


    # ======================================================
    # NO INVENTED METRICS
    # ======================================================

    serialized = (
        json.dumps(
            payload
        )
        .lower()
    )


    for invented in (
        "accuracy",
        "success_rate",
        "risk_score",
        "sla",
        "average_confidence",
        "overall_confidence",
        "throughput",
        "score",
    ):

        assert_false(
            invented in serialized,
            (
                "The dashboard exposes a metric "
                "this system does not define: "
                f"{invented}"
            ),
        )


    print(
        "[PASS] No invented analytics in the "
        "dashboard payload"
    )


    # ======================================================
    # NO DOCUMENT CONTENT
    # ======================================================

    for leaked in (
        "SAMPLE,PHASE8",
        "VIGILOX TEST AUTHORITY",
    ):

        assert_false(
            leaked in json.dumps(
                payload
            ),
            (
                "Extracted content leaked into "
                f"the dashboard: {leaked}"
            ),
        )


    print(
        "[PASS] No document content in the "
        "dashboard payload"
    )


    assert_true(
        response.headers.get(
            REQUEST_ID_HEADER
        )
        is not None,
        (
            "Dashboard response should carry a "
            "correlation ID."
        ),
    )


    print(
        "[PASS] Correlation ID header present"
    )


# ==========================================================
# TEST 8 — ERROR CONTRACT
# ==========================================================

def test_error_contract(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - ERROR CONTRACT"
    )
    print("-" * 76)


    cases = (
        ("page=0", "INVALID_PAGE"),
        ("page_size=0", "INVALID_PAGE_SIZE"),
        ("page_size=101", "PAGE_SIZE_TOO_LARGE"),
        ("document_type=nope", "INVALID_DOCUMENT_TYPE"),
        ("final_state=NOPE", "INVALID_FINAL_STATE"),
        ("machine_decision=NOPE", "INVALID_MACHINE_DECISION"),
        ("expiry_status=VALID", "INVALID_EXPIRY_STATUS"),
        ("sort=id", "INVALID_SORT_FIELD"),
        ("direction=sideways", "INVALID_SORT_DIRECTION"),
    )


    for (
        query,
        expected_code,
    ) in cases:

        response = (
            client.get(
                f"/api/v1/documents?{query}"
            )
        )


        assert_equal(
            response.status_code,
            400,
            (
                "Invalid parameter should return "
                f"400: {query}"
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body["status"],
            "error",
            "Error envelope should be preserved.",
        )


        assert_true(
            "detail" in body,
            (
                "Legacy detail field should be "
                "preserved."
            ),
        )


        assert_equal(
            body["error"]["code"],
            expected_code,
            (
                "Unexpected error code for "
                f"{query}."
            ),
        )


        header_request_id = (
            response.headers.get(
                REQUEST_ID_HEADER
            )
        )


        assert_equal(
            body["error"]["request_id"],
            header_request_id,
            (
                "error.request_id must match the "
                "response header."
            ),
        )


    print(
        f"[PASS] All {len(cases)} invalid "
        "parameters use the central error "
        "contract with matching request IDs"
    )


    # ======================================================
    # expiry_status=VALID IS REJECTED
    # ======================================================
    #
    # VALID looks plausible but the validator never emits
    # it; the real value is ACTIVE. Accepting it silently
    # would return an always-empty list.
    # ======================================================

    body = (
        client.get(
            "/api/v1/documents"
            "?expiry_status=VALID"
        )
        .json()
    )


    assert_true(
        "ACTIVE" in body["error"]["message"],
        (
            "The rejection message should tell "
            "the caller the real allowed values."
        ),
    )


    print(
        "[PASS] Plausible-but-wrong enum values "
        "are rejected with the real vocabulary"
    )


    # ======================================================
    # NO SQL LEAKED
    # ======================================================

    for query in (
        "sort=id",
        "page=0",
    ):

        serialized = (
            json.dumps(
                client.get(
                    f"/api/v1/documents?{query}"
                )
                .json()
            )
        )


        for forbidden in (
            "SELECT",
            "Traceback",
            "sqlalchemy",
            "psycopg",
        ):

            assert_false(
                forbidden.lower()
                in serialized.lower(),
                (
                    "Database internals leaked "
                    f"into an error: {forbidden}"
                ),
            )


    print(
        "[PASS] No SQL or driver internals in "
        "error responses"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 8.6A / 8.8A - DOCUMENTS LIST "
        "AND DASHBOARD SUMMARY"
    )
    print("=" * 76)


    created = {}


    original_query = (
        getattr(
            app.state,
            "document_query",
            None,
        )
    )


    original_persistence = (
        getattr(
            app.state,
            "persistence",
            None,
        )
    )


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        source_path = (
            temp_root
            / "source.jpg"
        )


        source_path.write_bytes(
            TEST_BYTES
        )


        storage_service = (
            DocumentStorageService(
                storage_root=(
                    temp_root
                    / "documents"
                )
            )
        )


        persistence = (
            PersistenceService(
                storage_service=(
                    storage_service
                )
            )
        )


        client = None


        try:

            created = (
                create_fixtures(
                    persistence,
                    source_path,
                )
            )


            print()
            print(
                f"[OK] {len(created)} fixture "
                "documents created"
            )


            # ==========================================
            # The API reads through its own service, so
            # app.state is wired explicitly rather than
            # relying on the lifespan.
            # ==========================================

            app.state.document_query = (
                DocumentQueryService()
            )


            app.state.persistence = (
                persistence
            )


            client = TestClient(
                app,
                raise_server_exceptions=False,
            )


            test_list_shape_and_no_detail_leak(
                client,
                created,
            )

            test_final_state_consistency(
                client,
                created,
            )

            test_filters(
                client,
                created,
            )

            test_search(
                client,
                created,
            )

            test_pagination_and_ordering(
                client,
                created,
            )

            test_no_n_plus_one(
                created
            )

            test_dashboard_summary(
                client,
                created,
            )

            test_error_contract(
                client
            )


            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 8.6A / 8.8A "
                "DOCUMENTS + DASHBOARD API TEST "
                "PASSED"
            )
            print("=" * 76)


        finally:

            if client is not None:

                client.close()


            remove_fixtures(
                created.values()
            )


            if original_query is not None:

                app.state.document_query = (
                    original_query
                )


            elif hasattr(
                app.state,
                "document_query",
            ):

                delattr(
                    app.state,
                    "document_query",
                )


            if original_persistence is not None:

                app.state.persistence = (
                    original_persistence
                )


            elif hasattr(
                app.state,
                "persistence",
            ):

                delattr(
                    app.state,
                    "persistence",
                )


            print()
            print(
                "[CLEANUP] Phase 8 fixture "
                "documents and API state removed."
            )


if __name__ == "__main__":

    main()
