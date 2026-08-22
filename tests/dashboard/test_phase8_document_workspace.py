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
)

from backend.app.services.final_record_service import (
    FinalRecordService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from tests.dashboard.source_audit import (
    audit_frontend_module,
    strip_js_comments,
)


# ==========================================================
# PHASE 8.10 - 8.14
# ADVANCED DOCUMENT WORKSPACE CONTRACT TEST
# ==========================================================
#
# The most important screen in the product, and the one that
# was rebuilt most heavily.
#
# WHAT CHANGED
# ----------------------------------------------------------
# review_detail.js was a single ~4,000 line file that rendered
# every panel with innerHTML string templates, carried its own
# fetch calls, read only the legacy `detail` error field, and
# escaped untrusted values by hand.
#
# Phase 8.10 split it by responsibility and rebuilt the screen
# on the design system. This suite guards the result.
#
# WHAT IS PROVEN BY EXECUTION
# ----------------------------------------------------------
# tests/dashboard/workspace_harness.js runs the real modules
# against a real parsed page, which is the only way to
# establish:
#
#     the review payload carries no reviewer id
#     four Approve clicks submit exactly once
#     a read-only reviewer cannot reach a submit path, even
#         when the module is called directly
#     PENDING_REVIEW and REJECTED publish no effective values
#     a corrected field shows machine AND correction AND
#         effective, with provenance
#     clearing a field sends null rather than omitting it
#     evidence boxes land on the pixels the OCR named
#     an unusable bbox is skipped, never clamped into a guess
#     raw JSON is never the landing view
#     hostile OCR text, notes and filenames create no elements
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
    / "workspace_harness.js"
)


WORKSPACE_ROUTE = (
    "/review/00000000-0000-4000-8000-000000000000"
)


# ----------------------------------------------------------
# The module set the rebuilt screen is split into.
# ----------------------------------------------------------

WORKSPACE_MODULES = (
    "/review/static/js/api.js",
    "/review/static/js/common.js",
    "/review/static/js/vocabulary.js",
    "/review/static/js/workspace/tabs.js",
    "/review/static/js/workspace/source_panel.js",
    "/review/static/js/workspace/fields_view.js",
    "/review/static/js/workspace/validation_view.js",
    "/review/static/js/workspace/result_view.js",
    "/review/static/js/workspace/review_actions.js",
    "/review/static/review_detail.js",
)


REQUIRED_STYLES = (
    "/review/static/css/tokens.css",
    "/review/static/css/base.css",
    "/review/static/css/layout.css",
    "/review/static/css/components.css",
    "/review/static/css/workspace.css",
    "/review/static/css/responsive.css",
)


# ----------------------------------------------------------
# The Phase 7B monolith was 3,969 lines. The controller must
# not have quietly grown back into one.
# ----------------------------------------------------------

CONTROLLER_LINE_BUDGET = 1200


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
                "document workspace. Without it this "
                "suite could only pattern-match "
                "source text, which would prove "
                "nothing about a review submission."
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
            timeout=180,
            cwd=str(
                PROJECT_ROOT
            ),
        )
    )


    if completed.returncode != 0:

        raise AssertionError(
            (
                "Workspace harness failed to run.\n"
                f"{completed.stdout[:4000]}\n"
                f"{completed.stderr[:4000]}"
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
# TEST 1 — ROUTE, MODULES, REFACTOR
# ==========================================================

def test_route_and_modules(
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - ROUTE AND MODULE STRUCTURE"
    )
    print("-" * 76)


    response = (
        client.get(
            WORKSPACE_ROUTE
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "GET /review/{id} should return "
            "HTTP 200."
        ),
    )


    markup = response.text


    # ======================================================
    # THE PAGE LOADS EVERY MODULE, AND EACH ONE RESOLVES
    # ======================================================

    for module in WORKSPACE_MODULES:

        assert_equal(
            client.get(
                module
            ).status_code,
            200,
            (
                "Workspace module should resolve: "
                f"{module}"
            ),
        )


        assert_true(
            module in markup,
            (
                "The workspace page should load "
                f"{module}"
            ),
        )


    for style in REQUIRED_STYLES:

        assert_equal(
            client.get(
                style
            ).status_code,
            200,
            (
                "Workspace stylesheet should "
                f"resolve: {style}"
            ),
        )


        assert_true(
            style in markup,
            (
                "The workspace page should load "
                f"{style}"
            ),
        )


    print(
        f"[PASS] All {len(WORKSPACE_MODULES)} modules "
        f"and {len(REQUIRED_STYLES)} stylesheets "
        "resolve and are loaded"
    )


    # ======================================================
    # THE MONOLITH IS ACTUALLY GONE
    # ======================================================
    #
    # Counting lines is crude, but the specific failure being
    # guarded against is crude too: a "refactor" that adds
    # modules while leaving the original file intact.
    # ======================================================

    controller = (
        client.get(
            "/review/static/review_detail.js"
        )
        .text
    )


    controller_lines = (
        controller.count(
            "\n"
        )
        + 1
    )


    assert_true(
        controller_lines
        < CONTROLLER_LINE_BUDGET,
        (
            "The page controller is "
            f"{controller_lines} lines. The Phase "
            "7B monolith was 3,969, and the point "
            "of splitting it was that this file "
            "stops rendering everything itself. "
            f"Budget is {CONTROLLER_LINE_BUDGET}."
        ),
    )


    print(
        f"[PASS] Controller is {controller_lines} "
        "lines, down from 3,969"
    )


    # ======================================================
    # RESPONSIBILITIES LIVE WHERE THEY BELONG
    # ======================================================

    ownership = {
        "/review/static/js/workspace/tabs.js": (
            "createTabs",
        ),
        "/review/static/js/workspace/source_panel.js": (
            "boxToPercent",
            "isUsableBox",
            "highlight",
        ),
        "/review/static/js/workspace/fields_view.js": (
            "FIELD_ORDER",
            "buildOcrLookup",
        ),
        "/review/static/js/workspace/validation_view.js": (
            "severityCounts",
        ),
        "/review/static/js/workspace/result_view.js": (
            "renderFinalRecord",
            "renderEffectiveValues",
            "renderReviewHistory",
        ),
        "/review/static/js/workspace/review_actions.js": (
            "renderHumanReviewState",
            "collectCorrections",
            "CORRECTABLE_FIELDS",
        ),
    }


    for (
        module,
        names,
    ) in ownership.items():

        source = (
            client.get(
                module
            )
            .text
        )


        for name in names:

            assert_true(
                name in source,
                (
                    f"{module} should own {name}."
                ),
            )


        # ==================================================
        # AND NOT DEFINED IN THE CONTROLLER
        # ==================================================
        #
        # The controller legitimately CALLS these, so a bare
        # substring search would flag every delegation. What
        # matters is that it does not DEFINE them: a second
        # implementation is how a refactor quietly becomes a
        # copy.
        # ==================================================

        controller_code = (
            strip_js_comments(
                controller
            )
        )


        for name in names:

            for definition in (
                f"function {name}(",
                f"var {name} =",
                f"const {name} =",
                f"let {name} =",
            ):

                assert_false(
                    definition
                    in controller_code,
                    (
                        "The controller should "
                        "delegate rather than define "
                        f"{name}. Found: {definition}"
                    ),
                )


    print(
        f"[PASS] {len(ownership)} modules each own "
        "their responsibility; the controller "
        "delegates"
    )


    # ======================================================
    # THE PHASE 7B CONTRACT SURVIVES
    # ======================================================

    for needle in (
        "Human Review",
        "review_detail.js",
        'id="approve-button"',
        'id="reject-button"',
        'id="correct-button"',
        'id="authenticated-reviewer-card"',
    ):

        assert_true(
            needle in markup,
            (
                "The Phase 7B workspace contract is "
                f"broken: {needle} is missing."
            ),
        )


    assert_false(
        'id="reviewer-id"'
        in markup,
        (
            "The legacy editable reviewer ID input "
            "must not exist."
        ),
    )


    print(
        "[PASS] Phase 7B page contract preserved; "
        "no editable reviewer ID"
    )


# ==========================================================
# TEST 2 — REQUEST BUDGET
# ==========================================================

def test_request_budget(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - REQUEST BUDGET"
    )
    print("-" * 76)


    budget = results[
        "request_budget"
    ]


    for key, description in (
        (
            "document",
            "the document",
        ),
        (
            "reviewer",
            "reviewer identity",
        ),
        (
            "history",
            "audit history",
        ),
        (
            "image",
            "the source image",
        ),
        (
            "health",
            "liveness",
        ),
    ):

        assert_equal(
            budget[
                key
            ],
            1,
            (
                "A page load should request "
                f"{description} exactly once. The "
                "Phase 8.3 audit found duplicate "
                "reads on this screen."
            ),
        )


    assert_equal(
        budget[
            "intervals"
        ],
        0,
        (
            "The workspace must not poll."
        ),
    )


    assert_true(
        budget[
            "content_visible"
        ]
        and budget[
            "loading_hidden"
        ],
        (
            "A completed load should show the "
            "workspace and hide the skeleton."
        ),
    )


    print(
        "[PASS] 5 requests total, one each, no "
        "duplicates and no polling"
    )


# ==========================================================
# TEST 3 — HEADER, FACTS, OVERVIEW
# ==========================================================

def test_summary_surfaces(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - SUMMARY SURFACES"
    )
    print("-" * 76)


    header = results[
        "header_and_facts"
    ]


    assert_equal(
        header[
            "title"
        ],
        "guard_front.jpg",
        (
            "The heading should be the document's "
            "filename."
        ),
    )


    assert_true(
        "doc-workspace-1"
        in header[
            "subtitle"
        ],
        (
            "The document id should be visible "
            "without opening a tab."
        ),
    )


    # ======================================================
    # STATUS IS ANSWERED IN THE HEADER
    # ======================================================

    badges = header[
        "badges"
    ]


    assert_true(
        "Guard Licence"
        in badges,
        (
            "The document type should be in the "
            "header."
        ),
    )


    assert_true(
        "Pending Review"
        in badges,
        (
            "The final status should be in the "
            "header."
        ),
    )


    assert_true(
        "Expired"
        in badges,
        (
            "The expiry state should be in the "
            "header."
        ),
    )


    assert_true(
        "High"
        in badges,
        (
            "The review priority should be in the "
            "header when one is assigned."
        ),
    )


    print(
        f"[PASS] Header answers status with "
        f"{len(badges)} badges, no JSON required"
    )


    # ======================================================
    # OVERVIEW
    # ======================================================

    overview = results[
        "overview"
    ]


    for needle, description in (
        (
            "Final status",
            "the final status",
        ),
        (
            "Machine decision",
            "the machine decision",
        ),
        (
            "Validity",
            "the expiry state",
        ),
        (
            "Findings",
            "the finding counts",
        ),
    ):

        assert_true(
            needle
            in overview[
                "text"
            ],
            (
                "The overview should state "
                f"{description}."
            ),
        )


    assert_true(
        overview[
            "note"
        ]
        is not None
        and "reviewer decides"
        in overview[
            "note"
        ],
        (
            "The overview should explain what the "
            "current status means in words, not "
            "just as a badge."
        ),
    )


    assert_true(
        "Not usable"
        in overview[
            "text"
        ],
        (
            "A pending document is not usable, and "
            "the overview should say so."
        ),
    )


    print(
        "[PASS] Overview answers status, decision, "
        "validity and findings in words"
    )


    # ======================================================
    # DOCUMENT FACTS
    # ======================================================

    facts = " ".join(
        header[
            "facts"
        ]
    )


    for needle in (
        "Document type",
        "Processing status",
        "Uploaded",
        "Analysed",
        "Document ID",
        "Analysis ID",
    ):

        assert_true(
            needle in facts,
            (
                "The document details panel is "
                f"missing {needle}."
            ),
        )


    print(
        "[PASS] Document details panel carries the "
        "provenance metadata"
    )


# ==========================================================
# TEST 4 — TABS
# ==========================================================

def test_tabs(
    results: dict,
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - TABS"
    )
    print("-" * 76)


    tabs = results[
        "tabs_default"
    ][
        "tabs"
    ]


    assert_equal(
        [
            tab[
                "label"
            ]
            for tab in tabs
        ],
        [
            "Extracted Data",
            "Validation",
            "Findings",
            "Final Record",
            "History",
            "Technical Data",
        ],
        (
            "The detail views should be ordered "
            "from what the reviewer needs first to "
            "what they need last."
        ),
    )


    # ======================================================
    # ROVING TABINDEX
    # ======================================================

    assert_equal(
        [
            tab[
                "tabindex"
            ]
            for tab in tabs
        ],
        [
            None,
            "-1",
            "-1",
            "-1",
            "-1",
            "-1",
        ],
        (
            "Only the active tab may be in the tab "
            "order, or Tab walks through six "
            "buttons instead of moving on."
        ),
    )


    assert_equal(
        len(
            [
                tab
                for tab in tabs
                if tab[
                    "panel_hidden"
                ]
                is False
            ]
        ),
        1,
        (
            "Exactly one panel may be visible."
        ),
    )


    print(
        "[PASS] 6 tabs, roving tabindex, exactly "
        "one visible panel"
    )


    # ======================================================
    # KEYBOARD
    # ======================================================

    keyboard = results[
        "tabs_keyboard"
    ]


    assert_equal(
        [
            step[
                "id"
            ]
            for step in keyboard[
                "trail"
            ]
        ],
        [
            "tab-fields",
            "tab-validation",
            "tab-anomalies",
            "tab-validation",
            "tab-raw",
            "tab-fields",
            "tab-raw",
        ],
        (
            "Arrow keys should move between tabs, "
            "Home and End should jump to the ends, "
            "and the ends should wrap."
        ),
    )


    assert_true(
        keyboard[
            "focused_after_arrow"
        ]
        is not None,
        (
            "Keyboard navigation should move focus, "
            "not only the selected state."
        ),
    )


    print(
        "[PASS] Arrow, Home, End and wrapping all "
        "work, and focus follows"
    )


    # ======================================================
    # CLICK
    # ======================================================

    clicked = results[
        "tabs_click_switches_panel"
    ]


    assert_equal(
        clicked[
            "raw_selected"
        ][
            "selected"
        ],
        "true",
        (
            "Clicking a tab should select it."
        ),
    )


    assert_equal(
        clicked[
            "visible_panels"
        ],
        1,
        (
            "Switching tabs must not leave two "
            "panels visible."
        ),
    )


    print(
        "[PASS] Clicking a tab switches exactly "
        "one panel"
    )


    # ======================================================
    # ARIA MARKUP
    # ======================================================

    markup = (
        client.get(
            WORKSPACE_ROUTE
        )
        .text
    )


    assert_true(
        'role="tablist"'
        in markup,
        (
            "The tab strip should expose "
            'role="tablist".'
        ),
    )


    assert_equal(
        markup.count(
            'role="tab"'
        ),
        6,
        (
            "Each tab should carry role=tab."
        ),
    )


    assert_equal(
        markup.count(
            'role="tabpanel"'
        ),
        6,
        (
            "Each panel should carry "
            "role=tabpanel."
        ),
    )


    assert_equal(
        markup.count(
            'aria-controls="panel-'
        ),
        6,
        (
            "Each tab should name its own panel."
        ),
    )


    print(
        "[PASS] tablist, 6 tabs, 6 panels, each "
        "tab naming its panel"
    )


# ==========================================================
# TEST 5 — EXTRACTED DATA, CONFIDENCE, EVIDENCE
# PHASE 8.11
# ==========================================================

def test_fields_and_evidence(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - EXTRACTED DATA / CONFIDENCE / "
        "EVIDENCE"
    )
    print("-" * 76)


    render = results[
        "fields_render"
    ]


    assert_equal(
        render[
            "row_count"
        ],
        len(
            FinalRecordService.FIELD_NAMES
        ),
        (
            "Every extracted field should have a "
            "row, including the ones that were not "
            "detected."
        ),
    )


    rows = {
        row[
            "label"
        ]: row

        for row in render[
            "rows"
        ]
    }


    # ======================================================
    # VALUE, CONFIDENCE, EVIDENCE STATUS, PROVENANCE
    # ======================================================

    name_row = rows[
        "Full Name"
    ]


    assert_equal(
        name_row[
            "value"
        ],
        "SAMPLE,JANE",
        (
            "An extracted value must be shown "
            "exactly as read. Reformatting it would "
            "mean the reviewer is checking the "
            "display rather than the data."
        ),
    )


    # PHASE 10.5. The fixture value is 0.9988, and it used to
    # display as "100%" because formatConfidence rounded to
    # whole percent.
    #
    # The calibration study found a field that was WRONG at
    # 0.998555 -- which displayed identically. A reviewer
    # cannot be shown "100%" on a value the system has not
    # established is correct, so the display now keeps two
    # decimals and reserves 100% for exactly 1.0.
    assert_equal(
        name_row[
            "confidence"
        ],
        "99.88%",
        (
            "The per-field OCR evidence support should be "
            "shown as a figure, and must not round up to "
            "100% for a value below 1."
        ),
    )


    badge_text = " ".join(
        badge[
            "text"
        ]
        for badge in name_row[
            "badges"
        ]
    )


    assert_true(
        "Evidence verified"
        in badge_text,
        (
            "The evidence status should be stated "
            "in words."
        ),
    )


    assert_true(
        "Machine"
        in badge_text,
        (
            "Provenance should be stated on every "
            "field, so a machine reading is never "
            "mistaken for a correction."
        ),
    )


    assert_equal(
        name_row[
            "evidence_ids"
        ],
        [
            "L2",
        ],
        (
            "The OCR line the value came from "
            "should be named."
        ),
    )


    assert_equal(
        name_row[
            "evidence_text"
        ],
        [
            "SAMPLE,JANE",
        ],
        (
            "The OCR text itself should be "
            "inspectable, not just its id."
        ),
    )


    print(
        "[PASS] Value, confidence, evidence "
        "status, provenance and OCR source all "
        "present per field"
    )


    # ======================================================
    # A FIELD THAT WAS NOT DETECTED
    # ======================================================

    missing = rows[
        "ID Number"
    ]


    assert_true(
        missing[
            "empty"
        ],
        (
            "A field with no value should be marked "
            "as such rather than rendered blank."
        ),
    )


    assert_equal(
        missing[
            "evidence_ids"
        ],
        [],
        (
            "A field with no value cites no "
            "evidence."
        ),
    )


    assert_true(
        "Not detected"
        in " ".join(
            badge[
                "text"
            ]
            for badge in missing[
                "badges"
            ]
        ),
        (
            "An undetected field should say so."
        ),
    )


    print(
        "[PASS] An undetected field is explicit, "
        "not blank"
    )


    # ======================================================
    # NO OVERALL CONFIDENCE
    # ======================================================
    #
    # field_confidence is per-field and there is no
    # authoritative document-level definition. Averaging the
    # per-field numbers would invent a statistic.
    # ======================================================

    overall = results[
        "no_overall_confidence"
    ]


    for key, description in (
        (
            "mentions_document_confidence",
            "a document confidence",
        ),
        (
            "mentions_overall",
            "an overall confidence",
        ),
        (
            "mentions_average",
            "an average confidence",
        ),
    ):

        assert_false(
            overall[
                key
            ],
            (
                "The workspace must not present "
                f"{description}. No such value is "
                "defined."
            ),
        )


    assert_true(
        overall[
            "states_absence"
        ],
        (
            "The absence should be stated rather "
            "than left as a silent gap, so nobody "
            "assumes the number is hidden "
            "somewhere."
        ),
    )


    print(
        "[PASS] No invented document-level "
        "confidence, and the absence is explained"
    )


    # ======================================================
    # EVIDENCE PROBLEMS ARE READABLE
    # ======================================================

    problems = {
        entry[
            "field"
        ]: entry

        for entry in results[
            "evidence_problems"
        ][
            "problems"
        ]
    }


    assert_equal(
        problems[
            "Full Name"
        ][
            "titles"
        ],
        [
            "Value not found in its evidence",
        ],
        (
            "FULL_NAME_EVIDENCE_MISMATCH should be "
            "explained, not shown as a code."
        ),
    )


    assert_equal(
        problems[
            "Issuer"
        ][
            "titles"
        ],
        [
            "Expected context missing",
        ],
        (
            "ISSUER_CONTEXT_MISSING should be "
            "explained."
        ),
    )


    assert_equal(
        problems[
            "Licence Number"
        ][
            "refs"
        ],
        [
            "Line L99",
        ],
        (
            "A flag carrying a line reference "
            "should surface that reference, so the "
            "reviewer can see which line was "
            "cited."
        ),
    )


    print(
        "[PASS] Evidence flags are attributed to "
        "the right field and explained in words"
    )


# ==========================================================
# TEST 6 — EVIDENCE HIGHLIGHTING
# ==========================================================

def test_evidence_highlighting(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - EVIDENCE HIGHLIGHTING"
    )
    print("-" * 76)


    # ======================================================
    # THE ARITHMETIC
    # ======================================================
    #
    # Highlighting was only implemented because four things
    # were verified first: bbox is persisted, it is in the
    # ORIGINAL image's pixel space (the analyze path runs OCR
    # on the stored bytes with no preprocessing), the format is
    # [x1, y1, x2, y2], and scaling can be expressed in
    # percentages of the image's intrinsic size.
    #
    # These assertions guard the last two.
    # ======================================================

    math = results[
        "bbox_arithmetic"
    ]


    assert_true(
        math[
            "usable"
        ],
        (
            "A well-formed box inside the image "
            "should be usable."
        ),
    )


    for key, description in (
        (
            "zero_area",
            "a zero-area box",
        ),
        (
            "out_of_bounds",
            "a box outside the image",
        ),
        (
            "inverted",
            "an inverted box",
        ),
        (
            "wrong_length",
            "a box with three numbers",
        ),
        (
            "non_numeric",
            "a box with a string coordinate",
        ),
        (
            "no_size",
            "a box with no image size to scale by",
        ),
    ):

        assert_false(
            math[
                key
            ],
            (
                "The renderer must refuse to draw "
                f"{description}. Clamping it into "
                "something plausible would be "
                "exactly the approximate highlight "
                "that must not happen."
            ),
        )


    assert_equal(
        math[
            "percent"
        ],
        {
            "left": 5,
            "top": 5,
            "width": 25,
            "height": 10,
        },
        (
            "A box of [30, 20, 180, 60] in a "
            "600x400 image is 5%, 5%, 25%, 10%. "
            "Percentages of the intrinsic size need "
            "no recalculation when the layout "
            "changes."
        ),
    )


    assert_true(
        math[
            "percent_bad"
        ]
        is None,
        (
            "An unusable box must convert to "
            "nothing, so no caller can position an "
            "element at NaN%."
        ),
    )


    print(
        "[PASS] Box geometry is exact, and 6 kinds "
        "of unusable box are refused"
    )


    # ======================================================
    # DRAWING
    # ======================================================

    highlight = results[
        "evidence_highlight"
    ]


    assert_equal(
        highlight[
            "after_name"
        ],
        [
            {
                "lineId": "L2",
                "left": "10%",
                "top": "30%",
                "width": "40%",
                "height": "10%",
            },
        ],
        (
            "Highlighting Full Name should draw one "
            "box over L2, at the position the OCR "
            "recorded."
        ),
    )


    assert_equal(
        [
            box[
                "lineId"
            ]
            for box in highlight[
                "after_expiry"
            ]
        ],
        [
            "L4",
        ],
        (
            "Highlighting another field should "
            "replace the previous highlight, not "
            "accumulate boxes."
        ),
    )


    assert_equal(
        highlight[
            "active_ids"
        ],
        [
            "L4",
        ],
        (
            "The panel should track only the "
            "currently highlighted lines."
        ),
    )


    print(
        "[PASS] Clicking a field draws its OCR box "
        "and replaces the previous one"
    )


    # ======================================================
    # AN UNUSABLE BOX IS SKIPPED AND SAID SO
    # ======================================================

    skipped = results[
        "unusable_bbox_is_skipped"
    ]


    assert_equal(
        skipped[
            "result"
        ][
            "drawn"
        ],
        1,
        (
            "Only the usable box should be drawn."
        ),
    )


    assert_equal(
        skipped[
            "result"
        ][
            "skipped"
        ],
        2,
        (
            "A zero-area box and a line that does "
            "not exist should both be skipped."
        ),
    )


    assert_true(
        "could not be positioned"
        in skipped[
            "caption"
        ],
        (
            "The reviewer should be told that some "
            "evidence could not be positioned, "
            "rather than silently seeing fewer "
            "boxes than fields."
        ),
    )


    # ======================================================
    # NO INTRINSIC SIZE MEANS NO BOXES AT ALL
    # ======================================================

    unknown = results[
        "highlight_without_intrinsic_size"
    ]


    assert_equal(
        unknown[
            "boxes"
        ],
        0,
        (
            "Without the image's intrinsic size "
            "there is no honest way to place a box."
        ),
    )


    assert_equal(
        unknown[
            "result"
        ][
            "reason"
        ],
        "unknown-intrinsic-size",
        (
            "The reason should be explicit."
        ),
    )


    assert_true(
        "line IDs and text"
        in unknown[
            "caption"
        ],
        (
            "When boxes cannot be drawn, the "
            "reviewer should be pointed at the "
            "evidence text, which is always "
            "available."
        ),
    )


    print(
        "[PASS] Unusable boxes are skipped and "
        "explained; no intrinsic size means no "
        "guessing"
    )


    # ======================================================
    # THE TOGGLE
    # ======================================================

    toggle = results[
        "highlight_toggle"
    ]


    assert_true(
        toggle[
            "before"
        ]
        == 2
        and toggle[
            "off"
        ]
        == 0
        and toggle[
            "back_on"
        ]
        == 2,
        (
            "The highlight toggle should clear and "
            "restore the overlay."
        ),
    )


    print(
        "[PASS] The evidence toggle clears and "
        "restores the overlay"
    )


    # ======================================================
    # A MISSING IMAGE IS NOT A PAGE FAILURE
    # ======================================================

    missing_image = results[
        "missing_image_is_not_a_page_failure"
    ]


    assert_true(
        missing_image[
            "content_visible"
        ],
        (
            "A missing source image must not take "
            "the whole screen down. The reviewer "
            "can still read the values and the "
            "evidence text."
        ),
    )


    assert_true(
        missing_image[
            "unavailable_visible"
        ],
        (
            "A missing image should be stated."
        ),
    )


    assert_true(
        "DOCUMENT_IMAGE_NOT_FOUND"
        in missing_image[
            "unavailable_text"
        ],
        (
            "The structured error code should be "
            "surfaced even for a binary endpoint."
        ),
    )


    assert_equal(
        missing_image[
            "field_rows"
        ],
        len(
            FinalRecordService.FIELD_NAMES
        ),
        (
            "The extracted fields should still "
            "render without the image."
        ),
    )


    print(
        "[PASS] A missing image degrades to an "
        "explained state; the rest of the "
        "workspace still works"
    )


# ==========================================================
# TEST 7 — VALIDATION AND EXPIRY
# PHASE 8.12
# ==========================================================

def test_validation_and_expiry(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 7 - VALIDATION AND EXPIRY"
    )
    print("-" * 76)


    render = results[
        "validation_render"
    ]


    assert_equal(
        render[
            "blocks"
        ],
        [
            "Validity",
            "Date fields",
            "Date consistency",
        ],
        (
            "Validation should be organised into "
            "expiry, per-field parse status and "
            "cross-field consistency."
        ),
    )


    text = render[
        "text"
    ]


    # ======================================================
    # EXPIRY
    # ======================================================

    assert_true(
        "Expired"
        in text,
        (
            "The expiry status should be presented "
            "as a readable label."
        ),
    )


    assert_true(
        "1 Jan 2026"
        in text,
        (
            "The expiry date itself should be "
            "shown."
        ),
    )


    # ==================================================
    # DAYS REMAINING COMES FROM THE VALIDATOR
    # ==================================================
    #
    # days_until_expiry is computed by DateLogicalValidator
    # against its own reference_date. Displaying it introduces
    # no new threshold; recomputing it locally could disagree
    # with the status beside it.
    # ==================================================

    assert_true(
        "231"
        in text,
        (
            "days_until_expiry should be shown when "
            "the validator supplied it."
        ),
    )


    assert_true(
        "Checked against"
        in text,
        (
            "The reference date the validator used "
            "should be stated, so 'expired' is "
            "attributable."
        ),
    )


    print(
        "[PASS] Expiry status, date, days remaining "
        "and reference date all shown"
    )


    # ======================================================
    # NO INVENTED DAYS FIGURE
    # ======================================================

    no_expiry = results[
        "no_expiry_date"
    ]


    assert_false(
        no_expiry[
            "mentions_days"
        ],
        (
            "With no expiry date the validator "
            "sends no days_until_expiry, so no days "
            "figure may appear."
        ),
    )


    assert_true(
        "No usable expiry date"
        in no_expiry[
            "text"
        ],
        (
            "A document with no expiry date should "
            "say so plainly."
        ),
    )


    print(
        "[PASS] With no expiry date, no days figure "
        "is invented"
    )


    # ======================================================
    # PER-FIELD DATE STATUS
    # ======================================================

    rows = " ".join(
        render[
            "rows"
        ]
    )


    for needle in (
        "Date of Birth",
        "Issue Date",
        "Expiry Date",
        "Valid date",
        "Not detected",
    ):

        assert_true(
            needle in rows,
            (
                "The date field breakdown is "
                f"missing {needle}."
            ),
        )


    print(
        "[PASS] Every date field reports its own "
        "parse status"
    )


    # ======================================================
    # LOGICAL ISSUES
    # ======================================================

    logical = results[
        "validation_logical_issues"
    ]


    titles = [
        issue[
            "title"
        ]
        for issue in logical[
            "issues"
        ]
    ]


    assert_true(
        "Date of birth in the future"
        in titles,
        (
            "FUTURE_DATE_OF_BIRTH should read as "
            "language."
        ),
    )


    assert_true(
        any(
            "not a valid date" in title
            for title in titles
        ),
        (
            "A per-field INVALID_FORMAT code should "
            "be explained for the field it names."
        ),
    )


    codes = [
        issue[
            "code"
        ]
        for issue in logical[
            "issues"
        ]
    ]


    assert_true(
        "FUTURE_DATE_OF_BIRTH"
        in codes,
        (
            "The machine code must stay reachable "
            "beside the readable title."
        ),
    )


    assert_true(
        logical[
            "raw_value_shown"
        ],
        (
            "An unparseable date must be shown "
            "exactly as extracted. Hiding it would "
            "leave the reviewer unable to see what "
            "went wrong."
        ),
    )


    print(
        "[PASS] Logical issues read as language, "
        "keep their codes, and show the raw value"
    )


# ==========================================================
# TEST 8 — FINDINGS AND RISK
# ==========================================================

def test_findings(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 8 - FINDINGS"
    )
    print("-" * 76)


    render = results[
        "findings_render"
    ]


    assert_equal(
        [
            badge[
                "text"
            ]
            for badge in render[
                "summary_badges"
            ]
        ],
        [
            "1 error",
            "1 warning",
        ],
        (
            "Findings should be summarised by the "
            "severities the backend attached."
        ),
    )


    items = render[
        "items"
    ]


    assert_equal(
        len(
            items
        ),
        2,
        (
            "Each anomaly issue should produce one "
            "row."
        ),
    )


    assert_equal(
        items[
            0
        ][
            "title"
        ],
        "Required field missing",
        (
            "MISSING_CRITICAL_FIELD should read as "
            "language."
        ),
    )


    assert_equal(
        items[
            0
        ][
            "code"
        ],
        "MISSING_CRITICAL_FIELD",
        (
            "The machine code must stay reachable."
        ),
    )


    assert_true(
        "id_number"
        in items[
            0
        ][
            "message"
        ],
        (
            "The validator's own message should be "
            "shown, so the affected field is named "
            "as the backend named it."
        ),
    )


    assert_true(
        "severity-error"
        in items[
            0
        ][
            "severity_class"
        ],
        (
            "An ERROR should be presented as an "
            "error."
        ),
    )


    # ======================================================
    # NO RISK SCORE
    # ======================================================

    assert_false(
        render[
            "mentions_risk"
        ],
        (
            "There is no document risk score in "
            "this system, and Phase 8 must not "
            "invent one."
        ),
    )


    assert_false(
        render[
            "has_percent"
        ],
        (
            "A percentage in the findings panel "
            "would imply a rate the backend does "
            "not compute."
        ),
    )


    print(
        "[PASS] Findings use real severities and "
        "real codes; no risk score, no percentage"
    )


    # ======================================================
    # THE MACHINE DECISION IS ATTRIBUTED
    # ======================================================

    assert_true(
        render[
            "summary_hint"
        ]
        is not None
        and "Review Required"
        in render[
            "summary_hint"
        ],
        (
            "The findings should be connected to "
            "the machine decision they produced."
        ),
    )


    print(
        "[PASS] Findings are connected to the "
        "machine decision they produced"
    )


    # ======================================================
    # NO FINDINGS
    # ======================================================

    clean = results[
        "no_findings"
    ]


    assert_equal(
        clean[
            "item_count"
        ],
        0,
        (
            "A clean document should list no "
            "findings."
        ),
    )


    assert_true(
        "No findings"
        in clean[
            "text"
        ],
        (
            "A clean document should say so rather "
            "than showing an empty panel."
        ),
    )


    # ======================================================
    # AN UNKNOWN SEVERITY IS NOT PROMOTED
    # ======================================================

    unknown = results[
        "unknown_severity_not_promoted"
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
        unknown[
            "code_shown"
        ],
        (
            "An unrecognised code should still be "
            "shown, as itself."
        ),
    )


    print(
        "[PASS] An unrecognised severity is shown "
        "as itself and never promoted"
    )


# ==========================================================
# TEST 9 — FINAL RESULT
# PHASE 8.14
# ==========================================================

def test_final_record(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 9 - FINAL RESULT"
    )
    print("-" * 76)


    # ======================================================
    # EVERY BACKEND STATE IS COVERED
    # ======================================================

    covered = {
        "PENDING_REVIEW": results[
            "final_pending"
        ],
        # PHASE 10.2.
        "UNSUPPORTED": results[
            "final_unsupported"
        ],
        "REJECTED": results[
            "final_rejected"
        ],
        "AUTO_ACCEPTED": results[
            "final_auto_accepted"
        ],
        "APPROVED": results[
            "final_approved"
        ],
        "CORRECTED": results[
            "final_corrected"
        ],
    }


    assert_equal(
        set(
            covered.keys()
        ),
        set(
            FinalRecordService.FINAL_STATUSES
        ),
        (
            "Every final status the backend can "
            "resolve must have a rendering, and no "
            "frontend-only state may exist."
        ),
    )


    print(
        f"[PASS] All {len(covered)} backend final "
        "states render"
    )


    # ======================================================
    # PENDING REVIEW: NOT FINAL, NOT USABLE, NO VALUES
    # ======================================================

    pending = covered[
        "PENDING_REVIEW"
    ]


    assert_equal(
        pending[
            "status_text"
        ],
        "Pending Review",
        (
            "The status should be named."
        ),
    )


    assert_true(
        "Not final"
        in pending[
            "badges"
        ]
        and "Not usable"
        in pending[
            "badges"
        ],
        (
            "A pending document is neither final "
            "nor usable, and both must be stated."
        ),
    )


    assert_true(
        "No effective values are published"
        in pending[
            "effective_text"
        ],
        (
            "FinalRecordService publishes no "
            "effective values for a pending "
            "document, and the UI must not imply "
            "otherwise."
        ),
    )


    assert_true(
        "must not be used downstream"
        in pending[
            "effective_text"
        ],
        (
            "The machine reading is shown for "
            "reference, and must be labelled as "
            "not usable."
        ),
    )


    for row in pending[
        "value_rows"
    ]:

        assert_equal(
            row[
                "source"
            ],
            [
                "Withheld",
            ],
            (
                "Every pending row should be marked "
                "withheld rather than carrying a "
                "provenance that implies "
                "publication."
            ),
        )


        assert_equal(
            [
                cell[
                    "label"
                ]
                for cell in row[
                    "cells"
                ]
            ],
            [
                "Machine",
            ],
            (
                "A pending row has a machine value "
                "and nothing else."
            ),
        )


    print(
        "[PASS] Pending: not final, not usable, no "
        "effective values, every row withheld"
    )


    # ======================================================
    # REJECTED: FINAL BUT NOT USABLE
    # ======================================================

    rejected = covered[
        "REJECTED"
    ]


    assert_true(
        "Final"
        in rejected[
            "badges"
        ],
        (
            "A rejected document is final."
        ),
    )


    assert_true(
        "Not usable"
        in rejected[
            "badges"
        ],
        (
            "A rejected document is not usable. "
            "Presenting it as a usable final record "
            "would be a correctness failure."
        ),
    )


    assert_true(
        "No effective values are published"
        in rejected[
            "effective_text"
        ],
        (
            "A rejected document publishes no "
            "effective values."
        ),
    )


    assert_true(
        "nothing from it should be used"
        in rejected[
            "note"
        ],
        (
            "The consequence of a rejection should "
            "be spelled out."
        ),
    )


    print(
        "[PASS] Rejected: final, not usable, "
        "nothing published"
    )


    # ======================================================
    # CORRECTED: MACHINE, CORRECTION AND EFFECTIVE
    # ======================================================

    corrected = covered[
        "CORRECTED"
    ]


    assert_true(
        "Final"
        in corrected[
            "badges"
        ]
        and "Usable"
        in corrected[
            "badges"
        ],
        (
            "A corrected document is final and "
            "usable."
        ),
    )


    rows = {
        row[
            "label"
        ]: row

        for row in corrected[
            "value_rows"
        ]
    }


    licence = rows[
        "Licence Number"
    ]


    assert_true(
        licence[
            "corrected"
        ],
        (
            "A corrected row must be visually "
            "distinct."
        ),
    )


    assert_equal(
        [
            cell[
                "label"
            ]
            for cell in licence[
                "cells"
            ]
        ],
        [
            "Machine",
            "Human correction",
            "Effective",
        ],
        (
            "A corrected field must show all three "
            "values. Hiding the machine reading "
            "would remove the reviewer's only way "
            "to see what changed."
        ),
    )


    values = {
        cell[
            "label"
        ]: cell[
            "value"
        ]

        for cell in licence[
            "cells"
        ]
    }


    assert_equal(
        values[
            "Machine"
        ],
        "12345678",
        (
            "The machine reading must be preserved "
            "exactly."
        ),
    )


    assert_equal(
        values[
            "Human correction"
        ],
        "87654321",
        (
            "The correction must be shown."
        ),
    )


    assert_equal(
        values[
            "Effective"
        ],
        "87654321",
        (
            "The effective value is the correction."
        ),
    )


    assert_equal(
        licence[
            "source"
        ],
        [
            "Human Corrected",
        ],
        (
            "Provenance must say a human corrected "
            "this field."
        ),
    )


    # ==================================================
    # AN UNCORRECTED FIELD IN A CORRECTED DOCUMENT
    # ==================================================

    issuer = rows[
        "Issuer"
    ]


    assert_false(
        issuer[
            "corrected"
        ],
        (
            "A field nobody touched must not be "
            "marked corrected."
        ),
    )


    assert_equal(
        issuer[
            "source"
        ],
        [
            "Machine",
        ],
        (
            "An untouched field keeps machine "
            "provenance."
        ),
    )


    assert_equal(
        [
            cell[
                "label"
            ]
            for cell in issuer[
                "cells"
            ]
        ],
        [
            "Machine",
            "Effective",
        ],
        (
            "An untouched field needs no correction "
            "column."
        ),
    )


    print(
        "[PASS] Corrected: machine, correction and "
        "effective shown together with provenance; "
        "untouched fields stay machine"
    )


    # ======================================================
    # APPROVED AND AUTO_ACCEPTED
    # ======================================================

    for name in (
        "APPROVED",
        "AUTO_ACCEPTED",
    ):

        record = covered[
            name
        ]


        assert_true(
            "Final"
            in record[
                "badges"
            ]
            and "Usable"
            in record[
                "badges"
            ],
            (
                f"{name} is final and usable."
            ),
        )


        assert_true(
            "No field was corrected"
            in record[
                "effective_text"
            ],
            (
                f"{name} publishes the machine "
                "values unchanged, and should say "
                "so."
            ),
        )


        for row in record[
            "value_rows"
        ]:

            assert_equal(
                row[
                    "source"
                ],
                [
                    "Machine",
                ],
                (
                    f"Every {name} value is a "
                    "machine reading."
                ),
            )


    print(
        "[PASS] Approved and auto-accepted publish "
        "the machine values, all machine provenance"
    )


# ==========================================================
# TEST 10 — HISTORY AND RAW DATA
# ==========================================================

def test_history_and_raw(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 10 - HISTORY AND TECHNICAL DATA"
    )
    print("-" * 76)


    history = results[
        "history_timeline"
    ]


    assert_equal(
        history[
            "item_count"
        ],
        2,
        (
            "Each audit event should produce one "
            "timeline entry."
        ),
    )


    assert_equal(
        history[
            "titles"
        ],
        [
            "Machine review decision",
            "Human review",
        ],
        (
            "Event types should be named in "
            "language."
        ),
    )


    assert_true(
        any(
            "vigilox-pipeline" in actor
            for actor in history[
                "actors"
            ]
        ),
        (
            "The actor should be attributed."
        ),
    )


    assert_true(
        "Required field missing"
        in history[
            "reason_chips"
        ],
        (
            "Reason codes in the audit trail should "
            "read as language too."
        ),
    )


    assert_true(
        any(
            "misread" in note
            for note in history[
                "notes"
            ]
        ),
        (
            "Reviewer notes should be shown."
        ),
    )


    assert_true(
        any(
            "87654321" in text
            for text in history[
                "corrections"
            ]
        ),
        (
            "The recorded correction should be "
            "shown."
        ),
    )


    # ======================================================
    # NOT A JSON DUMP
    # ======================================================

    assert_equal(
        history[
            "has_pre"
        ],
        0,
        (
            "The audit history must not be "
            "presented as raw JSON. That was the "
            "Phase 8.3 finding."
        ),
    )


    print(
        "[PASS] History is a readable timeline, not "
        "an audit JSON dump"
    )


    assert_true(
        "No audit history"
        in results[
            "history_empty"
        ][
            "text"
        ],
        (
            "A document with no audit events "
            "should say so."
        ),
    )


    # ======================================================
    # A HISTORY FAILURE IS ISOLATED
    # ======================================================

    isolated = results[
        "history_error_is_isolated"
    ]


    assert_true(
        isolated[
            "content_visible"
        ],
        (
            "A failed history read must not take "
            "the workspace down."
        ),
    )


    assert_true(
        isolated[
            "field_rows"
        ]
        > 0,
        (
            "The rest of the screen should still "
            "render."
        ),
    )


    assert_true(
        "HISTORY_LOAD_FAILED"
        in isolated[
            "history_text"
        ],
        (
            "The history panel should show the "
            "structured error."
        ),
    )


    assert_equal(
        isolated[
            "retry_buttons"
        ],
        1,
        (
            "The history panel should offer its own "
            "retry, so a reviewer does not have to "
            "reload the whole document."
        ),
    )


    print(
        "[PASS] A history failure is isolated to "
        "its own panel and retryable"
    )


    # ======================================================
    # RAW DATA IS SECONDARY
    # ======================================================

    raw = results[
        "raw_data_is_secondary"
    ]


    assert_equal(
        raw[
            "selected_on_load"
        ],
        "false",
        (
            "Raw JSON must never be the landing "
            "view."
        ),
    )


    assert_true(
        raw[
            "panel_hidden_on_load"
        ],
        (
            "The raw panel should start hidden."
        ),
    )


    assert_true(
        raw[
            "is_last_tab"
        ],
        (
            "Technical data belongs last."
        ),
    )


    assert_equal(
        raw[
            "first_tab"
        ],
        "tab-fields",
        (
            "The landing view should be the "
            "extracted data."
        ),
    )


    assert_true(
        raw[
            "contains_json"
        ],
        (
            "Raw data must still be available. "
            "Developers and reviewers genuinely "
            "need it."
        ),
    )


    print(
        "[PASS] Raw JSON is present, last, and "
        "never the default view"
    )


    # ======================================================
    # COPY AND DOWNLOAD
    # ======================================================

    export = results[
        "copy_and_download_json"
    ]


    assert_equal(
        export[
            "copied_count"
        ],
        1,
        (
            "Copy should write once to the "
            "clipboard."
        ),
    )


    assert_true(
        export[
            "copied_is_json"
        ],
        (
            "Copy should place the document JSON on "
            "the clipboard."
        ),
    )


    assert_true(
        "copied"
        in export[
            "status_after_copy"
        ]
        .lower(),
        (
            "A copy should be confirmed rather than "
            "happening invisibly."
        ),
    )


    assert_true(
        "downloaded"
        in export[
            "status_after_download"
        ]
        .lower(),
        (
            "A download should be confirmed."
        ),
    )


    # ==================================================
    # OBJECT URL LIFECYCLE
    # ==================================================
    #
    # The download builds a blob from data already in the page,
    # so no request is made and nothing is rendered
    # server-side. The URL is released immediately: the browser
    # has already taken the bytes, and holding a blob of
    # document data alive serves nothing.
    #
    # The download is measured as a DELTA rather than against a
    # running total. That mattered when the source image held a
    # live URL of its own; it no longer does (see below), but
    # measuring the delta is still the right shape -- it is the
    # download's own behaviour being asserted, not the page's
    # total.
    # ==================================================

    assert_equal(
        export[
            "download_created"
        ],
        1,
        (
            "Download should build exactly one blob "
            "from in-page data."
        ),
    )


    assert_equal(
        export[
            "download_revoked"
        ],
        1,
        (
            "The download URL should be revoked "
            "immediately after the click."
        ),
    )


    # ==================================================
    # PHASE 12.19 - NOTHING IS ALIVE ANY MORE
    # ==================================================
    #
    # This used to expect exactly ONE live object URL before
    # unload: the source image, held for as long as it was on
    # screen.
    #
    # The source image no longer uses an object URL at all.
    # It could not: the application's CSP is
    #
    #     img-src 'self' data:
    #
    # and a blob: URL is neither, so real Chrome blocked every
    # embedded document image. The panel now points the <img>
    # straight at the same-origin endpoint, which 'self'
    # already permits.
    #
    # So the expected count is zero, and that is strictly
    # better than one: the page holds no image bytes in
    # memory, and there is no URL whose revocation could race
    # a decode. The download still creates one and revokes it
    # immediately, which the two assertions above cover.
    assert_equal(
        export[
            "image_url_live_before_unload"
        ],
        0,
        (
            "No object URL should be alive. The source image "
            "is loaded from the same-origin endpoint "
            "directly -- a blob: URL is blocked by this "
            "application's own img-src policy -- and the "
            "download revokes its own URL on the click."
        ),
    )


    assert_true(
        export[
            "all_revoked_after_unload"
        ],
        (
            "Every object URL the page did create must be "
            "released. With the source image no longer "
            "creating one, this covers the download."
        ),
    )


    print(
        "[PASS] Copy and Download work from "
        "in-page data, and every object URL is "
        "revoked"
    )


# ==========================================================
# TEST 11 — HUMAN REVIEW STATES
# PHASE 8.13
# ==========================================================

def test_review_states(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 11 - HUMAN REVIEW STATES"
    )
    print("-" * 76)


    # ======================================================
    # ACTIONABLE
    # ======================================================

    actionable = results[
        "review_actionable"
    ]


    assert_true(
        actionable[
            "form_visible"
        ],
        (
            "A pending document with an authorised "
            "reviewer should offer the form."
        ),
    )


    assert_true(
        actionable[
            "completed_hidden"
        ]
        and actionable[
            "locked_hidden"
        ],
        (
            "Exactly one review state may be "
            "visible."
        ),
    )


    assert_equal(
        actionable[
            "buttons"
        ],
        {
            "approve": False,
            "correct": False,
            "reject": False,
            "submit_correction": True,
        },
        (
            "Approve, Correct and Reject should be "
            "offered; Submit Corrections belongs to "
            "correction mode."
        ),
    )


    # ==================================================
    # IDENTITY IS DISPLAYED, NOT REQUESTED
    # ==================================================

    assert_equal(
        actionable[
            "reviewer_name"
        ],
        "reviewer-7",
        (
            "The server-resolved reviewer should be "
            "displayed."
        ),
    )


    assert_equal(
        actionable[
            "reviewer_role"
        ],
        "REVIEWER",
        (
            "The role the server reported should be "
            "displayed."
        ),
    )


    assert_equal(
        actionable[
            "reviewer_source"
        ],
        "LOCAL_ENV",
        (
            "How the identity was verified should "
            "be displayed."
        ),
    )


    assert_true(
        "Review access granted"
        in actionable[
            "reviewer_access"
        ],
        (
            "can_review should be stated in words."
        ),
    )


    assert_true(
        "reviewer-card-authorized"
        in actionable[
            "card_classes"
        ],
        (
            "An authorised reviewer should be "
            "visually distinct from a read-only "
            "one."
        ),
    )


    assert_equal(
        actionable[
            "shell_reviewer"
        ],
        "reviewer-7",
        (
            "The sidebar should reuse the identity "
            "this page already loaded rather than "
            "fetching it again."
        ),
    )


    print(
        "[PASS] Actionable state offers 3 actions "
        "and displays the server-resolved identity"
    )


    # ======================================================
    # READ ONLY
    # ======================================================

    read_only = results[
        "review_read_only"
    ]


    assert_true(
        read_only[
            "form_hidden"
        ],
        (
            "A read-only reviewer must not be shown "
            "the form."
        ),
    )


    assert_true(
        read_only[
            "locked_visible"
        ],
        (
            "A read-only reviewer should be told "
            "why."
        ),
    )


    assert_true(
        "Read-only"
        in read_only[
            "locked_text"
        ],
        (
            "The explanation should name the "
            "reason."
        ),
    )


    assert_true(
        "reviewer-card-readonly"
        in read_only[
            "card_classes"
        ],
        (
            "Read-only access should be visually "
            "distinct."
        ),
    )


    print(
        "[PASS] Read-only access hides the form "
        "and explains why"
    )


    # ======================================================
    # UNAUTHENTICATED
    # ======================================================

    unauth = results[
        "review_unauthenticated"
    ]


    assert_true(
        unauth[
            "form_hidden"
        ]
        and unauth[
            "locked_visible"
        ],
        (
            "An unresolved identity must not offer "
            "a form."
        ),
    )


    assert_true(
        "authentication is required"
        in unauth[
            "locked_text"
        ]
        .lower(),
        (
            "The reviewer should be told that "
            "authentication is the problem."
        ),
    )


    assert_true(
        unauth[
            "reviewer_error_visible"
        ],
        (
            "The identity card should show the "
            "failure."
        ),
    )


    assert_true(
        "reviewer-card-error"
        in unauth[
            "card_classes"
        ],
        (
            "An unresolved identity should be "
            "visually distinct."
        ),
    )


    assert_true(
        unauth[
            "field_rows"
        ]
        > 0,
        (
            "A failed identity read must not hide "
            "the document. Reading a document is "
            "not a write."
        ),
    )


    print(
        "[PASS] An unresolved identity blocks the "
        "form but not the document"
    )


    # ======================================================
    # ALREADY REVIEWED — LOCKED
    # ======================================================

    completed = results[
        "review_completed_is_locked"
    ]


    assert_true(
        completed[
            "completed_visible"
        ],
        (
            "A completed review should be shown."
        ),
    )


    assert_true(
        completed[
            "form_hidden"
        ],
        (
            "One human review per document. A "
            "reviewed document must offer no form, "
            "which is the UI half of the database "
            "constraint."
        ),
    )


    assert_true(
        completed[
            "reviewer_section_hidden"
        ],
        (
            "There is nothing to authorise on a "
            "reviewed document."
        ),
    )


    assert_true(
        "Corrected"
        in completed[
            "action"
        ],
        (
            "The recorded decision should be "
            "named."
        ),
    )


    assert_equal(
        completed[
            "reviewer"
        ],
        "reviewer-7",
        (
            "The reviewer who decided should be "
            "named."
        ),
    )


    assert_true(
        "misread"
        in completed[
            "notes"
        ],
        (
            "The recorded notes should be shown."
        ),
    )


    # ==================================================
    # THE MACHINE VALUE SURVIVES BESIDE THE CORRECTION
    # ==================================================

    correction_rows = completed[
        "correction_rows"
    ]


    assert_equal(
        len(
            correction_rows
        ),
        1,
        (
            "One corrected field, one row."
        ),
    )


    labels = [
        cell[
            "label"
        ]
        for cell in correction_rows[
            0
        ][
            "cells"
        ]
    ]


    assert_equal(
        labels,
        [
            "Machine",
            "Corrected to",
        ],
        (
            "A completed correction must show what "
            "the machine read and what it was "
            "changed to."
        ),
    )


    print(
        "[PASS] A reviewed document is locked, and "
        "the machine reading survives beside the "
        "correction"
    )


    # ======================================================
    # AUTO ACCEPTED
    # ======================================================

    auto = results[
        "review_auto_accepted_is_locked"
    ]


    assert_true(
        auto[
            "form_hidden"
        ]
        and auto[
            "completed_hidden"
        ]
        and auto[
            "locked_visible"
        ],
        (
            "An auto-accepted document takes no "
            "human review."
        ),
    )


    assert_true(
        "No review required"
        in auto[
            "locked_text"
        ],
        (
            "The reason should be stated, and it "
            "should match the final-record rule: "
            "auto-accepted is already final."
        ),
    )


    print(
        "[PASS] Auto-accepted documents are locked "
        "with the correct reason"
    )


# ==========================================================
# TEST 12 — SUBMISSION
# ==========================================================

def test_submission(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 12 - REVIEW SUBMISSION"
    )
    print("-" * 76)


    approve = results[
        "approve_flow"
    ]


    # ======================================================
    # CONFIRMATION
    # ======================================================

    dialog = approve[
        "dialog"
    ]


    assert_true(
        dialog[
            "open"
        ],
        (
            "A review decision should be "
            "confirmed."
        ),
    )


    assert_true(
        "Approve this document"
        in dialog[
            "title"
        ],
        (
            "The confirmation should name the "
            "action."
        ),
    )


    assert_true(
        "becomes final"
        in dialog[
            "body"
        ],
        (
            "The confirmation should state what "
            "will happen, not just ask."
        ),
    )


    assert_equal(
        dialog[
            "focused"
        ],
        "confirm-cancel",
        (
            "Focus should enter the dialog on "
            "Cancel, so a stray Enter cannot "
            "record a decision."
        ),
    )


    assert_equal(
        dialog[
            "submissions_before"
        ],
        0,
        (
            "Nothing may be submitted before the "
            "reviewer confirms."
        ),
    )


    assert_false(
        approve[
            "dialog_still_open"
        ],
        (
            "The dialog should close after the "
            "decision."
        ),
    )


    assert_equal(
        approve[
            "focus_returned"
        ],
        "approve-button",
        (
            "Focus should return to the control "
            "that opened the dialog."
        ),
    )


    print(
        "[PASS] Confirmation names the action, "
        "states the consequence, focuses Cancel, "
        "and returns focus on close"
    )


    # ======================================================
    # CANCEL SUBMITS NOTHING
    # ======================================================

    cancelled = results[
        "approve_cancel_submits_nothing"
    ]


    assert_equal(
        cancelled[
            "submissions"
        ],
        0,
        (
            "Cancelling must submit nothing."
        ),
    )


    assert_false(
        cancelled[
            "dialog_open"
        ],
        (
            "Cancelling should close the dialog."
        ),
    )


    assert_equal(
        cancelled[
            "document_reads"
        ],
        1,
        (
            "Cancelling should not reload the "
            "document."
        ),
    )


    print(
        "[PASS] Cancelling submits nothing and "
        "reloads nothing"
    )


    # ======================================================
    # THE TRUST BOUNDARY
    # ======================================================

    payload = results[
        "payload_has_no_reviewer_id"
    ]


    assert_false(
        payload[
            "has_reviewer_id"
        ],
        (
            "The review payload must not carry a "
            "reviewer id. The backend resolves the "
            "reviewer itself, and sending one would "
            "be misleading about where authority "
            "lives."
        ),
    )


    assert_equal(
        sorted(
            payload[
                "keys"
            ]
        ),
        [
            "action",
            "notes",
        ],
        (
            "An approval sends the action and the "
            "notes, and nothing else."
        ),
    )


    assert_equal(
        payload[
            "action"
        ],
        "APPROVE",
        (
            "The action should reach the server."
        ),
    )


    assert_equal(
        payload[
            "notes"
        ],
        "Looks right to me.",
        (
            "Reviewer notes should reach the "
            "server."
        ),
    )


    print(
        "[PASS] The payload is action plus notes "
        "only; no reviewer id"
    )


    # ======================================================
    # AND IT RELOADS FROM THE SERVER
    # ======================================================

    assert_equal(
        approve[
            "document_reads"
        ],
        2,
        (
            "After a decision the document should "
            "be re-read. The final record is the "
            "backend's to compute, and only a "
            "reload proves what was stored."
        ),
    )


    assert_true(
        "Approved"
        in approve[
            "message"
        ],
        (
            "The outcome should be confirmed to the "
            "reviewer."
        ),
    )


    print(
        "[PASS] A recorded decision reloads from "
        "the server and is confirmed"
    )


    # ======================================================
    # DUPLICATE SUBMISSION
    # ======================================================

    duplicate = results[
        "duplicate_submission_blocked"
    ]


    during = duplicate[
        "during_flight"
    ]


    assert_equal(
        during[
            "submissions"
        ],
        1,
        (
            "The first confirmation should submit "
            "once."
        ),
    )


    for key in (
        "approve_disabled",
        "reject_disabled",
        "correct_disabled",
        "notes_disabled",
    ):

        assert_true(
            during[
                key
            ],
            (
                "Every review control should be "
                "disabled during a submission: "
                f"{key}"
            ),
        )


    assert_equal(
        during[
            "panel_busy"
        ],
        "true",
        (
            "The panel should announce that it is "
            "busy, not just look it."
        ),
    )


    assert_equal(
        duplicate[
            "total_submissions"
        ],
        1,
        (
            "Three further clicks during an "
            "in-flight submission must produce no "
            "further requests. The database rejects "
            "a duplicate with HTTP 409, which reads "
            "as a failure when it was a double tap."
        ),
    )


    print(
        "[PASS] 4 clicks produced exactly 1 "
        "submission, with every control disabled "
        "and aria-busy set"
    )


# ==========================================================
# TEST 13 — CORRECTIONS
# ==========================================================

def test_corrections(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 13 - CORRECTIONS"
    )
    print("-" * 76)


    flow = results[
        "correction_flow"
    ]


    opened = flow[
        "opened"
    ]


    # ======================================================
    # ONLY THE PERMITTED FIELDS
    # ======================================================

    # HumanReviewService.CORRECTABLE_FIELDS is a set, so the
    # backend defines WHICH fields, not their order.
    assert_equal(
        set(
            opened[
                "field_names"
            ]
        ),
        set(
            HumanReviewService.CORRECTABLE_FIELDS
        ),
        (
            "The correction form must offer exactly "
            "the fields HumanReviewService accepts. "
            "More would be rejected; fewer would be "
            "uncorrectable."
        ),
    )


    # The order is a UI decision, and it follows the canonical
    # field order so the form and the effective-values table
    # read the same way.
    assert_equal(
        opened[
            "field_names"
        ],
        list(
            FinalRecordService.FIELD_NAMES
        ),
        (
            "The correction form should follow the "
            "canonical field order, so it reads the "
            "same way as the effective record."
        ),
    )


    assert_equal(
        opened[
            "input_count"
        ],
        len(
            HumanReviewService.CORRECTABLE_FIELDS
        ),
        (
            "One control per correctable field."
        ),
    )


    print(
        f"[PASS] {opened['input_count']} editable "
        "fields, exactly the backend's correctable "
        "set"
    )


    # ======================================================
    # THE MACHINE READING STAYS VISIBLE
    # ======================================================

    assert_true(
        "SAMPLE,JANE"
        in opened[
            "machine_values"
        ],
        (
            "The machine reading must be shown "
            "beside its input, so a reviewer always "
            "sees what they are replacing."
        ),
    )


    assert_true(
        "Nothing"
        in opened[
            "machine_values"
        ],
        (
            "A field the machine did not read "
            "should say so rather than showing an "
            "empty label."
        ),
    )


    assert_true(
        "SAMPLE,JANE"
        in opened[
            "prefilled"
        ],
        (
            "The input should start from the "
            "machine value, so a reviewer changes "
            "rather than retypes."
        ),
    )


    assert_equal(
        opened[
            "focused"
        ],
        "correction-document_type",
        (
            "Opening correction mode should put a "
            "keyboard user where the work is."
        ),
    )


    print(
        "[PASS] Every input shows its machine "
        "reading, starts from it, and focus lands "
        "in the form"
    )


    # ======================================================
    # ONLY CHANGED FIELDS ARE SENT
    # ======================================================

    submission = flow[
        "submissions"
    ][
        0
    ]


    assert_equal(
        sorted(
            submission[
                "keys"
            ]
        ),
        [
            "action",
            "corrections",
            "notes",
        ],
        (
            "A correction sends the action, the "
            "notes and the corrections. No reviewer "
            "id."
        ),
    )


    assert_equal(
        submission[
            "payload"
        ][
            "corrections"
        ],
        {
            "licence_number": "87654321",
            # Cleared, not omitted.
            "issuer": None,
        },
        (
            "Only the fields the reviewer actually "
            "changed may be sent, and clearing a "
            "value must send null rather than "
            "dropping the key. Key presence is what "
            "distinguishes 'set to nothing' from "
            "'left alone'."
        ),
    )


    assert_equal(
        len(
            submission[
                "payload"
            ][
                "corrections"
            ]
        ),
        2,
        (
            "Six untouched fields must not appear "
            "in the payload."
        ),
    )


    assert_true(
        "Submit 2 corrections"
        in flow[
            "dialog_title"
        ],
        (
            "The confirmation should state how many "
            "values are being changed."
        ),
    )


    print(
        "[PASS] 2 of 8 fields changed produced a "
        "2-key payload, with a cleared field sent "
        "as null"
    )


    # ======================================================
    # NO CHANGE MEANS NO REQUEST
    # ======================================================

    unchanged = results[
        "correction_requires_a_change"
    ]


    assert_equal(
        unchanged[
            "submissions"
        ],
        0,
        (
            "Submitting an untouched correction "
            "form must not reach the server."
        ),
    )


    assert_false(
        unchanged[
            "dialog_open"
        ],
        (
            "There is nothing to confirm."
        ),
    )


    assert_true(
        "Change at least one value"
        in unchanged[
            "message"
        ],
        (
            "The reviewer should be told why "
            "nothing happened."
        ),
    )


    # ======================================================
    # CANCEL
    # ======================================================

    cancelled = results[
        "correction_cancel_restores_actions"
    ]


    assert_true(
        cancelled[
            "panel_hidden"
        ]
        and cancelled[
            "approve_visible"
        ]
        and cancelled[
            "submit_hidden"
        ],
        (
            "Cancelling correction mode should "
            "restore the three normal actions."
        ),
    )


    assert_equal(
        cancelled[
            "input_count"
        ],
        0,
        (
            "Cancelling should discard the inputs, "
            "so a stale edit cannot be submitted "
            "later."
        ),
    )


    assert_equal(
        cancelled[
            "submissions"
        ],
        0,
        (
            "Cancelling submits nothing."
        ),
    )


    assert_equal(
        cancelled[
            "focused"
        ],
        "correct-button",
        (
            "Cancelling should return focus to the "
            "control that opened correction mode."
        ),
    )


    print(
        "[PASS] An unchanged form sends nothing, "
        "and Cancel discards the inputs and "
        "returns focus"
    )


    # ======================================================
    # READ-ONLY CANNOT REACH A SUBMIT PATH
    # ======================================================
    #
    # Hiding a button is presentation. These call the module
    # directly, which is what an inspector-armed user could do.
    # ======================================================

    no_correct = results[
        "read_only_reviewer_cannot_open_corrections"
    ]


    assert_false(
        no_correct[
            "opened"
        ],
        (
            "A read-only reviewer must not be able "
            "to open correction mode even by "
            "calling the module directly."
        ),
    )


    assert_true(
        no_correct[
            "panel_hidden"
        ],
        (
            "The correction panel must stay closed."
        ),
    )


    no_submit = results[
        "read_only_reviewer_cannot_submit"
    ]


    assert_equal(
        no_submit[
            "submissions"
        ],
        0,
        (
            "A read-only reviewer must not reach a "
            "submission, even by calling the module "
            "directly. The backend enforces this "
            "too; the UI must not be the only "
            "gate."
        ),
    )


    assert_false(
        no_submit[
            "dialog_open"
        ],
        (
            "No confirmation should even open."
        ),
    )


    assert_true(
        "read-only access"
        in no_submit[
            "message"
        ]
        .lower(),
        (
            "The refusal should be explained."
        ),
    )


    print(
        "[PASS] A read-only reviewer cannot open "
        "corrections or submit, even calling the "
        "module directly"
    )


# ==========================================================
# TEST 14 — SUBMISSION ERRORS
# ==========================================================

def test_submission_errors(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 14 - SUBMISSION ERRORS"
    )
    print("-" * 76)


    # ======================================================
    # EVERY CODE THIS SCREEN CAN RECEIVE
    # ======================================================

    cases = {
        "error_already_reviewed": {
            "code": "DOCUMENT_ALREADY_REVIEWED",
            "request_id": "req-409",
            "guidance": "already been reviewed",
            "reloads": True,
        },
        "error_invalid_review": {
            "code": "INVALID_HUMAN_REVIEW",
            "request_id": "req-400",
            "guidance": "could not be accepted",
            "reloads": False,
        },
        "error_not_authorized": {
            "code": "REVIEWER_NOT_AUTHORIZED",
            "request_id": "req-403",
            "guidance": "not authorised",
            "reloads": False,
        },
        "error_authentication_required": {
            "code": "REVIEWER_AUTHENTICATION_REQUIRED",
            "request_id": "req-401",
            "guidance": "authentication is required",
            "reloads": False,
        },
    }


    for (
        name,
        expected,
    ) in cases.items():

        outcome = results[
            name
        ]


        message = outcome[
            "message"
        ]


        assert_true(
            expected[
                "guidance"
            ]
            in message,
            (
                f"{expected['code']} should be "
                "explained in language a reviewer "
                "can act on, not restated as a "
                f"code. Got: {message}"
            ),
        )


        assert_true(
            expected[
                "code"
            ]
            in message,
            (
                "The stable code should still be "
                "quotable for support: "
                f"{expected['code']}"
            ),
        )


        assert_true(
            expected[
                "request_id"
            ]
            in message,
            (
                "The request id should be quotable "
                "for support."
            ),
        )


        assert_true(
            outcome[
                "approve_enabled"
            ],
            (
                "A failed submission must re-enable "
                "the controls, or the reviewer is "
                "stuck."
            ),
        )


        assert_equal(
            outcome[
                "submissions"
            ],
            1,
            (
                "A failure must not retry by "
                "itself."
            ),
        )


    print(
        f"[PASS] All {len(cases)} named error codes "
        "are explained, keep their code and request "
        "id, and re-enable the controls"
    )


    # ======================================================
    # A LOST RACE RELOADS
    # ======================================================

    already = results[
        "error_already_reviewed"
    ]


    assert_equal(
        already[
            "document_reads"
        ],
        2,
        (
            "Losing the race to another reviewer "
            "should reload, so the completed review "
            "replaces the form."
        ),
    )


    # ======================================================
    # AN AUTHORISATION CHANGE RE-RESOLVES IDENTITY
    # ======================================================

    for name in (
        "error_not_authorized",
        "error_authentication_required",
    ):

        assert_equal(
            results[
                name
            ][
                "reviewer_reads"
            ],
            2,
            (
                "An authorisation failure should "
                "re-resolve the identity from the "
                "server, so the panel reflects the "
                "reviewer's real access."
            ),
        )


    print(
        "[PASS] A lost race reloads the document; "
        "an authorisation failure re-resolves "
        "identity"
    )


    # ======================================================
    # AN UNKNOWN CODE STILL PRODUCES A USABLE MESSAGE
    # ======================================================

    unknown = results[
        "error_unknown_code"
    ]


    assert_true(
        "SOMETHING_UNEXPECTED"
        in unknown[
            "message"
        ],
        (
            "An unmapped code should be surfaced "
            "rather than swallowed."
        ),
    )


    assert_true(
        "req-500"
        in unknown[
            "message"
        ],
        (
            "The request id should be available for "
            "any failure."
        ),
    )


    assert_false(
        "traceback"
        in unknown[
            "message"
        ]
        .lower(),
        (
            "The UI must never imply a stack "
            "trace."
        ),
    )


    print(
        "[PASS] An unmapped error code still "
        "produces a usable, traceable message"
    )


# ==========================================================
# TEST 15 — LOAD FAILURES
# ==========================================================

def test_load_failures(
    results: dict,
):

    print()
    print("-" * 76)
    print(
        "TEST 15 - LOAD FAILURES"
    )
    print("-" * 76)


    failure = results[
        "document_load_error"
    ]


    assert_true(
        failure[
            "error_visible"
        ]
        and failure[
            "content_hidden"
        ]
        and failure[
            "loading_hidden"
        ],
        (
            "A failed document read should replace "
            "the workspace with an error."
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
            failure[
                key
            ],
            (
                "The error should surface "
                f"{description}. The Phase 7B "
                "screen read only the legacy "
                "top-level detail field."
            ),
        )


    assert_false(
        failure[
            "mentions_traceback"
        ],
        (
            "No stack trace, real or implied."
        ),
    )


    assert_equal(
        failure[
            "retry_buttons"
        ],
        1,
        (
            "A failed load should be retryable."
        ),
    )


    print(
        "[PASS] A failed load shows the structured "
        "contract and offers one retry"
    )


    # ======================================================
    # A DOCUMENT WITH NO ANALYSIS
    # ======================================================

    no_analysis = results[
        "document_without_analysis"
    ]


    assert_true(
        no_analysis[
            "content_visible"
        ],
        (
            "A document whose processing failed "
            "should still open. The reviewer needs "
            "to see that it failed."
        ),
    )


    for key, needle in (
        (
            "fields_text",
            "No extraction is stored",
        ),
        (
            "validation_text",
            "No validation record",
        ),
        (
            "final_text",
            "No final record",
        ),
    ):

        assert_true(
            needle
            in no_analysis[
                key
            ],
            (
                "A document with no analysis should "
                "say what is missing rather than "
                f"rendering blank: {needle}"
            ),
        )


    assert_true(
        "Not available for review"
        in no_analysis[
            "locked_text"
        ],
        (
            "A document with no analysis is not a "
            "review target."
        ),
    )


    print(
        "[PASS] A document with no analysis opens "
        "and explains every gap"
    )


# ==========================================================
# TEST 16 — SAFETY, PRIVACY, ACCESSIBILITY
# ==========================================================

def test_safety_and_accessibility(
    results: dict,
    client: TestClient,
):

    print()
    print("-" * 76)
    print(
        "TEST 16 - SAFETY AND ACCESSIBILITY"
    )
    print("-" * 76)


    # ======================================================
    # UNTRUSTED CONTENT
    # ======================================================
    #
    # OCR text, extracted values, reviewer notes, filenames and
    # actor ids all originate outside the system. The Phase 7B
    # screen interpolated all of them into innerHTML behind a
    # hand-written escaper.
    #
    # The DOM stub throws on ANY innerHTML assignment, so these
    # checks could not pass if the modules wrote markup.
    # ======================================================

    hostile = results[
        "hostile_content_is_text"
    ]


    for key, description in (
        (
            "filename_literal",
            "a filename",
        ),
        (
            "ocr_literal",
            "OCR text",
        ),
        (
            "notes_literal",
            "reviewer notes",
        ),
        (
            "value_literal",
            "an extracted value",
        ),
    ):

        assert_true(
            hostile[
                key
            ],
            (
                f"A hostile {description} should "
                "survive as literal text."
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
            "svg_elements",
            "an svg",
        ),
        (
            "b_elements",
            "a bold",
        ),
        (
            "i_elements",
            "an italic",
        ),
    ):

        assert_equal(
            hostile[
                key
            ],
            0,
            (
                "Untrusted document content must "
                f"never create {description} "
                "element."
            ),
        )


    print(
        "[PASS] Hostile filename, OCR text, notes "
        "and values all render as text and create "
        "no element"
    )


    # ======================================================
    # NO CLIENT-SUPPLIED IDENTITY
    # ======================================================

    identity = results[
        "no_reviewer_identity_input"
    ]


    assert_false(
        identity[
            "has_reviewer_id_input"
        ],
        (
            "The legacy editable reviewer ID must "
            "not exist."
        ),
    )


    # ==================================================
    # EVERY INPUT ON THE PAGE IS ACCOUNTED FOR
    # ==================================================
    #
    # The only input outside correction mode is the evidence
    # highlight toggle, and the only textarea is the notes
    # field. Neither can state who the reviewer is.
    # ==================================================

    input_ids = sorted(
        entry[
            "id"
        ]
        for entry in identity[
            "inputs"
        ]
    )


    assert_equal(
        input_ids,
        [
            "highlight-toggle",
        ],
        (
            "An unexpected input exists on the "
            "workspace. Every control here must be "
            "accounted for, because an input is how "
            "a browser could try to assert an "
            f"identity. Found: {input_ids}"
        ),
    )


    assert_equal(
        identity[
            "textareas"
        ],
        [
            "review-notes",
        ],
        (
            "The only free-text field is the "
            "reviewer notes."
        ),
    )


    print(
        "[PASS] The only input is the evidence "
        "toggle and the only textarea is notes; "
        "identity cannot be asserted by the browser"
    )


    # ======================================================
    # DOCUMENT ID
    # ======================================================

    ids = results[
        "document_id_from_path"
    ]


    assert_equal(
        ids[
            "id"
        ],
        "doc-workspace-1",
        (
            "The document id should be read from "
            "the path the server served."
        ),
    )


    # ======================================================
    # STATIC AUDIT OF EVERY MODULE
    # ======================================================

    for module in WORKSPACE_MODULES:

        source = (
            client.get(
                module
            )
            .text
        )


        problems = (
            audit_frontend_module(
                source,
                module,
                # The shared client is the one place
                # fetch belongs.
                allow_fetch=module.endswith(
                    "js/api.js"
                ),
            )
        )


        assert_equal(
            problems,
            [],
            (
                f"{module} failed the shared "
                "frontend audit."
            ),
        )


    print(
        f"[PASS] All {len(WORKSPACE_MODULES)} "
        "modules pass the frontend audit: no "
        "unsafe sink, no console logging, no raw "
        "fetch outside the client, no secrets"
    )


    # ======================================================
    # THE HAND-ROLLED ESCAPER IS GONE
    # ======================================================

    controller = (
        strip_js_comments(
            client.get(
                "/review/static/review_detail.js"
            )
            .text
        )
    )


    assert_false(
        "escapeHtml"
        in controller,
        (
            "The hand-written HTML escaper is no "
            "longer needed. Building nodes and "
            "assigning textContent needs no "
            "escaping, and keeping an escaper "
            "invites someone to reach for innerHTML "
            "again."
        ),
    )


    print(
        "[PASS] The hand-rolled HTML escaper is "
        "gone"
    )


    # ======================================================
    # ACCESSIBILITY MARKUP
    # ======================================================

    markup = (
        client.get(
            WORKSPACE_ROUTE
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
            "live review status",
            'aria-live="polite"',
        ),
        (
            "native dialog",
            "<dialog",
        ),
        (
            "dialog label",
            'aria-labelledby="confirm-title"',
        ),
        (
            "dialog description",
            'aria-describedby="confirm-body"',
        ),
        (
            "notes label",
            'for="review-notes"',
        ),
        (
            "highlight toggle label",
            'class="switch"',
        ),
    ):

        assert_true(
            needle in markup,
            (
                "The workspace is missing the "
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


    # ==================================================
    # A NATIVE DIALOG, NOT A DIV
    # ==================================================
    #
    # Focus containment, Escape and the backdrop come from the
    # platform. A div-based modal would have to reimplement all
    # three, and usually gets one of them wrong.
    # ==================================================

    assert_false(
        'role="dialog"'
        in markup,
        (
            "A native <dialog> needs no role, and a "
            "div carrying one would mean the modal "
            "was hand-built."
        ),
    )


    print(
        "[PASS] Landmarks, one h1, labelled "
        "controls, and a native dialog rather than "
        "a div"
    )


    # ======================================================
    # RESPONSIVE
    # ======================================================

    responsive = (
        client.get(
            "/review/static/css/responsive.css"
        )
        .text
    )


    for selector, description in (
        (
            ".workspace-source",
            "the sticky source panel must stop "
            "being sticky on a tablet",
        ),
        (
            ".value-row",
            "the machine / correction / effective "
            "row must stack on a phone",
        ),
        (
            ".tablist",
            "the tab strip must remain reachable on "
            "a narrow screen",
        ),
        (
            ".raw-json",
            "the raw JSON block must be bounded on "
            "a small screen",
        ),
    ):

        assert_true(
            selector in responsive,
            (
                "Responsive rule missing: "
                f"{description} ({selector})"
            ),
        )


    workspace_css = (
        client.get(
            "/review/static/css/workspace.css"
        )
        .text
    )


    # ==================================================
    # LONG VALUES MUST NOT PUSH THE PAGE SIDEWAYS
    # ==================================================

    assert_true(
        "overflow-wrap: anywhere"
        in workspace_css,
        (
            "An OCR value can be a long unbroken "
            "string. It must wrap rather than force "
            "the page to scroll horizontally."
        ),
    )


    assert_true(
        "position: sticky"
        in workspace_css,
        (
            "The source document should follow the "
            "reviewer down the extracted values on "
            "desktop."
        ),
    )


    print(
        "[PASS] Responsive rules cover the sticky "
        "panel, value rows, tabs and raw JSON; long "
        "values wrap"
    )


# ==========================================================
# MAIN
# ==========================================================

# ==========================================================
# PHASE 12.18 - A 200 THAT DOES NOT DECODE
# ==========================================================
#
# RELEASE BLOCKER 2, CASE B.
#
# Two failure shapes reach this panel and only one of them was
# handled.
#
#   CASE A  the request fails -- 404
#           ORIGINAL_DOCUMENT_NOT_AVAILABLE. api.js rejects it,
#           .catch() runs, the clean unavailable state appears.
#           This always worked and is covered above.
#
#   CASE B  the request SUCCEEDS and the bytes do not decode.
#           Nothing rejects. The old code had already set src
#           and cleared `hidden`, so the browser painted its
#           broken-image icon and the alt text -- and there was
#           no error listener anywhere in source_panel to
#           notice.
#
# The backend is not at fault: it returns a real FileResponse
# or a clean 404. Nor is api.js, which rejects every non-2xx.
# The gap was treating "the fetch resolved" as "the picture is
# on screen". Those are different claims.
# ==========================================================

def test_undecodable_image(
    results: dict,
) -> None:

    print()
    print("-" * 76)
    print(
        "TEST 17 - A 200 WHOSE BYTES DO NOT DECODE SHOWS THE "
        "UNAVAILABLE STATE, NOT A BROKEN IMAGE"
    )
    print("-" * 76)

    outcome = results[
        "undecodable_image_shows_unavailable_not_broken"
    ]

    # ------------------------------------------------------
    # THE BROKEN IMAGE MUST NOT SURVIVE
    # ------------------------------------------------------

    assert_true(
        outcome["image_hidden"],
        (
            "An image whose bytes did not decode must be "
            "hidden. Leaving it visible is precisely the "
            "browser broken-image icon the release brief "
            "rules out."
        ),
    )

    assert_true(
        outcome["image_src_cleared"],
        (
            "The unusable src must be dropped as well. A "
            "hidden element still holding a bad src is one "
            "stylesheet change away from being visible "
            "again."
        ),
    )

    assert_true(
        outcome["unavailable_visible"],
        (
            "The professional unavailable state must take "
            "its place."
        ),
    )

    assert_true(
        "ORIGINAL_DOCUMENT_UNREADABLE"
        in outcome["unavailable_text"],
        (
            "The state should carry a distinct code, so a "
            "decode failure is distinguishable from a missing "
            "file in a support conversation.\n"
            f"got: {outcome['unavailable_text']!r}"
        ),
    )

    print(
        "[PASS] an undecodable 200 hides the image, clears "
        "its src and shows the unavailable state as "
        "ORIGINAL_DOCUMENT_UNREADABLE"
    )

    # ------------------------------------------------------
    # NO STORAGE PATH LEAKS INTO THE MESSAGE
    # ------------------------------------------------------

    lowered = outcome["unavailable_text"].lower()

    for leak in (
        "storage",
        "/data/",
        "c:\\",
        ".jpg",
        ".png",
    ):

        assert_true(
            leak not in lowered,
            (
                "The unavailable state must not expose a "
                f"path or filename (found {leak!r}).\n"
                f"text: {outcome['unavailable_text']!r}"
            ),
        )

    print(
        "[PASS] the unavailable state names no path, no "
        "filename and no storage location"
    )

    # ------------------------------------------------------
    # EVIDENCE STANDS DOWN
    # ------------------------------------------------------

    assert_equal(
        outcome["overlay_boxes"],
        0,
        (
            "No evidence box may be drawn against an image "
            "that is not there."
        ),
    )

    assert_true(
        outcome["toggle_disabled"],
        (
            "Show evidence must be disabled. Leaving it live "
            "next to an unavailable document offers an action "
            "that cannot be honoured, which reads as a broken "
            "feature rather than an absent image."
        ),
    )

    assert_false(
        outcome["toggle_checked"],
        (
            "It should also be unchecked, so the control "
            "does not imply highlighting is on."
        ),
    )

    print(
        "[PASS] no box is drawn and Show evidence is "
        "disabled and cleared"
    )

    # ------------------------------------------------------
    # THE PAGE IS STILL USABLE
    # ------------------------------------------------------

    assert_true(
        outcome["content_visible"],
        (
            "A missing picture is not a page failure."
        ),
    )

    assert_true(
        outcome["field_rows"] > 0,
        (
            "The reviewer must still be able to read the "
            f"extracted values (got "
            f"{outcome['field_rows']} rows)."
        ),
    )

    print(
        f"[PASS] the workspace stays usable: "
        f"{outcome['field_rows']} field rows still render"
    )


def test_decoded_image_still_works(
    results: dict,
) -> None:

    print()
    print("-" * 76)
    print(
        "TEST 18 - A DECODED IMAGE IS STILL SHOWN AND STILL "
        "TAKES EVIDENCE"
    )
    print("-" * 76)

    # ------------------------------------------------------
    # The other half of the change.
    #
    # A fix that hid a working image, or that stopped evidence
    # drawing, would be worse than the defect it replaced. The
    # panel now waits for a decode before revealing the
    # element, so this asserts the success path still reaches
    # the end.
    # ------------------------------------------------------

    outcome = results[
        "decoded_image_is_shown_and_evidence_works"
    ]

    assert_true(
        outcome["image_visible"],
        (
            "An image that decoded must be visible. Waiting "
            "for the decode must not mean never revealing it."
        ),
    )

    assert_true(
        outcome["image_has_src"],
        "It must keep its object URL.",
    )

    assert_equal(
        outcome["natural_width"],
        600,
        (
            "The intrinsic size must be readable once the "
            "decode reported, since every box is a percentage "
            "of it."
        ),
    )

    assert_true(
        outcome["unavailable_hidden"],
        (
            "The unavailable state must not be showing at "
            "the same time as the image."
        ),
    )

    assert_false(
        outcome["toggle_disabled"],
        (
            "Show evidence must stay available when there is "
            "an image to point at."
        ),
    )

    assert_true(
        outcome["overlay_boxes"] > 0,
        (
            "Evidence highlighting must still draw. This is "
            "the regression that would matter most: a "
            "reviewer checking a value against the document "
            f"is the product (got "
            f"{outcome['overlay_boxes']} boxes)."
        ),
    )

    print(
        f"[PASS] a decoded 600px image is revealed, keeps its "
        f"object URL, and draws {outcome['overlay_boxes']} "
        "evidence box(es)"
    )


# ==========================================================
# PHASE 12.19 - THE IMAGE URL MUST BE ONE CSP PERMITS
# ==========================================================
#
# THE RELEASE BLOCKER THIS CLOSES.
#
# The panel fetched the image and handed the browser a blob:
# URL. The application's own header is
#
#     img-src 'self' data:
#
# and blob: is neither, so real Chrome blocked every embedded
# document image:
#
#     Loading the image 'blob:http://127.0.0.1/...' violates
#     the following Content Security Policy directive:
#     "img-src 'self' data:". The action has been blocked.
#
# Every layer beneath was healthy. The endpoint returned 200
# with a decodable JPEG, which is why opening the same URL in
# a browser tab worked perfectly -- a top-level navigation is
# not subject to img-src. Only the <img> was blocked.
#
# The blocked load fires `error`, so the panel then correctly
# reported "the original document is not available". It was
# telling the truth about its own situation and being wrong
# about the document.
#
# The fix removes the blob entirely: the element points at the
# same-origin endpoint, which 'self' already permits. That
# needed NO CSP change, which is strictly better than adding
# blob: to the policy to make a detour work.
#
# So the scheme of the assigned src is not a detail. It is the
# bug, and it is asserted here in two independent ways: what
# the running module assigns, and what the source is even
# capable of assigning.
# ==========================================================

def test_image_url_is_csp_loadable(
    results: dict,
    client,
) -> None:

    print()
    print("-" * 76)
    print(
        "TEST 19 - THE IMAGE SRC IS A SCHEME THE PAGE'S OWN "
        "CSP PERMITS"
    )
    print("-" * 76)

    outcome = results["image_src_is_csp_loadable"]

    # ------------------------------------------------------
    # WHAT THE RUNNING MODULE ASSIGNS
    # ------------------------------------------------------

    assert_true(
        outcome["is_same_origin_path"],
        (
            "The src must be a same-origin path so img-src "
            f"'self' covers it. Got {outcome['src']!r}"
        ),
    )

    assert_false(
        outcome["is_blob"],
        (
            "The src must not be a blob: URL. img-src "
            "'self' data: does not permit blob:, and this is "
            "exactly the failure that hid every document "
            "image while the endpoint itself was healthy."
        ),
    )

    assert_false(
        outcome["is_absolute_other_origin"],
        (
            "The src must not be an absolute URL to another "
            "origin."
        ),
    )

    assert_true(
        outcome["names_the_document"],
        (
            "The src must address the document's own image "
            f"endpoint. Got {outcome['src']!r}"
        ),
    )

    print(
        f"[PASS] the panel assigns {outcome['src']!r} -- a "
        "same-origin path, not a blob"
    )

    # ------------------------------------------------------
    # AND THE POLICY REALLY DOES PERMIT IT
    # ------------------------------------------------------
    #
    # Asserted against the header the server actually sends,
    # not against a copy of it in a test.

    response = client.get(
        "/health"
    )

    policy = response.headers.get(
        "content-security-policy",
        "",
    )

    directive = ""

    for part in policy.split(
        ";"
    ):

        if part.strip().startswith(
            "img-src"
        ):
            directive = part.strip()

    assert_true(
        directive,
        (
            "The response must carry an img-src directive, or "
            "this test is asserting against nothing.\n"
            f"policy: {policy!r}"
        ),
    )

    assert_true(
        "'self'" in directive,
        (
            f"img-src must permit 'self'. Got {directive!r}"
        ),
    )

    # The point: the policy does NOT permit blob:, so the old
    # mechanism could never have worked.
    assert_false(
        "blob:" in directive,
        (
            "This assertion is deliberately inverted. If "
            "blob: has been ADDED to img-src, then the CSP "
            "was widened to accommodate a detour the panel no "
            "longer takes -- remove it rather than keeping "
            "both.\n"
            f"Got {directive!r}"
        ),
    )

    print(
        f"[PASS] the served policy is {directive!r}: it "
        "permits the path used and still does not permit "
        "blob:"
    )

    # ------------------------------------------------------
    # THE SOURCE CANNOT GO BACK
    # ------------------------------------------------------
    #
    # The running check above proves what happens with this
    # harness's configuration. This proves the module has no
    # code path that could produce a blob URL for the image at
    # all.

    source = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "js"
        / "workspace"
        / "source_panel.js"
    ).read_text(
        encoding="utf-8",
    )

    creating = [
        line.strip()
        for line in source.splitlines()
        if "createObjectURL" in line
        and not line.strip().startswith(
            "*"
        )
        and not line.strip().startswith(
            "/*"
        )
        and not line.strip().startswith(
            "//"
        )
    ]

    assert_equal(
        creating,
        [],
        (
            "source_panel must not create an object URL. The "
            "image loads from the same-origin endpoint, and a "
            "blob: URL is blocked by the page's own CSP."
        ),
    )

    print(
        "[PASS] source_panel.js contains no createObjectURL "
        "call outside comments, so the blocked mechanism "
        "cannot return"
    )

    # ------------------------------------------------------
    # EVIDENCE UNLOCKS ON LOAD
    # ------------------------------------------------------

    assert_true(
        outcome["image_visible"],
        "A loaded image must be visible.",
    )

    assert_equal(
        outcome["natural_width"],
        506,
        (
            "The intrinsic width must be readable after the "
            "load, since every evidence box is a percentage "
            "of it."
        ),
    )

    assert_false(
        outcome["toggle_disabled"],
        (
            "Show evidence must be ENABLED once the image has "
            "loaded. showUnavailable disables it, so a "
            "successful load has to hand it back -- "
            "otherwise a document whose first load failed "
            "would never regain highlighting."
        ),
    )

    print(
        "[PASS] a loaded 506px image is visible and re-enables "
        "Show evidence"
    )


def main():

    print("=" * 76)
    print(
        "PHASE 8.10-8.14 — ADVANCED DOCUMENT "
        "WORKSPACE"
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
        f"[OK] {len(results)} workspace checks "
        "executed under Node with a real parsed "
        "page"
    )


    client = None


    try:

        client = TestClient(
            app
        )

        client.__enter__()


        test_route_and_modules(
            client
        )

        test_request_budget(
            results
        )

        test_summary_surfaces(
            results
        )

        test_tabs(
            results,
            client,
        )

        test_fields_and_evidence(
            results
        )

        test_evidence_highlighting(
            results
        )

        test_validation_and_expiry(
            results
        )

        test_findings(
            results
        )

        test_final_record(
            results
        )

        test_history_and_raw(
            results
        )

        test_review_states(
            results
        )

        test_submission(
            results
        )

        test_corrections(
            results
        )

        test_submission_errors(
            results
        )

        test_load_failures(
            results
        )

        test_undecodable_image(
            results
        )

        test_decoded_image_still_works(
            results
        )

        test_image_url_is_csp_loadable(
            results,
            client,
        )

        test_safety_and_accessibility(
            results,
            client,
        )


        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 8.10-8.14 DOCUMENT "
            "WORKSPACE TEST PASSED"
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
