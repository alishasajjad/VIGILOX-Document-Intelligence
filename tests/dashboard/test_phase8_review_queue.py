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
    ALLOWED_REVIEW_PRIORITIES,
)

from tests.dashboard.source_audit import (
    audit_frontend_module,
    strip_js_comments,
)


# ==========================================================
# PHASE 8.9
# PROFESSIONAL REVIEW QUEUE CONTRACT TEST
# ==========================================================
#
# The Review Queue was rebuilt in Phase 8.9 onto the design
# system, the shared API client and the shared vocabulary. This
# suite guards the rebuild.
#
# WHAT IS DELIBERATELY PRESERVED
# ----------------------------------------------------------
# The Phase 7B white-box assertions on this screen protected
# real properties, and they are kept and strengthened here:
#
#     the route serves the queue page
#     the page still loads /review/static/dashboard.js
#     reviewer identity stays server-resolved with no input
#     priority is never recalculated in the browser
#
# WHAT IS NEW
# ----------------------------------------------------------
#     reason codes are shown as readable reasons, with the
#         machine code preserved alongside them
#     severities come only from the backend; an unrecognised
#         severity is never relabelled as ERROR or WARNING
#     errors use error.code / message / request_id rather than
#         the legacy top-level `detail`
#     no header pretends to sort, because the queue API
#         supports no sorting
#     empty and filtered-empty are distinct states
#
# Behaviour is EXECUTED under Node
# (tests/dashboard/review_queue_harness.js), not
# pattern-matched.
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
    / "review_queue_harness.js"
)


QUEUE_ROUTE = "/review"


REQUIRED_ASSETS = (
    "/review/static/dashboard.js",
    "/review/static/js/api.js",
    "/review/static/js/common.js",
    "/review/static/js/vocabulary.js",
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/responsive.css",
)


# ----------------------------------------------------------
# Severities the backend actually emits.
# DocumentAnomalyValidator uses exactly these two.
# ----------------------------------------------------------

BACKEND_SEVERITIES = (
    "ERROR",
    "WARNING",
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
                "Review Queue module."
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
                "Review Queue harness failed to "
                "run.\n"
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
# TEST 1 — ROUTE AND LEGACY CONTRACT
# ==========================================================

def test_route_and_assets(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - ROUTE AND LEGACY CONTRACT"
    )
    print("-" * 76)


    response = (
        client.get(
            QUEUE_ROUTE
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "GET /review should return HTTP 200."
        ),
    )


    markup = response.text


    # ======================================================
    # PHASE 7B CONTRACT PRESERVED
    # ======================================================
    #
    # Existing dashboard tests assert both of these by name.
    # The rebuild keeps the filename dashboard.js precisely so
    # cached browsers and those tests keep working.
    # ======================================================

    assert_true(
        "Review Queue"
        in markup,
        (
            "The queue page must still identify "
            "itself as the Review Queue."
        ),
    )


    assert_true(
        "/review/static/dashboard.js"
        in markup,
        (
            "The queue page must still load "
            "dashboard.js. Renaming it would break "
            "cached browsers and the Phase 7B "
            "regressions for no benefit."
        ),
    )


    for asset in REQUIRED_ASSETS:

        assert_equal(
            client.get(
                asset
            ).status_code,
            200,
            (
                "Review Queue asset should "
                f"resolve: {asset}"
            ),
        )


        assert_true(
            asset in markup,
            (
                "Review Queue page should load "
                f"{asset}"
            ),
        )


    print(
        "[PASS] Route serves the queue, keeps "
        f"dashboard.js, and all {len(REQUIRED_ASSETS)} "
        "assets resolve"
    )


    # ======================================================
    # THE OTHER SCREENS' MODULES ARE NOT LOADED HERE
    # ======================================================

    for foreign in (
        "/review/static/js/dashboard_page.js",
        "/review/static/js/documents_page.js",
        "/review/static/js/upload.js",
        "/review/static/review_detail.js",
    ):

        assert_false(
            foreign in markup,
            (
                "The Review Queue must not load "
                f"another screen's module: {foreign}"
            ),
        )


    print(
        "[PASS] Review Queue loads no other "
        "screen's module"
    )


# ==========================================================
# TEST 2 — MODULE IDENTITY
# ==========================================================

def test_module_identity(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - MODULE IDENTITY"
    )
    print("-" * 76)


    surface = results[
        "module_surface"
    ]


    assert_true(
        surface[
            "exposed"
        ],
        (
            "dashboard.js should expose the Review "
            "Queue module."
        ),
    )


    assert_true(
        surface[
            "is_not_dashboard"
        ],
        (
            "dashboard.js is the Review Queue, not "
            "the Dashboard. Defining the Dashboard "
            "module here would mean /review runs "
            "the wrong page."
        ),
    )


    assert_true(
        surface[
            "vocabulary_loaded"
        ],
        (
            "The queue needs the shared vocabulary "
            "to turn reason codes into readable "
            "reasons."
        ),
    )


    print(
        "[PASS] dashboard.js is the Review Queue "
        "module and is not the Dashboard"
    )


    # ======================================================
    # FILTER VOCABULARIES MATCH THE API
    # ======================================================

    assert_equal(
        sorted(
            surface[
                "priorities"
            ]
        ),
        sorted(
            ALLOWED_REVIEW_PRIORITIES
        ),
        (
            "The client priority list must match "
            "ALLOWED_REVIEW_PRIORITIES."
        ),
    )


    assert_equal(
        sorted(
            surface[
                "document_types"
            ]
        ),
        sorted(
            ALLOWED_DOCUMENT_TYPES
        ),
        (
            "The client document-type list must "
            "match ALLOWED_DOCUMENT_TYPES."
        ),
    )


    print(
        "[PASS] Priority and document-type "
        "vocabularies match the API exactly"
    )


# ==========================================================
# TEST 3 — QUEUE API CONTRACT
# ==========================================================

def test_api_contract(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - QUEUE API CONTRACT"
    )
    print("-" * 76)


    response = (
        client.get(
            "/api/v1/reviews/queue"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "GET /api/v1/reviews/queue should "
            "return HTTP 200."
        ),
    )


    payload = response.json()


    for key in (
        "total",
        "filters",
        "documents",
    ):

        assert_true(
            key in payload,
            (
                "The queue response is missing "
                f"{key}."
            ),
        )


    # ======================================================
    # THE QUEUE CARRIES NO PAGING CONTRACT
    # ======================================================
    #
    # This is why the rebuilt screen offers no pager, no search
    # and no sort control. Offering them would imply a server
    # capability that does not exist.
    # ======================================================

    for absent in (
        "page",
        "page_size",
        "total_pages",
    ):

        assert_false(
            absent in payload,
            (
                "The queue endpoint has no paging "
                "contract, so the UI must not "
                f"imply one: {absent}"
            ),
        )


    print(
        "[PASS] Queue returns one bounded, "
        "unpaged set"
    )


    # ======================================================
    # EVERY FILTER VALUE THE UI OFFERS IS ACCEPTED
    # ======================================================

    for priority in sorted(
        ALLOWED_REVIEW_PRIORITIES
    ):

        assert_equal(
            client.get(
                "/api/v1/reviews/queue"
                f"?priority={priority}"
            ).status_code,
            200,
            (
                "A priority the UI offers must be "
                f"accepted: {priority}"
            ),
        )


    for document_type in sorted(
        ALLOWED_DOCUMENT_TYPES
    ):

        assert_equal(
            client.get(
                "/api/v1/reviews/queue"
                f"?document_type={document_type}"
            ).status_code,
            200,
            (
                "A document type the UI offers "
                f"must be accepted: {document_type}"
            ),
        )


    print(
        f"[PASS] All "
        f"{len(ALLOWED_REVIEW_PRIORITIES) + len(ALLOWED_DOCUMENT_TYPES)} "
        "filter values the UI offers return "
        "HTTP 200"
    )


    # ======================================================
    # QUEUE ROWS CARRY NO DOCUMENT CONTENT
    # ======================================================

    if payload[
        "documents"
    ]:

        row_keys = set(
            payload[
                "documents"
            ][
                0
            ]
            .keys()
        )


        for field in (
            "extraction",
            "ocr_lines",
            "field_confidence",
            "evidence_flags",
        ):

            assert_false(
                field in row_keys,
                (
                    "A queue row must not carry "
                    f"document content: {field}"
                ),
            )


        print(
            "[PASS] Queue rows carry metadata and "
            "validation outcomes only"
        )


    # ======================================================
    # SERVER-SIDE PRIORITY ORDER
    # ======================================================

    priorities = [
        item[
            "review_priority"
        ]
        for item in payload[
            "documents"
        ]
    ]


    rank = {
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }


    ranks = [
        rank.get(
            value,
            4,
        )
        for value in priorities
    ]


    assert_equal(
        ranks,
        sorted(
            ranks
        ),
        (
            "The queue endpoint orders by priority. "
            "If it stopped doing so, the rebuilt "
            "screen would silently show an "
            "unordered queue, because it renders "
            "rows in the order they arrive."
        ),
    )


    print(
        f"[PASS] {len(priorities)} rows arrive in "
        "server priority order"
    )


# ==========================================================
# TEST 4 — LOADING AND REQUEST BEHAVIOUR
# ==========================================================

def test_requests(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - REQUESTS"
    )
    print("-" * 76)


    single = results[
        "single_request"
    ]


    assert_equal(
        single[
            "request_count"
        ],
        1,
        (
            "A queue load should issue exactly one "
            "request."
        ),
    )


    assert_equal(
        single[
            "first_filters"
        ],
        {
            "priority": None,
            "documentType": None,
        },
        (
            "An unfiltered load should send no "
            "filter values at all."
        ),
    )


    assert_equal(
        single[
            "reviewer_calls"
        ],
        1,
        (
            "Reviewer identity should be resolved "
            "once per page load."
        ),
    )


    assert_equal(
        single[
            "health_calls"
        ],
        1,
        (
            "Liveness should be checked once, not "
            "polled."
        ),
    )


    assert_equal(
        single[
            "intervals"
        ],
        0,
        (
            "The queue must not poll."
        ),
    )


    print(
        "[PASS] One queue request, one identity "
        "request, one liveness check, no polling"
    )


    guard = results[
        "concurrent_refresh_guard"
    ]


    assert_equal(
        guard[
            "request_count"
        ],
        1,
        (
            "Three Refresh clicks during an "
            "in-flight read must not start three "
            "requests."
        ),
    )


    assert_true(
        guard[
            "refresh_disabled"
        ],
        (
            "Refresh should be disabled while a "
            "read is in flight."
        ),
    )


    print(
        "[PASS] 3 Refresh clicks produced exactly "
        "1 request"
    )


    submitted = results[
        "form_submit_is_intercepted"
    ]


    assert_true(
        submitted[
            "prevented"
        ],
        (
            "Submitting the filter form must not "
            "reload the page."
        ),
    )


    print(
        "[PASS] Filter form submit does not "
        "reload the page"
    )


# ==========================================================
# TEST 5 — ROWS
# ==========================================================

def test_rows(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - QUEUE ROWS"
    )
    print("-" * 76)


    render = results[
        "row_render"
    ]


    assert_equal(
        render[
            "row_count"
        ],
        3,
        (
            "Each queue item should produce one "
            "row."
        ),
    )


    # ======================================================
    # SERVER ORDER IS PRESERVED
    # ======================================================

    assert_equal(
        render[
            "priorities"
        ],
        [
            "High",
            "Medium",
            "Low",
        ],
        (
            "Rows should render in the order the "
            "server returned them."
        ),
    )


    assert_equal(
        render[
            "filenames"
        ],
        [
            "guard_front.jpg",
            "badge.png",
            "card.jpg",
        ],
        (
            "Filenames should render from "
            "original_filename."
        ),
    )


    # ======================================================
    # NO FAKE SORTING
    # ======================================================
    #
    # The queue API accepts no sort parameter. A clickable
    # header here would sort one response and imply it had
    # ordered the whole queue.
    # ======================================================

    assert_equal(
        render[
            "header_buttons"
        ],
        0,
        (
            "No queue column may offer a sort "
            "control, because the queue endpoint "
            "supports no sorting. Sorting one "
            "bounded response and presenting it as "
            "a whole-queue order would be false."
        ),
    )


    print(
        "[PASS] Rows keep server order and no "
        "header pretends to sort"
    )


    # ======================================================
    # THE PRIMARY ACTION
    # ======================================================

    assert_equal(
        render[
            "open_hrefs"
        ],
        [
            "/review/doc-high",
            "/review/doc-medium",
            "/review/doc-low",
        ],
        (
            "Each row should open the real "
            "document."
        ),
    )


    assert_true(
        all(
            label == "Open Review"
            for label in render[
                "open_labels"
            ]
        ),
        (
            "The primary action should say what it "
            "does."
        ),
    )


    assert_true(
        "Why review is needed"
        in render[
            "headers"
        ],
        (
            "A reviewer should be told why a "
            "document is in the queue, in a column "
            "labelled as such."
        ),
    )


    print(
        "[PASS] Every row opens the real document "
        "with an Open Review action"
    )


    # ======================================================
    # PRIORITY IS NOT RECALCULATED
    # ======================================================

    authority = results[
        "priority_is_server_authoritative"
    ]


    assert_equal(
        authority[
            "order"
        ],
        [
            "Low",
            "High",
        ],
        (
            "The browser must not reorder the "
            "queue. A LOW row carrying an ERROR "
            "severity stayed first because the "
            "server put it first."
        ),
    )


    assert_equal(
        authority[
            "ids"
        ],
        [
            "doc-a",
            "doc-b",
        ],
        (
            "Row identity should follow the server "
            "order too."
        ),
    )


    print(
        "[PASS] A LOW row with an ERROR finding "
        "was not promoted; urgency stays "
        "server-side"
    )


    # ======================================================
    # SUMMARY
    # ======================================================

    summary = {
        card[
            "label"
        ]: card[
            "value"
        ]

        for card in results[
            "summary"
        ][
            "cards"
        ]
    }


    assert_equal(
        summary,
        {
            "Pending Reviews": "3",
            "High Priority": "1",
            "Medium Priority": "1",
            "Low Priority": "1",
        },
        (
            "The summary should tally the rows the "
            "server returned."
        ),
    )


    print(
        "[PASS] Summary tallies the returned rows"
    )


# ==========================================================
# TEST 6 — REVIEW REASONS
# ==========================================================

def test_reasons(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - REVIEW REASONS"
    )
    print("-" * 76)


    presentation = results[
        "reason_presentation"
    ]


    assert_equal(
        presentation[
            "chip_labels"
        ],
        [
            "Required field missing",
            "Required field not supported by evidence",
        ],
        (
            "Reason codes should be shown in "
            "language a reviewer can act on."
        ),
    )


    assert_false(
        presentation[
            "raw_code_visible"
        ],
        (
            "The raw machine code should not be "
            "the visible label. A reviewer should "
            "not have to decode the system."
        ),
    )


    assert_true(
        presentation[
            "code_available"
        ],
        (
            "The machine code must still be "
            "reachable, so the readable label and "
            "the API contract never become "
            "disconnected."
        ),
    )


    print(
        "[PASS] Reasons read as language, with the "
        "machine code preserved alongside"
    )


    # ======================================================
    # DUPLICATES AND OVERFLOW
    # ======================================================

    capped = results[
        "reason_deduplicated_and_capped"
    ]


    limit = capped[
        "visible_limit"
    ]


    assert_equal(
        capped[
            "chip_count"
        ],
        limit + 1,
        (
            "Seven reason codes, three of them "
            "identical, should collapse to "
            f"{limit} reasons plus one overflow "
            "chip."
        ),
    )


    assert_equal(
        capped[
            "more_label"
        ],
        "+2 more",
        (
            "The overflow chip should say how many "
            "reasons were not shown."
        ),
    )


    assert_true(
        "FUTURE_ISSUE_DATE"
        in (
            capped[
                "more_title"
            ]
            or ""
        ),
        (
            "The hidden reasons must remain "
            "reachable rather than being dropped."
        ),
    )


    print(
        f"[PASS] 7 codes with duplicates rendered "
        f"as {limit} reasons plus '+2 more'"
    )


    # ======================================================
    # UNKNOWN CODE
    # ======================================================

    unknown = results[
        "unknown_reason_code_is_shown"
    ]


    assert_equal(
        unknown[
            "label"
        ],
        "Some Future Backend Code",
        (
            "A code this build does not recognise "
            "should be humanised and shown, not "
            "hidden."
        ),
    )


    assert_true(
        unknown[
            "marked_unknown"
        ],
        (
            "An unrecognised code should be "
            "visibly unrecognised, so it is never "
            "mistaken for a familiar reason."
        ),
    )


    assert_equal(
        unknown[
            "title"
        ],
        "SOME_FUTURE_BACKEND_CODE",
        (
            "The raw code should remain available "
            "for an unrecognised reason."
        ),
    )


    print(
        "[PASS] An unrecognised reason code is "
        "shown as itself and marked unknown"
    )


    # ======================================================
    # NO REASONS AT ALL
    # ======================================================

    bare = results[
        "no_reason_codes"
    ]


    assert_true(
        bare[
            "row_rendered"
        ],
        (
            "A queued document with no reason "
            "codes must still appear. Dropping it "
            "would hide real work."
        ),
    )


    assert_true(
        "No reason recorded"
        in bare[
            "text"
        ],
        (
            "A row with no reason codes should say "
            "so plainly."
        ),
    )


    print(
        "[PASS] A queued document with no reason "
        "codes still appears, and says so"
    )


# ==========================================================
# TEST 7 — SEVERITIES
# ==========================================================

def test_severities(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - SEVERITIES"
    )
    print("-" * 76)


    badges = results[
        "severity_presentation"
    ][
        "badges"
    ]


    assert_equal(
        [
            badge[
                "text"
            ]
            for badge in badges
        ],
        [
            "1 error",
            "1 warning",
        ],
        (
            "Findings should be summarised using "
            "the severities the backend attached."
        ),
    )


    for badge in badges:

        assert_true(
            any(
                f"severity-{severity.lower()}"
                in badge[
                    "className"
                ]
                for severity in BACKEND_SEVERITIES
            ),
            (
                "A severity badge should map to a "
                "real backend severity: "
                f"{badge['className']}"
            ),
        )


    print(
        "[PASS] Findings summarise the backend's "
        "own ERROR and WARNING counts"
    )


    # ======================================================
    # AN UNKNOWN SEVERITY IS NOT PROMOTED
    # ======================================================

    unknown = results[
        "unknown_severity_is_not_relabelled"
    ]


    assert_false(
        unknown[
            "claims_error"
        ],
        (
            "An unrecognised severity must not be "
            "presented as ERROR."
        ),
    )


    assert_false(
        unknown[
            "claims_warning"
        ],
        (
            "An unrecognised severity must not be "
            "presented as WARNING."
        ),
    )


    assert_true(
        len(
            unknown[
                "badges"
            ]
        )
        > 0,
        (
            "An unrecognised severity should still "
            "be counted and shown, just not "
            "relabelled."
        ),
    )


    print(
        "[PASS] An unrecognised severity is "
        "counted separately, never promoted to "
        "ERROR or WARNING"
    )


# ==========================================================
# TEST 8 — FILTERS
# ==========================================================

def test_filters(
    client: TestClient,
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - FILTERS"
    )
    print("-" * 76)


    markup = (
        client.get(
            QUEUE_ROUTE
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
            "priority-filter"
        ),
        set(
            ALLOWED_REVIEW_PRIORITIES
        ),
        (
            "The priority filter must offer exactly "
            "the values the API accepts."
        ),
    )


    assert_equal(
        option_values(
            "document-type-filter"
        ),
        set(
            ALLOWED_DOCUMENT_TYPES
        ),
        (
            "The document type filter must offer "
            "exactly the values the API accepts."
        ),
    )


    for control_id in (
        "priority-filter",
        "document-type-filter",
    ):

        assert_true(
            f'for="{control_id}"'
            in markup,
            (
                "Every filter needs a real "
                f"<label for>: {control_id}"
            ),
        )


    print(
        "[PASS] Both filters offer only real "
        "values and both have real labels"
    )


    # ======================================================
    # FILTERS REACH THE SERVER
    # ======================================================

    priority = results[
        "priority_filter"
    ]


    assert_equal(
        priority[
            "last_filters"
        ],
        {
            "priority": "HIGH",
            "documentType": None,
        },
        (
            "Choosing a priority should re-query "
            "the server with that priority."
        ),
    )


    assert_equal(
        priority[
            "request_count"
        ],
        2,
        (
            "Changing a filter should issue one "
            "additional request."
        ),
    )


    assert_equal(
        results[
            "document_type_filter"
        ][
            "last_filters"
        ],
        {
            "priority": None,
            "documentType": "id_card",
        },
        (
            "Choosing a document type should "
            "re-query the server with that type."
        ),
    )


    print(
        "[PASS] Both filters are applied by the "
        "server, not in the browser"
    )


    # ======================================================
    # TAMPERED CONTROLS
    # ======================================================

    tampered = results[
        "tampered_filter_is_refused"
    ]


    for sent in tampered[
        "filters_sent"
    ]:

        assert_true(
            sent[
                "priority"
            ]
            in (
                None,
                "",
            )
            or sent[
                "priority"
            ]
            in ALLOWED_REVIEW_PRIORITIES,
            (
                "A tampered priority control must "
                "not put an unknown value into a "
                f"request: {sent}"
            ),
        )


        assert_true(
            sent[
                "documentType"
            ]
            in (
                None,
                "",
            )
            or sent[
                "documentType"
            ]
            in ALLOWED_DOCUMENT_TYPES,
            (
                "A tampered document-type control "
                "must not put an unknown value "
                f"into a request: {sent}"
            ),
        )


    print(
        "[PASS] Injected filter values never "
        "reach the server"
    )


    # ======================================================
    # RESET
    # ======================================================

    reset = results[
        "reset_filters"
    ]


    assert_equal(
        reset[
            "last_filters"
        ],
        {
            "priority": None,
            "documentType": None,
        },
        (
            "Reset should clear both filters in "
            "the request."
        ),
    )


    assert_equal(
        reset[
            "priority_control"
        ],
        "",
        (
            "Reset should clear the visible "
            "priority control too."
        ),
    )


    assert_equal(
        reset[
            "type_control"
        ],
        "",
        (
            "Reset should clear the visible "
            "document-type control too."
        ),
    )


    print(
        "[PASS] Reset clears both the request and "
        "the visible controls"
    )


# ==========================================================
# TEST 9 — STATES
# ==========================================================

def test_states(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 9 - LOADING / EMPTY / ERROR"
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
        f"{loading['skeleton_count']} skeletons"
    )


    # ======================================================
    # EMPTY QUEUE IS GOOD NEWS
    # ======================================================

    empty = results[
        "empty_queue"
    ]


    assert_true(
        empty[
            "empty_visible"
        ]
        and empty[
            "table_hidden"
        ],
        (
            "An empty queue should replace the "
            "table."
        ),
    )


    assert_true(
        "Nothing is waiting"
        in empty[
            "text"
        ],
        (
            "An empty queue is a healthy state and "
            "should read as one."
        ),
    )


    assert_true(
        "/documents"
        in empty[
            "hrefs"
        ]
        and "/upload"
        in empty[
            "hrefs"
        ],
        (
            "An empty queue should offer somewhere "
            "useful to go next."
        ),
    )


    assert_equal(
        empty[
            "summary_cards"
        ],
        4,
        (
            "The summary should still render zeros "
            "once the read has completed. Unlike "
            "the loading state, these zeros are "
            "true."
        ),
    )


    # ======================================================
    # FILTERED EMPTY IS A DIFFERENT FACT
    # ======================================================

    filtered = results[
        "empty_filtered_queue"
    ]


    assert_true(
        "filter"
        in filtered[
            "text"
        ]
        .lower(),
        (
            "A filtered-empty queue should say the "
            "filters are the reason, not that "
            "nothing needs review."
        ),
    )


    assert_equal(
        filtered[
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


    assert_true(
        "filter"
        in filtered[
            "status"
        ]
        .lower(),
        (
            "The status line should agree with the "
            "empty state."
        ),
    )


    recovered = results[
        "filtered_empty_recovers"
    ]


    assert_equal(
        recovered[
            "last_filters"
        ],
        {
            "priority": None,
            "documentType": None,
        },
        (
            "Resetting from the empty state should "
            "clear the filters."
        ),
    )


    assert_true(
        recovered[
            "table_visible"
        ],
        (
            "Resetting from the empty state should "
            "bring the queue back."
        ),
    )


    print(
        "[PASS] Empty and filtered-empty are "
        "distinct, and reset recovers"
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
                "The rebuilt queue should surface "
                f"{description}."
            ),
        )


    # ==================================================
    # THE LEGACY PATH IS NO LONGER PREFERRED
    # ==================================================
    #
    # The Phase 7B queue read only the top-level `detail`.
    # `detail` is still accepted by the shared client as a
    # fallback, but a structured error must win.
    # ==================================================

    assert_false(
        error[
            "uses_legacy_detail"
        ],
        (
            "With a structured error available, "
            "the UI must not fall back to the "
            "legacy top-level detail string."
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
            "summary_cleared"
        ],
        0,
        (
            "Stale priority counts must not "
            "survive a failed read."
        ),
    )


    assert_equal(
        error[
            "status_cleared"
        ],
        "",
        (
            "A stale status line must not survive "
            "a failed read."
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
            "queue."
        ),
    )


    print(
        "[PASS] Error uses the structured "
        "contract, not legacy detail, clears "
        "stale counts, and Retry recovers"
    )


# ==========================================================
# TEST 10 — REVIEWER IDENTITY TRUST BOUNDARY
# ==========================================================

def test_reviewer_identity(
    client: TestClient,
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 10 - REVIEWER IDENTITY"
    )
    print("-" * 76)


    markup = (
        client.get(
            QUEUE_ROUTE
        )
        .text
    )


    # ======================================================
    # NO CLIENT-SUPPLIED IDENTITY
    # ======================================================

    assert_false(
        'id="reviewer-id"'
        in markup,
        (
            "The legacy editable reviewer ID input "
            "must not exist."
        ),
    )


    assert_true(
        'id="shell-reviewer-name"'
        in markup,
        (
            "The shell should display the "
            "server-resolved reviewer."
        ),
    )


    identity = results[
        "reviewer_identity"
    ]


    assert_equal(
        identity[
            "calls"
        ],
        1,
        (
            "Reviewer identity should be fetched "
            "once."
        ),
    )


    assert_equal(
        identity[
            "shell_name"
        ],
        "queue-operator",
        (
            "The shell should show the reviewer the "
            "server returned."
        ),
    )


    assert_equal(
        identity[
            "identity_inputs"
        ],
        0,
        (
            "There must be no input through which "
            "the browser could state who the "
            "reviewer is."
        ),
    )


    print(
        "[PASS] Reviewer identity is "
        "server-resolved and the browser has no "
        "way to influence it"
    )


    # ======================================================
    # READ-ONLY REVIEWERS STILL SEE THE WORK
    # ======================================================
    #
    # Read-only access restricts writing a decision, which the
    # document workspace enforces. It must not hide the queue.
    # ======================================================

    read_only = results[
        "read_only_reviewer_still_sees_the_queue"
    ]


    assert_true(
        read_only[
            "table_visible"
        ],
        (
            "A read-only reviewer should still be "
            "able to see the queue."
        ),
    )


    assert_equal(
        read_only[
            "shell_access"
        ],
        "Read only",
        (
            "The shell should state the access "
            "level the server reported."
        ),
    )


    assert_true(
        read_only[
            "open_links"
        ]
        > 0,
        (
            "A read-only reviewer should still be "
            "able to open a document."
        ),
    )


    print(
        "[PASS] A read-only reviewer sees the "
        "queue and is labelled read only"
    )


# ==========================================================
# TEST 11 — SAFETY AND ACCESSIBILITY
# ==========================================================

def test_safety_and_accessibility(
    client: TestClient,
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 11 - SAFETY AND ACCESSIBILITY"
    )
    print("-" * 76)


    missing = results[
        "missing_document_id_is_safe"
    ]


    assert_equal(
        missing[
            "hrefs"
        ],
        [],
        (
            "A queue row without a document_id "
            "must not render a link."
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


    hostile = results[
        "hostile_values_are_text"
    ]


    assert_true(
        hostile[
            "filename_literal"
        ],
        (
            "A hostile filename should survive as "
            "literal text."
        ),
    )


    for key, description in (
        (
            "img_elements",
            "an img",
        ),
        (
            "script_elements",
            "a script",
        ),
        (
            "b_elements",
            "a bold",
        ),
    ):

        assert_equal(
            hostile[
                key
            ],
            0,
            (
                "Untrusted queue values must never "
                f"create {description} element."
            ),
        )


    privacy = results[
        "no_personal_data_in_queue"
    ]


    assert_false(
        privacy[
            "leaks_name"
        ],
        (
            "The queue must not render an "
            "extracted name."
        ),
    )


    assert_false(
        privacy[
            "leaks_ocr"
        ],
        (
            "The queue must not render OCR text."
        ),
    )


    print(
        "[PASS] Safe links, safe text, and no "
        "document content in the queue"
    )


    # ======================================================
    # STATIC SOURCE AUDIT
    # ======================================================

    source = (
        client.get(
            "/review/static/dashboard.js"
        )
        .text
    )


    # ==================================================
    # THE PHASE 7B IMPLEMENTATION IS GONE
    # ==================================================
    #
    # Comments are stripped first. This module's own header
    # documents what it replaced and names innerHTML in that
    # sentence, so a raw substring search would fail on the
    # prose describing the fix rather than on any code.
    # ==================================================

    problems = (
        audit_frontend_module(
            source,
            "dashboard.js",
        )
    )


    assert_equal(
        problems,
        [],
        (
            "The rebuilt Review Queue failed the "
            "shared frontend audit."
        ),
    )


    code = (
        strip_js_comments(
            source
        )
    )


    assert_false(
        "escapeHtml" in code,
        (
            "The hand-rolled HTML escaper is no "
            "longer needed. Building nodes and "
            "assigning textContent needs no "
            "escaping at all, and keeping an "
            "escaper invites someone to reach for "
            "innerHTML again."
        ),
    )


    print(
        "[PASS] No innerHTML, no hand-rolled "
        "escaping, no raw fetch, no console "
        "logging, no secrets"
    )


    # ======================================================
    # ACCESSIBILITY MARKUP
    # ======================================================

    markup = (
        client.get(
            QUEUE_ROUTE
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
            "live status region",
            'aria-live="polite"',
        ),
        (
            "filter form label",
            'aria-label="Filter the review queue"',
        ),
    ):

        assert_true(
            needle in markup,
            (
                "The Review Queue is missing the "
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
        "[PASS] Landmarks, live region, labelled "
        "filter form and a single h1"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 76)
    print(
        "PHASE 8.9 — PROFESSIONAL REVIEW QUEUE"
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
        "[OK] Review Queue module executed under "
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

        test_module_identity(
            results
        )

        test_api_contract(
            client
        )

        test_requests(
            results
        )

        test_rows(
            results
        )

        test_reasons(
            results
        )

        test_severities(
            results
        )

        test_filters(
            client,
            results,
        )

        test_states(
            results
        )

        test_reviewer_identity(
            client,
            results,
        )

        test_safety_and_accessibility(
            client,
            results,
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.9 REVIEW QUEUE TEST "
            "PASSED"
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
