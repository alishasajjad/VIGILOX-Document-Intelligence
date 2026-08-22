import json
import re
import shutil
import subprocess

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
    ALLOWED_DOCUMENT_TYPES,
    ALLOWED_EXPIRY_STATUSES,
    ALLOWED_MACHINE_DECISIONS,
    ALLOWED_SORT_DIRECTIONS,
    DEFAULT_DOCUMENT_SORT,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LENGTH,
)

from backend.app.services.final_record_service import (
    FinalRecordService,
)

from database.summary_repositories import (
    DocumentSummaryRepository,
)

from tests.dashboard.source_audit import (
    audit_frontend_module,
)


# ==========================================================
# PHASE 8.8B
# PROFESSIONAL DOCUMENTS UI CONTRACT TEST
# ==========================================================
#
# Two halves, as with the Dashboard.
#
# 1. HTTP contracts, through TestClient: the /documents route,
#    its assets, navigation, accessibility markup, and the
#    query contract of GET /api/v1/documents.
#
# 2. Real behaviour, by EXECUTING documents_page.js under Node
#    (tests/dashboard/documents_harness.js).
#
# The behaviours that only running can establish:
#
#     a filter change resets the page number
#     search is debounced, not fired per keystroke
#     an overlapping read is aborted and its stale response
#         discarded, so the table cannot show an older query
#     sort keys are always inside the backend whitelist, even
#         from a hand-edited URL
#     page_size can never exceed MAX_PAGE_SIZE
#     the URL reproduces the view
#     a row without a document_id never links anywhere
#     empty / search-empty / filtered-empty are distinct
#
# THE CLIENT MIRRORS ARE CHECKED AGAINST THE REAL BACKEND
# CONSTANTS, so a change on either side breaks this test
# instead of producing an HTTP 400 in the user's face.
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


HARNESS = (
    PROJECT_ROOT
    / "tests"
    / "dashboard"
    / "documents_harness.js"
)


DOCUMENTS_ROUTE = "/documents"


REQUIRED_ASSETS = (
    "/review/static/js/documents_page.js",
    "/review/static/js/api.js",
    "/review/static/js/common.js",
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/responsive.css",
)


PRODUCT_PAGES = (
    "/dashboard",
    "/upload",
    "/documents",
    "/review",
    "/review/00000000-0000-4000-8000-000000000000",
)


PRIMARY_NAVIGATION = (
    "Dashboard",
    "Upload Document",
    "Documents",
    "Review Queue",
)


# ----------------------------------------------------------
# Values that must never appear in a row on this screen.
# ----------------------------------------------------------

CONTENT_FIELDS = (
    "full_name",
    "licence_number",
    "id_number",
    "date_of_birth",
    "ocr_lines",
    "evidence_flags",
    "extraction",
)


# ==========================================================
# ASSERTIONS
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
# NODE HARNESS
# ==========================================================

def run_harness() -> dict:

    node = (
        shutil.which(
            "node"
        )
    )


    if node is None:

        raise AssertionError(
            (
                "Node is required to execute the "
                "Documents module. Without it this "
                "suite could only pattern-match "
                "source text."
            )
        )


    completed = (
        subprocess.run(
            [
                node,
                str(
                    HARNESS
                ),
            ],

            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(
                PROJECT_ROOT
            ),
        )
    )


    if completed.returncode != 0:

        raise AssertionError(
            (
                "Documents harness failed to run.\n"
                f"{completed.stdout}\n"
                f"{completed.stderr}"
            )
        )


    return json.loads(
        completed.stdout
    )


def assert_no_harness_errors(
    results: dict,
):

    for (
        name,
        value,
    ) in results.items():

        if (
            isinstance(
                value,
                dict,
            )
            and "error" in value
        ):

            raise AssertionError(
                (
                    "Harness check raised: "
                    f"{name}: {value['error']}\n"
                    f"{value.get('stack', '')}"
                )
            )


# ==========================================================
# TEST 1 — ROUTE, ASSETS, EXISTING ROUTES
# ==========================================================

def test_route_and_assets(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - DOCUMENTS ROUTE AND ASSETS"
    )
    print("-" * 76)


    response = (
        client.get(
            DOCUMENTS_ROUTE
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "GET /documents should return "
            "HTTP 200."
        ),
    )


    markup = response.text


    for asset in REQUIRED_ASSETS:

        assert_equal(
            client.get(
                asset
            ).status_code,
            200,
            (
                "Documents asset should resolve: "
                f"{asset}"
            ),
        )


        assert_true(
            asset in markup,
            (
                "Documents page should load "
                f"{asset}"
            ),
        )


    print(
        f"[PASS] Route serves HTML and all "
        f"{len(REQUIRED_ASSETS)} assets resolve"
    )


    # ======================================================
    # DEDICATED MODULE
    # ======================================================

    for foreign in (
        "/review/static/dashboard.js",
        "/review/static/review_detail.js",
        "/review/static/js/dashboard_page.js",
        "/review/static/js/upload.js",
    ):

        assert_false(
            foreign in markup,
            (
                "The Documents page must not load "
                f"another screen's module: {foreign}"
            ),
        )


    print(
        "[PASS] Documents owns documents_page.js "
        "and loads no other screen's module"
    )


    # ======================================================
    # NOTHING ELSE BROKE
    # ======================================================

    for path in (
        "/dashboard",
        "/upload",
        "/review",
        "/health",
        "/health/ready",
    ):

        assert_true(
            client.get(
                path
            ).status_code
            < 400,
            (
                "Adding the Documents page must "
                f"not break {path}."
            ),
        )


    print(
        "[PASS] Existing routes preserved"
    )


# ==========================================================
# TEST 2 — NAVIGATION
# ==========================================================

def test_navigation(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - NAVIGATION"
    )
    print("-" * 76)


    for path in PRODUCT_PAGES:

        markup = (
            client.get(
                path
            )
            .text
        )


        for label in PRIMARY_NAVIGATION:

            assert_true(
                label in markup,
                (
                    "Primary navigation is missing "
                    f"'{label}' on {path}"
                ),
            )


        for destination in (
            "/dashboard",
            "/upload",
            "/documents",
            "/review",
        ):

            assert_true(
                f'href="{destination}"'
                in markup,
                (
                    f"{destination} should be a real "
                    f"link on {path}."
                ),
            )


    print(
        "[PASS] All 4 destinations are real "
        f"links on {len(PRODUCT_PAGES)} pages"
    )


    # ======================================================
    # NOTHING IS PENDING ANY MORE
    # ======================================================

    for path in PRODUCT_PAGES:

        markup = (
            client.get(
                path
            )
            .text
        )


        nav_block = (
            re.search(
                r"<nav[^>]*>(.*?)</nav>",
                markup,
                re.DOTALL,
            )
        )


        assert_true(
            nav_block is not None,
            (
                "Could not locate the navigation "
                f"block on {path}."
            ),
        )


        nav_html = nav_block.group(
            1
        )


        assert_false(
            "is-pending"
            in nav_html,
            (
                "Every primary destination is now "
                "built, so no navigation item "
                f"should still be pending: {path}"
            ),
        )


        assert_false(
            "nav-pending-tag"
            in nav_html,
            (
                "A 'Soon' tag should not survive "
                f"on {path}."
            ),
        )


        # ==================================================
        # ACTIVE ITEM
        # ==================================================

        hrefs = (
            re.findall(
                r'href="([^"]+)"',
                nav_html,
            )
        )


        assert_equal(
            len(
                hrefs
            ),
            4,
            (
                "The primary navigation should be "
                f"exactly four links on {path}."
            ),
        )


        for href in hrefs:

            assert_true(
                client.get(
                    href
                ).status_code
                < 400,
                (
                    "Navigation contains a broken "
                    f"link on {path}: {href}"
                ),
            )


    print(
        "[PASS] No pending items remain and "
        "every navigation link resolves"
    )


    # ======================================================
    # DOCUMENTS IS ACTIVE ON ITS OWN PAGE
    # ======================================================

    documents_nav = (
        re.search(
            r"<nav[^>]*>(.*?)</nav>",
            client.get(
                DOCUMENTS_ROUTE
            )
            .text,
            re.DOTALL,
        )
        .group(
            1
        )
    )


    active = (
        re.search(
            r'href="([^"]+)"[^>]*aria-current="page"',
            documents_nav,
            re.DOTALL,
        )
    )


    assert_true(
        active is not None
        and active.group(
            1
        )
        == "/documents",
        (
            'aria-current="page" should mark the '
            "Documents item on /documents."
        ),
    )


    print(
        "[PASS] Documents is the active item on "
        "its own page"
    )


# ==========================================================
# TEST 3 — CLIENT MIRRORS THE SERVER CONTRACT
# ==========================================================

def test_contract_parity(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - CLIENT / SERVER CONTRACT PARITY"
    )
    print("-" * 76)


    surface = results[
        "module_surface"
    ]


    # ======================================================
    # SORT WHITELIST
    # ======================================================

    assert_equal(
        surface[
            "sort_fields"
        ],
        list(
            DocumentSummaryRepository.SORTABLE
        ),
        (
            "The client sort whitelist must match "
            "DocumentSummaryRepository.SORTABLE "
            "exactly, or a sort control can produce "
            "an HTTP 400 the user did not cause."
        ),
    )


    assert_equal(
        sorted(
            surface[
                "directions"
            ]
        ),
        sorted(
            ALLOWED_SORT_DIRECTIONS
        ),
        (
            "Sort directions must match the API."
        ),
    )


    # ======================================================
    # EVERY SORTABLE COLUMN USES A REAL KEY
    # ======================================================

    for field in surface[
        "sortable_columns"
    ]:

        assert_true(
            field
            in DocumentSummaryRepository.SORTABLE,
            (
                "A sortable column sends a key the "
                f"backend does not support: {field}"
            ),
        )


    assert_equal(
        sorted(
            set(
                surface[
                    "sortable_columns"
                ]
            )
        ),
        sorted(
            DocumentSummaryRepository.SORTABLE
        ),
        (
            "Every sortable backend field should be "
            "reachable from a column header."
        ),
    )


    print(
        f"[PASS] All {len(surface['sort_fields'])} "
        "sort keys and both directions match the "
        "backend whitelist"
    )


    # ======================================================
    # PAGINATION BOUNDS
    # ======================================================

    assert_equal(
        surface[
            "max_page_size"
        ],
        MAX_PAGE_SIZE,
        (
            "The client page-size ceiling must "
            "match MAX_PAGE_SIZE."
        ),
    )


    assert_equal(
        surface[
            "default_page_size"
        ],
        DEFAULT_PAGE_SIZE,
        (
            "The client default page size must "
            "match DEFAULT_PAGE_SIZE."
        ),
    )


    assert_true(
        max(
            surface[
                "page_size_choices"
            ]
        )
        <= MAX_PAGE_SIZE,
        (
            "No offered page size may exceed "
            f"{MAX_PAGE_SIZE}."
        ),
    )


    assert_equal(
        surface[
            "max_search_length"
        ],
        MAX_SEARCH_LENGTH,
        (
            "The client search limit must match "
            "MAX_SEARCH_LENGTH."
        ),
    )


    print(
        "[PASS] Page size, default and search "
        "length all match the API bounds"
    )


    # ======================================================
    # DEBOUNCE IS REAL
    # ======================================================

    assert_true(
        surface[
            "debounce_ms"
        ]
        >= 200,
        (
            "Search should be debounced by a "
            "meaningful interval, not effectively "
            "per keystroke."
        ),
    )


    print(
        "[PASS] Search debounce is "
        f"{surface['debounce_ms']}ms"
    )


# ==========================================================
# TEST 4 — FILTER MARKUP USES ONLY REAL VALUES
# ==========================================================

def test_filter_markup(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - FILTER CONTROLS"
    )
    print("-" * 76)


    markup = (
        client.get(
            DOCUMENTS_ROUTE
        )
        .text
    )


    def option_values(
        select_id: str,
    ) -> set:

        block = (
            re.search(
                (
                    r'<select[^>]*id="'
                    + re.escape(
                        select_id
                    )
                    + r'"(.*?)</select>'
                ),
                markup,
                re.DOTALL,
            )
        )


        assert_true(
            block is not None,
            (
                "Missing filter control: "
                f"{select_id}"
            ),
        )


        return {
            value
            for value in re.findall(
                r'value="([^"]*)"',
                block.group(
                    1
                ),
            )
            if value
        }


    assert_equal(
        option_values(
            "document-type-filter"
        ),
        set(
            ALLOWED_DOCUMENT_TYPES
        ),
        (
            "Document type options must match "
            "ALLOWED_DOCUMENT_TYPES."
        ),
    )


    assert_equal(
        option_values(
            "final-state-filter"
        ),
        set(
            FinalRecordService.FINAL_STATUSES
        ),
        (
            "Final state options must match "
            "FinalRecordService.FINAL_STATUSES."
        ),
    )


    assert_equal(
        option_values(
            "machine-decision-filter"
        ),
        set(
            ALLOWED_MACHINE_DECISIONS
        ),
        (
            "Machine decision options must match "
            "ALLOWED_MACHINE_DECISIONS."
        ),
    )


    assert_equal(
        option_values(
            "expiry-status-filter"
        ),
        set(
            ALLOWED_EXPIRY_STATUSES
        ),
        (
            "Expiry options must match the five "
            "authoritative statuses."
        ),
    )


    print(
        "[PASS] All 4 filters offer exactly the "
        "values the API accepts"
    )


    # ======================================================
    # PAGE SIZE OPTIONS ARE IN RANGE
    # ======================================================

    sizes = {
        int(
            value
        )
        for value in option_values(
            "page-size-select"
        )
    }


    assert_true(
        max(
            sizes
        )
        <= MAX_PAGE_SIZE,
        (
            "A page-size option exceeds "
            f"{MAX_PAGE_SIZE}, which the API "
            "rejects rather than clamps."
        ),
    )


    assert_true(
        DEFAULT_PAGE_SIZE in sizes,
        (
            "The default page size should be "
            "offered."
        ),
    )


    print(
        f"[PASS] Page sizes {sorted(sizes)} are "
        f"all within {MAX_PAGE_SIZE}"
    )


    # ======================================================
    # EVERY CONTROL HAS A REAL LABEL
    # ======================================================

    for control_id in (
        "search-input",
        "document-type-filter",
        "final-state-filter",
        "machine-decision-filter",
        "expiry-status-filter",
        "page-size-select",
    ):

        assert_true(
            f'for="{control_id}"'
            in markup,
            (
                "Every filter control needs a real "
                f"<label for>: {control_id}"
            ),
        )


    print(
        "[PASS] All 6 controls have real labels"
    )


    # ======================================================
    # SEARCH SEMANTICS
    # ======================================================

    assert_true(
        'role="search"'
        in markup,
        (
            "The filter bar should expose "
            'role="search".'
        ),
    )


    assert_true(
        f'maxlength="{MAX_SEARCH_LENGTH}"'
        in markup,
        (
            "The search input should carry the "
            "same length ceiling as the API."
        ),
    )


    print(
        "[PASS] Search landmark and length limit "
        "present"
    )


# ==========================================================
# TEST 5 — API QUERY CONTRACT
# ==========================================================

def test_api_contract(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - DOCUMENTS API CONTRACT"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/documents"
            f"?page=1&page_size=5"
            f"&sort={DEFAULT_DOCUMENT_SORT}"
            "&direction=desc"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "The Documents list endpoint should "
            "return HTTP 200."
        ),
    )


    payload = response.json()


    for key in (
        "items",
        "total",
        "page",
        "page_size",
        "total_pages",
    ):

        assert_true(
            key in payload,
            (
                "The list response is missing "
                f"{key}, which the pager needs."
            ),
        )


    assert_true(
        len(
            payload[
                "items"
            ]
        )
        <= 5,
        (
            "The API must honour page_size."
        ),
    )


    print(
        "[PASS] Paged response carries total, "
        "page, page_size and total_pages"
    )


    # ======================================================
    # THE SUMMARY SCHEMA CARRIES NO DOCUMENT CONTENT
    # ======================================================

    if payload[
        "items"
    ]:

        row_keys = set(
            payload[
                "items"
            ][
                0
            ]
            .keys()
        )


        for field in CONTENT_FIELDS:

            assert_false(
                field in row_keys,
                (
                    "A list row must not carry "
                    f"document content: {field}"
                ),
            )


        print(
            "[PASS] List rows carry metadata only, "
            "no extracted content"
        )


    # ======================================================
    # OVERSIZED PAGE SIZE IS REJECTED, NOT CLAMPED
    # ======================================================

    rejected = (
        client.get(
            "/api/v1/documents"
            f"?page_size={MAX_PAGE_SIZE + 1}"
        )
    )


    assert_equal(
        rejected.status_code,
        400,
        (
            "An oversized page_size should be "
            "rejected so the caller is never told "
            "it received more rows than it did."
        ),
    )


    assert_equal(
        rejected.json()[
            "error"
        ][
            "code"
        ],
        "PAGE_SIZE_TOO_LARGE",
        (
            "The rejection should carry a stable "
            "error code."
        ),
    )


    # ======================================================
    # UNKNOWN SORT KEY IS REJECTED
    # ======================================================

    bad_sort = (
        client.get(
            "/api/v1/documents?sort=reviewer_id"
        )
    )


    assert_equal(
        bad_sort.status_code,
        400,
        (
            "A sort key outside the whitelist "
            "should be rejected."
        ),
    )


    assert_equal(
        bad_sort.json()[
            "error"
        ][
            "code"
        ],
        "INVALID_SORT_FIELD",
        (
            "An invalid sort key should carry a "
            "stable error code."
        ),
    )


    print(
        "[PASS] Oversized page_size and unknown "
        "sort key are both rejected with stable "
        "codes"
    )


    # ======================================================
    # EVERY SORT KEY THE UI CAN SEND ACTUALLY WORKS
    # ======================================================

    for field in DocumentSummaryRepository.SORTABLE:

        for direction in sorted(
            ALLOWED_SORT_DIRECTIONS
        ):

            sorted_response = (
                client.get(
                    "/api/v1/documents"
                    f"?sort={field}"
                    f"&direction={direction}"
                    "&page_size=3"
                )
            )


            assert_equal(
                sorted_response.status_code,
                200,
                (
                    "A whitelisted sort must work: "
                    f"{field} {direction}"
                ),
            )


    print(
        f"[PASS] All "
        f"{len(DocumentSummaryRepository.SORTABLE) * 2} "
        "sort/direction combinations the UI can "
        "send return HTTP 200"
    )


    # ======================================================
    # EVERY FILTER VALUE THE UI OFFERS ACTUALLY WORKS
    # ======================================================

    filter_cases = []

    for value in sorted(
        ALLOWED_DOCUMENT_TYPES
    ):
        filter_cases.append(
            (
                "document_type",
                value,
            )
        )

    for value in sorted(
        FinalRecordService.FINAL_STATUSES
    ):
        filter_cases.append(
            (
                "final_state",
                value,
            )
        )

    for value in sorted(
        ALLOWED_MACHINE_DECISIONS
    ):
        filter_cases.append(
            (
                "machine_decision",
                value,
            )
        )

    for value in sorted(
        ALLOWED_EXPIRY_STATUSES
    ):
        filter_cases.append(
            (
                "expiry_status",
                value,
            )
        )


    for (
        name,
        value,
    ) in filter_cases:

        filtered = (
            client.get(
                "/api/v1/documents"
                f"?{name}={value}&page_size=3"
            )
        )


        assert_equal(
            filtered.status_code,
            200,
            (
                "A filter value the UI offers must "
                f"be accepted: {name}={value}"
            ),
        )


    print(
        f"[PASS] All {len(filter_cases)} filter "
        "values the UI offers return HTTP 200"
    )


# ==========================================================
# TEST 6 — REQUEST BUILDING
# ==========================================================

def test_requests(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - REQUEST BUILDING"
    )
    print("-" * 76)


    initial = results[
        "initial_request"
    ]


    assert_equal(
        initial[
            "request_count"
        ],
        1,
        (
            "A first load should issue exactly one "
            "list request."
        ),
    )


    assert_equal(
        initial[
            "url"
        ],
        (
            "/api/v1/documents"
            "?page=1&page_size=25"
            "&sort=created_at&direction=desc"
        ),
        (
            "The first request should ask for page "
            "1 with the documented defaults, and "
            "should not send empty filters."
        ),
    )


    print(
        "[PASS] First load requests one bounded "
        "page with defaults and no empty filters"
    )


    # ======================================================
    # PAGINATION
    # ======================================================

    pagination = results[
        "pagination"
    ]


    assert_equal(
        pagination[
            "before"
        ][
            "button_count"
        ],
        2,
        (
            "Pagination should offer Previous and "
            "Next."
        ),
    )


    assert_true(
        pagination[
            "before"
        ][
            "previous_disabled"
        ],
        (
            "Previous should be disabled on page "
            "one."
        ),
    )


    assert_false(
        pagination[
            "before"
        ][
            "next_disabled"
        ],
        (
            "Next should be available when more "
            "pages exist."
        ),
    )


    assert_equal(
        pagination[
            "second_request_page"
        ],
        2,
        (
            "Next should request the following "
            "page from the server rather than "
            "slicing rows already downloaded."
        ),
    )


    assert_true(
        "page=2"
        in pagination[
            "second_request_url"
        ],
        (
            "The page number should travel in the "
            "request."
        ),
    )


    last = results[
        "last_page_disables_next"
    ]


    assert_true(
        last[
            "next_disabled"
        ]
        and not last[
            "previous_disabled"
        ],
        (
            "On the last page, Next should be "
            "disabled and Previous available."
        ),
    )


    assert_equal(
        results[
            "single_page_hides_pagination"
        ][
            "child_count"
        ],
        0,
        (
            "A single-page result should render no "
            "pager at all."
        ),
    )


    print(
        "[PASS] Pagination is server-driven and "
        "correctly bounded at both ends"
    )


    # ======================================================
    # PAGE SIZE STAYS IN RANGE
    # ======================================================

    bounded = results[
        "page_size_bounded"
    ]


    assert_true(
        bounded[
            "requested_page_size"
        ]
        <= MAX_PAGE_SIZE,
        (
            "A tampered page-size control must not "
            "produce an oversized request."
        ),
    )


    assert_true(
        max(
            bounded[
                "offered_choices"
            ]
        )
        <= bounded[
            "max"
        ],
        (
            "No offered page size may exceed the "
            "backend maximum."
        ),
    )


    print(
        "[PASS] A page_size of 500 injected into "
        "the control produced a request for "
        f"{bounded['requested_page_size']}"
    )


    # ======================================================
    # FILTER CHANGE RESETS THE PAGE
    # ======================================================

    reset = results[
        "filter_resets_page"
    ]


    assert_equal(
        reset[
            "initial_page"
        ],
        3,
        (
            "The harness should have started on "
            "page 3."
        ),
    )


    assert_equal(
        reset[
            "page_after_filter"
        ],
        1,
        (
            "Changing a filter must reset to page "
            "1. Page 3 of the old result set is "
            "not page 3 of the new one."
        ),
    )


    assert_equal(
        reset[
            "final_state_sent"
        ],
        "REJECTED",
        (
            "The new filter should reach the "
            "server."
        ),
    )


    print(
        "[PASS] A filter change resets page 3 to "
        "page 1 and sends the new filter"
    )


# ==========================================================
# TEST 7 — SEARCH
# ==========================================================

def test_search(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - SEARCH"
    )
    print("-" * 76)


    debounce = results[
        "search_debounce"
    ]


    assert_equal(
        debounce[
            "requests_during_typing"
        ],
        0,
        (
            "Six keystrokes must not produce six "
            "requests."
        ),
    )


    assert_equal(
        debounce[
            "requests_after_debounce"
        ],
        1,
        (
            "After the debounce elapses there "
            "should be exactly one request."
        ),
    )


    assert_equal(
        debounce[
            "search_sent"
        ],
        "guard1",
        (
            "The debounced request should carry "
            "the final search text."
        ),
    )


    print(
        "[PASS] 6 keystrokes produced 0 requests "
        "while typing and exactly 1 afterwards"
    )


    # ======================================================
    # NORMALISATION
    # ======================================================

    normalised = results[
        "search_normalised"
    ]


    assert_true(
        normalised[
            "trimmed"
        ],
        (
            "Surrounding whitespace should be "
            "trimmed before the request."
        ),
    )


    assert_equal(
        normalised[
            "length"
        ],
        MAX_SEARCH_LENGTH,
        (
            "An over-long search should be cut to "
            f"{MAX_SEARCH_LENGTH} rather than "
            "producing SEARCH_TERM_TOO_LONG."
        ),
    )


    print(
        "[PASS] Search is trimmed and capped at "
        f"{MAX_SEARCH_LENGTH} characters"
    )


    # ======================================================
    # CLEAR
    # ======================================================

    cleared = results[
        "clear_search"
    ]


    assert_equal(
        cleared[
            "initial_search"
        ],
        "badge",
        (
            "The harness should have started with "
            "a search term."
        ),
    )


    assert_true(
        cleared[
            "search_after_clear"
        ]
        in (
            None,
            "",
        ),
        (
            "Clear should remove the search from "
            "the request entirely."
        ),
    )


    assert_equal(
        cleared[
            "input_value"
        ],
        "",
        (
            "Clear should also empty the input."
        ),
    )


    assert_false(
        "search="
        in cleared[
            "url"
        ],
        (
            "A cleared search should not linger in "
            "the request URL."
        ),
    )


    print(
        "[PASS] Clear empties the input and drops "
        "search from the request"
    )


    # ======================================================
    # RESET
    # ======================================================

    reset = results[
        "reset_filters"
    ]


    assert_equal(
        reset[
            "after_reset"
        ][
            "page"
        ],
        1,
        (
            "Reset should return to page 1."
        ),
    )


    assert_equal(
        reset[
            "after_reset"
        ][
            "pageSize"
        ],
        DEFAULT_PAGE_SIZE,
        (
            "Reset should restore the default page "
            "size."
        ),
    )


    for key in (
        "search",
        "documentType",
        "finalState",
        "machineDecision",
        "expiryStatus",
    ):

        assert_true(
            reset[
                "after_reset"
            ][
                key
            ]
            in (
                None,
                "",
            ),
            (
                "Reset should clear every filter: "
                f"{key}"
            ),
        )


    assert_equal(
        reset[
            "after_reset"
        ][
            "sort"
        ],
        DEFAULT_DOCUMENT_SORT,
        (
            "Reset should restore the default "
            "sort."
        ),
    )


    assert_equal(
        reset[
            "controls"
        ],
        {
            "search": "",
            "document_type": "",
            "page_size": str(
                DEFAULT_PAGE_SIZE
            ),
        },
        (
            "Reset should also put the visible "
            "controls back, or the screen would "
            "disagree with the request."
        ),
    )


    print(
        "[PASS] Reset restores every parameter "
        "and every visible control"
    )


# ==========================================================
# TEST 8 — SORTING
# ==========================================================

def test_sorting(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - SORTING"
    )
    print("-" * 76)


    sorting = results[
        "sorting"
    ]


    assert_equal(
        sorting[
            "first"
        ][
            "sort"
        ],
        "document_type",
        (
            "Clicking the Type header should sort "
            "by document_type."
        ),
    )


    assert_equal(
        sorting[
            "first"
        ][
            "direction"
        ],
        "desc",
        (
            "A newly selected column should start "
            "descending."
        ),
    )


    assert_equal(
        sorting[
            "second"
        ][
            "direction"
        ],
        "asc",
        (
            "Clicking the same column again should "
            "flip the direction."
        ),
    )


    assert_equal(
        sorting[
            "first"
        ][
            "page"
        ],
        1,
        (
            "Reordering changes which rows land on "
            "page 1, so sorting must reset the "
            "page number."
        ),
    )


    assert_true(
        "ascending"
        in sorting[
            "aria"
        ],
        (
            "The sorted column should expose "
            "aria-sort so assistive technology "
            "can announce the order."
        ),
    )


    assert_equal(
        sorting[
            "aria"
        ]
        .count(
            "ascending"
        )
        + sorting[
            "aria"
        ]
        .count(
            "descending"
        ),
        1,
        (
            "Exactly one column may claim to be "
            "sorted."
        ),
    )


    print(
        "[PASS] Sorting toggles direction, resets "
        "the page and announces aria-sort on one "
        "column only"
    )


    # ======================================================
    # ONLY WHITELISTED KEYS EVER LEAVE THE CLIENT
    # ======================================================

    whitelist = results[
        "sort_only_whitelisted"
    ]


    assert_equal(
        whitelist[
            "request_count"
        ],
        1,
        (
            "Attempting to sort by a key the "
            "backend does not support must not "
            "issue a request at all."
        ),
    )


    assert_equal(
        whitelist[
            "sort_sent"
        ],
        DEFAULT_DOCUMENT_SORT,
        (
            "The sort field should be unchanged "
            "after a rejected attempt."
        ),
    )


    hostile = results[
        "sort_from_hostile_url"
    ]


    assert_equal(
        hostile[
            "sort_sent"
        ],
        DEFAULT_DOCUMENT_SORT,
        (
            "A hand-edited sort parameter must not "
            "reach the server."
        ),
    )


    assert_equal(
        hostile[
            "direction_sent"
        ],
        "desc",
        (
            "A hand-edited direction must not "
            "reach the server."
        ),
    )


    print(
        "[PASS] Unknown sort keys are refused, "
        "including from a hand-edited URL"
    )


# ==========================================================
# TEST 9 — URL STATE
# ==========================================================

def test_url_state(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 9 - URL STATE"
    )
    print("-" * 76)


    url_state = results[
        "url_state"
    ]


    assert_equal(
        url_state[
            "restored"
        ][
            "page"
        ],
        2,
        (
            "The page number should be restored "
            "from the URL."
        ),
    )


    assert_equal(
        url_state[
            "restored"
        ][
            "search"
        ],
        "badge",
        (
            "The search term should be restored "
            "from the URL."
        ),
    )


    assert_equal(
        url_state[
            "restored"
        ][
            "documentType"
        ],
        "sia_badge",
        (
            "Filters should be restored from the "
            "URL."
        ),
    )


    assert_equal(
        url_state[
            "restored"
        ][
            "sort"
        ],
        "filename",
        (
            "Sort should be restored from the URL."
        ),
    )


    assert_equal(
        url_state[
            "control_values"
        ],
        {
            "search": "badge",
            "document_type": "sia_badge",
        },
        (
            "The visible controls must reflect the "
            "restored state, or the screen would "
            "disagree with the request it made."
        ),
    )


    print(
        "[PASS] Page, search, filters and sort all "
        "survive a refresh"
    )


    # ======================================================
    # replaceState, NOT pushState
    # ======================================================

    assert_equal(
        url_state[
            "history_mode"
        ],
        "replace",
        (
            "Adjusting a filter is not a new "
            "place. pushState would force the user "
            "back through every intermediate "
            "keystroke."
        ),
    )


    # ======================================================
    # DEFAULTS STAY OUT OF THE URL
    # ======================================================

    assert_equal(
        results[
            "url_omits_defaults"
        ][
            "url"
        ],
        "/documents",
        (
            "A default view should produce a clean "
            "URL rather than a query string of "
            "defaults."
        ),
    )


    print(
        "[PASS] History is replaced, not pushed, "
        "and defaults stay out of the URL"
    )


# ==========================================================
# TEST 10 — OVERLAPPING READS
# ==========================================================

def test_overlapping_reads(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 10 - OVERLAPPING READS"
    )
    print("-" * 76)


    stale = results[
        "stale_response_discarded"
    ]


    assert_equal(
        stale[
            "request_count"
        ],
        2,
        (
            "The harness should have produced two "
            "overlapping reads."
        ),
    )


    assert_false(
        stale[
            "shows_stale"
        ],
        (
            "A response that arrives after a newer "
            "one must be discarded. Rendering it "
            "would show the results of a query the "
            "user has already replaced."
        ),
    )


    assert_true(
        stale[
            "shows_fresh"
        ],
        (
            "The newest response should be the one "
            "rendered."
        ),
    )


    assert_false(
        "999"
        in stale[
            "status"
        ],
        (
            "The result summary must not come from "
            "the stale response either."
        ),
    )


    print(
        "[PASS] A late-arriving stale response is "
        "discarded, rows and count both"
    )


    # ======================================================
    # THE SUPERSEDED READ IS ACTUALLY CANCELLED
    # ======================================================

    aborted = results[
        "overlapping_read_is_aborted"
    ]


    assert_true(
        aborted[
            "first_signal_aborted"
        ],
        (
            "Starting a new read should abort the "
            "one it supersedes."
        ),
    )


    assert_false(
        aborted[
            "second_signal_aborted"
        ],
        (
            "The current read must not be aborted."
        ),
    )


    # ======================================================
    # AN ABORT IS NOT AN ERROR TO REPORT
    # ======================================================

    assert_true(
        results[
            "abort_is_not_reported_as_error"
        ][
            "error_hidden"
        ],
        (
            "A cancellation is this module's own "
            "doing and must not be shown to the "
            "user as a failure."
        ),
    )


    print(
        "[PASS] The superseded read is cancelled "
        "and its abort is not reported as an error"
    )


# ==========================================================
# TEST 11 — STATES
# ==========================================================

def test_states(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 11 - LOADING / EMPTY / ERROR"
    )
    print("-" * 76)


    loading = results[
        "loading_state"
    ]


    assert_true(
        loading[
            "loading_visible"
        ],
        (
            "A read in flight should show a "
            "loading state."
        ),
    )


    for key in (
        "table_hidden",
        "error_hidden",
        "empty_hidden",
    ):

        assert_true(
            loading[
                key
            ],
            (
                "Only one state may be visible at "
                f"a time: {key}"
            ),
        )


    assert_true(
        loading[
            "skeleton_count"
        ]
        > 0,
        (
            "Loading should render skeleton rows."
        ),
    )


    print(
        f"[PASS] Loading shows "
        f"{loading['skeleton_count']} skeletons "
        "and hides every other state"
    )


    # ======================================================
    # THREE DISTINCT EMPTY STATES
    # ======================================================

    database_empty = results[
        "empty_database"
    ]


    assert_true(
        database_empty[
            "empty_visible"
        ]
        and database_empty[
            "table_hidden"
        ],
        (
            "An empty result should replace the "
            "table."
        ),
    )


    assert_true(
        database_empty[
            "has_upload_cta"
        ],
        (
            "With no documents at all, the empty "
            "state should lead to /upload."
        ),
    )


    assert_equal(
        database_empty[
            "pagination_children"
        ],
        0,
        (
            "No pager should be drawn over an "
            "empty result."
        ),
    )


    search_empty = results[
        "empty_search"
    ]


    assert_true(
        "search"
        in search_empty[
            "text"
        ]
        .lower(),
        (
            "A search that matches nothing should "
            "say so, rather than claiming there "
            "are no documents."
        ),
    )


    assert_equal(
        search_empty[
            "button_labels"
        ],
        [
            "Clear search",
        ],
        (
            "The search-empty state should offer a "
            "way out of the search."
        ),
    )


    assert_equal(
        search_empty[
            "upload_cta"
        ],
        [],
        (
            "Offering Upload to a user whose "
            "search matched nothing is the wrong "
            "next step."
        ),
    )


    filtered_empty = results[
        "empty_filtered"
    ]


    assert_true(
        "filter"
        in filtered_empty[
            "text"
        ]
        .lower(),
        (
            "A filtered-empty result should say "
            "the filters are the reason."
        ),
    )


    assert_equal(
        filtered_empty[
            "button_labels"
        ],
        [
            "Reset filters",
        ],
        (
            "The filtered-empty state should offer "
            "a reset."
        ),
    )


    print(
        "[PASS] Empty, search-empty and "
        "filtered-empty are three distinct states "
        "with the right recovery action"
    )


    # ======================================================
    # RECOVERY ACTUALLY WORKS
    # ======================================================

    recovered = results[
        "empty_search_button_recovers"
    ]


    assert_equal(
        recovered[
            "calls"
        ],
        2,
        (
            "Clearing the search from the empty "
            "state should issue a fresh read."
        ),
    )


    assert_true(
        recovered[
            "table_visible"
        ],
        (
            "Recovering from an empty search "
            "should show the table again."
        ),
    )


    print(
        "[PASS] Clearing the search from the "
        "empty state recovers the table"
    )


    # ======================================================
    # ERROR
    # ======================================================

    error = results[
        "error_state"
    ]


    assert_true(
        error[
            "error_visible"
        ]
        and error[
            "table_hidden"
        ],
        (
            "A failed read should replace the "
            "table."
        ),
    )


    for key, description in (
        (
            "shows_code",
            "error.code",
        ),
        (
            "shows_message",
            "error.message",
        ),
        (
            "shows_request_id",
            "error.request_id",
        ),
    ):

        assert_true(
            error[
                key
            ],
            (
                "The error state should surface "
                f"{description}."
            ),
        )


    assert_false(
        error[
            "mentions_traceback"
        ],
        (
            "The UI must never imply a stack "
            "trace."
        ),
    )


    assert_equal(
        error[
            "retry_buttons"
        ],
        1,
        (
            "There should be exactly one Retry."
        ),
    )


    assert_equal(
        error[
            "status_cleared"
        ],
        "",
        (
            "A stale result count must not survive "
            "an error."
        ),
    )


    assert_equal(
        error[
            "pagination_cleared"
        ],
        0,
        (
            "A stale pager must not survive an "
            "error."
        ),
    )


    assert_equal(
        results[
            "error_retry_recovers"
        ][
            "calls"
        ],
        2,
        (
            "Retry should issue a second read."
        ),
    )


    assert_true(
        results[
            "error_retry_recovers"
        ][
            "table_visible"
        ],
        (
            "A successful retry should restore the "
            "table."
        ),
    )


    print(
        "[PASS] Error shows the structured "
        "contract, clears stale count and pager, "
        "and Retry recovers"
    )


# ==========================================================
# TEST 12 — SAFE RENDERING, PRIVACY, KEYBOARD
# ==========================================================

def test_safety_and_accessibility(
    results: dict,
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 12 - SAFETY AND ACCESSIBILITY"
    )
    print("-" * 76)


    # ======================================================
    # SAFE DOCUMENT LINKS
    # ======================================================

    missing = results[
        "missing_document_id_is_safe"
    ]


    assert_equal(
        missing[
            "hrefs"
        ],
        [],
        (
            "A row without a document_id must not "
            "render a link."
        ),
    )


    assert_false(
        missing[
            "builds_undefined"
        ],
        (
            "/review/undefined must be "
            "impossible."
        ),
    )


    print(
        "[PASS] A row without an id renders no "
        "link at all"
    )


    # ======================================================
    # UNTRUSTED FILENAME
    # ======================================================

    hostile = results[
        "hostile_filename_is_text"
    ]


    assert_true(
        hostile[
            "renders_literally"
        ],
        (
            "A hostile filename should survive as "
            "literal text."
        ),
    )


    assert_equal(
        hostile[
            "script_elements"
        ],
        0,
        (
            "A filename must never be parsed as "
            "markup."
        ),
    )


    print(
        "[PASS] A filename containing a script "
        "tag renders as text and creates no "
        "element"
    )


    # ======================================================
    # NO DOCUMENT CONTENT IN A ROW
    # ======================================================

    privacy = results[
        "no_personal_data"
    ]


    for key, description in (
        (
            "leaks_name",
            "full name",
        ),
        (
            "leaks_id",
            "ID number",
        ),
        (
            "leaks_licence",
            "licence number",
        ),
        (
            "leaks_dob",
            "date of birth",
        ),
        (
            "leaks_ocr",
            "OCR text",
        ),
    ):

        assert_false(
            privacy[
                key
            ],
            (
                "A document list row must not "
                f"render the {description}."
            ),
        )


    print(
        "[PASS] No extracted content is rendered "
        "in a list row"
    )


    # ======================================================
    # KEYBOARD
    # ======================================================

    keyboard = results[
        "keyboard_controls"
    ]


    assert_equal(
        keyboard[
            "sort_buttons"
        ],
        len(
            DocumentSummaryRepository.SORTABLE
        ),
        (
            "Every sortable column should offer a "
            "real button."
        ),
    )


    assert_true(
        keyboard[
            "sort_all_buttons"
        ],
        (
            "Sort controls must be real buttons so "
            "they are focusable and announced."
        ),
    )


    assert_true(
        all(
            value == "button"
            for value in keyboard[
                "sort_button_types"
            ]
        ),
        (
            "A button inside a form needs an "
            "explicit type, or it submits."
        ),
    )


    assert_equal(
        keyboard[
            "no_div_buttons"
        ],
        0,
        (
            "No div-with-role=button controls. "
            "Real elements only."
        ),
    )


    assert_true(
        keyboard[
            "open_links"
        ]
        > 0
        and keyboard[
            "page_buttons"
        ]
        == 2,
        (
            "Open actions should be links and "
            "paging should be buttons."
        ),
    )


    print(
        f"[PASS] {keyboard['sort_buttons']} sort "
        "buttons, "
        f"{keyboard['open_links']} open links and "
        "2 page buttons, all real elements"
    )


    # ======================================================
    # THE TOOLBAR FORM DOES NOT RELOAD THE PAGE
    # ======================================================

    submitted = results[
        "form_submit_is_intercepted"
    ]


    assert_true(
        submitted[
            "prevented"
        ],
        (
            "Pressing Enter in the search box "
            "must not reload the page."
        ),
    )


    assert_equal(
        submitted[
            "new_requests"
        ],
        1,
        (
            "Submitting should search immediately, "
            "once."
        ),
    )


    print(
        "[PASS] Enter searches immediately and "
        "does not reload the page"
    )


    # ======================================================
    # ACCESSIBILITY MARKUP
    # ======================================================

    markup = (
        client.get(
            DOCUMENTS_ROUTE
        )
        .text
    )


    for description, needle in (
        (
            "skip link",
            'class="skip-link"',
        ),
        (
            "main landmark",
            'id="main-content"',
        ),
        (
            "navigation label",
            'aria-label="Primary"',
        ),
        (
            "search landmark",
            'role="search"',
        ),
        (
            "live result summary",
            'aria-live="polite"',
        ),
        (
            "pagination landmark",
            'aria-label="Document pages"',
        ),
    ):

        assert_true(
            needle in markup,
            (
                "The Documents page is missing the "
                f"{description}."
            ),
        )


    assert_equal(
        len(
            re.findall(
                r"<h1[\s>]",
                markup,
            )
        ),
        1,
        (
            "There should be exactly one h1."
        ),
    )


    print(
        "[PASS] Landmarks, live region and single "
        "h1 all present"
    )


    # ======================================================
    # STATIC SOURCE AUDIT
    # ======================================================

    problems = (
        audit_frontend_module(
            client.get(
                "/review/static/js/documents_page.js"
            )
            .text,
            "documents_page.js",
        )
    )


    assert_equal(
        problems,
        [],
        (
            "documents_page.js failed the shared "
            "frontend audit."
        ),
    )


    print(
        "[PASS] No unsafe rendering, no console "
        "logging, no raw fetch, no secrets"
    )


# ==========================================================
# TEST 13 — RESPONSIVE
# ==========================================================

def test_responsive(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 13 - RESPONSIVE"
    )
    print("-" * 76)


    assert_true(
        "width=device-width"
        in client.get(
            DOCUMENTS_ROUTE
        )
        .text,
        (
            "The Documents page needs a responsive "
            "viewport."
        ),
    )


    responsive = (
        client.get(
            "/review/static/css/responsive.css"
        )
        .text
    )


    assert_true(
        ".toolbar"
        in responsive,
        (
            "The filter bar must reflow on narrow "
            "screens, or the controls become "
            "untappable."
        ),
    )


    assert_true(
        ".pagination"
        in responsive,
        (
            "Pagination should reflow on narrow "
            "screens."
        ),
    )


    components = (
        client.get(
            "/review/static/css/components.css"
        )
        .text
    )


    assert_true(
        re.search(
            r"\.table-wrap\s*\{[^}]*overflow-x\s*:\s*auto",
            components,
        )
        is not None,
        (
            "A nine-column table must scroll "
            "inside its own container so the page "
            "body never scrolls sideways."
        ),
    )


    print(
        "[PASS] Toolbar and pager reflow, and the "
        "table scrolls inside its own container"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 76)
    print(
        "PHASE 8.8B — PROFESSIONAL DOCUMENTS UI"
    )
    print("=" * 76)


    results = (
        run_harness()
    )


    assert_no_harness_errors(
        results
    )


    print()
    print(
        "[OK] Documents module executed under "
        "Node with a DOM stub"
    )


    client = None


    try:

        client = TestClient(
            app
        )

        client.__enter__()


        test_route_and_assets(
            client
        )

        test_navigation(
            client
        )

        test_contract_parity(
            results
        )

        test_filter_markup(
            client
        )

        test_api_contract(
            client
        )

        test_requests(
            results
        )

        test_search(
            results
        )

        test_sorting(
            results
        )

        test_url_state(
            results
        )

        test_overlapping_reads(
            results
        )

        test_states(
            results
        )

        test_safety_and_accessibility(
            results,
            client,
        )

        test_responsive(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.8B DOCUMENTS UI "
            "TEST PASSED"
        )
        print("=" * 76)


    finally:

        if client is not None:

            client.__exit__(
                None,
                None,
                None,
            )


if __name__ == "__main__":

    main()
