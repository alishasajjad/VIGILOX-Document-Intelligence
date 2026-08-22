import re

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)


# ==========================================================
# PHASE 8.4 / 8.5
# DESIGN SYSTEM + APPLICATION SHELL CONTRACT TEST
# ==========================================================
#
# These are contract tests, not visual tests.
#
# Nothing here asserts a colour, a pixel value or a piece of
# copy, because those are expected to change as the product
# is designed. What is asserted is structural and security
# behaviour that must not regress:
#
#     the design-system entrypoints are actually served
#     the legacy asset URLs still resolve
#     accessibility landmarks exist on every page
#     navigation never contains a broken link
#     reviewer identity stays server-resolved
#     new shared JS renders without innerHTML
#
# The pages are fetched over HTTP rather than read from disk,
# so the FastAPI static mount is exercised too.
# ==========================================================

DESIGN_SYSTEM_ASSETS = (
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/responsive.css",
)


SHARED_SCRIPTS = (
    "/review/static/js/api.js",
    "/review/static/js/common.js",
)


# ----------------------------------------------------------
# Asset URLs that existed before Phase 8. Existing dashboard
# tests fetch these by name, and real browsers have them
# cached, so they must keep resolving.
# ----------------------------------------------------------

LEGACY_ASSETS = (
    "/review/static/dashboard.css",
    "/review/static/dashboard.js",
    "/review/static/review_detail.js",
)


SHELL_PAGES = (
    "/review",
    "/review/00000000-0000-4000-8000-000000000000",
)


PRIMARY_NAVIGATION = (
    "Dashboard",
    "Upload Document",
    "Documents",
    "Review Queue",
)


# ==========================================================
# JAVASCRIPT COMMENT STRIPPING
# ==========================================================
#
# The safe-rendering assertions below must inspect executable
# code, not prose.
#
# common.js documents *why* it avoids innerHTML, so a naive
# substring search matches its own explanation and fails.
# That is a defect in the assertion, not in the module.
#
# This strips // line comments and /* block */ comments so the
# checks look only at code.
# ==========================================================

def strip_js_comments(
    source: str,
) -> str:

    result = []

    index = 0
    length = len(source)

    in_line_comment = False
    in_block_comment = False
    in_string = None


    while index < length:

        char = source[index]
        following = (
            source[index + 1]
            if index + 1 < length
            else ""
        )


        # ==============================================
        # INSIDE A COMMENT
        # ==============================================

        if in_line_comment:

            if char == "\n":
                in_line_comment = False
                result.append(char)

            index += 1
            continue


        if in_block_comment:

            if char == "*" and following == "/":
                in_block_comment = False
                index += 2
                continue

            index += 1
            continue


        # ==============================================
        # INSIDE A STRING
        # ==============================================

        if in_string:

            result.append(char)

            if char == "\\":
                if index + 1 < length:
                    result.append(following)
                index += 2
                continue

            if char == in_string:
                in_string = None

            index += 1
            continue


        # ==============================================
        # CODE
        # ==============================================

        if char == "/" and following == "/":
            in_line_comment = True
            index += 2
            continue

        if char == "/" and following == "*":
            in_block_comment = True
            index += 2
            continue

        if char in ("\"", "'", "`"):
            in_string = char
            result.append(char)
            index += 1
            continue

        result.append(char)
        index += 1


    return "".join(result)


def strip_css_comments(
    source: str,
) -> str:

    # ======================================================
    # Same reasoning as strip_js_comments.
    #
    # dashboard.css documents which shell rules were removed
    # from it, including the old
    #
    #     .sidebar { display: none }
    #
    # so a regex looking for that rule matches the note
    # describing its removal. The assertion is about CSS
    # rules, not prose.
    # ======================================================

    result = []

    index = 0
    length = len(source)


    while index < length:

        if (
            source[index] == "/"
            and index + 1 < length
            and source[index + 1] == "*"
        ):

            closing = (
                source.find(
                    "*/",
                    index + 2,
                )
            )


            if closing == -1:
                break

            index = closing + 2
            continue


        result.append(
            source[index]
        )

        index += 1


    return "".join(result)


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
# TEST 1 — DESIGN SYSTEM IS SERVED
# ==========================================================

def test_design_system_assets(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - DESIGN SYSTEM ASSETS"
    )
    print("-" * 76)


    for path in DESIGN_SYSTEM_ASSETS:

        response = (
            client.get(
                path
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Design system stylesheet "
                f"should be served: {path}"
            ),
        )


        assert_true(
            len(
                response.content
            )
            > 0,
            (
                "Design system stylesheet "
                f"should not be empty: {path}"
            ),
        )


    print(
        "[PASS] All 5 design system "
        "stylesheets served"
    )


    for path in SHARED_SCRIPTS:

        response = (
            client.get(
                path
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Shared script should be "
                f"served: {path}"
            ),
        )


    print(
        "[PASS] Shared api.js and common.js "
        "served"
    )


    # ======================================================
    # BACKWARD COMPATIBILITY
    # ======================================================

    for path in LEGACY_ASSETS:

        response = (
            client.get(
                path
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Pre-Phase-8 asset URL must "
                f"keep resolving: {path}"
            ),
        )


    print(
        "[PASS] Legacy asset URLs still "
        "resolve"
    )


# ==========================================================
# TEST 2 — DESIGN TOKENS
# ==========================================================

def test_design_tokens(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - DESIGN TOKEN COVERAGE"
    )
    print("-" * 76)


    tokens = (
        client.get(
            "/review/static/css/tokens.css"
        )
        .text
    )


    # ======================================================
    # TOKEN FAMILIES
    # ======================================================
    #
    # Named families rather than individual values, so the
    # palette can be retuned without breaking this test.
    # ======================================================

    required_families = {
        "surface":
            "--surface",

        "text":
            "--text",

        "border":
            "--border",

        "brand":
            "--primary",

        "success":
            "--success",

        "warning":
            "--warning",

        "danger":
            "--danger",

        "spacing":
            "--space-4",

        "typography":
            "--text-base",

        "font weight":
            "--weight-semibold",

        "radius":
            "--radius",

        "shadow":
            "--shadow-sm",

        "focus":
            "--focus-ring",

        "layout width":
            "--sidebar-width",

        "confidence state":
            "--confidence-high",

        "expiry state":
            "--expiry-expired",

        "review state":
            "--state-pending",

        "anomaly severity":
            "--severity-warning",

        "provenance":
            "--provenance-human",
    }


    for (
        family,
        token,
    ) in required_families.items():

        assert_true(
            token in tokens,
            (
                "Design tokens are missing the "
                f"{family} family: {token}"
            ),
        )


    print(
        f"[PASS] All {len(required_families)} "
        "token families defined"
    )


    # ======================================================
    # ORIGINAL TOKEN NAMES PRESERVED
    # ======================================================
    #
    # dashboard.css still contains many var() references
    # that were written against the original names. If a
    # name were dropped here those rules would silently
    # lose their value.
    # ======================================================

    legacy_tokens = (
        "--background",
        "--surface",
        "--sidebar",
        "--sidebar-soft",
        "--text",
        "--text-soft",
        "--border",
        "--primary",
        "--primary-soft",
        "--success",
        "--success-soft",
        "--danger",
        "--danger-soft",
        "--warning",
        "--warning-soft",
        "--high",
        "--high-soft",
        "--medium",
        "--medium-soft",
        "--low",
        "--low-soft",
        "--radius",
    )


    for token in legacy_tokens:

        assert_true(
            f"{token}:" in tokens,
            (
                "Original token name must be "
                "preserved so existing var() "
                f"references resolve: {token}"
            ),
        )


    print(
        f"[PASS] All {len(legacy_tokens)} "
        "pre-Phase-8 token names preserved"
    )


    # ======================================================
    # NO STALE TOKEN BLOCK LEFT BEHIND
    # ======================================================

    legacy_css = (
        strip_css_comments(
            client.get(
                "/review/static/dashboard.css"
            )
            .text
        )
    )


    assert_false(
        ":root {" in legacy_css,
        (
            "dashboard.css must not declare a "
            "second :root token block. Tokens "
            "have one owner: tokens.css."
        ),
    )


    print(
        "[PASS] Tokens have a single owner"
    )


# ==========================================================
# TEST 3 — ACCESSIBILITY LANDMARKS
# ==========================================================

def test_accessibility_landmarks(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - ACCESSIBILITY LANDMARKS"
    )
    print("-" * 76)


    for path in SHELL_PAGES:

        response = (
            client.get(
                path
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                f"Shell page should load: {path}"
            ),
        )


        markup = (
            response.text
        )


        # ==============================================
        # SKIP LINK
        # ==============================================

        assert_true(
            'class="skip-link"' in markup,
            (
                "Every page needs a skip link so "
                "keyboard users can bypass the "
                f"sidebar: {path}"
            ),
        )


        assert_true(
            'href="#main-content"' in markup,
            (
                "The skip link must target the "
                f"main landmark: {path}"
            ),
        )


        # ==============================================
        # LANDMARKS
        # ==============================================

        assert_true(
            'id="main-content"' in markup,
            (
                "The main landmark needs the id "
                "the skip link points at: "
                f"{path}"
            ),
        )


        assert_true(
            "<main" in markup,
            (
                f"Missing main landmark: {path}"
            ),
        )


        assert_true(
            "<nav" in markup,
            (
                f"Missing nav landmark: {path}"
            ),
        )


        # A page with one nav still benefits from a label,
        # and it becomes required once a second nav exists.
        assert_true(
            'aria-label="Primary"' in markup,
            (
                "Primary navigation must be "
                f"labelled: {path}"
            ),
        )


        # ==============================================
        # CURRENT PAGE
        # ==============================================

        assert_true(
            "aria-current" in markup,
            (
                "The active navigation item must "
                "expose aria-current so the "
                "accessible state matches the "
                f"visual state: {path}"
            ),
        )


    print(
        f"[PASS] Landmarks, skip link and "
        f"aria-current present on all "
        f"{len(SHELL_PAGES)} pages"
    )


# ==========================================================
# TEST 4 — NAVIGATION CONTRACT
# ==========================================================

def test_navigation_contract(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - NAVIGATION CONTRACT"
    )
    print("-" * 76)


    for path in SHELL_PAGES:

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


    print(
        "[PASS] All 4 primary destinations "
        "present on every page"
    )


    # ======================================================
    # NO BROKEN LINKS
    # ======================================================
    #
    # Destinations that are not built yet must not be
    # anchors. A nav item that looks clickable and goes
    # nowhere is worse than one that is visibly pending.
    #
    # Every href in the navigation is fetched and must
    # resolve.
    # ======================================================

    markup = (
        client.get(
            "/review"
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
            "block."
        ),
    )


    hrefs = (
        re.findall(
            r'href="([^"]+)"',
            nav_block.group(
                1
            ),
        )
    )


    assert_true(
        len(
            hrefs
        )
        > 0,
        (
            "Navigation should contain at least "
            "one real link."
        ),
    )


    for href in hrefs:

        response = (
            client.get(
                href
            )
        )


        assert_true(
            response.status_code < 400,
            (
                "Navigation contains a broken "
                f"link: {href} returned "
                f"{response.status_code}"
            ),
        )


    print(
        f"[PASS] All {len(hrefs)} navigation "
        "link(s) resolve; nothing is broken"
    )


    # ======================================================
    # EVERY DESTINATION IS EITHER A WORKING LINK
    # OR AN EXPLICITLY DISABLED PLACEHOLDER
    # ======================================================
    #
    # UPDATED IN PHASE 8.8B.
    #
    # This assertion originally required at least one
    # aria-disabled item, because Dashboard and Documents were
    # still unbuilt. Both now exist, so nothing is pending and
    # that requirement would fail for the right reason.
    #
    # The rule it was protecting is what matters and is kept:
    #
    #     a nav item is EITHER a real anchor whose href
    #     resolves, OR a non-anchor marked aria-disabled
    #
    # so a nav item can never look clickable and go nowhere.
    # Asserted for every destination by name, which is
    # strictly stronger than counting attributes.
    # ======================================================

    pending_anchor = (
        re.search(
            r'<a[^>]*class="[^"]*is-pending',
            markup,
        )
    )


    assert_true(
        pending_anchor is None,
        (
            "A not-yet-routed navigation item is "
            "rendered as an anchor. Pending items "
            "must be non-interactive so they "
            "cannot be clicked or focused."
        ),
    )


    nav_markup = (
        nav_block.group(
            1
        )
    )


    for label in PRIMARY_NAVIGATION:

        # --------------------------------------------------
        # Find the element that carries this label and
        # inspect it, rather than searching the whole page.
        # --------------------------------------------------

        item = (
            re.search(
                (
                    r'<(a|span)(\s[^>]*)?>\s*'
                    r'<span class="nav-item-label">'
                    + re.escape(
                        label
                    )
                    + r"</span>"
                ),
                nav_markup,
                re.DOTALL,
            )
        )


        assert_true(
            item is not None,
            (
                "Could not locate the navigation "
                f"item for '{label}'."
            ),
        )


        tag = item.group(
            1
        )

        attributes = (
            item.group(
                2
            )
            or ""
        )


        if tag == "a":

            href = (
                re.search(
                    r'href="([^"]+)"',
                    attributes,
                )
            )


            assert_true(
                href is not None,
                (
                    f"'{label}' is an anchor with "
                    "no href."
                ),
            )


            assert_true(
                client.get(
                    href.group(
                        1
                    )
                ).status_code
                < 400,
                (
                    f"'{label}' links to "
                    f"{href.group(1)}, which does "
                    "not resolve."
                ),
            )


        else:

            assert_true(
                "aria-disabled"
                in attributes,
                (
                    f"'{label}' is not a link, so "
                    "it must be marked "
                    "aria-disabled to keep it out "
                    "of the tab order."
                ),
            )


    print(
        f"[PASS] All {len(PRIMARY_NAVIGATION)} "
        "destinations are either working links or "
        "explicitly disabled placeholders"
    )


# ==========================================================
# TEST 5 — REVIEWER IDENTITY REMAINS SERVER-RESOLVED
# ==========================================================

def test_reviewer_identity_trust_boundary(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - REVIEWER IDENTITY TRUST "
        "BOUNDARY"
    )
    print("-" * 76)


    # ======================================================
    # SHELL SHOWS IDENTITY ON EVERY PAGE
    # ======================================================

    for path in SHELL_PAGES:

        markup = (
            client.get(
                path
            )
            .text
        )


        for element_id in (
            "shell-reviewer-name",
            "shell-reviewer-role",
            "shell-reviewer-access",
        ):

            assert_true(
                element_id in markup,
                (
                    "The shell must display the "
                    "resolved reviewer identity: "
                    f"{element_id} missing on "
                    f"{path}"
                ),
            )


    print(
        "[PASS] Shell exposes reviewer "
        "identity on every page"
    )


    # ======================================================
    # NO CLIENT-SIDE IDENTITY ENTRY
    # ======================================================
    #
    # Phase 7C.5 removed manual reviewer entry. The shell
    # must not reintroduce a way for the browser to choose
    # who the reviewer is.
    # ======================================================

    for path in SHELL_PAGES:

        markup = (
            client.get(
                path
            )
            .text
        )


        offending = (
            re.findall(
                r"<(?:input|select)[^>]*"
                r"(?:name|id)=\"[^\"]*reviewer[^\"]*\"",
                markup,
                re.IGNORECASE,
            )
        )


        assert_equal(
            offending,
            [],
            (
                "A reviewer identity input was "
                "found. Reviewer identity is "
                "server-resolved and must never "
                f"be enterable in the browser: "
                f"{path}"
            ),
        )


    print(
        "[PASS] No client-side reviewer "
        "identity input exists"
    )


    # ======================================================
    # SHARED CLIENT SENDS NO REVIEWER ID
    # ======================================================

    api_source = (
        client.get(
            "/review/static/js/api.js"
        )
        .text
    )


    assert_true(
        "/api/v1/reviewer/me" in api_source,
        (
            "The shared API client should resolve "
            "identity from the server endpoint."
        ),
    )


    assert_false(
        "reviewer_id:" in api_source,
        (
            "The shared API client must not "
            "construct a reviewer_id. Identity "
            "comes from the server."
        ),
    )


    print(
        "[PASS] Shared client resolves identity "
        "server-side and sends none"
    )


# ==========================================================
# TEST 6 — STRUCTURED ERROR FOUNDATION
# ==========================================================

def test_structured_error_foundation(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - STRUCTURED ERROR "
        "FOUNDATION"
    )
    print("-" * 76)


    api_source = (
        client.get(
            "/review/static/js/api.js"
        )
        .text
    )


    # ======================================================
    # STRUCTURED CONTRACT CONSUMED
    # ======================================================

    for marker in (
        "error.code",
        "error.message",
        "request_id",
        "X-Request-ID",
    ):

        assert_true(
            marker in api_source
            or marker.replace(
                "error.",
                "",
            ) in api_source,
            (
                "The shared client must consume "
                "the structured error contract: "
                f"{marker} not referenced"
            ),
        )


    print(
        "[PASS] Shared client consumes "
        "error.code / message / request_id"
    )


    # ======================================================
    # REQUEST ID SURFACED FOR SUPPORT
    # ======================================================

    common_source = (
        strip_js_comments(
            client.get(
                "/review/static/js/common.js"
            )
            .text
        )
    )


    assert_true(
        "requestId" in common_source,
        (
            "Error presentation should surface "
            "the request id so a reviewer can "
            "quote it in a support request."
        ),
    )


    print(
        "[PASS] Request ID surfaced in error "
        "presentation"
    )


    # ======================================================
    # LEGACY FALLBACK RETAINED
    # ======================================================

    assert_true(
        "detail" in api_source,
        (
            "The legacy detail field should "
            "remain as a fallback while older "
            "call sites migrate."
        ),
    )


    print(
        "[PASS] Legacy detail retained as "
        "fallback"
    )


    # ======================================================
    # NO STACK TRACE EXPECTATION
    # ======================================================

    for forbidden in (
        "traceback",
        "stack_trace",
        ".stack",
    ):

        assert_false(
            forbidden in common_source.lower(),
            (
                "The UI must not attempt to "
                "display internal exception "
                f"detail: {forbidden}"
            ),
        )


    print(
        "[PASS] UI never surfaces internal "
        "exception detail"
    )


# ==========================================================
# TEST 7 — SAFE RENDERING IN NEW CODE
# ==========================================================

def test_safe_rendering_in_shared_ui(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - SAFE DOM RENDERING"
    )
    print("-" * 76)


    common_source = (
        strip_js_comments(
            client.get(
                "/review/static/js/common.js"
            )
            .text
        )
    )


    # ======================================================
    # NO innerHTML IN NEW SHARED CODE
    # ======================================================
    #
    # OCR text, extracted values and filenames come from
    # uploaded documents and are untrusted. The shared
    # renderer builds nodes and assigns textContent.
    #
    # This is asserted for the NEW shared module only.
    # Legacy innerHTML use in review_detail.js is known
    # debt, tracked for the workspace rebuild, and is
    # deliberately not asserted here.
    # ======================================================

    assert_false(
        "innerHTML" in common_source,
        (
            "The shared UI module must not use "
            "innerHTML. Untrusted document values "
            "flow through these helpers."
        ),
    )


    assert_false(
        "outerHTML" in common_source,
        (
            "The shared UI module must not use "
            "outerHTML."
        ),
    )


    assert_false(
        "insertAdjacentHTML" in common_source,
        (
            "The shared UI module must not use "
            "insertAdjacentHTML."
        ),
    )


    print(
        "[PASS] Shared UI module contains no "
        "HTML-string injection sink"
    )


    assert_true(
        "textContent" in common_source,
        (
            "The shared UI module should render "
            "text via textContent."
        ),
    )


    print(
        "[PASS] Shared UI renders via "
        "textContent"
    )


# ==========================================================
# TEST 8 — RESPONSIVE FOUNDATION
# ==========================================================

def test_responsive_foundation(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - RESPONSIVE FOUNDATION"
    )
    print("-" * 76)


    responsive = (
        client.get(
            "/review/static/css/responsive.css"
        )
        .text
    )


    breakpoint_count = (
        responsive.count(
            "@media"
        )
    )


    assert_true(
        breakpoint_count >= 3,
        (
            "The responsive layer should cover "
            "laptop, tablet and small screens. "
            f"Found {breakpoint_count} media "
            "queries."
        ),
    )


    print(
        f"[PASS] {breakpoint_count} responsive "
        "breakpoints defined"
    )


    # ======================================================
    # NAVIGATION SURVIVES SMALL SCREENS
    # ======================================================
    #
    # The pre-Phase-8 stylesheet hid the sidebar entirely
    # below 760px, which removed all navigation on a phone.
    # The shell must reflow it instead.
    # ======================================================

    legacy_css = (
        strip_css_comments(
            client.get(
                "/review/static/dashboard.css"
            )
            .text
        )
    )


    hides_sidebar = (
        re.search(
            r"\.sidebar\s*\{[^}]*display\s*:\s*none",
            legacy_css,
        )
    )


    assert_true(
        hides_sidebar is None,
        (
            "The sidebar must not be hidden "
            "outright on small screens, because "
            "that removes all navigation. It "
            "should reflow instead."
        ),
    )


    print(
        "[PASS] Navigation is never hidden "
        "outright on small screens"
    )


    # ======================================================
    # META VIEWPORT
    # ======================================================

    for path in SHELL_PAGES:

        markup = (
            client.get(
                path
            )
            .text
        )


        assert_true(
            "viewport" in markup,
            (
                "A responsive page needs a "
                f"viewport meta tag: {path}"
            ),
        )


    print(
        "[PASS] Viewport meta present on all "
        "pages"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 8.4 / 8.5 - DESIGN SYSTEM + "
        "APPLICATION SHELL"
    )
    print("=" * 76)


    client = None


    try:

        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        test_design_system_assets(
            client
        )

        test_design_tokens(
            client
        )

        test_accessibility_landmarks(
            client
        )

        test_navigation_contract(
            client
        )

        test_reviewer_identity_trust_boundary(
            client
        )

        test_structured_error_foundation(
            client
        )

        test_safe_rendering_in_shared_ui(
            client
        )

        test_responsive_foundation(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.4 / 8.5 DESIGN "
            "SYSTEM + SHELL TEST PASSED"
        )
        print("=" * 76)


    finally:

        if client is not None:

            client.close()


if __name__ == "__main__":

    main()
