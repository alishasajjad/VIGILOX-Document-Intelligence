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
    DASHBOARD_RECENT_LIMIT,
)

from tests.dashboard.source_audit import (
    audit_frontend_module,
)


# ==========================================================
# PHASE 8.6B
# PROFESSIONAL DASHBOARD UI CONTRACT TEST
# ==========================================================
#
# Two halves.
#
# 1. HTTP contracts, through TestClient: the /dashboard route,
#    its assets, the shared shell, navigation, accessibility
#    landmarks, and the single summary endpoint it consumes.
#
# 2. Real behaviour, by EXECUTING dashboard_page.js under Node
#    with a DOM stub (tests/dashboard/dashboard_harness.js).
#
# The second half is where the value is. Pattern-matching the
# source could not prove that four Refresh clicks issue one
# request, that a recent row with no document_id never becomes
# /review/undefined, that loading withholds zeros instead of
# showing them, or that a hostile filename renders as text.
#
# Nothing here asserts colours or copy, so the page can be
# redesigned without breaking these tests.
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
    / "dashboard_harness.js"
)


DASHBOARD_ROUTE = "/dashboard"


DASHBOARD_PAGE = (
    PROJECT_ROOT
    / "frontend"
    / "pages"
    / "dashboard.html"
)


REQUIRED_ASSETS = (
    "/review/static/js/dashboard_page.js",
    "/review/static/js/api.js",
    "/review/static/js/common.js",
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/responsive.css",
)


# ----------------------------------------------------------
# Every product page must carry the same four destinations.
# ----------------------------------------------------------

PRODUCT_PAGES = (
    "/dashboard",
    "/upload",
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
# The five authoritative expiry statuses emitted by
# date_validation.expiry.status.
#
# VALID and UNKNOWN are NOT among them. An earlier Phase 8.4
# draft guessed those two names, which meant a healthy
# document's badge could never have matched. They are listed
# here as forbidden so that mistake cannot come back.
# ----------------------------------------------------------

EXPIRY_STATUSES = (
    "EXPIRED",
    "EXPIRES_TODAY",
    "EXPIRING_SOON",
    "ACTIVE",
    "NOT_AVAILABLE",
)


FORBIDDEN_EXPIRY_STATUSES = (
    "VALID",
    "UNKNOWN",
)


# ----------------------------------------------------------
# Statistics this system does not define. Displaying any of
# them would be an invention, not a measurement.
# ----------------------------------------------------------

INVENTED_METRICS = (
    "accuracy",
    "average confidence",
    "risk score",
    "sla",
    "automation rate",
    "time saved",
    "throughput",
    "model score",
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
                "Dashboard module. Without it this "
                "suite could only pattern-match "
                "source text, which would not prove "
                "the behaviour."
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
                "Dashboard harness failed to run.\n"
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
                    f"{name}: {value['error']}"
                )
            )


# ==========================================================
# TEST 1 — ROUTE AND ASSETS
# ==========================================================

def test_route_and_assets(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - DASHBOARD ROUTE AND ASSETS"
    )
    print("-" * 76)


    response = (
        client.get(
            DASHBOARD_ROUTE
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "GET /dashboard should return "
            "HTTP 200."
        ),
    )


    assert_true(
        "text/html"
        in response.headers[
            "content-type"
        ],
        (
            "GET /dashboard should return HTML."
        ),
    )


    markup = response.text


    print(
        "[PASS] GET /dashboard returns the page"
    )


    # ======================================================
    # ONE AUTHORITATIVE URL
    # ======================================================

    assert_true(
        DASHBOARD_PAGE.exists(),
        (
            "frontend/pages/dashboard.html "
            "should exist."
        ),
    )


    # ======================================================
    # ASSETS RESOLVE
    # ======================================================

    for asset in REQUIRED_ASSETS:

        asset_response = (
            client.get(
                asset
            )
        )


        assert_equal(
            asset_response.status_code,
            200,
            (
                "Dashboard asset should resolve: "
                f"{asset}"
            ),
        )


        assert_true(
            asset in markup,
            (
                "Dashboard page should load "
                f"{asset}"
            ),
        )


    print(
        f"[PASS] All {len(REQUIRED_ASSETS)} "
        "dashboard assets resolve and are linked"
    )


    # ======================================================
    # DEDICATED MODULE, NOT THE REVIEW QUEUE MODULE
    # ======================================================
    #
    # dashboard.js is the Review Queue behaviour and predates
    # this screen. Loading it here would run the wrong page.
    # ======================================================

    assert_false(
        "/review/static/dashboard.js"
        in markup,
        (
            "The Dashboard page must not load "
            "dashboard.js, which owns the Review "
            "Queue at /review. The Dashboard has "
            "its own module, dashboard_page.js."
        ),
    )


    assert_false(
        "review_detail.js"
        in markup,
        (
            "The Dashboard page must not load "
            "the document workspace module."
        ),
    )


    print(
        "[PASS] Dashboard owns dashboard_page.js "
        "and does not reuse the Review Queue module"
    )


    # ======================================================
    # THE PREVIOUSLY BROKEN ROUTES STILL WORK
    # ======================================================

    for path in (
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
                "Adding the Dashboard must not "
                f"break {path}."
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


        # ==================================================
        # DASHBOARD IS A REAL LINK EVERYWHERE
        # ==================================================

        assert_true(
            'href="/dashboard"'
            in markup,
            (
                "Dashboard must be a real link on "
                f"{path}, not a pending placeholder."
            ),
        )


    print(
        f"[PASS] All {len(PRIMARY_NAVIGATION)} "
        "destinations present on "
        f"{len(PRODUCT_PAGES)} pages"
    )


    # ======================================================
    # DASHBOARD IS NO LONGER PENDING
    # ======================================================

    dashboard_markup = (
        client.get(
            DASHBOARD_ROUTE
        )
        .text
    )


    nav_block = (
        re.search(
            r"<nav[^>]*>(.*?)</nav>",
            dashboard_markup,
            re.DOTALL,
        )
    )


    assert_true(
        nav_block is not None,
        (
            "Could not locate the navigation "
            "block on the Dashboard."
        ),
    )


    nav_html = nav_block.group(
        1
    )


    assert_false(
        "Dashboard</span>"
        in nav_html
        and "nav-pending-tag"
        in nav_html
        and "Dashboard"
        in re.sub(
            r"<a[^>]*>.*?</a>",
            "",
            nav_html,
            flags=re.DOTALL,
        ),
        (
            "Dashboard is still rendered as a "
            "pending navigation item."
        ),
    )


    # ======================================================
    # EVERY NAVIGATION LINK RESOLVES
    # ======================================================

    hrefs = (
        re.findall(
            r'href="([^"]+)"',
            nav_html,
        )
    )


    assert_true(
        len(
            hrefs
        )
        >= 2,
        (
            "Navigation should contain real links."
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
                f"link: {href}"
            ),
        )


    print(
        f"[PASS] All {len(hrefs)} navigation "
        "links resolve"
    )


    # ======================================================
    # ACTIVE STATE
    # ======================================================

    assert_true(
        'aria-current="page"'
        in nav_html,
        (
            "The Dashboard page should mark its "
            "own navigation item with "
            'aria-current="page".'
        ),
    )


    active = (
        re.search(
            r'<a[^>]*href="([^"]+)"[^>]*aria-current="page"',
            nav_html,
            re.DOTALL,
        )
    )


    assert_true(
        active is not None
        and active.group(
            1
        )
        == "/dashboard",
        (
            "aria-current=page should be on the "
            "Dashboard item, not another item."
        ),
    )


    print(
        "[PASS] Dashboard is the active "
        "navigation item"
    )


# ==========================================================
# TEST 3 — ACCESSIBILITY MARKUP
# ==========================================================

def test_accessibility(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - ACCESSIBILITY"
    )
    print("-" * 76)


    markup = (
        client.get(
            DASHBOARD_ROUTE
        )
        .text
    )


    required = {
        "skip link":
            'class="skip-link"',

        "main landmark":
            'id="main-content"',

        "main element":
            "<main",

        "navigation landmark":
            "<nav",

        "navigation label":
            'aria-label="Primary"',

        "complementary landmark":
            "<aside",
    }


    for (
        description,
        needle,
    ) in required.items():

        assert_true(
            needle in markup,
            (
                "Dashboard is missing the "
                f"{description}."
            ),
        )


    print(
        f"[PASS] All {len(required)} landmarks "
        "present"
    )


    # ======================================================
    # HEADING HIERARCHY
    # ======================================================
    #
    # Exactly one h1, and every section heading is an h2 with
    # its section referencing it through aria-labelledby.
    # ======================================================

    h1_count = (
        len(
            re.findall(
                r"<h1[\s>]",
                markup,
            )
        )
    )


    assert_equal(
        h1_count,
        1,
        (
            "The Dashboard should have exactly "
            "one h1."
        ),
    )


    labelled = (
        re.findall(
            r'aria-labelledby="([^"]+)"',
            markup,
        )
    )


    assert_true(
        len(
            labelled
        )
        >= 4,
        (
            "Each dashboard section should be "
            "labelled by its own heading. Found "
            f"{len(labelled)}."
        ),
    )


    for target in labelled:

        assert_true(
            f'id="{target}"'
            in markup,
            (
                "aria-labelledby points at a "
                f"missing id: {target}"
            ),
        )


    print(
        f"[PASS] One h1 and {len(labelled)} "
        "labelled sections"
    )


    # ======================================================
    # LIVE REGIONS
    # ======================================================

    assert_true(
        'role="status"'
        in markup,
        (
            "The API liveness indicator should "
            'expose role="status".'
        ),
    )


    print(
        "[PASS] Status region present"
    )


# ==========================================================
# TEST 4 — SUMMARY API IS THE ONLY SOURCE
# ==========================================================

def test_summary_api_contract(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - SUMMARY API CONTRACT"
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
            "GET /api/v1/dashboard/summary "
            "should return HTTP 200."
        ),
    )


    payload = response.json()


    # ======================================================
    # EVERY FIGURE THE PAGE SHOWS IS IN THIS ONE PAYLOAD
    # ======================================================

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


    for key in (
        "pending_review",
        "auto_accepted",
        "review_required",
        "approved",
        "corrected",
        "rejected",
    ):

        assert_true(
            key
            in payload[
                "review"
            ],
            (
                "review counts are missing "
                f"{key}."
            ),
        )


    expiry_keys = {
        status.lower()
        for status in EXPIRY_STATUSES
    }


    assert_equal(
        set(
            payload[
                "expiry"
            ]
            .keys()
        ),
        expiry_keys,
        (
            "The expiry breakdown must mirror "
            "the five authoritative statuses "
            "exactly."
        ),
    )


    assert_equal(
        set(
            payload[
                "pending_review_priority"
            ]
            .keys()
        ),
        {
            "high",
            "medium",
            "low",
        },
        (
            "Priority distribution should carry "
            "high, medium and low."
        ),
    )


    print(
        "[PASS] Summary payload carries every "
        "figure the Dashboard renders"
    )


    # ======================================================
    # BOUNDED RECENT LIST
    # ======================================================

    assert_true(
        len(
            payload[
                "recent_documents"
            ]
        )
        <= DASHBOARD_RECENT_LIMIT,
        (
            "recent_documents must stay bounded "
            f"by {DASHBOARD_RECENT_LIMIT}."
        ),
    )


    print(
        "[PASS] recent_documents is bounded at "
        f"{DASHBOARD_RECENT_LIMIT}"
    )


    # ======================================================
    # NO INVENTED STATISTIC IN THE PAYLOAD EITHER
    # ======================================================

    serialized = (
        json.dumps(
            payload
        )
        .lower()
    )


    for metric in INVENTED_METRICS:

        assert_false(
            metric in serialized,
            (
                "The summary endpoint should not "
                "report a statistic this system "
                f"does not define: {metric}"
            ),
        )


    print(
        "[PASS] No invented statistic in the "
        "summary payload"
    )


# ==========================================================
# TEST 5 — SINGLE REQUEST, NO POLLING
# ==========================================================

def test_single_request(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - ONE REQUEST, NO POLLING"
    )
    print("-" * 76)


    single = results[
        "single_request"
    ]


    assert_equal(
        single[
            "summary_calls"
        ],
        1,
        (
            "A normal Dashboard load must issue "
            "exactly one summary request, not one "
            "per metric."
        ),
    )


    assert_equal(
        single[
            "documents_calls"
        ],
        0,
        (
            "The Dashboard must not call the "
            "Documents list API. Recent documents "
            "arrive inside the summary payload."
        ),
    )


    assert_equal(
        single[
            "intervals_started"
        ],
        0,
        (
            "The Dashboard must not poll."
        ),
    )


    print(
        "[PASS] One summary request, zero "
        "document-list requests, no polling"
    )


    # ======================================================
    # SHELL DOES NOT DUPLICATE ITS OWN REQUESTS
    # ======================================================

    shell = results[
        "shell_wiring"
    ]


    assert_equal(
        shell[
            "reviewer_calls"
        ],
        1,
        (
            "Reviewer identity should be fetched "
            "once per page load."
        ),
    )


    assert_equal(
        shell[
            "health_calls"
        ],
        1,
        (
            "Liveness should be checked once per "
            "page load, not polled."
        ),
    )


    print(
        "[PASS] Shell issues one identity and "
        "one liveness request"
    )


    # ======================================================
    # CONCURRENT REFRESH COLLAPSES
    # ======================================================

    guard = results[
        "concurrent_refresh_guard"
    ]


    assert_equal(
        guard[
            "summary_calls"
        ],
        1,
        (
            "Four Refresh clicks during an "
            "in-flight read must not start four "
            "requests. A later response could "
            "otherwise be an older read."
        ),
    )


    print(
        "[PASS] 4 Refresh clicks produced "
        "exactly 1 request"
    )


# ==========================================================
# TEST 6 — LOADING, EMPTY, ERROR, RETRY
# ==========================================================

def test_states(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - LOADING / EMPTY / ERROR / RETRY"
    )
    print("-" * 76)


    # ======================================================
    # LOADING
    # ======================================================

    loading = results[
        "loading_state"
    ]


    assert_true(
        loading[
            "loading_visible"
        ],
        (
            "The loading panel should be visible "
            "while the summary is in flight."
        ),
    )


    for key in (
        "body_hidden",
        "error_hidden",
        "empty_hidden",
    ):

        assert_true(
            loading[
                key
            ],
            (
                "Only one dashboard state may be "
                f"visible at a time: {key}"
            ),
        )


    assert_true(
        loading[
            "skeleton_count"
        ]
        > 0,
        (
            "Loading should render skeletons."
        ),
    )


    # ==================================================
    # NO NUMBERS WHILE LOADING
    # ==================================================
    #
    # A dashboard showing "0 Pending Review" before its data
    # arrives is indistinguishable from one reporting a clear
    # queue, and only one of those is true.
    # ==================================================

    assert_false(
        any(
            character.isdigit()
            for character in loading[
                "loading_text"
            ]
        ),
        (
            "The loading state must not display "
            "any figure. Found: "
            f"{loading['loading_text']!r}"
        ),
    )


    assert_true(
        loading[
            "refresh_disabled"
        ],
        (
            "Refresh should be disabled while a "
            "read is in flight."
        ),
    )


    print(
        f"[PASS] Loading shows "
        f"{loading['skeleton_count']} skeletons "
        "and not a single figure"
    )


    # ======================================================
    # EMPTY
    # ======================================================

    empty = results[
        "empty_state"
    ]


    assert_true(
        empty[
            "empty_visible"
        ],
        (
            "An empty database should produce an "
            "empty state."
        ),
    )


    assert_true(
        empty[
            "body_hidden"
        ],
        (
            "The metric body must stay hidden on "
            "an empty dashboard rather than "
            "showing a wall of zeros."
        ),
    )


    assert_equal(
        empty[
            "primary_cards"
        ],
        0,
        (
            "No stat cards should be rendered "
            "when there are no documents."
        ),
    )


    assert_true(
        empty[
            "has_upload_cta"
        ],
        (
            "The empty state should lead to "
            "/upload."
        ),
    )


    print(
        "[PASS] Empty dashboard shows a real "
        "empty state with an Upload action"
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
        ],
        (
            "A failed summary read should render "
            "an error state."
        ),
    )


    assert_true(
        error[
            "body_hidden"
        ]
        and error[
            "loading_hidden"
        ],
        (
            "The error state must replace the "
            "loading and content states."
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
                f"{description} from the "
                "structured contract."
            ),
        )


    assert_false(
        error[
            "mentions_traceback"
        ],
        (
            "The UI must never imply a stack "
            "trace. The API does not return one."
        ),
    )


    assert_equal(
        error[
            "has_retry"
        ],
        1,
        (
            "The error state should offer exactly "
            "one Retry control."
        ),
    )


    print(
        "[PASS] Error state shows code, message "
        "and request id, and one Retry"
    )


    # ======================================================
    # RETRY
    # ======================================================

    retry = results[
        "retry_recovers"
    ]


    assert_equal(
        retry[
            "attempts"
        ],
        2,
        (
            "Retry should issue a second read."
        ),
    )


    assert_true(
        retry[
            "body_visible"
        ]
        and retry[
            "error_hidden"
        ],
        (
            "A successful retry should replace the "
            "error with content."
        ),
    )


    guard = results[
        "retry_double_click_guard"
    ]


    assert_equal(
        guard[
            "calls_after"
        ]
        - guard[
            "calls_before"
        ],
        1,
        (
            "Four Retry clicks must produce one "
            "request, not four."
        ),
    )


    print(
        "[PASS] Retry recovers, and 4 Retry "
        "clicks produced exactly 1 request"
    )


# ==========================================================
# TEST 7 — METRICS RENDER FROM REAL FIELDS
# ==========================================================

def test_metrics(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - METRICS"
    )
    print("-" * 76)


    render = results[
        "success_render"
    ]


    assert_true(
        render[
            "body_visible"
        ]
        and render[
            "loading_hidden"
        ],
        (
            "A successful read should show the "
            "content and hide the skeletons."
        ),
    )


    # ======================================================
    # PRIMARY CARDS
    # ======================================================
    #
    # The fixture uses a distinct number per field, so a
    # mis-wired card shows the wrong figure rather than
    # accidentally matching.
    # ======================================================

    primary = {
        card[
            "label"
        ]: card[
            "value"
        ]

        for card in render[
            "primary_cards"
        ]
    }


    assert_equal(
        primary,
        {
            "Total Documents": "41",
            "Pending Review": "7",
            "Auto Accepted": "12",
            # approved 5 + corrected 3 + rejected 2
            "Human Reviewed": "10",
        },
        (
            "Primary summary cards do not match "
            "the summary payload."
        ),
    )


    outcomes = {
        card[
            "label"
        ]: card[
            "value"
        ]

        for card in render[
            "outcome_cards"
        ]
    }


    assert_equal(
        outcomes,
        {
            "Approved": "5",
            "Corrected": "3",
            "Rejected": "2",
        },
        (
            "Review outcome cards do not match "
            "the summary payload."
        ),
    )


    print(
        "[PASS] 4 primary and 3 outcome cards "
        "render the real counts"
    )


    # ======================================================
    # PENDING REVIEW IS VISUALLY FLAGGED
    # ======================================================

    pending_card = [
        card
        for card in render[
            "primary_cards"
        ]
        if card[
            "label"
        ]
        == "Pending Review"
    ][0]


    assert_true(
        pending_card[
            "modifiers"
        ][
            "attention"
        ],
        (
            "A non-zero pending count should be "
            "visually flagged."
        ),
    )


    assert_true(
        "19"
        in (
            pending_card[
                "hint"
            ]
            or ""
        ),
        (
            "The pending card should distinguish "
            "documents still awaiting review from "
            "the machine's review_required total."
        ),
    )


    no_pending = results[
        "no_pending_hides_attention"
    ]


    assert_false(
        no_pending[
            "pending_card_attention"
        ],
        (
            "A zero pending count must not be "
            "flagged as needing attention."
        ),
    )


    print(
        "[PASS] Pending Review is flagged only "
        "when work is actually waiting"
    )


    # ======================================================
    # EXPIRY BREAKDOWN
    # ======================================================

    expiry_rows = render[
        "expiry_rows"
    ]


    assert_equal(
        len(
            expiry_rows
        ),
        5,
        (
            "All five expiry statuses should be "
            "represented."
        ),
    )


    assert_equal(
        [
            row[
                "value"
            ]
            for row in expiry_rows
        ],
        [
            "6",
            "1",
            "4",
            "27",
            "3",
        ],
        (
            "Expiry counts do not match the "
            "summary payload, or the rows are in "
            "the wrong order."
        ),
    )


    labels = results[
        "expiry_labels"
    ]


    assert_equal(
        labels[
            "badge_labels"
        ],
        [
            "Expired",
            "Expires Today",
            "Expiring Soon",
            "Active",
            "No Expiry Date",
        ],
        (
            "Expiry labels should be readable "
            "presentations of the five real "
            "statuses."
        ),
    )


    # ==================================================
    # THE PHASE 8.4 MISTAKE MUST NOT COME BACK
    # ==================================================

    badge_classes = " ".join(
        labels[
            "badge_classes"
        ]
    )


    for forbidden in FORBIDDEN_EXPIRY_STATUSES:

        assert_false(
            f"badge-expiry-{forbidden.lower()}"
            in badge_classes,
            (
                "The expiry vocabulary must not "
                "reintroduce a status the "
                "validator never emits: "
                f"{forbidden}"
            ),
        )


    assert_true(
        all(
            f"badge-expiry-"
            f"{status.lower().replace('_', '-')}"
            in badge_classes
            for status in EXPIRY_STATUSES
        ),
        (
            "Every authoritative expiry status "
            "should map to its own badge "
            "modifier."
        ),
    )


    print(
        "[PASS] All 5 real expiry statuses map "
        "to badges; VALID and UNKNOWN are absent"
    )


    # ======================================================
    # PRIORITY DISTRIBUTION
    # ======================================================

    attention_rows = render[
        "attention_rows"
    ]


    assert_false(
        render[
            "attention_hidden"
        ],
        (
            "The attention section should be "
            "visible when reviews are pending."
        ),
    )


    assert_equal(
        [
            (
                row[
                    "label"
                ],
                row[
                    "value"
                ],
            )
            for row in attention_rows
        ],
        [
            (
                "High",
                "4",
            ),
            (
                "Medium",
                "2",
            ),
            (
                "Low",
                "1",
            ),
        ],
        (
            "Priority distribution should come "
            "straight from the backend counts."
        ),
    )


    assert_true(
        results[
            "no_pending_hides_attention"
        ][
            "attention_hidden"
        ],
        (
            "With nothing pending, the attention "
            "section should be hidden rather than "
            "shown empty."
        ),
    )


    print(
        "[PASS] Priority distribution uses "
        "backend counts and hides when empty"
    )


    # ======================================================
    # NO INVENTED METRIC IN THE RENDERED PAGE
    # ======================================================

    invented = results[
        "no_invented_metrics"
    ]


    assert_equal(
        invented[
            "found"
        ],
        [],
        (
            "The rendered dashboard displays a "
            "statistic this system does not "
            "define."
        ),
    )


    assert_false(
        invented[
            "has_percent_figure"
        ],
        (
            "The Dashboard reports counts. A "
            "percentage here would be an invented "
            "rate."
        ),
    )


    print(
        "[PASS] No invented metric and no "
        "percentage figure on the page"
    )


# ==========================================================
# TEST 8 — RECENT DOCUMENTS
# ==========================================================

def test_recent_documents(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - RECENT DOCUMENTS"
    )
    print("-" * 76)


    render = results[
        "success_render"
    ]


    assert_equal(
        render[
            "recent_row_count"
        ],
        2,
        (
            "Each recent document should produce "
            "one row."
        ),
    )


    assert_equal(
        render[
            "recent_hrefs"
        ],
        [
            "/review/doc-aaa",
            "/review/doc-bbb",
        ],
        (
            "Each recent row should open the real "
            "document."
        ),
    )


    print(
        "[PASS] Recent rows open the real "
        "document workspace"
    )


    # ======================================================
    # MISSING ID MUST NOT PRODUCE A LINK
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
            "render a link at all."
        ),
    )


    assert_false(
        missing[
            "builds_undefined_link"
        ],
        (
            "/review/undefined must be "
            "impossible."
        ),
    )


    assert_true(
        "Unavailable"
        in missing[
            "row_text"
        ],
        (
            "A row without an id should say so "
            "rather than render a dead control."
        ),
    )


    print(
        "[PASS] A row without an id never "
        "becomes /review/undefined"
    )


    # ======================================================
    # IDS ARE ENCODED
    # ======================================================

    encoded = results[
        "document_id_encoded"
    ]


    assert_equal(
        encoded[
            "hrefs"
        ],
        [
            "/review/a%2Fb%3Fc%3D1%26d",
        ],
        (
            "A document id must be percent "
            "encoded so it cannot alter the URL "
            "structure."
        ),
    )


    print(
        "[PASS] Document ids are percent encoded "
        "into the link"
    )


# ==========================================================
# TEST 9 — SAFE RENDERING AND PRIVACY
# ==========================================================

def test_safe_rendering_and_privacy(
    results: dict,
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 9 - SAFE RENDERING AND PRIVACY"
    )
    print("-" * 76)


    # ======================================================
    # HOSTILE FILENAME IS TEXT
    # ======================================================
    #
    # The filename comes from an uploaded file, so it is
    # untrusted input.
    #
    # This runs the real renderer. The DOM stub throws on any
    # innerHTML assignment, so the check below could not pass
    # if the module wrote markup.
    # ======================================================

    hostile = results[
        "filename_is_text_not_markup"
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
            "img_elements"
        ],
        0,
        (
            "A filename must never be parsed as "
            "markup."
        ),
    )


    print(
        "[PASS] A filename containing an img tag "
        "renders as text and creates no element"
    )


    # ======================================================
    # NO EXTRACTED IDENTITY DATA ON THIS SCREEN
    # ======================================================

    privacy = results[
        "no_personal_data_rendered"
    ]


    for key, description in (
        (
            "leaks_name",
            "full name",
        ),
        (
            "leaks_id_number",
            "ID number",
        ),
        (
            "leaks_licence",
            "licence number",
        ),
    ):

        assert_false(
            privacy[
                key
            ],
            (
                "The Dashboard must not render "
                f"the extracted {description}. A "
                "browsable index of document "
                "contents is not what this screen "
                "is for."
            ),
        )


    print(
        "[PASS] No extracted identity value is "
        "rendered on the Dashboard"
    )


    # ======================================================
    # STATIC SOURCE AUDIT
    # ======================================================

    problems = (
        audit_frontend_module(
            client.get(
                "/review/static/js/dashboard_page.js"
            )
            .text,
            "dashboard_page.js",
        )
    )


    assert_equal(
        problems,
        [],
        (
            "dashboard_page.js failed the shared "
            "frontend audit."
        ),
    )


    print(
        "[PASS] No unsafe rendering, no console "
        "logging, no raw fetch, no credential "
        "material"
    )


# ==========================================================
# TEST 10 — RESPONSIVE CONTRACT
# ==========================================================

def test_responsive(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 10 - RESPONSIVE"
    )
    print("-" * 76)


    markup = (
        client.get(
            DASHBOARD_ROUTE
        )
        .text
    )


    assert_true(
        "width=device-width"
        in markup,
        (
            "The Dashboard needs a responsive "
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
        responsive.count(
            "@media"
        )
        >= 3,
        (
            "The responsive layer should cover "
            "laptop, tablet and small screens."
        ),
    )


    # ======================================================
    # THE ATTENTION PANEL COLLAPSES
    # ======================================================

    assert_true(
        ".attention-panel"
        in responsive,
        (
            "The two-column attention panel must "
            "collapse on narrow screens, or the "
            "priority list becomes unreadable."
        ),
    )


    # ======================================================
    # LONG FILENAMES SCROLL THE TABLE, NOT THE PAGE
    # ======================================================

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
        is not None
        or re.search(
            r"\.table-wrap\s*\{[^}]*overflow\s*:\s*auto",
            components,
        )
        is not None,
        (
            "A wide table must scroll inside its "
            "own container so the page body never "
            "scrolls sideways."
        ),
    )


    print(
        "[PASS] Responsive viewport, collapsing "
        "panels and self-scrolling tables"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 76)
    print(
        "PHASE 8.6B — PROFESSIONAL DASHBOARD UI"
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
        "[OK] Dashboard module executed under "
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

        test_accessibility(
            client
        )

        test_summary_api_contract(
            client
        )

        test_single_request(
            results
        )

        test_states(
            results
        )

        test_metrics(
            results
        )

        test_recent_documents(
            results
        )

        test_safe_rendering_and_privacy(
            results,
            client,
        )

        test_responsive(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.6B DASHBOARD UI "
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
