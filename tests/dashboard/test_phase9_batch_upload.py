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

from backend.app.services.job_service import (
    DEFAULT_MAX_BATCH_FILES,
)

from backend.app.api.request_validation import (
    ALLOWED_CONTENT_TYPES,
    MAX_UPLOAD_BYTES,
)


# ==========================================================
# PHASE 9.4
# BATCH UPLOAD CONTRACT TEST
# ==========================================================
#
# Two halves, the same shape as the other frontend suites.
#
# 1. Contracts the browser depends on, checked against the
#    real backend constants rather than against a copy of
#    them. The frontend mirrors three numbers -- the batch
#    file cap, the per-file byte cap and the accepted types --
#    and each mirror is asserted equal to the Python value it
#    mirrors. A frontend that quietly drifts to 50 files would
#    let somebody select 50 and then be refused by the server,
#    which is a worse experience than not offering it.
#
# 2. Real behaviour, by EXECUTING js/upload_batch.js and
#    js/upload.js against the shipped page
#    (tests/dashboard/batch_harness.js).
#
# The second half is where the value is. A batch screen is
# mostly a list and a loop, and the interesting claims are the
# ones a single-file test cannot make:
#
#   - one invalid file does not reject its siblings, and the
#     invalid one is named rather than counted
#   - removing a file removes that file and moves focus
#     somewhere deliberate
#   - four submit clicks create one batch
#   - twenty files are one polling chain, not twenty timers
#   - a mixed terminal batch shows two Open Document links and
#     one safe failure sentence at the same time
#   - a completed job with no document_id produces no link and
#     no navigation
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
    / "batch_harness.js"
)

BATCH_MODULE = (
    PROJECT_ROOT
    / "frontend"
    / "static"
    / "js"
    / "upload_batch.js"
)

UPLOAD_PAGE = (
    PROJECT_ROOT
    / "frontend"
    / "pages"
    / "upload.html"
)


PASSES: list[str] = []


def ok(
    message: str,
) -> None:

    PASSES.append(
        message
    )

    print(
        f"[PASS] {message}"
    )


def fail(
    message: str,
) -> None:

    raise AssertionError(
        message
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
                "Node is required to execute the batch "
                "selection and polling behaviour. "
                "Without it this suite could only "
                "pattern-match source text, which "
                "proves nothing about a list and a "
                "loop."
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
                "Batch harness failed to run.\n"
                f"{completed.stdout}\n"
                f"{completed.stderr}"
            )
        )


    return json.loads(
        completed.stdout
    )


def assert_no_harness_errors(
    results: dict,
) -> None:

    for name, value in results.items():

        if (
            isinstance(
                value,
                dict,
            )
            and "harness_error" in value
        ):

            fail(
                f"Harness check {name} raised:\n"
                f"{value['harness_error']}"
            )


    ok(
        "every batch check ran without a harness error"
    )


# ==========================================================
# 1. THE MIRRORED LIMITS
# ==========================================================
#
# The frontend cannot ask the server for these: it needs them
# to render a hint before it has made a request. So it mirrors
# them, and the mirrors are asserted here.
#
# The server stays authoritative either way -- it re-checks
# the count and returns BATCH_TOO_LARGE, and that response is
# rendered like any other failure. This is about not offering
# somebody a choice that will be refused.
# ==========================================================

def test_limits_mirror_the_backend() -> None:

    source = (
        BATCH_MODULE.read_text(
            encoding="utf-8",
        )
    )


    def number(
        name: str,
    ) -> int:

        found = re.search(
            r"var\s+" + name + r"\s*=\s*([0-9*\s]+);",
            source,
        )

        if not found:
            fail(
                f"{name} is not declared in "
                "upload_batch.js."
            )

        # Handles "10 * 1024 * 1024".
        return eval(          # noqa: S307
            found.group(1).strip()
        )


    max_files = number(
        "MAX_FILES"
    )

    max_bytes = number(
        "MAX_BYTES"
    )


    if max_files != DEFAULT_MAX_BATCH_FILES:

        fail(
            "The batch file cap in the frontend "
            f"({max_files}) does not match "
            "DEFAULT_MAX_BATCH_FILES in "
            f"job_service.py ({DEFAULT_MAX_BATCH_FILES}). "
            "A browser that offers more files than the "
            "server accepts lets somebody select them "
            "and then be refused."
        )


    if max_bytes != MAX_UPLOAD_BYTES:

        fail(
            "The per-file byte cap in the frontend "
            f"({max_bytes}) does not match "
            f"MAX_UPLOAD_BYTES ({MAX_UPLOAD_BYTES})."
        )


    # The accepted types have to be the same set, not a
    # subset: an async path that accepted what the sync one
    # rejected would be a way around the validation.
    declared = set(
        re.findall(
            r'"(image/[a-z]+)":\s*true',
            source,
        )
    )

    if declared != set(
        ALLOWED_CONTENT_TYPES
    ):

        fail(
            "The accepted types in the frontend "
            f"({sorted(declared)}) do not match "
            "ALLOWED_CONTENT_TYPES "
            f"({sorted(ALLOWED_CONTENT_TYPES)})."
        )


    ok(
        f"the frontend mirrors {max_files} files, "
        f"{max_bytes // (1024 * 1024)} MiB and "
        f"{len(declared)} types, all asserted equal to "
        "the backend"
    )


# ==========================================================
# 2. ROUTE AND PAGE CONTRACTS
# ==========================================================

def test_page_serves_the_batch_module(
    client: TestClient,
) -> None:

    response = (
        client.get(
            "/upload"
        )
    )

    if response.status_code != 200:
        fail(
            "GET /upload returned "
            f"{response.status_code}."
        )


    html = response.text


    for asset in (
        "/review/static/js/upload.js",
        "/review/static/js/upload_batch.js",
        "/review/static/js/vocabulary.js",
    ):

        if asset not in html:
            fail(
                f"The upload page does not load {asset}."
            )


        served = (
            client.get(
                asset
            )
        )

        if served.status_code != 200:
            fail(
                f"{asset} does not resolve "
                f"({served.status_code})."
            )


    ok(
        "the upload page loads and serves the batch "
        "module and its vocabulary"
    )


def test_batch_markup(
    client: TestClient,
) -> None:

    html = (
        UPLOAD_PAGE.read_text(
            encoding="utf-8",
        )
    )


    required = (
        "mode-single",
        "mode-batch",
        "single-mode",
        "batch-mode",
        "single-actions",
        "batch-actions",
        "batch-file-input",
        "batch-validation",
        "batch-selection",
        "batch-selection-count",
        "batch-file-list",
        "batch-progress",
        "batch-progress-state",
        "batch-summary",
        "batch-results",
        "batch-error",
        "batch-submit-button",
        "batch-clear-button",
    )

    missing = [
        element_id
        for element_id in required
        if f'id="{element_id}"' not in html
    ]

    if missing:
        fail(
            f"The upload page is missing {missing}."
        )


    # The file input has to accept several files, or batch
    # mode is a single-file screen with a different label.
    input_block = html[
        html.index('id="batch-file-input"'):
    ][:400]

    if "multiple" not in input_block:
        fail(
            "The batch file input does not accept "
            "multiple files."
        )


    if 'for="batch-file-input"' not in html:
        fail(
            "The batch file input has no label. It is "
            "visually replaced by a styled label, so "
            "without one there is no accessible name "
            "and no way to open the picker by keyboard."
        )


    ok(
        "the batch markup is present, accepts multiple "
        "files and is labelled"
    )


# ==========================================================
# 3. MODE SWITCH
# ==========================================================

def test_mode_switch(
    results: dict,
) -> None:

    switch = results["mode_switch"]


    if switch["violations"]:
        fail(
            "The two upload modes are not mutually "
            "exclusive:\n"
            f"{json.dumps(switch['violations'], indent=2)}"
        )


    if switch["mode_after_switch"] != "batch":
        fail(
            "Selecting the batch radio did not change "
            "the mode."
        )


    # Real radios in a real radiogroup. Arrow-key navigation,
    # the grouping and the "1 of 2" announcement all come from
    # the platform; a pair of divs with aria-pressed would have
    # to reimplement every one of them, badly.
    if not switch["is_radiogroup"]:
        fail(
            "The mode switch is not a radiogroup."
        )


    if switch["radio_count"] != 2:
        fail(
            "Expected two mode radios, found "
            f"{switch['radio_count']}."
        )


    if not switch["every_radio_labelled"]:
        fail(
            "A mode radio has no label, so it has no "
            "accessible name."
        )


    ok(
        "the mode switch is an accessible radiogroup and "
        "exactly one panel is painted, at every width"
    )


# ==========================================================
# 4. SELECTION
# ==========================================================

def test_per_file_validation(
    results: dict,
) -> None:

    selection = results["selection_validation"]


    if selection["selected"] != 8:
        fail(
            "Expected 8 files to be represented, got "
            f"{selection['selected']}."
        )


    # THE property. One unsupported file must not reject its
    # siblings, and the invalid one must be identified.
    if selection["valid"] != 4:
        fail(
            "Expected 4 of 8 files to be valid, got "
            f"{selection['valid']}. A batch containing "
            "one bad file must keep the good ones."
        )


    if selection["rows_rendered"] != selection["selected"]:
        fail(
            "Not every selected file is rendered. An "
            "invalid file has to stay visible so it can "
            "be identified and removed -- 'some files "
            "were rejected' is not actionable."
        )


    reasons = selection["reasons"]

    expected = {
        "a.jpg": None,
        "b.png": None,
        "c.webp": None,
        "typeless.jpg": None,
    }

    for name, reason in expected.items():

        if reasons.get(
            name,
            "missing",
        ) != reason:

            fail(
                f"{name} should be acceptable, but the "
                f"reason given was {reasons.get(name)!r}."
            )


    # Each rejection must say what is actually wrong, not
    # "invalid file".
    for name, fragment in (
        ("notes.txt", "not a supported document type"),
        ("huge.jpg", "The limit is"),
        ("empty.png", "empty"),
        ("typeless.exe", "not a supported document type"),
    ):

        reason = (
            reasons.get(
                name
            )
            or ""
        )

        if fragment.lower() not in reason.lower():

            fail(
                f"{name} should be rejected with a "
                f"reason mentioning {fragment!r}; got "
                f"{reason!r}."
            )


    if not selection["submit_enabled"]:
        fail(
            "Submit is disabled even though four files "
            "are valid. One bad file must not block the "
            "batch."
        )


    # A row of twenty identical "Remove" buttons is useless to
    # anyone navigating by control.
    labels = selection["remove_labels"]

    if any(
        label is None
        for label in labels
    ):
        fail(
            "A selected file has no remove control."
        )


    if len(
        set(
            labels
        )
    ) != len(
        labels
    ):
        fail(
            "Remove controls do not name the file they "
            "remove: "
            f"{labels}"
        )


    ok(
        "each file validates independently with a "
        "specific reason, siblings survive, and every "
        "remove control names its own file"
    )


def test_removal_and_cap(
    results: dict,
) -> None:

    removal = results["selection_removal_and_cap"]


    if removal["after_removal"] != ["a.jpg", "b.png"]:
        fail(
            "Removing one file did not leave the rest: "
            f"{removal['after_removal']}"
        )


    # The element focus was on has just left the tree. Without
    # deliberate handling the browser drops focus to the body
    # and a keyboard user loses their place.
    if not removal["focused_after_removal"]:
        fail(
            "Focus was not moved after a row was "
            "removed, so it fell to the document body."
        )


    if removal["max_files"] != DEFAULT_MAX_BATCH_FILES:
        fail(
            "The harness read a different cap "
            f"({removal['max_files']}) from the backend "
            f"default ({DEFAULT_MAX_BATCH_FILES})."
        )


    if removal["capped_at"] != removal["max_files"]:
        fail(
            "Selection was not capped: "
            f"{removal['capped_at']} files held with a "
            f"cap of {removal['max_files']}. Unlimited "
            "selection is how a browser submits a batch "
            "the server will refuse."
        )


    if not removal["overflow_reported"]:
        fail(
            "Files were silently dropped when the cap "
            "was reached. Nothing may be discarded "
            "without saying so."
        )


    if removal["after_clear"] != 0:
        fail(
            "Clear did not empty the selection."
        )


    if not removal["clear_disabled_when_empty"]:
        fail(
            "Clear is still enabled with nothing "
            "selected."
        )


    ok(
        f"removal keeps siblings and moves focus; the "
        f"{removal['max_files']}-file cap holds and "
        "reports what it dropped"
    )


# ==========================================================
# 5. SUBMISSION
# ==========================================================

def test_one_batch_per_submission(
    results: dict,
) -> None:

    submission = results["submission"]


    if submission["batch_calls_for_four_clicks"] != 1:
        fail(
            "Four submit clicks created "
            f"{submission['batch_calls_for_four_clicks']} "
            "batches. A duplicate batch is a second set "
            "of real documents, not a retry."
        )


    # Only valid files are sent. Sending the invalid one to be
    # rejected would waste the upload and the server's time.
    if submission["files_submitted"] != 3:
        fail(
            "Expected 3 valid files to be submitted, "
            f"got {submission['files_submitted']}."
        )


    if not submission["batch_id"]:
        fail(
            "No batch id was recorded from the 202."
        )


    # One chain for the whole batch. Twenty files with a timer
    # each would be twenty requests per interval for
    # information one response already carries.
    if submission["timers_scheduled"] != 1:
        fail(
            f"{submission['timers_scheduled']} timers "
            "were scheduled for one batch. The batch "
            "endpoint returns every child's state in one "
            "response, so there must be exactly one "
            "polling chain."
        )


    if submission["aria_busy"] != "true":
        fail(
            "The processing region is not marked "
            "aria-busy during submission."
        )


    if not submission["progress_shown"] or not submission["select_hidden"]:
        fail(
            "Submitting should replace the selection "
            "with the progress view."
        )


    # The server-rejected file is named once, in the validation
    # region, and never appears in the results list because it
    # has no job to poll.
    if "notes.txt" not in submission["rejected_note"]:
        fail(
            "A file the server refused was not named: "
            f"{submission['rejected_note']!r}"
        )


    ok(
        "four clicks create one batch of only the valid "
        "files, on one polling chain, and the refused "
        "file is named"
    )


# ==========================================================
# 6. STATUS AND MIXED RESULTS
# ==========================================================

def test_real_states_and_no_percentages(
    results: dict,
) -> None:

    polling = results["polling_and_results"]

    working = polling["working"]

    terminal = polling["terminal"]


    # Real counts, from the batch endpoint.
    for fragment in (
        "Total3",
        "Queued1",
        "Processing1",
        "Retrying1",
    ):

        if fragment not in working["summary"]:
            fail(
                "The working summary should contain "
                f"{fragment!r}; got "
                f"{working['summary']!r}"
            )


    # No invented progress. A percentage anywhere in the batch
    # view would be a number the pipeline cannot produce.
    for view in (
        working["summary"],
        terminal["summary"],
        " ".join(
            working["rows"]
        ),
        " ".join(
            terminal["rows"]
        ),
    ):

        if "%" in view:
            fail(
                "A percentage appears in the batch "
                "view. The pipeline cannot report "
                "progress within a document, so any "
                "number would be invented."
            )


    # The advisory stage refines the label while PROCESSING.
    joined = " ".join(
        working["rows"]
    )

    if "Reading text from the document" not in joined:
        fail(
            "The advisory stage is not shown for a "
            "processing document: "
            f"{working['rows']}"
        )


    # RETRY_WAIT is not a failure, and which attempt it is on
    # is the difference between "working" and "broken".
    if "Attempt 1 of 3" not in joined:
        fail(
            "A retrying document does not say which "
            "attempt it is on: "
            f"{working['rows']}"
        )


    if not working["polling"]:
        fail(
            "Polling stopped while the batch was still "
            "working."
        )


    ok(
        "the batch view shows real per-state counts, the "
        "advisory stage and the retry attempt, and no "
        "percentage anywhere"
    )


def test_mixed_terminal_batch(
    results: dict,
) -> None:

    terminal = results["polling_and_results"]["terminal"]


    for fragment in (
        "Completed2",
        "Failed1",
    ):

        if fragment not in terminal["summary"]:
            fail(
                "The terminal summary should contain "
                f"{fragment!r}; got "
                f"{terminal['summary']!r}"
            )


    # THE batch property: one failed item must not erase its
    # successful siblings.
    if terminal["document_links"] != [
        "/review/doc-a",
        "/review/doc-b",
    ]:
        fail(
            "Expected two Open Document links to the "
            "real document ids, got "
            f"{terminal['document_links']}. A failed "
            "sibling must not remove the successful "
            "results."
        )


    joined = " ".join(
        terminal["rows"]
    )

    if "Not a supported document type." not in joined:
        fail(
            "The failed document does not show its safe "
            "failure sentence: "
            f"{terminal['rows']}"
        )


    if terminal["polling"]:
        fail(
            "Polling continues after every job reached a "
            "terminal state."
        )


    if terminal["aria_busy"] != "false":
        fail(
            "The processing region is still aria-busy "
            "after the batch finished."
        )


    if not terminal["select_available"]:
        fail(
            "A new batch cannot be selected after the "
            "previous one finished."
        )


    ok(
        "a mixed batch shows two real document links "
        "beside one safe failure, then stops polling"
    )


def test_polling_is_bounded(
    results: dict,
) -> None:

    stops = results["polling_stops"]


    if not stops["polling_before_unload"]:
        fail(
            "The batch was not polling to begin with, so "
            "this proves nothing."
        )


    if stops["polling_after_unload"]:
        fail(
            "Polling continues after the page unloads. A "
            "forgotten tab would keep asking forever."
        )


    if stops["polls_after_unload"] != stops["polls_before_unload"]:
        fail(
            "A poll was issued after unload."
        )


    # Leaving batch mode retires the loop: the jobs carry on
    # server-side, so polling a panel nobody is looking at is
    # load for nothing.
    if not stops["polling_before_switch"]:
        fail(
            "The batch was not polling before the mode "
            "switch."
        )


    if stops["polling_after_switch"]:
        fail(
            "Switching back to single mode left the "
            "batch polling loop running."
        )


    if stops["batch_painted_after_switch"]:
        fail(
            "The batch panel is still painted after "
            "switching to single mode."
        )


    if not stops["max_polls"]:
        fail(
            "The batch poll loop has no ceiling."
        )


    if stops["poll_interval_ms"] < 1000:
        fail(
            "The batch poll interval is "
            f"{stops['poll_interval_ms']}ms. OCR takes "
            "tens of seconds, so polling faster only "
            "adds load."
        )


    ok(
        f"batch polling is capped at {stops['max_polls']} "
        f"polls at {stops['poll_interval_ms']}ms and stops "
        "on unload and on leaving batch mode"
    )


# ==========================================================
# 7. SAFETY
# ==========================================================

def test_hostile_filenames(
    results: dict,
) -> None:

    hostile = results["hostile_filename"]


    if not hostile["text_contains_payload"]:
        fail(
            "The filename payload is not present as "
            "text, so this test is not exercising what "
            "it claims."
        )


    if hostile["img_elements"] or hostile["script_elements"]:
        fail(
            "A filename created "
            f"{hostile['img_elements']} img and "
            f"{hostile['script_elements']} script "
            "element(s). Filenames are untrusted input "
            "and must be assigned with textContent."
        )


    if hostile["rows"] != 2:
        fail(
            "Both hostile filenames should still be "
            "listed."
        )


    ok(
        "a filename containing markup renders as text and "
        "creates no elements"
    )


def test_completed_without_document_id(
    results: dict,
) -> None:

    orphan = results["completed_without_document_id"]


    if orphan["links"]:
        fail(
            "A completed job with no document_id "
            "produced a link. /review/undefined must be "
            "impossible."
        )


    if not orphan["explains"]:
        fail(
            "A completed job with no document_id says "
            "nothing. It is a real possibility and "
            "should be stated plainly rather than "
            "rendered as a dead link."
        )


    if orphan["navigations"]:
        fail(
            "The page navigated despite having no "
            "document reference: "
            f"{orphan['navigations']}"
        )


    ok(
        "a completed job with no document reference "
        "produces no link, no navigation, and says so"
    )


def test_submit_failure_keeps_selection(
    results: dict,
) -> None:

    failure = results["submit_failure_restores_selection"]


    if not failure["error_shown"]:
        fail(
            "A refused batch shows no error."
        )


    if "20 files" not in failure["message"]:
        fail(
            "The server's own message is not shown: "
            f"{failure['message']!r}"
        )


    # Stable code and request id, for support. Never a stack
    # trace: the API does not return one.
    for fragment in (
        "BATCH_TOO_LARGE",
        "req-b-1",
    ):

        if fragment not in failure["meta"]:
            fail(
                f"The error meta is missing {fragment}: "
                f"{failure['meta']!r}"
            )


    if failure["selection_kept"] != 1:
        fail(
            "A refused batch lost the selection, so the "
            "files have to be picked again."
        )


    if not failure["can_resubmit"]:
        fail(
            "A refused batch cannot be resubmitted."
        )


    if not failure["progress_hidden"]:
        fail(
            "The progress view is still shown after the "
            "batch was refused."
        )


    ok(
        "a refused batch shows the server's code and "
        "request id, keeps the selection and can be "
        "resubmitted"
    )


# ==========================================================
# 8. RESPONSIVE
# ==========================================================

def test_responsive(
    results: dict,
) -> None:

    responsive = results["responsive_contract"]


    required = {
        "summary_reflows": (
            "the six-column batch summary must reflow, "
            "or it overflows below about a thousand "
            "pixels"
        ),
        "file_row_stacks": (
            "the three-column file row must stack on a "
            "phone, or the filename gets a few "
            "characters"
        ),
        "mode_switch_stacks": (
            "the mode switch must stack so its two "
            "labels have the full width"
        ),
        "filename_wraps": (
            "a long unbroken filename must wrap; "
            "without it the row widens the grid and "
            "pushes the page sideways at every width"
        ),
    }

    for key, why in required.items():

        if not responsive[key]:
            fail(
                f"Responsive contract broken: {why}."
            )


    ok(
        "the batch summary, file row and mode switch all "
        "reflow, and long filenames wrap"
    )


# ==========================================================
# MAIN
# ==========================================================

# ==========================================================
# PHASE 12.18 - BATCH ROW IDENTITY, AND NO URLS TO LEAK
# ==========================================================
#
# The release brief asks two things of batch mode: that a row
# carries enough identity for a person to tell which document
# is in which state, and that object URLs are managed safely
# when rows are removed or the batch is reset.
#
# The second has a short answer -- batch mode creates none. A
# thumbnail per row was considered and NOT added:
#
#   the compact row already answers the question, with
#     filename, type, size and a state badge
#   the brief calls a thumbnail "acceptable", not required,
#     and warns against building a gallery
#   N rows means N object URLs to revoke on remove, on clear,
#     on unload and on submit failure -- four places to leak,
#     for information the row already carries
#
# So the design is unchanged and the ABSENCE is asserted. That
# is not decoration. It is trivially true today and it fails
# the moment somebody adds a thumbnail without the revocation,
# which is exactly when it needs to fail.
#
# Single-file upload is the opposite case: it does create a
# preview, deliberately, and upload_harness.js asserts its
# whole lifecycle.
# ==========================================================

def test_row_identity_and_object_urls(
    results: dict,
) -> None:

    print()
    print("-" * 76)
    print(
        "TEST 13 - EVERY ROW IS IDENTIFIABLE AND NO OBJECT "
        "URL IS CREATED"
    )
    print("-" * 76)

    outcome = results[
        "row_identity_and_no_object_urls"
    ]

    selected = outcome["after_select"]

    # ------------------------------------------------------
    # EVERY FILE IS REPRESENTED, VALID OR NOT
    # ------------------------------------------------------

    if selected["rows"] != 4:
        fail(
            "All four files must be listed, including the "
            "rejected one -- a person has to see which file "
            f"is the problem. Got {selected['rows']} row(s)."
        )


    expected_names = [
        "licence-front.jpg",
        "badge.png",
        "card.webp",
        "contract.pdf",
    ]

    if selected["names"] != expected_names:
        fail(
            "Each row must name its own file, in the order "
            "they were chosen.\n"
            f"expected {expected_names}\n"
            f"got      {selected['names']}"
        )


    for label in (
        "types",
        "sizes",
    ):

        blank = [
            index
            for index, value in enumerate(
                selected[label]
            )
            if not value
        ]

        if blank:
            fail(
                f"Every row must show its {label[:-1]}. "
                f"Rows missing one: {blank}"
            )


    ok(
        "all 4 rows carry filename, type and size -- enough "
        "to tell them apart without a thumbnail"
    )


    # ------------------------------------------------------
    # AND ITS OWN STATE
    # ------------------------------------------------------

    expected_states = [
        "Ready",
        "Ready",
        "Ready",
        "Cannot process",
    ]

    if selected["states"] != expected_states:
        fail(
            "Each row must show its own state, and the "
            "rejected file must be distinguishable from the "
            "three that will be processed.\n"
            f"expected {expected_states}\n"
            f"got      {selected['states']}"
        )


    ok(
        "each row shows its own state: three Ready, one "
        "Cannot process"
    )


    # ------------------------------------------------------
    # NOTHING TO LEAK
    # ------------------------------------------------------

    for stage, block in (
        (
            "selecting",
            selected,
        ),
        (
            "removing a row",
            outcome["after_remove"],
        ),
        (
            "clearing the batch",
            outcome["after_reset"],
        ),
    ):

        if block["object_urls_created"]:
            fail(
                f"Batch mode created "
                f"{block['object_urls_created']} object "
                f"URL(s) while {stage}.\n"
                "If a thumbnail has been added, every URL "
                "needs revoking on remove, on clear, on "
                "unload and on submit failure. This "
                "assertion exists to make that impossible "
                "to forget."
            )


    if not outcome["every_url_revoked"]:
        fail(
            "Every object URL created must have been "
            "revoked by remove, clear or unload."
        )


    ok(
        "batch mode creates no object URLs at all, so "
        "remove, clear and unload have nothing to leak"
    )


def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 9.4 - BATCH UPLOAD"
    )
    print("=" * 76)
    print()

    client = None


    try:

        client = (
            TestClient(
                app,
                raise_server_exceptions=False,
            )
        )

        test_limits_mirror_the_backend()

        test_page_serves_the_batch_module(
            client
        )

        test_batch_markup(
            client
        )

        results = (
            run_harness()
        )

        assert_no_harness_errors(
            results
        )

        test_mode_switch(
            results
        )

        test_per_file_validation(
            results
        )

        test_removal_and_cap(
            results
        )

        test_one_batch_per_submission(
            results
        )

        test_real_states_and_no_percentages(
            results
        )

        test_mixed_terminal_batch(
            results
        )

        test_polling_is_bounded(
            results
        )

        test_row_identity_and_object_urls(
            results
        )

        test_hostile_filenames(
            results
        )

        test_completed_without_document_id(
            results
        )

        test_submit_failure_keeps_selection(
            results
        )

        test_responsive(
            results
        )


    finally:

        if client is not None:
            client.close()


    print()
    print("=" * 76)
    print(
        f"[PASS] PHASE 9.4 BATCH UPLOAD PASSED - "
        f"{len(PASSES)} properties asserted"
    )
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
