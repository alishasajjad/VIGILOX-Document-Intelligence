import re

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from tests.dashboard.source_audit import (
    CONSOLE_CALLS,
    SECRET_MARKERS,
    UNSAFE_SINKS,
    audit_frontend_module,
    strip_css_comments,
    strip_js_comments,
)


# ==========================================================
# PHASE 8.15
# GLOBAL FRONTEND AUDIT
# ==========================================================
#
# Per-screen suites prove each screen. This one sweeps the
# WHOLE frontend, so a property cannot hold on four screens
# and quietly fail on the fifth, and a new file cannot be
# added without inheriting the rules.
#
# It walks the real files on disk rather than a hand-written
# list, so a module added tomorrow is audited tomorrow.
#
# WHAT IS ENFORCED GLOBALLY
# ----------------------------------------------------------
#   every product page is complete and consistent
#   the navigation is identical on every page
#   every referenced asset resolves
#   exactly one file may call fetch
#   no HTML-string injection sink anywhere
#   no console logging anywhere
#   no credential material anywhere
#   tokens have exactly one owner
#   the retired stylesheet stays retired
#   every interactive control is a real element
#   every form control has a real label
#   one h1 per page, and no skipped heading level
#   the responsive layer covers every screen
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


FRONTEND = (
    PROJECT_ROOT
    / "frontend"
)


PAGES = (
    "dashboard.html",
    "upload.html",
    "documents.html",
    "index.html",
    "review_detail.html",
)


ROUTES = {
    "dashboard.html": "/dashboard",
    "upload.html": "/upload",
    "documents.html": "/documents",
    "index.html": "/review",
    "review_detail.html": (
        "/review/00000000-0000-4000-8000-000000000000"
    ),
}


# ----------------------------------------------------------
# The only file allowed to call fetch. Centralising it is the
# whole point of having a shared client: one place parses
# responses, normalises the error contract and reads the
# request id.
# ----------------------------------------------------------

FETCH_OWNER = "js/api.js"


# ----------------------------------------------------------
# The retired legacy stylesheet. Its URL must keep resolving
# for cached browsers, but nothing may link it and no rule may
# come back into it.
# ----------------------------------------------------------

RETIRED_STYLESHEET = "/review/static/dashboard.css"


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
# FILE DISCOVERY
# ==========================================================

def javascript_files() -> list:

    """
    Every frontend JavaScript file, discovered rather than
    listed, so a new module is audited the day it lands.
    """

    found = sorted(
        path
        for path in (
            FRONTEND / "static"
        ).rglob(
            "*.js"
        )
    )


    if not found:

        raise AssertionError(
            (
                "No frontend JavaScript was found. "
                "The audit would pass vacuously."
            )
        )


    return found


def stylesheet_files() -> list:

    return sorted(
        path
        for path in (
            FRONTEND / "static"
        ).rglob(
            "*.css"
        )
    )


def relative(
    path: Path,
) -> str:

    return (
        path.relative_to(
            FRONTEND / "static"
        )
        .as_posix()
    )


# ==========================================================
# TEST 1 — PAGE INVENTORY
# ==========================================================

def test_page_inventory(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - PAGE INVENTORY"
    )
    print("-" * 76)


    # ======================================================
    # EVERY PAGE ON DISK HAS A ROUTE, AND VICE VERSA
    # ======================================================

    on_disk = sorted(
        path.name
        for path in (
            FRONTEND / "pages"
        ).glob(
            "*.html"
        )
    )


    assert_equal(
        on_disk,
        sorted(
            PAGES
        ),
        (
            "Every page on disk should be a known "
            "product page. An unrouted page is dead "
            "weight; a page missing from this list "
            "is unaudited."
        ),
    )


    for page in PAGES:

        route = ROUTES[
            page
        ]


        response = (
            client.get(
                route
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                f"{route} should serve {page}."
            ),
        )


        assert_true(
            "text/html"
            in response.headers[
                "content-type"
            ],
            (
                f"{route} should return HTML."
            ),
        )


    print(
        f"[PASS] All {len(PAGES)} pages exist and "
        "are routed"
    )


# ==========================================================
# TEST 1b — SYSTEM AND API ROUTES
# ==========================================================
#
# The product pages are only half the surface. The Phase 8
# screens are useless if the endpoints they read are not
# there, and the operational endpoints must keep working
# regardless of any frontend change.
# ==========================================================

def test_system_and_api_routes(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1b - SYSTEM AND API ROUTES"
    )
    print("-" * 76)


    # ======================================================
    # OPERATIONAL ENDPOINTS
    # ======================================================

    for route in (
        "/health",
        "/health/ready",
    ):

        response = (
            client.get(
                route
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                f"{route} should return HTTP 200."
            ),
        )


        # ==================================================
        # REQUEST CORRELATION SURVIVES
        # ==================================================

        assert_true(
            "X-Request-ID"
            in response.headers,
            (
                f"{route} should carry a "
                "server-generated request id."
            ),
        )


    print(
        "[PASS] /health and /health/ready both "
        "respond and carry a request id"
    )


    # ======================================================
    # THE ENDPOINTS THE PHASE 8 SCREENS READ
    # ======================================================

    for route, screen in (
        (
            "/api/v1/dashboard/summary",
            "Dashboard",
        ),
        (
            "/api/v1/documents?page=1&page_size=5",
            "Documents",
        ),
        (
            "/api/v1/reviews/queue",
            "Review Queue",
        ),
        (
            "/api/v1/reviewer/me",
            "the reviewer identity in every shell",
        ),
    ):

        assert_equal(
            client.get(
                route
            ).status_code,
            200,
            (
                f"The endpoint {screen} depends on "
                f"should respond: {route}"
            ),
        )


    print(
        "[PASS] Every endpoint the Phase 8 screens "
        "read responds"
    )


    # ======================================================
    # A REAL DOCUMENT ROUND TRIP
    # ======================================================
    #
    # The workspace route ignores the id when choosing a file,
    # so a synthetic id proves the route. This proves the DATA
    # path a real reviewer follows: pick a document out of the
    # list, then open its detail, image and history.
    # ======================================================

    listing = (
        client.get(
            "/api/v1/documents?page=1&page_size=1"
        )
        .json()
    )


    if not listing[
        "items"
    ]:

        print(
            "[SKIP] No persisted document to round "
            "trip. The list endpoint responded "
            "correctly and is empty."
        )

        return


    document_id = (
        listing[
            "items"
        ][
            0
        ][
            "document_id"
        ]
    )


    detail = (
        client.get(
            f"/api/v1/documents/{document_id}"
        )
    )


    assert_equal(
        detail.status_code,
        200,
        (
            "A document taken from the list should "
            "open."
        ),
    )


    payload = detail.json()


    for key in (
        "document",
        "analysis",
        "human_review",
        "final_record",
    ):

        assert_true(
            key in payload,
            (
                "The workspace reads "
                f"{key} from the detail response."
            ),
        )


    history = (
        client.get(
            f"/api/v1/documents/{document_id}/history"
        )
    )


    assert_equal(
        history.status_code,
        200,
        (
            "The audit history should open for a "
            "real document."
        ),
    )


    # ==================================================
    # THE IMAGE MAY LEGITIMATELY BE ABSENT
    # ==================================================
    #
    # Storage reconciliation can remove an orphaned file, and
    # the workspace degrades to an explained state. What must
    # not happen is an unhandled status.
    # ==================================================

    image = (
        client.get(
            f"/api/v1/documents/{document_id}/image"
        )
    )


    assert_true(
        image.status_code
        in (
            200,
            404,
        ),
        (
            "The document image endpoint should "
            "either serve the image or report a "
            "clean 404. Got "
            f"{image.status_code}."
        ),
    )


    if image.status_code == 404:

        assert_true(
            "error"
            in image.json(),
            (
                "A missing image should return the "
                "structured error contract."
            ),
        )


    # ==================================================
    # AND THE PAGE FOR IT
    # ==================================================

    assert_equal(
        client.get(
            f"/review/{document_id}"
        ).status_code,
        200,
        (
            "The workspace page should serve for a "
            "real document id."
        ),
    )


    print(
        f"[PASS] Round trip on a real document: "
        f"list, detail, history, image "
        f"({image.status_code}) and page"
    )


# ==========================================================
# TEST 2 — EVERY REFERENCED ASSET RESOLVES
# ==========================================================

def test_assets_resolve(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - ASSET RESOLUTION"
    )
    print("-" * 76)


    total = 0


    for page in PAGES:

        markup = (
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        references = (
            re.findall(
                r'(?:href|src)="(/review/static/[^"]+)"',
                markup,
            )
        )


        assert_true(
            len(
                references
            )
            > 0,
            (
                f"{page} references no assets, "
                "which cannot be right."
            ),
        )


        for reference in references:

            assert_equal(
                client.get(
                    reference
                ).status_code,
                200,
                (
                    f"{page} references an asset "
                    f"that does not resolve: "
                    f"{reference}"
                ),
            )


            total += 1


    print(
        f"[PASS] All {total} asset references "
        f"across {len(PAGES)} pages resolve"
    )


    # ======================================================
    # AND EVERY SHIPPED MODULE IS ACTUALLY USED
    # ======================================================
    #
    # A module nobody loads is dead code that still has to be
    # maintained and audited.
    # ======================================================

    linked = set()


    for page in PAGES:

        markup = (
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        for reference in re.findall(
            r'(?:href|src)="/review/static/([^"]+)"',
            markup,
        ):
            linked.add(
                reference
            )


    unused = []


    for path in javascript_files():

        name = relative(
            path
        )


        if name not in linked:

            unused.append(
                name
            )


    assert_equal(
        unused,
        [],
        (
            "Every shipped JavaScript module should "
            "be loaded by at least one page. An "
            "unloaded module is dead code."
        ),
    )


    print(
        f"[PASS] All {len(javascript_files())} "
        "modules are loaded by a page"
    )


# ==========================================================
# TEST 3 — NAVIGATION CONSISTENCY
# ==========================================================

def test_navigation_consistency(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - NAVIGATION CONSISTENCY"
    )
    print("-" * 76)


    def nav_block(
        markup: str,
    ) -> str:

        found = (
            re.search(
                r"<nav[^>]*>(.*?)</nav>",
                markup,
                re.DOTALL,
            )
        )


        assert_true(
            found is not None,
            (
                "A product page has no navigation "
                "block."
            ),
        )


        return found.group(
            1
        )


    # ======================================================
    # THE NAVIGATION IS IDENTICAL EVERYWHERE
    # ======================================================
    #
    # Compared after removing aria-current, which is the only
    # thing that may legitimately differ per page.
    #
    # Five hand-written copies of the same block is exactly the
    # kind of thing that drifts, so it is asserted rather than
    # hoped for.
    # ======================================================

    normalised = {}


    for page in PAGES:

        block = nav_block(
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        cleaned = (
            re.sub(
                r'\s*aria-current="page"',
                "",
                block,
            )
        )


        cleaned = (
            re.sub(
                r"\s+",
                " ",
                cleaned,
            )
            .strip()
        )


        normalised[
            page
        ] = cleaned


    distinct = set(
        normalised.values()
    )


    if len(
        distinct
    ) != 1:

        differences = []

        reference = normalised[
            PAGES[
                0
            ]
        ]

        for page in PAGES[
            1:
        ]:

            if normalised[
                page
            ] != reference:

                differences.append(
                    page
                )


        raise AssertionError(
            (
                "The primary navigation differs "
                "between pages, ignoring "
                "aria-current. Pages that diverge "
                f"from {PAGES[0]}: {differences}"
            )
        )


    print(
        f"[PASS] The navigation block is identical "
        f"on all {len(PAGES)} pages"
    )


    # ======================================================
    # FOUR REAL LINKS, ALL RESOLVING, ONE ACTIVE
    # ======================================================

    destinations = (
        "/dashboard",
        "/upload",
        "/documents",
        "/review",
    )


    for page in PAGES:

        markup = (
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        block = nav_block(
            markup
        )


        hrefs = (
            re.findall(
                r'href="([^"]+)"',
                block,
            )
        )


        assert_equal(
            hrefs,
            list(
                destinations
            ),
            (
                "Every page should offer the same "
                "four destinations in the same "
                f"order: {page}"
            ),
        )


        # ==================================================
        # NOTHING IS PENDING ANY MORE
        # ==================================================

        assert_false(
            "is-pending"
            in block
            or "nav-pending-tag"
            in block,
            (
                "Every destination is built, so no "
                "navigation item should still be "
                f"marked pending: {page}"
            ),
        )


        # ==================================================
        # EXACTLY ONE ACTIVE ITEM
        # ==================================================

        active = (
            re.findall(
                r'aria-current="page"',
                block,
            )
        )


        assert_equal(
            len(
                active
            ),
            1,
            (
                "Exactly one navigation item may be "
                f"marked current: {page}"
            ),
        )


    print(
        "[PASS] Four resolving destinations in a "
        "fixed order, nothing pending, exactly one "
        "active item per page"
    )


# ==========================================================
# TEST 4 — REQUEST ARCHITECTURE
# ==========================================================

def test_request_architecture():

    print()
    print("-" * 76)
    print(
        "TEST 4 - REQUEST ARCHITECTURE"
    )
    print("-" * 76)


    callers = []


    for path in javascript_files():

        code = (
            strip_js_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        if "fetch(" in code:

            callers.append(
                relative(
                    path
                )
            )


    assert_equal(
        callers,
        [
            FETCH_OWNER,
        ],
        (
            "Exactly one file may call fetch. The "
            "Phase 8.3 audit found 8 separate fetch "
            "sites, each with its own error handling "
            "and all of them reading the legacy "
            "`detail` field. Centralising it is why "
            "the shared client exists."
        ),
    )


    print(
        f"[PASS] Exactly one fetch site, in "
        f"{FETCH_OWNER}"
    )


    # ======================================================
    # ONLY THE UPLOAD PAGE MAY POLL, AND ONLY ON A LEASH
    # ======================================================
    #
    # PHASE 9.4 CHANGED THIS RULE. It used to be "no timer may
    # issue a request", full stop, and that was right while
    # every screen loaded once.
    #
    # Async processing makes it wrong. A document now becomes a
    # job and the Upload page has to ask the server how it is
    # getting on, because the alternative is inventing progress
    # -- which is what the page used to do, rotating five
    # written-in-advance sentences on a 2.6 second timer while
    # a synchronous request blocked for eighteen seconds.
    #
    # So the rule is narrowed rather than dropped, and the
    # narrowed version is stricter than the original in three
    # ways:
    #
    #   1. It now covers setTimeout as well as setInterval. The
    #      original only looked at setInterval, which means the
    #      poll loop added in Phase 9.4 would have passed the
    #      old rule without being examined at all.
    #
    #   2. Exactly one module may poll, by name. Not a
    #      directory, not a pattern -- js/upload.js. Any other
    #      module gaining a timer that touches the network is a
    #      failure.
    #
    #   3. The one module that may poll has to prove it is on a
    #      leash: a bounded poll count, an AbortController, a
    #      clearTimeout, and a beforeunload handler that stops
    #      it. A poller with no ceiling is a page that hammers
    #      a server forever after the tab is forgotten.
    #
    # setInterval is forbidden for polling outright, including
    # in upload.js. An interval keeps firing while a slow
    # response is still outstanding and stacks requests on a
    # server that is by definition already busy; chained
    # setTimeout cannot do that, because the next one is only
    # scheduled once an answer has arrived.
    # ======================================================

    #   4. PHASE 9.4 added the batch view, which polls the
    #      batch endpoint. Two modules now, still named
    #      individually, and both have to prove the same leash.
    #
    #      The batch loop is one chain for the whole batch, not
    #      one per file: the batch endpoint returns every
    #      child's state in one response, so twenty files are
    #      still one request per interval.
    POLLING_ALLOWED = {
        "js/upload.js",
        "js/upload_batch.js",
    }

    NETWORK_MARKERS = (
        "api.",
        "endpoints.",
        "fetch(",
        "XMLHttpRequest",
    )

    def timer_bodies(
        code: str,
        opener: str,
    ) -> list:

        bodies = []
        search = 0


        while True:

            start_at = code.find(
                opener,
                search,
            )


            if start_at == -1:
                break


            # Walk to the matching close paren, so a nested
            # function body is captured whole.
            depth = 0

            index = code.index(
                "(",
                start_at,
            )

            finish = None


            while index < len(
                code
            ):

                if code[
                    index
                ] == "(":
                    depth += 1

                elif code[
                    index
                ] == ")":
                    depth -= 1

                    if depth == 0:
                        finish = index
                        break


                index += 1


            if finish is None:
                break


            bodies.append(
                code[
                    start_at:
                    finish
                ]
            )


            search = finish


        return bodies


    unauthorized_pollers = []

    interval_pollers = []

    timer_users = []

    poller_modules = []


    for path in javascript_files():

        name = relative(
            path
        )


        code = (
            strip_js_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        interval_calls = timer_bodies(
            code,
            "setInterval(",
        )

        timeout_calls = timer_bodies(
            code,
            "setTimeout(",
        )


        if interval_calls or timeout_calls:

            timer_users.append(
                name
            )


        # ------------------------------------------------
        # FOLLOW ONE LEVEL OF INDIRECTION
        # ------------------------------------------------
        #
        # A timer body rarely calls the network directly. The
        # real shape is
        #
        #     setTimeout(function () { pollJob(id); }, ms)
        #
        # where pollJob is what touches the network. A scan
        # that only looked inside the timer body would find
        # nothing and report that no module polls -- which is
        # exactly what the first version of this rule did, and
        # it passed while upload.js was polling.
        #
        # So the identifiers called inside each timer body are
        # collected, and any function of that name defined in
        # the same file is examined too.
        # ------------------------------------------------

        def reaches_network(
            bodies: list,
        ) -> bool:

            for body in bodies:

                for marker in NETWORK_MARKERS:

                    if marker in body:
                        return True


                for called in re.findall(
                    r"\b([A-Za-z_$][\w$]*)\s*\(",
                    body,
                ):

                    if called in (
                        "setTimeout",
                        "setInterval",
                        "function",
                        "clearTimeout",
                        "clearInterval",
                    ):
                        continue


                    for pattern in (
                        "function " + called + "(",
                        "var " + called + " = function",
                        called + " = function",
                    ):

                        at = code.find(
                            pattern
                        )

                        if at == -1:
                            continue


                        # A generous window rather than a real
                        # parse. These functions are small and
                        # the alternative is a JavaScript
                        # parser in a Python test.
                        window = code[
                            at:
                            at + 4000
                        ]

                        for marker in NETWORK_MARKERS:

                            if marker in window:
                                return True


            return False


        uses_network = False


        for body in interval_calls:

            for marker in NETWORK_MARKERS:

                if marker in body:

                    uses_network = True

                    # An interval that touches the network is
                    # wrong even in the module that is allowed
                    # to poll.
                    interval_pollers.append(
                        (
                            name,
                            marker,
                        )
                    )


        if timeout_calls and reaches_network(
            timeout_calls
        ):

            uses_network = True


            if name not in POLLING_ALLOWED:

                unauthorized_pollers.append(
                    (
                        name,
                        "setTimeout -> network",
                    )
                )


        if uses_network:

            poller_modules.append(
                name
            )


    assert_equal(
        unauthorized_pollers,
        [],
        (
            "Only the Upload page may poll, because "
            "only it is waiting on a job. Every other "
            "screen loads once and offers an explicit "
            "refresh where refreshing makes sense."
        ),
    )


    assert_equal(
        interval_pollers,
        [],
        (
            "setInterval must never issue a request, "
            "including on the Upload page. An interval "
            "keeps firing while a slow response is "
            "outstanding and stacks requests on a "
            "server that is already busy. Chain "
            "setTimeout instead, so the next poll is "
            "only scheduled once an answer arrives."
        ),
    )


    # ------------------------------------------------------
    # THE LEASH
    # ------------------------------------------------------

    LEASH_REQUIREMENTS = {
        "a bounded poll ceiling":
            "MAX_POLLS",

        "an AbortController on the request in flight":
            "AbortController",

        "a clearTimeout so the loop can be stopped":
            "clearTimeout",

        "a beforeunload handler":
            "beforeunload",

        "a token guard against duplicate loops":
            "pollToken",
    }

    missing_leash = []


    for module in sorted(
        POLLING_ALLOWED
    ):

        module_source = (
            strip_js_comments(
                (
                    PROJECT_ROOT
                    / "frontend"
                    / "static"
                    / module
                ).read_text(
                    encoding="utf-8"
                )
            )
        )

        for requirement, marker in (
            LEASH_REQUIREMENTS.items()
        ):

            if marker not in module_source:

                missing_leash.append(
                    f"{module}: {requirement}"
                )


    assert_equal(
        sorted(
            missing_leash
        ),
        [],
        (
            "A module is allowed to poll only because "
            "it is bounded and stoppable. Without every "
            "one of these it is a page that hammers the "
            "server forever after the tab is forgotten."
        ),
    )


    # This rule is only meaningful if it can see the poller
    # that is known to exist. An empty list here means the
    # detection is broken, not that nothing polls -- which is
    # how the first version of this rule passed.
    undetected = sorted(
        POLLING_ALLOWED
        - set(
            poller_modules
        )
    )

    if undetected:

        raise AssertionError(
            (
                "The polling detector did not find "
                f"{undetected}, which are known to poll. "
                "The rule is not looking properly, so a "
                "pass from it means nothing.\n"
                f"detected: {sorted(poller_modules)}"
            )
        )


    print(
        f"[PASS] Only {sorted(poller_modules)} polls, "
        f"with a bounded ceiling, an AbortController, "
        f"a stop path and no setInterval "
        f"({len(timer_users)} module(s) use a timer)"
    )


    # ======================================================
    # THE SHARED CLIENT CARRIES THE ERROR CONTRACT
    # ======================================================

    api_source = (
        FRONTEND
        / "static"
        / "js"
        / "api.js"
    ).read_text(
        encoding="utf-8"
    )


    for needle, description in (
        (
            "error.code",
            "the structured code",
        ),
        (
            "structured.code",
            "the structured code lookup",
        ),
        (
            "structured.message",
            "the structured message",
        ),
        (
            "request_id",
            "the structured request id",
        ),
        (
            "X-Request-ID",
            "the request id header",
        ),
        (
            "body.detail",
            "the legacy detail fallback",
        ),
    ):

        assert_true(
            needle in api_source,
            (
                "The shared client should handle "
                f"{description}."
            ),
        )


    # ==================================================
    # LEGACY COMPATIBILITY IS RETAINED, NOT PREFERRED
    # ==================================================
    #
    # The structured branch has to come first, or a response
    # carrying both would be read from the legacy field.
    # ==================================================

    structured_at = (
        api_source.index(
            "var structured ="
        )
    )


    legacy_at = (
        api_source.index(
            "var legacy ="
        )
    )


    assert_true(
        structured_at < legacy_at,
        (
            "The structured error contract must be "
            "consulted before the legacy `detail` "
            "field, or a response carrying both "
            "would be read from the wrong one."
        ),
    )


    print(
        "[PASS] The structured contract is "
        "authoritative and `detail` remains only a "
        "fallback"
    )


    # ======================================================
    # IN-FLIGHT DEDUPLICATION EXISTS AND IS USED
    # ======================================================

    assert_true(
        "getJsonShared"
        in api_source,
        (
            "Concurrent reads of the same endpoint "
            "should share one request. The audit "
            "found the same endpoints being fetched "
            "more than once per page load."
        ),
    )


    assert_true(
        "getJsonShared(\"/api/v1/reviewer/me\")"
        in api_source,
        (
            "Reviewer identity is the endpoint most "
            "likely to be requested twice, so it "
            "should use the shared path."
        ),
    )


    print(
        "[PASS] In-flight deduplication exists and "
        "covers reviewer identity"
    )


# ==========================================================
# TEST 5 — SAFE RENDERING AND PRIVACY
# ==========================================================

def test_safe_rendering_and_privacy():

    print()
    print("-" * 76)
    print(
        "TEST 5 - SAFE RENDERING AND PRIVACY"
    )
    print("-" * 76)


    audited = 0


    for path in javascript_files():

        name = relative(
            path
        )


        problems = (
            audit_frontend_module(
                path.read_text(
                    encoding="utf-8"
                ),
                name,
                allow_fetch=(
                    name == FETCH_OWNER
                ),
            )
        )


        assert_equal(
            problems,
            [],
            (
                f"{name} failed the frontend audit."
            ),
        )


        audited += 1


    print(
        f"[PASS] All {audited} modules: no "
        f"{len(UNSAFE_SINKS)} unsafe sinks, no "
        f"{len(CONSOLE_CALLS)} console calls, no "
        f"{len(SECRET_MARKERS)} secret markers"
    )


    # ======================================================
    # AND THE PAGES THEMSELVES
    # ======================================================
    #
    # An inline handler or an inline <script> would be a
    # rendering sink outside the module audit.
    # ======================================================

    for page in PAGES:

        markup = (
            FRONTEND
            / "pages"
            / page
        ).read_text(
            encoding="utf-8"
        )


        for handler in (
            "onclick=",
            "onerror=",
            "onload=",
            "onsubmit=",
            "onchange=",
            "javascript:",
        ):

            assert_false(
                handler in markup,
                (
                    "Pages must not carry inline "
                    "handlers. Behaviour belongs in "
                    f"a module: {page} has "
                    f"{handler}"
                ),
            )


        inline_scripts = (
            re.findall(
                r"<script(?![^>]*\bsrc=)[^>]*>",
                markup,
            )
        )


        assert_equal(
            inline_scripts,
            [],
            (
                "Pages must not carry inline "
                f"script: {page}"
            ),
        )


    print(
        f"[PASS] No inline handlers and no inline "
        f"script across {len(PAGES)} pages"
    )


    # ======================================================
    # NO CREDENTIAL MATERIAL IN ANY FRONTEND FILE
    # ======================================================

    frontend_files = (
        javascript_files()
        + stylesheet_files()
        + sorted(
            (
                FRONTEND / "pages"
            ).glob(
                "*.html"
            )
        )
    )


    for path in frontend_files:

        lowered = (
            path.read_text(
                encoding="utf-8"
            )
            .lower()
        )


        for marker in SECRET_MARKERS:

            assert_false(
                marker.lower()
                in lowered,
                (
                    "The frontend must never "
                    f"contain {marker}: {path.name}"
                ),
            )


    print(
        f"[PASS] No credential material in any of "
        f"{len(frontend_files)} frontend files"
    )


# ==========================================================
# TEST 6 — STYLESHEET OWNERSHIP AND CLEANUP
# ==========================================================

def test_stylesheets(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - STYLESHEETS"
    )
    print("-" * 76)


    # ======================================================
    # TOKENS HAVE EXACTLY ONE OWNER
    # ======================================================

    # A top-level :root block DECLARES tokens. A :root inside a
    # media query only OVERRIDES one for a breakpoint, which is
    # how a responsive token is supposed to work, so the two
    # are distinguished rather than lumped together.

    declarers = []


    for path in stylesheet_files():

        code = (
            strip_css_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        if re.search(
            r"^:root\s*\{",
            code,
            re.MULTILINE,
        ):

            declarers.append(
                relative(
                    path
                )
            )


    assert_equal(
        declarers,
        [
            "css/tokens.css",
        ],
        (
            "Design tokens must have exactly one "
            "owner. A second top-level :root block "
            "is how two stylesheets start "
            "disagreeing about the same colour."
        ),
    )


    print(
        "[PASS] Tokens have exactly one declaring "
        "owner"
    )


    # ======================================================
    # AND AN OVERRIDE MAY ONLY OVERRIDE A REAL TOKEN
    # ======================================================
    #
    # A breakpoint that sets a token tokens.css never declared
    # would look like it worked while every var() reading it
    # fell back to nothing.
    # ======================================================

    owner_source = (
        strip_css_comments(
            (
                FRONTEND
                / "static"
                / "css"
                / "tokens.css"
            ).read_text(
                encoding="utf-8"
            )
        )
    )


    owned = set(
        re.findall(
            r"(--[\w-]+)\s*:",
            owner_source,
        )
    )


    undeclared = set()


    for path in stylesheet_files():

        name = relative(
            path
        )


        if name == "css/tokens.css":
            continue


        code = (
            strip_css_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        for token in re.findall(
            r"(--[\w-]+)\s*:",
            code,
        ):

            if token not in owned:

                undeclared.add(
                    (
                        name,
                        token,
                    )
                )


    assert_equal(
        sorted(
            undeclared
        ),
        [],
        (
            "A stylesheet sets a token that "
            "tokens.css never declares, so every "
            "var() reading it falls back to "
            "nothing."
        ),
    )


    print(
        f"[PASS] Every token override targets one "
        f"of the {len(owned)} declared tokens"
    )


    # ======================================================
    # THE RETIRED STYLESHEET STAYS RETIRED
    # ======================================================

    retired = (
        client.get(
            RETIRED_STYLESHEET
        )
    )


    assert_equal(
        retired.status_code,
        200,
        (
            "The retired stylesheet URL must keep "
            "resolving. Real browsers have it "
            "cached and existing regressions fetch "
            "it by name."
        ),
    )


    rules = (
        strip_css_comments(
            retired.text
        )
        .strip()
    )


    assert_equal(
        rules,
        "",
        (
            "The retired stylesheet must contain no "
            "rules. An audit found 100 of its 141 "
            "classes unreferenced and the other 41 "
            "already covered by the design system. "
            "Deleting dead rules is the point of "
            "the cleanup."
        ),
    )


    for page in PAGES:

        markup = (
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        assert_false(
            RETIRED_STYLESHEET
            in markup,
            (
                "No page may link the retired "
                f"stylesheet: {page}"
            ),
        )


    print(
        "[PASS] The retired stylesheet resolves, "
        "contains no rules, and is linked by no "
        "page"
    )


    # ======================================================
    # EVERY var() RESOLVES TO A DECLARED TOKEN
    # ======================================================

    tokens_source = (
        FRONTEND
        / "static"
        / "css"
        / "tokens.css"
    ).read_text(
        encoding="utf-8"
    )


    declared = set(
        re.findall(
            r"(--[\w-]+)\s*:",
            tokens_source,
        )
    )


    missing = set()


    for path in stylesheet_files():

        code = (
            strip_css_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        for name in re.findall(
            r"var\(\s*(--[\w-]+)",
            code,
        ):

            if name not in declared:

                missing.add(
                    (
                        relative(
                            path
                        ),
                        name,
                    )
                )


    assert_equal(
        sorted(
            missing
        ),
        [],
        (
            "A var() reference resolves to no "
            "declared token, so that property "
            "silently falls back to its initial "
            "value."
        ),
    )


    print(
        f"[PASS] Every var() across "
        f"{len(stylesheet_files())} stylesheets "
        f"resolves to one of {len(declared)} "
        "declared tokens"
    )


    # ======================================================
    # THE RESPONSIVE LAYER COVERS EVERY SCREEN
    # ======================================================

    responsive = (
        client.get(
            "/review/static/css/responsive.css"
        )
        .text
    )


    breakpoints = (
        responsive.count(
            "@media"
        )
    )


    assert_true(
        breakpoints >= 5,
        (
            "The responsive layer should cover "
            "large desktop, laptop, tablet, phone "
            "and short-viewport cases. Found "
            f"{breakpoints}."
        ),
    )


    for selector, screen in (
        (
            ".attention-panel",
            "Dashboard",
        ),
        (
            ".toolbar",
            "Documents",
        ),
        (
            ".reason-chips",
            "Review Queue",
        ),
        (
            ".workspace-source",
            "Document Workspace",
        ),
        (
            ".drop-zone",
            "Upload",
        ),
    ):

        assert_true(
            selector in responsive,
            (
                "The responsive layer has no rule "
                f"for the {screen} screen "
                f"({selector})."
            ),
        )


    # ==================================================
    # NAVIGATION SURVIVES SMALL SCREENS
    # ==================================================
    #
    # The pre-Phase-8 stylesheet hid the sidebar outright below
    # 760px, which removed every navigation link on a phone.
    # ==================================================

    for path in stylesheet_files():

        code = (
            strip_css_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        assert_true(
            re.search(
                r"\.sidebar\s*\{[^}]*display\s*:\s*none",
                code,
            )
            is None,
            (
                "The sidebar must never be hidden "
                "outright, because that removes all "
                "navigation. It should reflow: "
                f"{relative(path)}"
            ),
        )


    print(
        f"[PASS] {breakpoints} breakpoints, a rule "
        "for all 5 screens, and navigation never "
        "hidden outright"
    )


# ==========================================================
# TEST 7 — ACCESSIBILITY BASELINE
# ==========================================================

def test_accessibility_baseline(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - ACCESSIBILITY BASELINE"
    )
    print("-" * 76)


    for page in PAGES:

        markup = (
            client.get(
                ROUTES[
                    page
                ]
            )
            .text
        )


        # ==================================================
        # LANDMARKS AND LANGUAGE
        # ==================================================

        for description, needle in (
            (
                "a language declaration",
                '<html lang="en"',
            ),
            (
                "a responsive viewport",
                "width=device-width",
            ),
            (
                "a skip link",
                'class="skip-link"',
            ),
            (
                "a main landmark",
                "<main",
            ),
            (
                "a skip target",
                'id="main-content"',
            ),
            (
                "a navigation landmark",
                "<nav",
            ),
            (
                "a labelled navigation",
                'aria-label="Primary"',
            ),
            (
                "a complementary landmark",
                "<aside",
            ),
            (
                "a page title",
                "<title>",
            ),
        ):

            assert_true(
                needle in markup,
                (
                    f"{page} is missing "
                    f"{description}."
                ),
            )


        # ==================================================
        # EXACTLY ONE h1
        # ==================================================

        assert_equal(
            len(
                re.findall(
                    r"<h1[\s>]",
                    markup,
                )
            ),
            1,
            (
                f"{page} should have exactly one h1."
            ),
        )


        # ==================================================
        # NO SKIPPED HEADING LEVEL
        # ==================================================

        levels = [
            int(
                level
            )
            for level in re.findall(
                r"<h([1-6])[\s>]",
                markup,
            )
        ]


        seen = set()


        for level in levels:

            if level > 1:

                assert_true(
                    (
                        level - 1
                    )
                    in seen
                    or level in seen,
                    (
                        f"{page} jumps to an h{level} "
                        f"without an h{level - 1} "
                        "before it. A screen-reader "
                        "user navigating by heading "
                        "would lose the structure."
                    ),
                )


            seen.add(
                level
            )


        # ==================================================
        # NO DIV PRETENDING TO BE A CONTROL
        # ==================================================

        for fake in (
            'role="button"',
            'role="link"',
            'role="checkbox"',
            'role="dialog"',
        ):

            assert_false(
                fake in markup,
                (
                    f"{page} carries {fake}. Real "
                    "elements come with focus, "
                    "keyboard behaviour and "
                    "announcements already; a div "
                    "with a role has to reimplement "
                    "all three and usually gets one "
                    "wrong."
                ),
            )


        # ==================================================
        # EVERY FORM CONTROL HAS A REAL LABEL
        # ==================================================

        controls = (
            re.findall(
                r"<(input|select|textarea)\b([^>]*)>",
                markup,
            )
        )


        labelled = set(
            re.findall(
                r'<label[^>]*\bfor="([^"]+)"',
                markup,
            )
        )


        for (
            tag,
            attributes,
        ) in controls:

            control_id = (
                re.search(
                    r'id="([^"]+)"',
                    attributes,
                )
            )


            # A control wrapped in its own label needs no id,
            # and a hidden control is not a control.
            if control_id is None:

                assert_true(
                    "hidden" in attributes
                    or 'type="hidden"' in attributes,
                    (
                        f"{page} has a <{tag}> with "
                        "no id, so no label can "
                        "point at it."
                    ),
                )

                continue


            name = control_id.group(
                1
            )


            has_label = (
                name in labelled
                or "aria-label"
                in attributes
                or "aria-labelledby"
                in attributes
            )


            assert_true(
                has_label,
                (
                    f"{page}: the <{tag}> #{name} "
                    "has no label, no aria-label and "
                    "no aria-labelledby."
                ),
            )


        # ==================================================
        # EVERY BUTTON INSIDE A FORM DECLARES ITS TYPE
        # ==================================================
        #
        # A button with no type submits, which is almost never
        # what a filter bar wants.
        # ==================================================

        for attributes in re.findall(
            r"<button\b([^>]*)>",
            markup,
        ):

            assert_true(
                'type="' in attributes,
                (
                    f"{page} has a <button> with no "
                    "explicit type. The default is "
                    "submit."
                ),
            )


        # ==================================================
        # ARIA REFERENCES POINT AT SOMETHING
        # ==================================================

        for attribute in (
            "aria-labelledby",
            "aria-describedby",
            "aria-controls",
        ):

            for value in re.findall(
                r'{0}="([^"]+)"'.format(
                    attribute
                ),
                markup,
            ):

                for target in value.split():

                    assert_true(
                        f'id="{target}"'
                        in markup,
                        (
                            f"{page}: {attribute} "
                            "points at a missing id: "
                            f"{target}"
                        ),
                    )


    print(
        f"[PASS] All {len(PAGES)} pages: landmarks, "
        "one h1, no skipped heading level, no fake "
        "controls, every control labelled, every "
        "button typed, every aria reference resolves"
    )


    # ======================================================
    # FOCUS IS ALWAYS VISIBLE
    # ======================================================

    base = (
        client.get(
            "/review/static/css/base.css"
        )
        .text
    )


    assert_true(
        ":focus-visible"
        in base,
        (
            "There must be a visible focus "
            "treatment, or keyboard users cannot "
            "tell where they are."
        ),
    )


    assert_false(
        re.search(
            r":focus\s*\{[^}]*outline\s*:\s*none",
            strip_css_comments(
                base
            ),
        )
        is not None
        and ":focus-visible"
        not in base,
        (
            "Focus outlines must not be removed "
            "without a replacement."
        ),
    )


    # ======================================================
    # REDUCED MOTION IS HONOURED
    # ======================================================

    assert_true(
        "prefers-reduced-motion"
        in base,
        (
            "A user who asks for reduced motion "
            "should get it."
        ),
    )


    print(
        "[PASS] Visible focus treatment and "
        "reduced-motion support"
    )


# ==========================================================
# TEST 8 — VOCABULARY OWNERSHIP
# ==========================================================

def test_vocabulary_ownership(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - VOCABULARY OWNERSHIP"
    )
    print("-" * 76)


    # ======================================================
    # BACKEND CODES ARE TRANSLATED IN ONE PLACE
    # ======================================================
    #
    # Three screens present anomaly codes, evidence flags and
    # confidence statuses. Translating them in three places
    # guarantees the three eventually disagree.
    # ======================================================

    vocabulary = (
        client.get(
            "/review/static/js/vocabulary.js"
        )
        .text
    )


    for needle, description in (
        (
            "MISSING_CRITICAL_FIELD",
            "anomaly codes",
        ),
        (
            "EVIDENCE_MISMATCH",
            "evidence flag kinds",
        ),
        (
            "INVALID_EVIDENCE",
            "confidence statuses",
        ),
        (
            "SKIPPED_INVALID_EVIDENCE",
            "date field statuses",
        ),
        (
            "AUTO_ACCEPTED",
            "final statuses",
        ),
        (
            "describeReasonCode",
            "the reason code translator",
        ),
        (
            "describeEvidenceFlag",
            "the evidence flag translator",
        ),
    ):

        assert_true(
            needle in vocabulary,
            (
                "The shared vocabulary should own "
                f"{description}."
            ),
        )


    # ======================================================
    # AND NOBODY ELSE DUPLICATES THEM
    # ======================================================

    duplicators = []


    for path in javascript_files():

        name = relative(
            path
        )


        if name == "js/vocabulary.js":
            continue


        code = (
            strip_js_comments(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )


        if "MISSING_CRITICAL_FIELD" in code:

            duplicators.append(
                name
            )


    assert_equal(
        duplicators,
        [],
        (
            "Anomaly codes should be translated only "
            "in the shared vocabulary. A second copy "
            "is how two screens start describing the "
            "same finding differently."
        ),
    )


    print(
        "[PASS] Backend codes are translated in "
        "exactly one module"
    )


    # ======================================================
    # UNKNOWN CODES ARE SHOWN, NOT SWALLOWED
    # ======================================================

    assert_true(
        "known: false"
        in vocabulary,
        (
            "An unrecognised code must be surfaced "
            "as itself. Relabelling it as something "
            "familiar, or hiding it, would mean a "
            "future backend code silently reads as "
            "healthy."
        ),
    )


    print(
        "[PASS] An unrecognised code is surfaced "
        "as itself"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 76)
    print(
        "PHASE 8.15 — GLOBAL FRONTEND AUDIT"
    )
    print("=" * 76)


    client = None


    try:

        client = TestClient(
            app
        )

        client.__enter__()


        test_page_inventory(
            client
        )

        test_system_and_api_routes(
            client
        )

        test_assets_resolve(
            client
        )

        test_navigation_consistency(
            client
        )

        test_request_architecture()

        test_safe_rendering_and_privacy()

        test_stylesheets(
            client
        )

        test_accessibility_baseline(
            client
        )

        test_vocabulary_ownership(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.15 GLOBAL FRONTEND "
            "AUDIT PASSED"
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
