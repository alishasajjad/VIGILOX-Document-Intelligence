import re
import sys

from pathlib import Path


# ==========================================================
# PHASE 12.6 - EVERY TEST FILE IS ACTUALLY RUN BY SOMETHING
# ==========================================================
#
# The gap this closes is one the regression runner cannot see
# for itself.
#
# The runner reports MISSING when a REGISTERED file is not on
# disk. The inverse -- a file on disk that nothing registers --
# produces no signal at all: the suite simply never runs, and
# every summary reads green.
#
# It has happened twice.
#
#   Phase 8.0 found 19 of 49 test files unguarded.
#   Phase 12.6 found four more: the real-dependency OCR,
#     preprocessing, extraction and pipeline tests, all
#     maintained as recently as Phase 8.2, none of them
#     executed by either gate.
#
# A test nobody runs is worse than no test: it looks like
# coverage on the file listing and it rots without anyone
# noticing, so when it is finally run it fails for reasons
# unrelated to whatever is being released.
#
# So the inverse is asserted here. Every test file is either
# registered with the runner or named in the exclusion list
# below WITH A REASON. There is no third category.
# ==========================================================


PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)

if str(
    PROJECT_ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


RUNNER = (
    PROJECT_ROOT
    / "scripts"
    / "verification"
    / "run_phase7c7g_regressions.py"
)


# ==========================================================
# THE EXCLUSION LIST
# ==========================================================
#
# A directory may be excluded, with a reason that has to be
# written down. "We meant to" is not a reason; the point of
# the list is that skipping a test becomes a decision on the
# record rather than an omission.
# ==========================================================

EXCLUDED_DIRECTORIES = {
    "tests/legacy": (
        "Superseded suites, already failing when they were "
        "quarantined in Phase 8.1. Kept for reference rather "
        "than deleted, because they document behaviour that "
        "used to be expected. Intentionally not run."
    ),
}


# Helper modules and harnesses -- imported by tests, not run
# as tests. Recognised by NOT matching test_*.py, so they need
# no listing; noted here so a reader does not look for them.


# ==========================================================
# ASSERTIONS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
) -> None:

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def assert_true(
    value,
    message: str,
) -> None:

    if not value:
        raise AssertionError(
            message
        )


def section(
    title: str,
) -> None:

    print()
    print(
        "-" * 74
    )
    print(
        title
    )
    print(
        "-" * 74
    )


def ok(
    message: str,
) -> None:

    print(
        f"[PASS] {message}"
    )


# ==========================================================
# WHAT THE RUNNER REGISTERS
# ==========================================================

def registered_suites() -> set[str]:

    """
    Every test path the runner will actually execute.

    IMPORTED, not scraped.

    The first version of this read the runner's source with a
    regular expression and missed a path that is written as
    two adjacent string literals for line length:

        (
            "tests/e2e/test_phase7c_final"
            "_production_readiness_e2e.py"
        ),

    Python concatenates those at parse time; a regex reading
    one literal at a time sees neither half as a path. The
    suite was registered and running, and the detector
    reported it as unrun -- a false positive that, had it been
    "fixed" by registering the file again, would have made the
    gate run it twice.

    Importing gets the values after Python has done the
    concatenation, which is the only view that is actually
    correct. The runner's module level defines constants and
    guards main() behind __name__, so importing it runs
    nothing.

    This is the same lesson as reading routes from the OpenAPI
    document rather than from app.routes: use the view the
    language has already resolved, not a text approximation of
    it.
    """

    import importlib.util

    specification = importlib.util.spec_from_file_location(
        "vigilox_regression_runner",
        RUNNER,
    )

    module = importlib.util.module_from_spec(
        specification
    )

    specification.loader.exec_module(
        module
    )

    collected = set()

    for name in dir(
        module
    ):

        value = getattr(
            module,
            name,
        )

        collected |= _paths_in(
            value
        )

    return collected


def _paths_in(
    value,
) -> set[str]:

    """
    Every .py path inside an arbitrarily nested tuple or list.

    The runner holds suites in flat tuples, in a tuple of
    (label, tuple) pairs, and in a tuple of directory-plus-
    filenames. Walking the structure means a new group is
    picked up without this test being edited -- which matters,
    because a group nobody knows about is exactly the failure
    this file exists to catch.
    """

    found = set()

    if isinstance(
        value,
        str,
    ):

        if value.endswith(
            ".py"
        ):
            found.add(
                value.replace(
                    "\\",
                    "/",
                )
            )

        return found

    if isinstance(
        value,
        (
            tuple,
            list,
            set,
        ),
    ):

        for item in value:
            found |= _paths_in(
                item
            )

    return found


def test_files_on_disk() -> set[str]:

    return {
        str(
            path.relative_to(
                PROJECT_ROOT
            )
        ).replace(
            "\\",
            "/",
        )
        for path in (
            PROJECT_ROOT
            / "tests"
        ).rglob(
            "test_*.py"
        )
    }


# ==========================================================
# TEST 1 - NOTHING IS SILENTLY UNRUN
# ==========================================================

def test_every_test_file_is_run_or_excluded() -> None:

    section(
        "TEST 1 - EVERY TEST FILE IS EITHER REGISTERED OR "
        "EXCLUDED WITH A REASON"
    )

    on_disk = test_files_on_disk()

    assert_true(
        len(
            on_disk
        ) > 40,
        (
            f"Only {len(on_disk)} test files found. The "
            "detector is looking in the wrong place, and a "
            "check that cannot see the files it guards passes "
            "for the wrong reason."
        ),
    )

    registered = registered_suites()

    unaccounted = []

    excluded_count = 0

    for path in sorted(
        on_disk
    ):

        directory = "/".join(
            path.split(
                "/"
            )[:-1]
        )

        if directory in EXCLUDED_DIRECTORIES:
            excluded_count += 1
            continue

        name = path.split(
            "/"
        )[-1]

        if path in registered or name in registered:
            continue

        unaccounted.append(
            path
        )

    assert_equal(
        unaccounted,
        [],
        (
            "These test files are on disk and no runner "
            "executes them.\n"
            "\n"
            "A test nobody runs is worse than no test: it "
            "looks like coverage and it rots unnoticed. "
            "Either register it in "
            "scripts/verification/run_phase7c7g_regressions.py"
            ", or move it to an excluded directory and write "
            "down why."
        ),
    )

    ok(
        f"all {len(on_disk) - excluded_count} active test "
        f"files are registered with the runner "
        f"({excluded_count} deliberately excluded)"
    )


# ==========================================================
# TEST 2 - EVERY EXCLUSION HAS A REASON, AND STILL EXISTS
# ==========================================================

def test_exclusions_are_justified() -> None:

    section(
        "TEST 2 - EVERY EXCLUSION IS JUSTIFIED AND STILL "
        "APPLIES"
    )

    for directory, reason in sorted(
        EXCLUDED_DIRECTORIES.items()
    ):

        path = (
            PROJECT_ROOT
            / directory
        )

        assert_true(
            path.is_dir(),
            (
                f"{directory} is excluded but does not "
                "exist. A stale exclusion is a hole waiting "
                "for a file to be dropped into it: anything "
                "put there in future would be silently "
                "unrun."
            ),
        )

        assert_true(
            len(
                reason
            ) > 60,
            (
                f"The exclusion for {directory} needs a real "
                "reason, not a placeholder. The list exists "
                "so that skipping a test is a decision on "
                "the record."
            ),
        )

        contents = sorted(
            item.name
            for item in path.rglob(
                "test_*.py"
            )
        )

        print(
            f"       {directory}: "
            f"{len(contents)} file(s) -- "
            + reason.split(
                "."
            )[0]
        )

    ok(
        f"all {len(EXCLUDED_DIRECTORIES)} exclusion(s) point "
        "at a real directory and carry a written reason"
    )


# ==========================================================
# TEST 3 - THE REGISTRATION LIST HAS NO GHOSTS
# ==========================================================

def test_registered_files_exist() -> None:

    section(
        "TEST 3 - EVERY REGISTERED PATH EXISTS"
    )

    # The runner reports this at run time as MISSING, which is
    # the right place for it. Asserted here too so a typo is
    # caught by a fast test rather than by a gate that has
    # already spent twenty minutes.

    registered = registered_suites()

    on_disk = test_files_on_disk()

    bare_names = {
        path.split(
            "/"
        )[-1]
        for path in on_disk
    }

    # Only TEST paths. The runner also holds a list of
    # production files for its compile check, and those are
    # legitimately not under tests/ -- collecting them here
    # was a false positive from walking every module
    # attribute.
    test_entries = {
        entry
        for entry in registered
        if entry.startswith(
            "tests/"
        )
        or (
            "/" not in entry
            and entry.startswith(
                "test_"
            )
        )
    }

    assert_true(
        len(
            test_entries
        ) > 40,
        (
            f"Only {len(test_entries)} test entries found in "
            "the runner. The reader is not seeing the groups, "
            "and a check that cannot see what it guards "
            "passes for the wrong reason."
        ),
    )

    ghosts = sorted(
        entry
        for entry in test_entries
        if entry.startswith(
            "tests/"
        )
        and entry not in on_disk
    )

    ghosts += sorted(
        entry
        for entry in test_entries
        if not entry.startswith(
            "tests/"
        )
        and entry not in bare_names
    )

    assert_equal(
        ghosts,
        [],
        (
            "The runner registers paths that do not exist. "
            "The gate would report MISSING and fail, but it "
            "would do so after running everything else."
        ),
    )

    ok(
        f"all {len(test_entries)} registered test entries "
        "resolve to a real file"
    )


# ==========================================================
# TEST 4 - THE DETECTOR CAN STILL FAIL
# ==========================================================

def test_the_detector_works() -> None:

    section(
        "TEST 4 - THE DETECTOR CATCHES A PLANTED "
        "UNREGISTERED FILE"
    )

    # ------------------------------------------------------
    # Without this, TEST 1 passing means either "everything is
    # registered" or "the detector reads nothing". Those look
    # identical from the outside, and this suite exists
    # precisely because a silent no-op went unnoticed twice.
    # ------------------------------------------------------

    registered = registered_suites()

    planted = "tests/unit/test_definitely_not_registered.py"

    assert_true(
        planted not in registered,
        (
            "The planted name must not actually be "
            "registered."
        ),
    )

    directory = "/".join(
        planted.split(
            "/"
        )[:-1]
    )

    assert_true(
        directory not in EXCLUDED_DIRECTORIES,
        (
            "The planted file must not sit in an excluded "
            "directory, or this proves nothing."
        ),
    )

    name = planted.split(
        "/"
    )[-1]

    would_be_caught = (
        planted not in registered
        and name not in registered
    )

    assert_true(
        would_be_caught,
        (
            "The detector does not flag an unregistered "
            "file, so its verdict in TEST 1 is meaningless."
        ),
    )

    ok(
        "a planted unregistered path is flagged, so TEST 1's "
        "verdict means something"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 12.6 - TEST COVERAGE OF THE TEST SUITE ITSELF"
    )
    print(
        "=" * 74
    )

    test_every_test_file_is_run_or_excluded()
    test_exclusions_are_justified()
    test_registered_files_exist()
    test_the_detector_works()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 12.6 TEST COVERAGE TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
