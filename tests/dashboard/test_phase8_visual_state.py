import json
import shutil
import subprocess

from pathlib import Path


# ==========================================================
# PHASE 8 FINAL VISUAL QA
# COMPUTED-VISIBILITY STATE GATE
# ==========================================================
#
# This suite exists because of a defect that the whole
# Phase 8 test set -- 272 asserted properties, 134 executed
# behavioural checks, 49 green regressions -- passed straight
# through, and that a person found in about thirty seconds by
# opening Chrome.
#
# The upload page rendered "Analysis in progress", "Document
# analyzed successfully" and "Analysis failed" at the same
# time, above a file card whose <img> had no src and so drew
# the broken-image icon, with "Analyze Document" and "Try
# Again" side by side. The document workspace offered
# Approve, Correct, Reject and Submit Corrections at once.
#
# None of it was a JavaScript bug. applyState() set the hidden
# attribute on exactly the right elements in exactly the right
# combinations, and every test that asked element.hidden got
# the right answer.
#
# The bug was one missing CSS rule. The browser's own
# stylesheet says [hidden] { display: none }, but an author
# rule that sets display outranks it -- author styles beat the
# user-agent origin regardless of specificity. The hidden
# elements carry .btn, .alert, .file-card, .processing-panel,
# .drop-zone and img, and every one of those sets display. So
# hidden was inert on precisely the elements that depended on
# it, and no test could tell, because they were all asking the
# wrong question.
#
# The lesson is the point of this file. "Did the JavaScript
# set hidden" and "can the user see it" are different
# questions, and only the second one is the product.
#
# So tests/dashboard/css_engine.js resolves the display
# property through the real shipped stylesheets -- cascade
# origin, !important, specificity, source order and
# width-based media queries -- and every assertion below is
# about what would be painted, at six viewport widths, on
# every page.
#
# Two independent bugs were found by this harness while it was
# being written, after the CSS rule was already fixed:
#
#   1. applyState() hid Analyze only in SUCCESS, so ERROR
#      genuinely did offer Analyze and Try Again together.
#      That half of the reported symptom was a real
#      JavaScript bug hiding behind the CSS one.
#
#   2. One of this file's own rules was wrong: it counted
#      visible submit controls and would have failed the
#      correct design, because Approve and Reject are two
#      different decisions and are both meant to be offered.
#      The real invariant is narrower -- Submit Corrections
#      must never appear beside them.
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)

HARNESS = (
    PROJECT_ROOT
    / "tests"
    / "dashboard"
    / "visibility_harness.js"
)

CSS_ENGINE = (
    PROJECT_ROOT
    / "tests"
    / "dashboard"
    / "css_engine.js"
)


# The set of !important declarations that are allowed to
# exist. Pinned so a new one has to be added here
# deliberately, with a reason, rather than accumulating.
#
#   base.css [hidden]           the rule this suite is about
#   base.css reduced motion     4 declarations, accessibility
#   base.css print              hides chrome when printing
#   components.css is-pending   hides label under a spinner
ALLOWED_IMPORTANT = 7


EXPECTED_WIDTHS = 6

EXPECTED_PAGES = 5


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
                "Node is required to resolve the CSS "
                "cascade against the shipped "
                "stylesheets. Without it this suite "
                "could only assert that a rule exists "
                "in a file, which is what the previous "
                "suites did, and is how the defect "
                "shipped."
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
                "Visibility harness failed to run.\n"
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
            and "harness_error" in value
        ):

            raise AssertionError(
                (
                    f"Harness check {name} raised:\n"
                    f"{value['harness_error']}"
                )
            )


    print(
        (
            "[PASS] every visibility check ran "
            "without a harness error"
        )
    )


# ==========================================================
# 1. THE ENGINE ITSELF
# ==========================================================
#
# A test whose engine is wrong is worse than no test, so the
# engine's own claims are checked before anything is asserted
# with it.
# ==========================================================

def test_engine_present():

    if not CSS_ENGINE.exists():

        raise AssertionError(
            (
                "tests/dashboard/css_engine.js is "
                "missing. Every assertion in this "
                "suite resolves display through it."
            )
        )


    source = (
        CSS_ENGINE.read_text(
            encoding="utf-8",
        )
    )


    # The engine must model the user-agent [hidden] rule.
    # Without it, a plain <div hidden> with no component class
    # reads as painted, which would have reported every hidden
    # element on every page as broken instead of the five that
    # actually were.
    if "node.hidden === true" not in source:

        raise AssertionError(
            (
                "css_engine.js must model the "
                "user-agent [hidden] rule, or it "
                "over-reports every hidden element."
            )
        )


    for marker in (
        "important",
        "specificity",
        "mediaMatches",
    ):

        if marker not in source:

            raise AssertionError(
                (
                    "css_engine.js must model "
                    f"{marker}: the defect turned "
                    "entirely on cascade order."
                )
            )


    print(
        (
            "[PASS] the display cascade models origin, "
            "!important, specificity and media width"
        )
    )


def test_engine_coverage(
    results: dict,
):

    static = results["static_hidden_never_painted"]


    if static["widths"] != EXPECTED_WIDTHS:

        raise AssertionError(
            (
                "Expected "
                f"{EXPECTED_WIDTHS} viewport widths, "
                f"got {static['widths']}."
            )
        )


    if static["pages"] != EXPECTED_PAGES:

        raise AssertionError(
            (
                f"Expected {EXPECTED_PAGES} pages, "
                f"got {static['pages']}."
            )
        )


    # A suite that checks nothing passes. The count is
    # asserted so that a page losing its hidden elements, or
    # loadPage silently returning an empty tree, is a failure
    # rather than a green run.
    if static["elements_checked"] < 100:

        raise AssertionError(
            (
                "Only "
                f"{static['elements_checked']} hidden "
                "elements were examined across "
                f"{EXPECTED_PAGES} pages at "
                f"{EXPECTED_WIDTHS} widths. That is too "
                "few to be real -- the page tree is "
                "probably not being built."
            )
        )


    print(
        (
            "[PASS] "
            f"{static['elements_checked']} hidden "
            f"elements examined across "
            f"{static['pages']} pages at "
            f"{static['widths']} widths"
        )
    )


# ==========================================================
# 2. NOTHING MARKED HIDDEN MAY BE PAINTED
# ==========================================================

def test_static_hidden_never_painted(
    results: dict,
):

    leaks = (
        results["static_hidden_never_painted"]["leaks"]
    )


    if leaks:

        detail = "\n\n".join(
            (
                f"  {leak['page']} @ {leak['width']}px  "
                f"{leak['element']}\n"
                f"    {leak['why']}"
            )
            for leak in leaks[:8]
        )

        raise AssertionError(
            (
                f"{len(leaks)} element(s) carry the "
                "hidden attribute and would still be "
                "painted. This is the defect that shipped "
                "to a real browser.\n\n"
                f"{detail}"
            )
        )


    print(
        (
            "[PASS] no element marked hidden is "
            "painted on any page at any width"
        )
    )


def test_hidden_rule_is_load_bearing(
    results: dict,
):

    rule = results["hidden_rule_wins"]


    if not rule["hidden_rule_found"]:

        raise AssertionError(
            (
                "No [hidden] rule in any stylesheet. "
                "The browser's own rule is not enough: "
                "every author display declaration beats "
                "it."
            )
        )


    if not rule["hidden_rule_important"]:

        raise AssertionError(
            (
                "The [hidden] rule exists but is not "
                "!important, so it does nothing. "
                "[hidden] and .btn have identical "
                "specificity -- one class each -- and "
                "base.css is linked before "
                "components.css, so .btn wins on source "
                "order and the attribute is inert."
            )
        )


    # The reasoning above, asserted rather than asserted-in-a-
    # comment, so it stays true if the stylesheet order or the
    # selectors change.
    if not rule["same_specificity"]:

        raise AssertionError(
            (
                "[hidden] and .btn no longer have equal "
                "specificity. Re-derive whether "
                "!important is still required before "
                "changing this."
            )
        )


    if not rule["hidden_declared_before_btn"]:

        raise AssertionError(
            (
                "[hidden] is no longer declared before "
                ".btn. It still needs !important, but "
                "the reason recorded here is now wrong."
            )
        )


    if rule["resolved"] != "none":

        raise AssertionError(
            (
                "A hidden .btn resolves to display:"
                f"{rule['resolved']}, not none."
            )
        )


    if rule["hidden_rule_source"] != "css/base.css":

        raise AssertionError(
            (
                "The [hidden] rule should live in "
                "base.css with the rest of the "
                "foundation, not in "
                f"{rule['hidden_rule_source']}."
            )
        )


    print(
        (
            "[PASS] [hidden] beats .btn only because it "
            "is !important, and that is asserted, not "
            "assumed"
        )
    )


# ==========================================================
# 3. THE UPLOAD STATE MACHINE
# ==========================================================
#
# IDLE -> SELECTED -> ANALYZING -> SUCCESS | ERROR.
#
# Exactly one outcome region may be painted, and a visible
# <img> must have a source.
# ==========================================================

def test_upload_states_are_exclusive(
    results: dict,
):

    exclusivity = results["upload_state_exclusivity"]


    if exclusivity["violations"]:

        raise AssertionError(
            (
                "The upload page paints more than one "
                "state at once, or shows a sourceless "
                "image:\n"
                f"{json.dumps(exclusivity['violations'], indent=2)}"
            )
        )


    observed = exclusivity["observed"]


    # The states are asserted positively as well, so that a
    # page which paints nothing at all cannot pass an
    # exclusivity check by being empty.
    expected = {
        "idle": "drop_zone",
        "selected": "file_card",
        "analyzing": "processing",
    }


    for (
        state,
        region,
    ) in expected.items():

        for key in observed:

            if not key.startswith(
                state + "@"
            ):
                continue


            if not observed[key][region]:

                raise AssertionError(
                    (
                        f"In {key} the {region} region "
                        "is not painted, so the state "
                        "renders as nothing at all."
                    )
                )


    print(
        (
            "[PASS] IDLE, SELECTED and ANALYZING each "
            "paint exactly their own region, at every "
            "width"
        )
    )


def test_upload_terminal_states(
    results: dict,
):

    terminal = results["upload_terminal_states"]


    if terminal["violations"]:

        raise AssertionError(
            (
                "A terminal upload state is wrong. "
                "both_buttons means Analyze and Try "
                "Again are on screen together, which is "
                "two buttons for one decision:\n"
                f"{json.dumps(terminal['violations'], indent=2)}"
            )
        )


    observed = terminal["observed"]


    for key, shown in observed.items():

        if key.startswith(
            "success@"
        ):

            if shown["analyze"]:

                raise AssertionError(
                    (
                        f"{key}: Analyze is still "
                        "painted after a successful "
                        "analysis, so the document can "
                        "be submitted twice."
                    )
                )


        if key.startswith(
            "error@"
        ):

            if not shown["retry"]:

                raise AssertionError(
                    (
                        f"{key}: the error state offers "
                        "no Try Again."
                    )
                )


            if shown["analyze"]:

                raise AssertionError(
                    (
                        f"{key}: Analyze is painted "
                        "beside Try Again."
                    )
                )


    print(
        (
            "[PASS] SUCCESS retires Analyze and ERROR "
            "replaces it with Try Again, at every width"
        )
    )


# ==========================================================
# 3b. THE ASYNC JOB FLOW
# ==========================================================
#
# Phase 9.4 replaced the synchronous request with a job and a
# poll loop. That is a material rewrite of the state machine
# whose failure was the original reported defect, so the same
# question is asked of the new flow.
#
# QUEUED, PROCESSING and RETRY_WAIT deliberately share one
# visual state -- all three mean "the user is waiting" and only
# the label differs. Sharing is exactly where exclusivity goes
# wrong, so it is checked rather than assumed.
# ==========================================================

def test_async_states_are_exclusive(
    results: dict,
):

    async_states = results["async_upload_states"]


    if async_states["violations"]:

        raise AssertionError(
            (
                "The async upload flow paints more than "
                "one state at once, or paints none:\n"
                f"{json.dumps(async_states['violations'], indent=2)}"
            )
        )


    observed = async_states["observed"]


    # Every waiting state must show a label that came from the
    # server, not a sentence this page made up. The old code
    # rotated five invented strings on a timer; the test that
    # it does not do that any more is that the label reflects
    # the status and stage the job actually reported.
    expected_labels = {
        "queued":
            "Queued",

        "processing":
            "Reading text from the document",

        "retry_wait":
            "attempt 1 of 3",
    }


    for scenario, fragment in expected_labels.items():

        label = (
            observed.get(
                scenario + ":label",
            )
            or ""
        )

        if fragment not in label:

            raise AssertionError(
                (
                    f"In the {scenario} state the page "
                    f"shows {label!r}, which does not "
                    f"contain {fragment!r}. The label "
                    "must come from the job's real "
                    "status and stage."
                )
            )


    # A terminal job must retire Analyze, and only the failed
    # one may offer Try Again.
    for width_key, shown in observed.items():

        if not isinstance(
            shown,
            dict,
        ) or "analyze" not in shown:
            continue


        if width_key.startswith(
            "completed@"
        ):

            if shown["analyze"] or shown["retry"]:

                raise AssertionError(
                    (
                        f"{width_key}: a completed job "
                        "still offers a submit control."
                    )
                )


        if width_key.startswith(
            "failed@"
        ):

            if shown["analyze"]:

                raise AssertionError(
                    (
                        f"{width_key}: Analyze is "
                        "painted beside Try Again."
                    )
                )


            if not shown["retry"]:

                raise AssertionError(
                    (
                        f"{width_key}: the failed state "
                        "offers no Try Again."
                    )
                )


    print(
        (
            "[PASS] QUEUED, PROCESSING and RETRY_WAIT "
            "share one exclusive waiting state with "
            "server-authored labels; COMPLETED and "
            "FAILED each paint exactly their own"
        )
    )


def test_polling_is_on_a_leash(
    results: dict,
):

    discipline = results["async_polling_discipline"]


    if discipline["create_calls_for_four_clicks"] != 1:

        raise AssertionError(
            (
                "Four Analyze clicks created "
                f"{discipline['create_calls_for_four_clicks']} "
                "jobs. A duplicate submission is a "
                "second real document, not a retry."
            )
        )


    if not discipline["polling_while_working"]:

        raise AssertionError(
            (
                "The page is not polling while the job "
                "is working, so it can never learn that "
                "the job finished."
            )
        )


    if not discipline["polls_chained"]:

        raise AssertionError(
            (
                "The poll loop fired once and stopped. "
                "It must chain, or the page freezes on "
                "the first status it saw."
            )
        )


    # The whole point of the leash.
    if discipline["polling_after_unload"]:

        raise AssertionError(
            (
                "Polling continues after the page "
                "unloads. A forgotten tab would keep "
                "asking the server forever."
            )
        )


    if (
        discipline["polls_after_unload"]
        != discipline["polls_before_unload"]
    ):

        raise AssertionError(
            (
                "A poll was issued after unload: "
                f"{discipline['polls_before_unload']} "
                "before, "
                f"{discipline['polls_after_unload']} "
                "after."
            )
        )


    if (
        discipline["object_urls_created"]
        != discipline["object_urls_revoked"]
    ):

        raise AssertionError(
            (
                "Object URLs are leaking: "
                f"{discipline['object_urls_created']} "
                "created, "
                f"{discipline['object_urls_revoked']} "
                "revoked. An un-revoked URL keeps the "
                "whole file alive in memory."
            )
        )


    # A poller with no ceiling is a page that hammers a server
    # forever.
    if not discipline["max_polls"]:

        raise AssertionError(
            "The poll loop has no ceiling."
        )


    # Fast polling buys nothing here: OCR is the entire cost
    # and it takes tens of seconds, so a short interval just
    # produces identical answers under load.
    if discipline["poll_interval_ms"] < 1000:

        raise AssertionError(
            (
                "The poll interval is "
                f"{discipline['poll_interval_ms']}ms. "
                "OCR takes tens of seconds, so polling "
                "faster than once a second only adds "
                "load."
            )
        )


    print(
        (
            "[PASS] four clicks make one job; polling "
            f"chains at {discipline['poll_interval_ms']}ms, "
            f"is capped at {discipline['max_polls']} polls, "
            "stops on unload and leaks no object URL"
        )
    )


# ==========================================================
# 4. THE REVIEW CONTROLS
# ==========================================================
#
# Normal mode offers Approve, Correct and Reject. Correction
# mode replaces them with Submit Corrections and Cancel. A
# document that has been reviewed offers nothing.
# ==========================================================

def test_review_controls_are_exclusive(
    results: dict,
):

    workspace = results["workspace_control_exclusivity"]


    if "missing_controls" in workspace:

        raise AssertionError(
            (
                "Review controls are missing from the "
                "page: "
                f"{workspace['missing_controls']}"
            )
        )


    if workspace["violations"]:

        raise AssertionError(
            (
                "The review controls compete:\n"
                f"{json.dumps(workspace['violations'], indent=2)}"
            )
        )


    observed = workspace["observed"]


    for key, shown in observed.items():

        if key.startswith(
            "normal@"
        ):

            for control in (
                "approve",
                "correct",
                "reject",
            ):

                if not shown[control]:

                    raise AssertionError(
                        (
                            f"{key}: normal review mode "
                            f"does not offer {control}."
                        )
                    )


        if key.startswith(
            "correcting@"
        ):

            for control in (
                "submit",
                "cancel",
            ):

                if not shown[control]:

                    raise AssertionError(
                        (
                            f"{key}: correction mode "
                            f"does not offer {control}."
                        )
                    )


        if key.startswith(
            "locked@"
        ):

            painted = [
                name
                for name, on in shown.items()
                if on
            ]

            if painted:

                raise AssertionError(
                    (
                        f"{key}: a document that has "
                        "already been reviewed still "
                        f"offers {painted}."
                    )
                )


    print(
        (
            "[PASS] normal mode offers three decisions, "
            "correction mode replaces them, a reviewed "
            "document offers none"
        )
    )


# ==========================================================
# 5. THE !important INVENTORY
# ==========================================================

def test_important_inventory(
    results: dict,
):

    inventory = results["important_inventory"]


    if inventory["count"] != ALLOWED_IMPORTANT:

        listing = "\n".join(
            (
                f"  {item['file']}:{item['line']}  "
                f"{item['text']}"
            )
            for item in inventory["declarations"]
        )

        raise AssertionError(
            (
                "The !important inventory changed: "
                f"expected {ALLOWED_IMPORTANT}, found "
                f"{inventory['count']}.\n\n"
                f"{listing}\n\n"
                "[hidden] needs it. Reduced motion, "
                "print and .btn.is-pending have it for "
                "reasons. Anything else is a specificity "
                "fight that should be won properly, so "
                "raise this number only with a reason."
            )
        )


    # The one that matters must still be the one that is
    # there. A count alone would pass if [hidden] were
    # deleted and something else gained !important.
    hidden_rules = [
        item
        for item in inventory["declarations"]
        if item["file"] == "base.css"
        and "display: none" in item["text"]
    ]


    if len(hidden_rules) < 2:

        raise AssertionError(
            (
                "base.css should carry two "
                "display:none !important declarations: "
                "[hidden] and the print override. Found "
                f"{len(hidden_rules)}."
            )
        )


    print(
        (
            "[PASS] "
            f"{inventory['count']} !important "
            "declarations, all accounted for"
        )
    )


# ==========================================================
# 6. TAB ROW GEOMETRY
# ==========================================================
#
# Honest scope note. This engine resolves display, not layout.
# It cannot measure rendered text, so it cannot prove the six
# workspace tabs fit their column -- only a browser can. What
# it pins is the geometry that was changed to make them fit,
# so the fix cannot be quietly reverted, and the fact that
# overflow-x survives as the fallback for narrow windows.
# ==========================================================

def test_tab_geometry(
    results: dict,
):

    geometry = results["tab_geometry"]


    if not geometry["tablist_found"] or not geometry["tab_found"]:

        raise AssertionError(
            "The .tablist or .tab rule is gone."
        )


    required = {
        "tablist_scrolls": (
            "overflow-x: auto is the honest fallback "
            "for narrow windows and must stay"
        ),
        "tablist_no_side_padding": (
            "the strip's 24px of side padding was "
            "reclaimed for the labels"
        ),
        "tablist_no_gap": (
            "the 20px of inter-tab gap was reclaimed "
            "for the labels"
        ),
        "tab_padding": (
            "tabs use uniform --space-3 padding, not "
            "--space-4 on the sides"
        ),
        "tab_font": (
            "tab labels are --text-sm"
        ),
        "tab_nowrap": (
            "a tab label must not wrap mid-phrase"
        ),
    }


    for key, why in required.items():

        if not geometry[key]:

            raise AssertionError(
                (
                    "Tab geometry regressed: "
                    f"{why}.\n"
                    "Six tabs have to fit the 7 of a "
                    "5fr:7fr split, which is about 600px "
                    "on a 1366px laptop. Before this, "
                    "the whole tab set sat behind a "
                    "horizontal scrollbar on an ordinary "
                    "laptop."
                )
            )


    if geometry["measured_in_browser"]:

        raise AssertionError(
            (
                "measured_in_browser claims a real "
                "measurement. Nothing here measures "
                "rendered text."
            )
        )


    print(
        (
            "[PASS] tab geometry pinned; fit itself "
            "still needs a browser and says so"
        )
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 8 FINAL VISUAL QA - COMPUTED "
        "VISIBILITY STATE GATE"
    )
    print("=" * 76)


    test_engine_present()


    results = (
        run_harness()
    )

    assert_no_harness_errors(
        results
    )

    test_engine_coverage(
        results
    )

    test_static_hidden_never_painted(
        results
    )

    test_hidden_rule_is_load_bearing(
        results
    )

    test_upload_states_are_exclusive(
        results
    )

    test_upload_terminal_states(
        results
    )

    test_async_states_are_exclusive(
        results
    )

    test_polling_is_on_a_leash(
        results
    )

    test_review_controls_are_exclusive(
        results
    )

    test_important_inventory(
        results
    )

    test_tab_geometry(
        results
    )


    print()
    print("=" * 76)
    print(
        "[PASS] PHASE 8 VISUAL STATE GATE PASSED"
    )
    print("=" * 76)


if __name__ == "__main__":
    main()
