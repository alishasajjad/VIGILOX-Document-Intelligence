import json
import re
import shutil
import subprocess
import sys

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from backend.app.api.request_validation import (
    ALLOWED_CONTENT_TYPES,
)

from backend.app.main import (
    MAX_UPLOAD_BYTES,
)


# ==========================================================
# PHASE 8.7
# UPLOAD & ANALYZE EXPERIENCE CONTRACT TEST
# ==========================================================
#
# Two halves.
#
# 1. HTTP contracts, through TestClient: the route, the
#    assets, the shell, navigation and accessibility markup.
#
# 2. Real behaviour, by EXECUTING upload.js under Node with a
#    DOM stub (tests/dashboard/upload_harness.js).
#
# The second half matters. Pattern-matching source text would
# prove almost nothing about a state machine; running it
# proves which files are rejected, that a replaced file
# revokes its predecessor's object URL, that a second submit
# is dropped, and that a response without a document_id does
# not navigate.
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
    / "upload_harness.js"
)


UPLOAD_ROUTE = "/upload"


PRODUCT_PAGES = (
    "/upload",
    "/review",
    "/review/00000000-0000-4000-8000-000000000000",
)


REQUIRED_ASSETS = (
    "/review/static/js/upload.js",
    "/review/static/js/api.js",
    "/review/static/js/common.js",
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/responsive.css",
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
# JS COMMENT STRIPPING
# ==========================================================
#
# Assertions about code must not match prose. upload.js
# documents that it avoids fake percentages, so a naive
# search for "%" or "progress" finds its own explanation.
# ==========================================================

def strip_js_comments(
    source: str,
) -> str:

    result = []

    index = 0
    length = len(source)

    in_line = False
    in_block = False
    in_string = None


    while index < length:

        char = source[index]

        following = (
            source[index + 1]
            if index + 1 < length
            else ""
        )


        if in_line:

            if char == "\n":
                in_line = False
                result.append(char)

            index += 1
            continue


        if in_block:

            if char == "*" and following == "/":
                in_block = False
                index += 2
                continue

            index += 1
            continue


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


        if char == "/" and following == "/":
            in_line = True
            index += 2
            continue

        if char == "/" and following == "*":
            in_block = True
            index += 2
            continue

        if char in ('"', "'", "`"):
            in_string = char
            result.append(char)
            index += 1
            continue

        result.append(char)
        index += 1


    return "".join(
        result
    )


# ==========================================================
# HARNESS RUNNER
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
                "upload state machine. Without it "
                "this suite could only pattern-match "
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
                "Upload harness failed to run.\n"
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
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - ROUTE AND ASSETS"
    )
    print("-" * 76)


    response = (
        client.get(
            UPLOAD_ROUTE
        )
    )


    assert_equal(
        response.status_code,
        200,
        "GET /upload should return 200.",
    )


    assert_true(
        "text/html" in response.headers.get(
            "content-type",
            "",
        ),
        "Upload route should serve HTML.",
    )


    print(
        "[PASS] GET /upload returns 200 HTML"
    )


    for path in REQUIRED_ASSETS:

        asset = (
            client.get(
                path
            )
        )


        assert_equal(
            asset.status_code,
            200,
            (
                "Required Upload asset should be "
                f"served: {path}"
            ),
        )


        assert_true(
            len(
                asset.content
            )
            > 0,
            (
                f"Asset should not be empty: {path}"
            ),
        )


    print(
        f"[PASS] All {len(REQUIRED_ASSETS)} "
        "required assets served"
    )


    # ======================================================
    # EXISTING PAGES STILL ROUTABLE
    # ======================================================

    for path in (
        "/review",
        "/review/00000000-0000-4000-8000-000000000000",
    ):

        assert_equal(
            client.get(
                path
            ).status_code,
            200,
            (
                "Existing page must remain "
                f"routable: {path}"
            ),
        )


    print(
        "[PASS] Review Queue and document detail "
        "remain routable"
    )


    assert_true(
        response.headers.get(
            "X-Request-ID"
        )
        is not None,
        (
            "Upload page response should carry a "
            "correlation ID."
        ),
    )


    print(
        "[PASS] Correlation ID header present"
    )


# ==========================================================
# TEST 2 — SHELL AND NAVIGATION
# ==========================================================

def test_shell_and_navigation(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - SHELL AND NAVIGATION"
    )
    print("-" * 76)


    markup = (
        client.get(
            UPLOAD_ROUTE
        )
        .text
    )


    # ======================================================
    # SHARED SHELL
    # ======================================================

    for marker in (
        'class="app-shell"',
        'class="sidebar"',
        'class="brand"',
        'aria-label="Primary"',
        'id="main-content"',
        'class="skip-link"',
        "shell-reviewer-name",
    ):

        assert_true(
            marker in markup,
            (
                "Upload page must reuse the "
                f"application shell: {marker}"
            ),
        )


    print(
        "[PASS] Upload page reuses the shared "
        "application shell"
    )


    # ======================================================
    # UPLOAD IS A REAL LINK EVERYWHERE
    # ======================================================

    for path in PRODUCT_PAGES:

        page = (
            client.get(
                path
            )
            .text
        )


        assert_true(
            'href="/upload"' in page,
            (
                "Upload Document must be a real "
                f"link on {path}"
            ),
        )


        # It must no longer be a pending placeholder.
        pending_upload = (
            re.search(
                r'is-pending[^>]*>\s*<span[^>]*>'
                r'Upload Document',
                page,
            )
        )


        assert_true(
            pending_upload is None,
            (
                "Upload Document is still rendered "
                "as a pending placeholder on "
                f"{path}"
            ),
        )


    print(
        f"[PASS] Upload is a working link on all "
        f"{len(PRODUCT_PAGES)} product pages"
    )


    # ======================================================
    # NO BROKEN NAV LINKS
    # ======================================================

    nav = (
        re.search(
            r"<nav[^>]*>(.*?)</nav>",
            markup,
            re.DOTALL,
        )
    )


    assert_true(
        nav is not None,
        "Could not locate the navigation block.",
    )


    hrefs = (
        re.findall(
            r'href="([^"]+)"',
            nav.group(
                1
            ),
        )
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

    upload_anchor = (
        re.search(
            r'<a[^>]*href="/upload"[^>]*>',
            markup,
            re.DOTALL,
        )
    )


    assert_true(
        upload_anchor is not None,
        "Upload nav anchor not found.",
    )


    assert_true(
        'aria-current="page"'
        in upload_anchor.group(
            0
        ),
        (
            "On the Upload page the Upload nav "
            "item must expose aria-current=\"page\", "
            "so the accessible state matches the "
            "visual state."
        ),
    )


    print(
        "[PASS] Upload nav item marks itself "
        "current with aria-current"
    )


    # ======================================================
    # REVIEWER IDENTITY TRUST BOUNDARY
    # ======================================================

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
            "The Upload page must not introduce a "
            "reviewer identity input. Identity is "
            "server-resolved."
        ),
    )


    print(
        "[PASS] No client-side reviewer identity "
        "input introduced"
    )


# ==========================================================
# TEST 3 — ACCESSIBLE FILE SELECTION
# ==========================================================

def test_accessible_file_selection(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - ACCESSIBLE FILE SELECTION"
    )
    print("-" * 76)


    markup = (
        client.get(
            UPLOAD_ROUTE
        )
        .text
    )


    # ======================================================
    # NATIVE INPUT
    # ======================================================

    file_input = (
        re.search(
            r'<input[^>]*type="file"[^>]*>',
            markup,
            re.DOTALL,
        )
    )


    assert_true(
        file_input is not None,
        (
            "A native file input must exist. Drag "
            "and drop cannot be the only way in."
        ),
    )


    input_markup = (
        file_input.group(
            0
        )
    )


    print(
        "[PASS] Native file input present"
    )


    # ======================================================
    # ACCEPTED TYPES MATCH THE BACKEND
    # ======================================================

    accept = (
        re.search(
            r'accept="([^"]+)"',
            input_markup,
        )
    )


    assert_true(
        accept is not None,
        (
            "The file input should declare an "
            "accept list."
        ),
    )


    accepted = {
        value.strip()
        for value in accept.group(
            1
        ).split(",")
    }


    assert_equal(
        accepted,
        set(
            ALLOWED_CONTENT_TYPES
        ),
        (
            "The accept list must match the "
            "backend ALLOWED_CONTENT_TYPES "
            "exactly, so the picker never offers "
            "a type the server will reject."
        ),
    )


    print(
        "[PASS] accept list matches backend "
        "ALLOWED_CONTENT_TYPES exactly"
    )


    # ======================================================
    # LABEL ASSOCIATION
    # ======================================================
    #
    # The input is visually hidden, so a real <label for>
    # is what makes it operable by click and by keyboard.
    # ======================================================

    input_id = (
        re.search(
            r'id="([^"]+)"',
            input_markup,
        )
    )


    assert_true(
        input_id is not None,
        "The file input needs an id to be labelled.",
    )


    assert_true(
        f'for="{input_id.group(1)}"' in markup,
        (
            "The file input must have an "
            "associated label, otherwise a "
            "visually hidden input is unreachable."
        ),
    )


    print(
        "[PASS] File input has an associated label"
    )


    # ======================================================
    # INPUT IS NOT REMOVED FROM THE A11Y TREE
    # ======================================================

    assert_false(
        "display: none" in input_markup
        or "display:none" in input_markup,
        (
            "The file input must not be hidden "
            "with display:none, which removes it "
            "from the accessibility tree."
        ),
    )


    print(
        "[PASS] File input stays focusable, not "
        "display:none"
    )


    # ======================================================
    # CONSTRAINTS ARE DESCRIBED
    # ======================================================

    assert_true(
        "aria-describedby" in input_markup,
        (
            "The file input should point at its "
            "format and size constraints."
        ),
    )


    print(
        "[PASS] Constraints associated via "
        "aria-describedby"
    )


    # ======================================================
    # LIVE REGIONS
    # ======================================================

    for marker in (
        'role="alert"',
        'aria-live="assertive"',
        'role="status"',
        'aria-live="polite"',
    ):

        assert_true(
            marker in markup,
            (
                "Validation, processing and result "
                "outcomes must be announced: "
                f"{marker} missing"
            ),
        )


    print(
        "[PASS] Validation, processing and result "
        "regions are announced"
    )


# ==========================================================
# TEST 4 — TRUTHFUL PROCESSING
# ==========================================================

def test_truthful_processing(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - TRUTHFUL PROCESSING"
    )
    print("-" * 76)


    markup = (
        client.get(
            UPLOAD_ROUTE
        )
        .text
    )


    code = (
        strip_js_comments(
            client.get(
                "/review/static/js/upload.js"
            )
            .text
        )
    )


    # ======================================================
    # NO FAKE PROGRESS
    # ======================================================
    #
    # The analyze endpoint is synchronous and reports no
    # stage information, so any percentage would be invented.
    # ======================================================

    assert_false(
        re.search(
            r"\d+\s*%",
            code,
        )
        is not None,
        (
            "Upload code contains a numeric "
            "percentage. The analyze endpoint "
            "reports no progress, so any "
            "percentage would be fabricated."
        ),
    )


    for forbidden in (
        "progress",
        "percent",
    ):

        assert_false(
            forbidden in code.lower(),
            (
                "Upload code references "
                f"'{forbidden}'. Processing must be "
                "indeterminate."
            ),
        )


    print(
        "[PASS] No numeric progress or percentage "
        "in Upload code"
    )


    assert_false(
        "<progress" in markup.lower(),
        (
            "The Upload page must not render a "
            "progress element."
        ),
    )


    print(
        "[PASS] No progress element in the markup"
    )


    # ======================================================
    # INDETERMINATE INDICATOR AND ACCESSIBLE STATE
    # ======================================================

    assert_true(
        'class="spinner"' in markup,
        (
            "An indeterminate spinner should "
            "indicate work in progress."
        ),
    )


    assert_true(
        "aria-busy" in code,
        (
            "The processing region should expose "
            "aria-busy while a request is in "
            "flight."
        ),
    )


    print(
        "[PASS] Indeterminate spinner plus "
        "aria-busy"
    )


    # ======================================================
    # MESSAGES DO NOT CLAIM COMPLETED STAGES
    # ======================================================

    results = (
        run_harness()
    )


    assert_no_harness_errors(
        results
    )


    messages = (
        results["module_loaded"]
        ["processing_messages"]
    )


    assert_true(
        len(
            messages
        )
        >= 2,
        (
            "There should be several rotating "
            "processing messages."
        ),
    )


    for message in messages:

        lowered = (
            message.lower()
        )


        for claim in (
            "complete",
            "completed",
            "finished",
            "done",
            "100",
            "%",
        ):

            assert_false(
                claim in lowered,
                (
                    "A processing message claims a "
                    "finished stage, which the "
                    "backend never reports: "
                    f"{message!r}"
                ),
            )


    print(
        f"[PASS] All {len(messages)} processing "
        "messages are non-committal"
    )


# ==========================================================
# TEST 5 — FILE VALIDATION BEHAVIOUR
# ==========================================================

def test_file_validation(
    results,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - FILE VALIDATION (EXECUTED)"
    )
    print("-" * 76)


    module = (
        results["module_loaded"]
    )


    # ======================================================
    # LIMIT IS MEBIBYTES, NOT DECIMAL
    # ======================================================

    assert_equal(
        module["max_bytes"],
        MAX_UPLOAD_BYTES,
        (
            "The client size limit must equal the "
            "backend MAX_UPLOAD_BYTES exactly. A "
            "decimal 10,000,000 would reject files "
            "the server accepts."
        ),
    )


    print(
        f"[PASS] Client limit is "
        f"{module['max_bytes']} bytes, identical "
        "to the backend"
    )


    assert_equal(
        set(
            module["allowed_types"]
        ),
        set(
            ALLOWED_CONTENT_TYPES
        ),
        (
            "Client allowed types must match the "
            "backend exactly."
        ),
    )


    print(
        "[PASS] Client allowed types match the "
        "backend"
    )


    assert_equal(
        set(
            module["states"]
        ),
        {
            "IDLE",
            "SELECTED",
            "ANALYZING",
            "SUCCESS",
            "ERROR",
        },
        (
            "The upload state machine should "
            "expose the five documented states."
        ),
    )


    assert_equal(
        module["initial_state"],
        "IDLE",
        "The page should start in IDLE.",
    )


    print(
        "[PASS] Explicit 5-state machine, starts "
        "IDLE"
    )


    # ======================================================
    # ACCEPTED
    # ======================================================

    validation = (
        results["validation"]
    )


    for case in (
        "jpeg_ok",
        "png_ok",
        "webp_ok",
        "jpeg_alt_ext_ok",
        "at_limit_ok",
        "decimal_boundary_ok",
        "blank_type_valid_ext_ok",
    ):

        assert_true(
            validation[case] is None,
            (
                "This file should have been "
                f"accepted: {case} "
                f"({validation[case]})"
            ),
        )


    print(
        "[PASS] JPG, JPEG, PNG, WEBP accepted; "
        "exactly-at-limit accepted"
    )


    print(
        "[PASS] A 10,000,001 byte file is accepted, "
        "proving the limit is 10 MiB not 10 MB"
    )


    # ======================================================
    # REJECTED
    # ======================================================

    for case in (
        "pdf_rejected",
        "gif_rejected",
        "svg_rejected",
        "bmp_rejected",
        "tiff_rejected",
        "empty_rejected",
        "no_file_rejected",
        "over_limit_rejected",
        "long_name_rejected",
        "blank_type_bad_ext_rejected",
    ):

        reason = (
            validation[case]
        )


        assert_true(
            isinstance(
                reason,
                str,
            )
            and reason,
            (
                "This file should have been "
                f"rejected: {case}"
            ),
        )


        # Human wording, not a developer message.
        for jargon in (
            "Exception",
            "Traceback",
            "undefined",
            "null",
            "MIME",
        ):

            assert_false(
                jargon in reason,
                (
                    "Validation message reads like "
                    f"developer output: {reason!r}"
                ),
            )


    print(
        "[PASS] PDF, GIF, SVG, BMP, TIFF, empty, "
        "oversized and overlong names rejected"
    )


    print(
        "[PASS] Rejection messages are "
        "user-facing, not developer output"
    )


    # ======================================================
    # AN INVALID PICK DOES NOT BECOME A SELECTION
    # ======================================================

    invalid = (
        results["invalid_selection"]
    )


    assert_equal(
        invalid["state"],
        "IDLE",
        (
            "An invalid file must not put the page "
            "into SELECTED."
        ),
    )


    assert_true(
        invalid["analyze_disabled"],
        (
            "Analyze must stay disabled after an "
            "invalid selection."
        ),
    )


    assert_true(
        bool(
            invalid["message_shown"]
        ),
        (
            "An invalid selection should show a "
            "validation message."
        ),
    )


    assert_equal(
        invalid["object_urls_created"],
        0,
        (
            "An invalid file must not create a "
            "preview object URL."
        ),
    )


    print(
        "[PASS] Invalid pick stays IDLE, Analyze "
        "disabled, no object URL created"
    )


# ==========================================================
# TEST 6 — OBJECT URL LIFECYCLE
# ==========================================================

def test_object_url_lifecycle(
    results,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - OBJECT URL LIFECYCLE "
        "(EXECUTED)"
    )
    print("-" * 76)


    lifecycle = (
        results["object_url_lifecycle"]
    )


    assert_equal(
        lifecycle["after_first"]["created"],
        1,
        (
            "Selecting a file should create one "
            "preview object URL."
        ),
    )


    assert_equal(
        lifecycle["after_first"]["state"],
        "SELECTED",
        (
            "A valid file should move the page to "
            "SELECTED."
        ),
    )


    print(
        "[PASS] Valid file creates one object URL "
        "and enters SELECTED"
    )


    # ======================================================
    # REPLACE REVOKES THE PREDECESSOR
    # ======================================================

    replace = (
        lifecycle["after_replace"]
    )


    assert_equal(
        replace["created"],
        2,
        "Replacing should create a second URL.",
    )


    assert_equal(
        replace["revoked"],
        1,
        (
            "Replacing a file must revoke the "
            "previous object URL, otherwise the "
            "old file stays in memory."
        ),
    )


    assert_true(
        replace["revoked_first"],
        (
            "The URL revoked on replace must be "
            "the first one."
        ),
    )


    print(
        "[PASS] Replacing a file revokes the "
        "previous object URL"
    )


    # ======================================================
    # REMOVE RESETS TO IDLE
    # ======================================================

    removed = (
        lifecycle["after_remove"]
    )


    assert_equal(
        removed["state"],
        "IDLE",
        "Removing should return the page to IDLE.",
    )


    assert_equal(
        removed["revoked"],
        2,
        "Removing should revoke the current URL.",
    )


    assert_true(
        removed["preview_src"]
        in (
            None,
            "",
        ),
        (
            "Removing should clear the preview "
            "source."
        ),
    )


    print(
        "[PASS] Remove clears preview, revokes the "
        "URL and returns to IDLE"
    )


    assert_true(
        lifecycle["all_created_revoked"],
        (
            "Every object URL created must "
            "eventually be revoked. An unrevoked "
            "URL keeps the whole file alive."
        ),
    )


    print(
        "[PASS] Every object URL created was "
        "revoked, including on unload"
    )


# ==========================================================
# TEST 7 — SUBMISSION BEHAVIOUR
# ==========================================================

def test_submission(
    results,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - SUBMISSION (EXECUTED)"
    )
    print("-" * 76)


    # ======================================================
    # CANNOT SUBMIT WITHOUT A FILE
    # ======================================================

    requires = (
        results["analyze_requires_file"]
    )


    assert_equal(
        requires["analyze_calls"],
        0,
        (
            "Analyze must not call the API without "
            "a selected file."
        ),
    )


    print(
        "[PASS] Analyze does nothing without a "
        "selected file"
    )


    # ======================================================
    # DUPLICATE SUBMISSION BLOCKED
    # ======================================================

    duplicate = (
        results["duplicate_submission_blocked"]
    )


    assert_equal(
        duplicate["after_first"]["calls"],
        1,
        "The first Analyze should call the API once.",
    )


    assert_equal(
        duplicate["after_first"]["state"],
        "ANALYZING",
        (
            "Submitting should move the page to "
            "ANALYZING."
        ),
    )


    assert_true(
        duplicate["after_first"]["disabled"],
        (
            "Analyze should be disabled while a "
            "request is in flight."
        ),
    )


    assert_equal(
        duplicate["after_first"]["aria_busy"],
        "true",
        (
            "The processing region should report "
            "aria-busy while working."
        ),
    )


    # ======================================================
    # This is the important one. Three further clicks while
    # the first request is pending must not produce three
    # more documents.
    # ======================================================

    assert_equal(
        duplicate["total_calls"],
        1,
        (
            "Four Analyze clicks produced "
            f"{duplicate['total_calls']} API calls. "
            "A duplicate submission would create a "
            "second real document, not a retry."
        ),
    )


    print(
        "[PASS] 4 Analyze clicks produced exactly "
        "1 API call"
    )


    # ======================================================
    # MULTIPART
    # ======================================================

    multipart = (
        results["multipart_request"]
    )


    assert_equal(
        multipart["path"],
        "/api/v1/documents/analyze",
        (
            "Upload must use the existing analyze "
            "endpoint. No second upload API."
        ),
    )


    assert_equal(
        multipart["method"],
        "POST",
        "Analyze should be a POST.",
    )


    assert_true(
        multipart["body_is_formdata"],
        (
            "The request body must be FormData, "
            "not JSON or base64."
        ),
    )


    assert_equal(
        multipart["form_field"],
        "file",
        (
            "The multipart field must be named "
            "file, matching the endpoint."
        ),
    )


    # ==================================================
    # The browser must generate the multipart boundary.
    # Setting Content-Type by hand produces a request the
    # server cannot parse.
    # ==================================================

    assert_false(
        multipart["content_type_set"],
        (
            "Content-Type must NOT be set manually "
            "for multipart. The browser has to "
            "generate the boundary."
        ),
    )


    print(
        "[PASS] POSTs FormData to the existing "
        "analyze endpoint, field 'file'"
    )


    print(
        "[PASS] Content-Type is left to the "
        "browser, so the boundary is correct"
    )


# ==========================================================
# TEST 8 — SUCCESS AND ERROR FLOWS
# ==========================================================

def test_success_and_error_flows(
    results,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - SUCCESS AND ERROR (EXECUTED)"
    )
    print("-" * 76)


    # ======================================================
    # SUCCESS
    # ======================================================

    success = (
        results["success_navigation"]
    )


    assert_equal(
        success["state"],
        "SUCCESS",
        (
            "A successful analysis should enter "
            "SUCCESS."
        ),
    )


    assert_false(
        success["success_hidden"],
        "The success panel should be visible.",
    )


    # PHASE 9.4. This used to expect the extraction summary --
    # document type, machine decision, review requirement --
    # from the synchronous analyze response.
    #
    # A job response does not carry those, deliberately: a job
    # row is queue state, and putting the extraction into it
    # would make it a second, staler copy of the document
    # record in a table nobody thinks of as holding personal
    # data.
    #
    # So the panel confirms what was submitted rather than what
    # was found -- filename, type, size, all real job columns
    # -- and the workspace owns the result. The panel is on
    # screen for 900ms; fetching the document to fill it would
    # be a request spent on decoration.
    assert_true(
        success["fact_count"] >= 3,
        (
            "The success state should confirm what "
            "was submitted from real job fields: "
            "filename, type and size."
        ),
    )


    assert_true(
        success["analyze_hidden"],
        (
            "Analyze should be hidden after "
            "success, so the same document cannot "
            "be submitted twice."
        ),
    )


    print(
        "[PASS] Success shows real response facts "
        "and hides Analyze"
    )


    # ======================================================
    # MISSING document_id MUST NOT NAVIGATE
    # ======================================================
    #
    # The dangerous case: navigating on a malformed response
    # would produce /review/undefined.
    # ======================================================

    missing = (
        results["missing_document_id"]
    )


    assert_equal(
        missing["state"],
        "ERROR",
        (
            "A response without document_id must "
            "be treated as an error."
        ),
    )


    assert_equal(
        missing["navigations"],
        [],
        (
            "A response without document_id must "
            "not navigate. Doing so would produce "
            "/review/undefined."
        ),
    )


    assert_true(
        bool(
            missing["error_message"]
        ),
        (
            "A malformed response should explain "
            "itself to the user."
        ),
    )


    print(
        "[PASS] Missing document_id surfaces an "
        "error and never navigates"
    )


    # ======================================================
    # STRUCTURED ERROR
    # ======================================================

    error = (
        results["structured_error"]
    )


    assert_equal(
        error["message"],
        "Unsupported file type.",
        (
            "The API's structured error.message "
            "should be shown to the user."
        ),
    )


    assert_true(
        "UNSUPPORTED_FILE_TYPE" in error["meta"],
        (
            "The stable error.code should be "
            "displayed for support."
        ),
    )


    assert_true(
        "req-abc-123" in error["meta"],
        (
            "error.request_id should be displayed "
            "as a support reference."
        ),
    )


    assert_true(
        "Support Request ID" in error["meta"],
        (
            "The request id should be labelled so "
            "a reviewer knows what it is for."
        ),
    )


    print(
        "[PASS] Structured code, message and "
        "request ID all surfaced"
    )


    assert_equal(
        error["navigations"],
        [],
        "A failed analysis must not navigate.",
    )


    # ======================================================
    # RETRY KEEPS THE FILE
    # ======================================================

    assert_equal(
        error["state_after_retry"],
        "SELECTED",
        (
            "Retry should return to SELECTED, "
            "keeping the chosen file, rather than "
            "forcing the user to pick it again."
        ),
    )


    assert_true(
        error["retry_reenables_analyze"],
        "Retry should re-enable Analyze.",
    )


    print(
        "[PASS] Failure keeps the file and retry "
        "re-enables Analyze"
    )


    # ======================================================
    # NETWORK FAILURE IS DISTINGUISHED
    # ======================================================

    network = (
        results["network_error"]
    )


    assert_true(
        "reach" in network["title"].lower(),
        (
            "A network failure should read "
            "differently from an API rejection. "
            f"Got: {network['title']!r}"
        ),
    )


    print(
        "[PASS] Network failure is distinguished "
        "from an API rejection"
    )


# ==========================================================
# TEST 9 — SAFE RENDERING AND PRIVACY
# ==========================================================

def test_safe_rendering_and_privacy(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 9 - SAFE RENDERING AND PRIVACY"
    )
    print("-" * 76)


    code = (
        strip_js_comments(
            client.get(
                "/review/static/js/upload.js"
            )
            .text
        )
    )


    # ======================================================
    # NO HTML INJECTION SINK
    # ======================================================
    #
    # Filenames, server messages and detected document types
    # are untrusted.
    # ======================================================

    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
    ):

        assert_false(
            sink in code,
            (
                "New Upload code must not use "
                f"{sink}. Filenames and server "
                "messages are untrusted."
            ),
        )


    print(
        "[PASS] No HTML-string injection sink in "
        "Upload code"
    )


    assert_true(
        "textContent" in code,
        (
            "Upload code should render text via "
            "textContent."
        ),
    )


    print(
        "[PASS] Upload renders via textContent"
    )


    # ======================================================
    # NO CONSOLE LOGGING
    # ======================================================
    #
    # A logged analyze response would put extracted personal
    # data into the browser console.
    # ======================================================

    for logger in (
        "console.log",
        "console.debug",
        "console.info",
        "console.warn",
        "console.error",
    ):

        assert_false(
            logger in code,
            (
                "Upload code must not log to the "
                "console. The analyze response "
                "carries extracted personal data: "
                f"{logger}"
            ),
        )


    print(
        "[PASS] No console logging of the analyze "
        "response"
    )


    # ======================================================
    # LEGACY detail IS FALLBACK ONLY
    # ======================================================

    api_code = (
        strip_js_comments(
            client.get(
                "/review/static/js/api.js"
            )
            .text
        )
    )


    assert_true(
        "error.code" in api_code
        or "structured.code" in api_code,
        (
            "The shared client should read the "
            "structured error code."
        ),
    )


    assert_true(
        "detail" in api_code,
        (
            "Legacy detail should remain as a "
            "fallback."
        ),
    )


    # Upload consumes the normalised ApiError, so it should
    # not be reaching for the legacy field itself.
    #
    # PHASE 9.4 sharpened this. A bare ".detail" substring is
    # too blunt: the job status label is built from
    # vocabulary.describeJobStatus(), whose result has its own
    # "detail" property, and that has nothing to do with the
    # legacy API field. The blunt version failed on it, which
    # is a rule flagging correct code.
    #
    # What must not exist is reading detail off an API payload
    # or an error, so those are named.
    # PHASE 10.3 sharpened this a second time.
    #
    # Plain substring matching flagged error.detailS -- the
    # STRUCTURED field api.js exposes, and the correct thing to
    # read. "error.detail" is a prefix of it, so the rule
    # rejected exactly the code it exists to encourage.
    #
    # The trailing guard requires the property name to END
    # there, so .detail is caught and .details is not.
    legacy_detail_reads = [
        pattern
        for pattern in (
            "error.detail",
            "payload.detail",
            "response.detail",
            "data.detail",
            "body.detail",
            "job.detail",
            "result.detail",
        )
        if re.search(
            re.escape(
                pattern
            )
            + r"(?![A-Za-z0-9_])",
            code,
        )
    ]

    assert_equal(
        legacy_detail_reads,
        [],
        (
            "Upload code should consume the "
            "structured error object from api.js, "
            "not the legacy detail field directly."
        ),
    )


    print(
        "[PASS] Structured errors primary, legacy "
        "detail confined to the shared client"
    )


    # ======================================================
    # NO SECOND ANALYZE ENDPOINT
    # ======================================================

    analyze_routes = {
        route.path
        for route in app.routes
        if hasattr(
            route,
            "path",
        )
        and "analyze" in route.path
    }


    assert_equal(
        analyze_routes,
        {
            "/api/v1/documents/analyze"
        },
        (
            "Phase 8.7 must not add a second "
            "analysis endpoint. Found: "
            f"{analyze_routes}"
        ),
    )


    print(
        "[PASS] Exactly one analyze endpoint "
        "exists; no duplicate was added"
    )


# ==========================================================
# TEST 10 — RESPONSIVE FOUNDATION
# ==========================================================

def test_responsive(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 10 - RESPONSIVE FOUNDATION"
    )
    print("-" * 76)


    markup = (
        client.get(
            UPLOAD_ROUTE
        )
        .text
    )


    assert_true(
        "viewport" in markup,
        (
            "A responsive page needs a viewport "
            "meta tag."
        ),
    )


    responsive = (
        client.get(
            "/review/static/css/responsive.css"
        )
        .text
    )


    for selector in (
        ".upload-layout",
        ".file-card",
        ".file-preview",
    ):

        assert_true(
            selector in responsive,
            (
                "Upload layout should adapt at "
                f"narrow widths: {selector} has no "
                "responsive rule"
            ),
        )


    print(
        "[PASS] Upload layout, file card and "
        "preview all have responsive rules"
    )


    components = (
        client.get(
            "/review/static/css/components.css"
        )
        .text
    )


    # ======================================================
    # A tall or wide document must be letterboxed rather
    # than cropped or stretched out of the layout.
    # ======================================================

    preview_rule = (
        re.search(
            r"\.file-preview\s*\{([^}]*)\}",
            components,
        )
    )


    assert_true(
        preview_rule is not None,
        "The preview needs a sizing rule.",
    )


    assert_true(
        "object-fit" in preview_rule.group(
            1
        ),
        (
            "The preview must use object-fit so a "
            "portrait or panoramic document cannot "
            "distort or overflow."
        ),
    )


    print(
        "[PASS] Preview uses object-fit, so no "
        "overflow or distortion"
    )


# ==========================================================
# MAIN
# ==========================================================

# ==========================================================
# LOCAL OUTPUT HELPERS
# ==========================================================
#
# This file prints its sections inline everywhere else. The
# Phase 12.18 tests below add enough sections that repeating
# the four-line print block would bury the assertions, so the
# idiom is factored out here rather than changed above.
# ==========================================================

def section(
    title: str,
) -> None:

    print()
    print("-" * 76)
    print(
        title
    )
    print("-" * 76)


def ok(
    message: str,
) -> None:

    print(
        f"[PASS] {message}"
    )


# ==========================================================
# PHASE 12.18 - THE PREVIEW SURVIVES PROCESSING
# ==========================================================
#
# RELEASE BLOCKER 1.
#
# applyState read
#
#     nodes.fileCard.hidden = next !== STATE.SELECTED
#
# so the card holding the preview vanished the moment Analyze
# was pressed. Everything about the preview lifecycle was
# already correct -- created on selection, revoked on replace,
# remove and unload -- and none of that mattered, because the
# element was inside a container the state machine hid.
#
# That is worth stating plainly: this was not a missing
# feature. It was a working feature made invisible one line
# away from where it was implemented, which is why reading the
# object-URL code found nothing wrong.
#
# It hurt most exactly where the product is now. A job in
# RETRY_WAIT behind a provider rate limit can sit for minutes,
# and the only thing a person wants in that window is
# confirmation that the right document is queued.
# ==========================================================

def test_preview_survives_processing(
    results: dict,
) -> None:

    section(
        "TEST 11 - THE SELECTED IMAGE STAYS VISIBLE THROUGH "
        "EVERY JOB STATUS"
    )

    outcome = results["preview_survives_every_job_status"]

    states = outcome["states"]

    # ------------------------------------------------------
    # Every waiting state keeps the picture
    # ------------------------------------------------------

    for label in (
        "READY",
        "QUEUED",
        "PROCESSING",
        "RETRY_WAIT",
    ):

        snapshot = states[label]

        assert_true(
            snapshot["card_visible"],
            (
                f"In {label} the file card must still be "
                "visible. Hiding it removes the only thing on "
                "screen that says WHICH document is being "
                "processed."
            ),
        )

        assert_true(
            snapshot["image_visible"],
            (
                f"In {label} the preview image must still be "
                "visible."
            ),
        )

        assert_true(
            snapshot["src_is_object_url"],
            (
                f"In {label} the preview must be a blob: URL "
                "from the selected File -- not a server "
                "fetch, and not a path."
            ),
        )

        assert_true(
            bool(
                snapshot["filename_shown"]
            ),
            f"In {label} the filename must still be shown.",
        )

    ok(
        "the preview and filename survive READY, QUEUED, "
        "PROCESSING and RETRY_WAIT"
    )

    # ------------------------------------------------------
    # Replace and Remove retire once it is a server job
    # ------------------------------------------------------

    assert_true(
        states["READY"]["actions_visible"],
        (
            "Replace and Remove must be available while the "
            "file is only selected."
        ),
    )

    for label in (
        "QUEUED",
        "PROCESSING",
        "RETRY_WAIT",
    ):

        assert_false(
            states[label]["actions_visible"],
            (
                f"Replace and Remove must be gone in {label}. "
                "The document is a job on the server by then; "
                "swapping the local file would change nothing "
                "and only mislead."
            ),
        )

    ok(
        "Replace and Remove are selection-time only, so the "
        "card cannot be edited once the job exists"
    )

    # ------------------------------------------------------
    # THE PREVIEW COSTS NOTHING EXTRA
    # ------------------------------------------------------

    assert_equal(
        outcome["analyze_calls"],
        1,
        (
            "One selection and one Analyze must produce "
            "exactly one submission. A preview that re-read "
            "or re-sent the file would double the upload."
        ),
    )

    assert_equal(
        outcome["object_urls_created"],
        1,
        (
            "One file, one object URL. The preview is created "
            "once at selection and reused for every "
            "subsequent state."
        ),
    )

    ok(
        "one file produced one submission and one object URL: "
        "the preview is free"
    )


def test_preview_survives_terminal_states(
    results: dict,
) -> None:

    section(
        "TEST 12 - COMPLETED, FAILED AND DUPLICATE KEEP A "
        "VALID PREVIEW"
    )

    outcome = results["preview_survives_completed_and_failed"]

    for label, snapshot in (
        (
            "COMPLETED",
            outcome["after_completed"],
        ),
        (
            "FAILED",
            outcome["after_failed"],
        ),
    ):

        assert_true(
            snapshot["card_visible"],
            f"In {label} the card must still be visible.",
        )

        assert_true(
            snapshot["src_is_object_url"],
            (
                f"In {label} the preview must still be a "
                "blob: URL."
            ),
        )

    # ------------------------------------------------------
    # A FAILED JOB MUST NOT LEAVE A BROKEN IMAGE
    # ------------------------------------------------------
    #
    # The card now outlives SELECTED, so an <img> with its src
    # removed would be ON SCREEN rather than inside a hidden
    # container -- and a src-less img is what a browser paints
    # as its broken-image icon.

    assert_true(
        outcome["failed_image_has_src"],
        (
            "A failed job must leave the preview with a real "
            "src. An empty src on a visible <img> is the "
            "browser's broken-image icon, which is the exact "
            "thing RELEASE BLOCKER 2 forbids."
        ),
    )

    ok(
        "COMPLETED and FAILED both keep a valid preview; "
        "neither leaves a src-less image on screen"
    )

    duplicate = results["preview_survives_duplicate"]

    assert_true(
        duplicate["snapshot"]["card_visible"],
        (
            "A duplicate must keep the preview: the user "
            "needs to see which image was recognised as "
            "already processed."
        ),
    )

    assert_true(
        duplicate["snapshot"]["src_is_object_url"],
        "The duplicate preview must still be a blob: URL.",
    )

    assert_equal(
        duplicate["error_title"],
        "Duplicate document detected",
        (
            "The duplicate outcome wording must not change. "
            "A duplicate is a source-identity result, not a "
            "failure and not a fraud signal."
        ),
    )

    assert_equal(
        duplicate["analyze_calls"],
        1,
        (
            "A duplicate must not re-upload. The "
            "short-circuit happens on the server."
        ),
    )

    ok(
        "DUPLICATE keeps its preview, keeps its wording, and "
        "still costs exactly one submission"
    )


def test_no_local_path_exposed(
    results: dict,
) -> None:

    section(
        "TEST 13 - THE PREVIEW EXPOSES NO FILESYSTEM PATH"
    )

    outcome = results["no_filesystem_path_is_exposed"]

    assert_true(
        outcome["src_is_object_url"],
        (
            "The preview src must be a blob: URL. A browser "
            "does not give a File a path, and nothing here "
            "should construct one."
        ),
    )

    assert_false(
        outcome["src_has_drive_letter"],
        "No drive letter may appear in the preview src.",
    )

    assert_false(
        outcome["src_has_backslash"],
        "No Windows separator may appear in the preview src.",
    )

    assert_true(
        outcome["name_rendered_as_text"],
        (
            "The filename is still shown to the user -- as "
            "textContent, so a name containing markup is "
            "text."
        ),
    )

    ok(
        "a file named like an absolute Windows path still "
        "previews from a blob: URL, with the name rendered as "
        "text"
    )


# ==========================================================
# PHASE 12.18 - RETRY_WAIT TELLS THE TRUTH
# ==========================================================
#
# RELEASE BLOCKER 3.
#
# The retry architecture was already right: a 429 parks the job
# in RETRY_WAIT with a scheduled next_attempt_at and a bounded
# attempt count, durably, in PostgreSQL. Nothing about it
# changed here.
#
# What changed is what the page says while that happens. It
# used to show a spinner and a label, which is
# indistinguishable from stuck -- and during a real rate limit
# the wait is minutes, so "stuck" is the natural reading.
# ==========================================================

def test_retry_wait_ux(
    results: dict,
) -> None:

    section(
        "TEST 14 - RETRY_WAIT REPORTS THE REAL ATTEMPT, THE "
        "REAL REASON AND THE REAL TIME"
    )

    outcome = results[
        "retry_wait_reports_real_attempt_and_time"
    ]

    assert_true(
        outcome["has_two_of_three"],
        (
            "The page must show attempt 2 of 3 from the API "
            "values. Nothing may be hard-coded -- least of "
            "all 'attempt 1 of 3', which would be wrong on "
            "every retry."
        ),
    )

    assert_true(
        outcome["mentions_capacity"],
        (
            "The note must explain WHY the job is waiting. "
            "A provider at capacity is not a defect, and "
            "saying so is the difference between 'waiting' "
            "and 'broken'."
        ),
    )

    assert_true(
        outcome["mentions_queued_and_automatic"],
        (
            "The note must say the document is queued and "
            "will retry automatically, so nobody re-uploads "
            "it."
        ),
    )

    # ------------------------------------------------------
    # THE TIME IS THE BACKEND'S, RENDERED LOCALLY
    # ------------------------------------------------------

    assert_true(
        outcome["note_has_expected_time"],
        (
            "The note must render next_attempt_at as a local "
            "time.\n"
            f"expected {outcome['expected_local_time']!r} "
            f"in: {outcome['note']!r}"
        ),
    )

    assert_true(
        outcome["says_can_leave"],
        (
            "The note must say the page can be left. The job "
            "is a committed row with its bytes already in "
            "pending storage."
        ),
    )

    ok(
        "RETRY_WAIT shows 'attempt 2 of 3', names the "
        "capacity limit, renders the backend's own "
        f"next_attempt_at as {outcome['expected_local_time']}, "
        "and says the page can be left"
    )

    # ------------------------------------------------------
    # NO TIME MEANS NO CLAIM
    # ------------------------------------------------------

    absent = results[
        "retry_wait_without_next_attempt_invents_nothing"
    ]

    assert_false(
        absent["mentions_next_attempt"],
        (
            "With next_attempt_at null the page must say "
            "nothing about a next attempt. Computing one in "
            "JavaScript would drift from the scheduler that "
            "actually decides, and then be wrong in a way "
            "nobody could explain."
        ),
    )

    assert_false(
        absent["has_dangling_around"],
        (
            "A missing time must drop the whole sentence, not "
            "leave 'around .'"
        ),
    )

    assert_true(
        absent["still_reports_attempts"],
        (
            "The attempt count is still known and still worth "
            "showing when the time is not."
        ),
    )

    ok(
        "with next_attempt_at null the page invents no time "
        "and still reports 'attempt 3 of 3'"
    )

    # ------------------------------------------------------
    # AND THE EXPLANATION DOES NOT OUTLIVE THE WAIT
    # ------------------------------------------------------

    reset = results[
        "processing_note_resets_after_retry_clears"
    ]

    assert_true(
        reset["while_waiting_mentions_capacity"],
        "The capacity explanation must appear while waiting.",
    )

    assert_false(
        reset["after_resume_mentions_capacity"],
        (
            "Once the job is claimed again the retry "
            "explanation must go. A stale reason is a lie "
            "about the current state."
        ),
    )

    assert_true(
        reset["after_resume_says_background"],
        (
            "The resting note must return, including the "
            "durable-queue wording."
        ),
    )

    ok(
        "the retry explanation appears while waiting and is "
        "replaced when the job resumes"
    )


def test_durable_queue_wording(
    client,
) -> None:

    section(
        "TEST 15 - THE PAGE NO LONGER ASKS TO BE KEPT OPEN"
    )

    # ------------------------------------------------------
    # THE CLAIM IS CHECKED AGAINST THE ARCHITECTURE
    # ------------------------------------------------------
    #
    # "You can leave this page" is only allowed because it is
    # true. Three properties make it true, and all three are
    # asserted rather than assumed:
    #
    #   the job row and its bytes are committed before the
    #     page is told the job exists
    #   the worker claims from PostgreSQL on its own schedule
    #   nothing in the API cancels a job when a client
    #     disconnects

    page = client.get(
        "/upload"
    ).text

    assert_true(
        "keep this page open" not in page.lower(),
        (
            "The page must not ask the user to keep it open. "
            "The queue is durable, and during a provider rate "
            "limit that instruction turns a working queue "
            "into an order to sit and wait."
        ),
    )

    assert_true(
        "leave this page" in page.lower(),
        (
            "The page should say the work continues without "
            "it."
        ),
    )

    assert_true(
        "background" in page.lower(),
        (
            "The page should say processing continues in the "
            "background."
        ),
    )

    ok(
        "the upload page tells the user they can leave, "
        "because the durable queue means they can"
    )

    # ------------------------------------------------------
    # NOTHING CANCELS A JOB ON DISCONNECT
    # ------------------------------------------------------

    backend = (
        PROJECT_ROOT
        / "backend"
    )

    offenders = []

    for path in backend.rglob(
        "*.py"
    ):

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for marker in (
            "is_disconnected",
            "client_disconnect",
        ):

            if marker in text:

                offenders.append(
                    f"{path.name}: {marker}"
                )

    assert_equal(
        offenders,
        [],
        (
            "Nothing in the backend may cancel work when a "
            "client disconnects, or the wording above would "
            "be false."
        ),
    )

    ok(
        "no backend path reacts to a client disconnect, so a "
        "closed browser cannot cancel a job"
    )


def main():

    print()
    print("=" * 76)
    print(
        "PHASE 8.7 - UPLOAD AND ANALYZE "
        "EXPERIENCE"
    )
    print("=" * 76)


    client = None


    try:

        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        # ==================================================
        # The harness runs once and every executed
        # assertion reads from its results.
        # ==================================================

        results = (
            run_harness()
        )


        assert_no_harness_errors(
            results
        )


        print()
        print(
            "[OK] Upload state machine executed "
            "under Node with a DOM stub"
        )


        test_route_and_assets(
            client
        )

        test_shell_and_navigation(
            client
        )

        test_accessible_file_selection(
            client
        )

        test_truthful_processing(
            client
        )

        test_file_validation(
            results
        )

        test_object_url_lifecycle(
            results
        )

        test_preview_survives_processing(
            results
        )

        test_preview_survives_terminal_states(
            results
        )

        test_no_local_path_exposed(
            results
        )

        test_retry_wait_ux(
            results
        )

        test_durable_queue_wording(
            client
        )

        test_submission(
            results
        )

        test_success_and_error_flows(
            results
        )

        test_safe_rendering_and_privacy(
            client
        )

        test_responsive(
            client
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.7 UPLOAD EXPERIENCE "
            "TEST PASSED"
        )
        print("=" * 76)


    finally:

        if client is not None:

            client.close()


if __name__ == "__main__":

    main()
