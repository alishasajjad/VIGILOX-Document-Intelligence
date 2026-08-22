import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from pathlib import Path


# ==========================================================
# REAL BROWSER ACCEPTANCE
# PHASE 12.16
# ==========================================================
#
# Renders every page in an actual browser and captures what it
# produced, so a human can look at it.
#
# WHY THIS IS DIFFERENT FROM THE EXISTING TESTS
# ----------------------------------------------------------
# tests/dashboard/* already execute the real JavaScript
# modules against the real pages and assert on the resulting
# DOM. That is genuinely useful and it covers structure,
# routes, assets, titles and behaviour.
#
# What it cannot do is render. It has no layout engine, so it
# cannot tell you that a table overflows its container at
# 390px, that a long filename pushes a card off screen, or
# that two colours that pass a contrast calculation look wrong
# next to each other.
#
# This drives headless Chrome, which has a layout engine.
#
#
# NO NEW DEPENDENCIES
# ----------------------------------------------------------
# Chrome's own command line does everything needed:
#
#   --dump-dom     prints the DOM after JavaScript has run,
#                  which proves the page populated rather
#                  than merely parsed
#   --screenshot   renders at a given viewport
#
# No playwright, no selenium, no driver to keep in step with a
# browser version.
#
# --dump-dom cannot evaluate arbitrary JavaScript against a
# page, so measuring anything needs a page of our own: an
# IFRAME harness whose script reads scrollWidth out of the
# frame it hosts. It runs against the captured snapshots on a
# throwaway server rather than against the live application,
# because the application's CSP correctly blocks inline
# scripts -- see THE IFRAME HARNESS below.
#
#
# WHAT IT CANNOT DO
# ----------------------------------------------------------
# It cannot click. Upload flows, review submission and tab
# switching are covered by the harness tests, which can drive
# the modules directly.
#
# So this is not a replacement for the manual checklist in
# docs/release/v1-production-readiness.md -- it removes the
# part of it that a machine can do reliably, and says so.
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


from dotenv import load_dotenv  # noqa: E402

load_dotenv(
    PROJECT_ROOT
    / ".env"
)


# ==========================================================
# FINDING A BROWSER
# ==========================================================

CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application"
    r"\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application"
    r"\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/"
    "Google Chrome",
)


def find_browser() -> Path | None:

    override = os.getenv(
        "VIGILOX_BROWSER",
        "",
    ).strip()

    if override and Path(
        override
    ).is_file():

        return Path(
            override
        )

    for name in (
        "google-chrome",
        "chromium",
        "chrome",
        "msedge",
    ):

        found = shutil.which(
            name
        )

        if found:
            return Path(
                found
            )

    for candidate in CANDIDATES:

        path = Path(
            candidate
        )

        if path.is_file():
            return path

    return None


# ==========================================================
# THE VIEWPORTS
# ==========================================================
#
# Chosen to match the widths the design has breakpoints for,
# rather than a list of device names.
#
#
# CHROME WILL NOT GO BELOW ABOUT 500 PIXELS
# ----------------------------------------------------------
# READ THIS BEFORE TRUSTING A NARROW SCREENSHOT.
#
# --window-size=390,844 does NOT give a 390px viewport.
# Headless Chrome clamps the window: it reports
# clientWidth 512 (or 500 with --force-device-scale-factor=1)
# and then crops the screenshot to 390.
#
# Measured across --headless=new, --headless=old and bare
# --headless: all three clamp identically.
#
# The consequence is a trap. A 390px PNG of a 512px layout
# shows text cut off mid-line, a nav strip sliced through and
# controls running past the edge -- which is EXACTLY what real
# horizontal overflow looks like. It cost this project a
# reported defect that did not exist.
#
# So anything below the clamp is rendered inside an IFRAME.
# An iframe is not clamped: a 390px iframe has a real 390px
# viewport, media queries evaluate against it, and because it
# is same-origin the parent can read scrollWidth from inside.
# That also turns "does it overflow" from something a person
# squints at into something measured.
# ==========================================================

# Rendered directly: above the clamp, so --window-size is real.
DIRECT_VIEWPORTS = (
    (
        "large-desktop",
        1920,
        1080,
    ),
    (
        "laptop",
        1440,
        900,
    ),
    (
        "tablet",
        820,
        1180,
    ),
)

# Rendered in an iframe: below the clamp.
FRAMED_VIEWPORTS = (
    (
        "phone",
        390,
        844,
    ),
    (
        "narrow-phone",
        320,
        720,
    ),
)

# Every width overflow is measured at. Cheap, so the list is
# wider than the screenshot list -- a layout that only breaks
# at 600px is still a layout that breaks.
MEASURED_WIDTHS = (
    320,
    390,
    480,
    600,
    767,
    820,
    1024,
    1440,
)


PAGES = (
    (
        "dashboard",
        "/dashboard",
    ),
    (
        "upload",
        "/upload",
    ),
    (
        "documents",
        "/documents",
    ),
    (
        "review-queue",
        "/review",
    ),
)


# ==========================================================
# RUNNING THE BROWSER
# ==========================================================

BASE_FLAGS = (
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--hide-scrollbars",

    # Deterministic rendering, so a screenshot taken twice is
    # the same image and a diff means something changed.
    "--force-device-scale-factor=1",
    "--disable-lcd-text",

    # Nothing here should reach the network, and a page that
    # tries should fail visibly rather than hang.
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
)


def run_browser(
    browser: Path,
    *arguments: str,
    profile: Path,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess:

    return subprocess.run(
        [
            str(
                browser
            ),
            *BASE_FLAGS,
            f"--user-data-dir={profile}",
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ==========================================================
# THE IFRAME HARNESS
# ==========================================================
#
# WHY IT IS NOT SERVED BY THE APPLICATION
# ----------------------------------------------------------
# The first version wrote this file into the static tree so it
# would be same-origin with the pages it framed. It produced
# no measurement at all, and the reason is a good one: the
# application sends a strict Content-Security-Policy, and the
# harness needs an INLINE script. CSP blocked it.
#
# That is the security header working exactly as intended, and
# it is not something to weaken for a test. Adding a nonce or
# an 'unsafe-inline' exception would put a hole in production's
# CSP to make a measurement convenient.
#
# So the measurement runs against the RENDERED SNAPSHOTS that
# step 2 already captured -- the post-JavaScript DOM of each
# real page -- served from a throwaway local server together
# with the real stylesheets. Same CSS, same markup, same
# layout engine, no CSP in the way.
#
# What that gives up: the snapshot is static, so a layout that
# only breaks after an interaction is not covered. What it
# keeps: everything that determines whether the page overflows
# at a given width, which is the question being asked.
# ==========================================================

HARNESS_NAME = "harness.html"

HARNESS_TEMPLATE = """<!doctype html>
<html>
<head>
<title>pending</title>
<style>
  html, body { margin: 0; padding: 0; background: #fff; }
  iframe { border: 0; display: block; }
</style>
</head>
<body>
<iframe id="frame" src="__PAGE__" width="__WIDTH__" height="__HEIGHT__"></iframe>
<script>
var frame = document.getElementById("frame");

frame.addEventListener("load", function () {

    // The page's own modules fetch and render. Give them a
    // moment, then measure what actually laid out.
    setTimeout(function () {

        var inner = frame.contentDocument;
        var root = inner.documentElement;

        var view = root.clientWidth;
        var scroll = root.scrollWidth;

        // Elements pushed past the viewport, EXCLUDING those
        // inside an element that scrolls horizontally on
        // purpose -- the nav strip is meant to overflow
        // itself, and counting it would report the design as
        // a bug.
        var offenders = [];

        inner.querySelectorAll("*").forEach(function (node) {

            var rect = node.getBoundingClientRect();

            if (rect.right <= view + 1) {
                return;
            }

            var parent = node.parentElement;
            var scrolls = false;

            while (parent && parent !== root) {
                var style = inner.defaultView.getComputedStyle(parent);
                if (style.overflowX === "auto" || style.overflowX === "scroll") {
                    scrolls = true;
                    break;
                }
                parent = parent.parentElement;
            }

            if (!scrolls) {
                offenders.push(
                    node.tagName.toLowerCase()
                    + "." + (node.className || "").toString()
                        .split(" ").filter(Boolean).slice(0, 2).join(".")
                    + "@" + Math.round(rect.right)
                );
            }
        });

        document.title = "VIEW=" + view
            + " SCROLL=" + scroll
            + " OVER=" + (scroll - view)
            + " OFFENDERS=" + offenders.slice(0, 8).join(",");
    }, 900);
});
</script>
</body>
</html>
"""


def start_snapshot_server(
    *,
    snapshots: dict,
) -> tuple:

    """
    A throwaway HTTP server holding the captured page
    snapshots and the real static assets.

    Returns (base_url, shutdown_callable, root_path).

    Plain http.server on a loopback port, so there is no CSP
    and the harness's inline script runs. It serves only what
    is copied into a temporary directory and it goes away with
    the run.
    """

    import http.server
    import shutil as _shutil
    import socket
    import threading

    root = Path(
        tempfile.mkdtemp(
            prefix="vigilox-snapshot-",
        )
    )

    # The real stylesheets and scripts, so the layout under
    # test is the layout that ships.
    _shutil.copytree(
        PROJECT_ROOT
        / "frontend"
        / "static",
        root / "static",
        dirs_exist_ok=True,
    )

    for name, dom in snapshots.items():

        # The snapshots reference /review/static/...; the
        # throwaway server roots the same tree at /static/.
        (
            root
            / f"{name}.html"
        ).write_text(
            dom.replace(
                '="/review/static/',
                '="/static/',
            ),
            encoding="utf-8",
        )

    with socket.socket() as probe:

        probe.bind(
            (
                "127.0.0.1",
                0,
            )
        )

        port = probe.getsockname()[1]

    class Handler(
        http.server.SimpleHTTPRequestHandler
    ):

        def __init__(
            self,
            *arguments,
            **keywords,
        ):
            super().__init__(
                *arguments,
                directory=str(
                    root
                ),
                **keywords,
            )

        def log_message(
            self,
            *arguments,
        ):
            pass

    server = http.server.ThreadingHTTPServer(
        (
            "127.0.0.1",
            port,
        ),
        Handler,
    )

    threading.Thread(
        target=server.serve_forever,
        daemon=True,
    ).start()

    def stop() -> None:

        server.shutdown()

        _shutil.rmtree(
            root,
            ignore_errors=True,
        )

    return (
        f"http://127.0.0.1:{port}",
        stop,
        root,
    )


def write_harness(
    *,
    root: Path,
    page_url: str,
    width: int,
    height: int,
) -> Path:

    path = root / HARNESS_NAME

    path.write_text(
        HARNESS_TEMPLATE
        .replace(
            "__PAGE__",
            page_url,
        )
        .replace(
            "__WIDTH__",
            str(
                width
            ),
        )
        .replace(
            "__HEIGHT__",
            str(
                height
            ),
        ),
        encoding="utf-8",
    )

    return path


def read_title(
    output: str,
) -> str:

    if "<title>" not in output:
        return ""

    return output.split(
        "<title>",
        1,
    )[1].split(
        "</title>",
        1,
    )[0].strip()


# ==========================================================
# THE APPLICATION UNDER TEST
# ==========================================================

def wait_for(
    url: str,
    *,
    seconds: float,
) -> bool:

    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:

        try:

            with urllib.request.urlopen(
                url,
                timeout=5,
            ) as response:

                if response.status == 200:
                    return True

        except (
            urllib.error.URLError,
            OSError,
        ):
            time.sleep(
                0.5
            )

    return False


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Render every page in a real browser and capture "
            "the result."
        ),
    )

    parser.add_argument(
        "--base-url",
        default="",
        help=(
            "An already-running deployment. If omitted, a "
            "local API is started for the duration."
        ),
    )

    parser.add_argument(
        "--output",
        default="",
        help=(
            "Where to write screenshots and DOM dumps. "
            "Defaults to output/browser-acceptance."
        ),
    )

    arguments = parser.parse_args()

    print(
        "=" * 66
    )
    print(
        "VIGILOX REAL BROWSER ACCEPTANCE"
    )
    print(
        "=" * 66
    )

    browser = find_browser()

    if browser is None:

        print()
        print(
            "EXTERNAL_BLOCKED: no Chrome or Edge binary was "
            "found."
        )
        print(
            "  Looked on PATH, in VIGILOX_BROWSER, and in "
            "the usual install locations."
        )
        print()
        print(
            "  NOT PASSING. A browser acceptance run that "
            "skips when it cannot find a browser is the "
            "reassurance nobody should have."
        )
        return 1

    print(
        f"  browser: {browser}"
    )

    destination = Path(
        arguments.output
        or (
            PROJECT_ROOT
            / "output"
            / "browser-acceptance"
        )
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        f"  output : {destination}"
    )

    # ------------------------------------------------------
    # THE SERVER
    # ------------------------------------------------------

    server = None

    profile = Path(
        tempfile.mkdtemp(
            prefix="vigilox-browser-",
        )
    )

    log = destination / "server.log"

    try:

        if arguments.base_url:

            base = arguments.base_url.rstrip(
                "/"
            )

        else:

            import socket

            with socket.socket() as probe:

                probe.bind(
                    (
                        "127.0.0.1",
                        0,
                    )
                )

                port = probe.getsockname()[1]

            base = f"http://127.0.0.1:{port}"

            environment = dict(
                os.environ
            )

            environment["PYTHONPATH"] = str(
                PROJECT_ROOT
            )

            # Lazy: this renders pages, it does not run OCR.
            environment[
                "VIGILOX_API_EAGER_PIPELINE"
            ] = "false"

            handle = log.open(
                "wb",
            )

            server = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "uvicorn",
                    "backend.app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(
                        port
                    ),
                ],
                stdout=handle,
                stderr=subprocess.STDOUT,
                cwd=str(
                    PROJECT_ROOT
                ),
                env=environment,
            )

            print(
                f"  serving: {base}"
            )

            if not wait_for(
                f"{base}/health",
                seconds=120,
            ):

                print()
                print(
                    "[FAIL] the API did not come up."
                )
                print(
                    log.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )[-2000:]
                )
                return 1

        failures = []

        report = {
            "browser": str(
                browser
            ),
            "base_url": base,
            "pages": {},
        }

        snapshots = {}

        # --------------------------------------------------
        # 1. THE FAVICON, BEFORE ANYTHING ELSE
        # --------------------------------------------------

        print()
        print(
            "  [1] favicon"
        )

        try:

            with urllib.request.urlopen(
                f"{base}/favicon.ico",
                timeout=20,
            ) as response:

                icon = response.read()

            print(
                f"      [ok] HTTP {response.status}, "
                f"{len(icon)} bytes"
            )

            report["favicon_bytes"] = len(
                icon
            )

        except Exception as error:

            print(
                f"      [FAIL] {error}"
            )
            failures.append(
                "favicon"
            )

        # --------------------------------------------------
        # 2. POST-JAVASCRIPT DOM PER PAGE
        # --------------------------------------------------
        #
        # --dump-dom runs the page's JavaScript and prints the
        # resulting DOM. A page that parsed but whose modules
        # threw looks completely different here from one that
        # populated, which is the thing a static read of the
        # HTML cannot tell you.

        print()
        print(
            "  [2] rendered DOM"
        )

        for name, route in PAGES:

            completed = run_browser(
                browser,
                "--dump-dom",
                f"{base}{route}",
                profile=profile,
            )

            dom = completed.stdout

            path = (
                destination
                / f"{name}.dom.html"
            )

            path.write_text(
                dom,
                encoding="utf-8",
            )

            # Kept in memory as well: the overflow measurement
            # below renders these snapshots rather than the
            # live pages, because the live pages' CSP blocks
            # the harness script.
            snapshots[name] = dom

            title = ""

            if "<title>" in dom:

                title = dom.split(
                    "<title>",
                    1,
                )[1].split(
                    "</title>",
                    1,
                )[0].strip()

            branded = "VIGILOX" in title

            linked = "favicon" in dom

            # A populated page is much larger than a shell.
            # This is a floor, not a precise measure: the
            # point is to catch a page whose JavaScript threw
            # before it rendered anything.
            substantial = len(
                dom
            ) > 4000

            page_report = {
                "title": title,
                "dom_bytes": len(
                    dom
                ),
                "branded_title": branded,
                "links_icon": linked,
            }

            report["pages"][name] = page_report

            if (
                branded
                and linked
                and substantial
            ):

                print(
                    f"      [ok] {route:12} "
                    f"{len(dom):>7} bytes  "
                    f"title={title!r}"
                )

            else:

                print(
                    f"      [FAIL] {route}: "
                    f"branded={branded} icon={linked} "
                    f"bytes={len(dom)}"
                )
                failures.append(
                    f"dom:{name}"
                )

        # --------------------------------------------------
        # 3. MEASURED HORIZONTAL OVERFLOW
        # --------------------------------------------------
        #
        # The assertion that used to be a person squinting at
        # a screenshot. scrollWidth greater than clientWidth
        # is page-level horizontal overflow, full stop --
        # there is nothing subjective in it.
        #
        # Elements inside a deliberately scrolling container
        # are excluded, because the nav strip is SUPPOSED to
        # overflow itself at narrow widths.

        print()
        print(
            "  [3] horizontal overflow, measured in a real "
            "layout engine"
        )

        snapshot_base, stop_snapshots, snapshot_root = (
            start_snapshot_server(
                snapshots=snapshots,
            )
        )

        try:

            for name, route in PAGES:

                worst = 0

                measured = 0

                for width in MEASURED_WIDTHS:

                    write_harness(
                        root=snapshot_root,
                        page_url=f"/{name}.html",
                        width=width,
                        height=900,
                    )

                    completed = run_browser(
                        browser,
                        "--window-size=1600,1000",
                        "--virtual-time-budget=6000",
                        "--dump-dom",
                        f"{snapshot_base}/{HARNESS_NAME}",
                        profile=profile,
                    )

                    title = read_title(
                        completed.stdout
                    )

                    if "OVER=" not in title:

                        print(
                            f"      [FAIL] {name} @ {width}: "
                            "no measurement"
                        )
                        failures.append(
                            f"measure:{name}:{width}"
                        )
                        continue

                    measured += 1

                    view = int(
                        title.split(
                            "VIEW=",
                            1,
                        )[1].split()[0]
                    )

                    over = int(
                        title.split(
                            "OVER=",
                            1,
                        )[1].split()[0]
                    )

                    offenders = (
                        title.split(
                            "OFFENDERS=",
                            1,
                        )[1].strip()
                        if "OFFENDERS=" in title
                        else ""
                    )

                    # The iframe must actually have got the
                    # width asked for, or the measurement is
                    # about a different layout than the label
                    # claims -- which is the exact mistake the
                    # viewport note above describes.
                    if view != width:

                        print(
                            f"      [FAIL] {name} @ {width}: "
                            f"the frame reported {view}px. "
                            "The measurement does not "
                            "describe the width it claims to."
                        )
                        failures.append(
                            f"viewport:{name}:{width}"
                        )
                        continue

                    if over > 0:

                        print(
                            f"      [FAIL] {name} @ {width}px "
                            f"overflows by {over}px  "
                            f"{offenders[:60]}"
                        )
                        failures.append(
                            f"overflow:{name}:{width}"
                        )

                        worst = max(
                            worst,
                            over,
                        )

                report.setdefault(
                    "overflow",
                    {},
                )[name] = {
                    "worst_overflow_px": worst,
                    "widths_measured": measured,
                }

                if worst == 0 and measured == len(
                    MEASURED_WIDTHS
                ):

                    print(
                        f"      [ok] {name:12} no overflow at "
                        f"any of {measured} widths "
                        f"({MEASURED_WIDTHS[0]}-"
                        f"{MEASURED_WIDTHS[-1]}px)"
                    )

            # ----------------------------------------------
            # 3b. SCREENSHOTS
            # ----------------------------------------------
            #
            # Above the clamp, rendered directly from the live
            # application. Below it, rendered through the
            # harness so the image shows a real narrow layout
            # rather than a wide one with its right-hand side
            # cut off.

            print()
            print(
                "  [3b] screenshots"
            )

            for label, width, height in DIRECT_VIEWPORTS:

                for name, route in PAGES:

                    shot = (
                        destination
                        / f"{name}-{label}-"
                        f"{width}x{height}.png"
                    )

                    run_browser(
                        browser,
                        f"--screenshot={shot}",
                        f"--window-size={width},{height}",
                        f"{base}{route}",
                        profile=profile,
                    )

                    if not shot.is_file() or (
                        shot.stat().st_size < 3000
                    ):

                        print(
                            f"      [FAIL] {name} {label}: "
                            "did not paint"
                        )
                        failures.append(
                            f"shot:{name}:{label}"
                        )
                        continue

                    print(
                        f"      [ok] {name:12} {label:14} "
                        f"{width}x{height} live  "
                        f"{shot.stat().st_size:>7} bytes"
                    )

            for label, width, height in FRAMED_VIEWPORTS:

                for name, route in PAGES:

                    write_harness(
                        root=snapshot_root,
                        page_url=f"/{name}.html",
                        width=width,
                        height=height,
                    )

                    shot = (
                        destination
                        / f"{name}-{label}-"
                        f"{width}x{height}.png"
                    )

                    run_browser(
                        browser,
                        f"--screenshot={shot}",
                        f"--window-size={width + 20},"
                        f"{height + 20}",
                        "--virtual-time-budget=6000",
                        f"{snapshot_base}/{HARNESS_NAME}",
                        profile=profile,
                    )

                    if not shot.is_file() or (
                        shot.stat().st_size < 3000
                    ):

                        print(
                            f"      [FAIL] {name} {label}: "
                            "did not paint"
                        )
                        failures.append(
                            f"shot:{name}:{label}"
                        )
                        continue

                    print(
                        f"      [ok] {name:12} {label:14} "
                        f"{width}px framed  "
                        f"{shot.stat().st_size:>7} bytes"
                    )

        finally:

            # The throwaway server and its directory go away
            # with the run. Nothing is written into the
            # application's own static tree, so there is no
            # stray page left served.
            stop_snapshots()

        # --------------------------------------------------
        # 4. WHAT THE SERVER SAW
        # --------------------------------------------------
        #
        # A 404 for a static asset is invisible in a
        # screenshot and obvious in the access log. The
        # application's access log is off by policy, so this
        # only applies to the locally started server, which
        # runs with uvicorn's default logging.

        if server is not None:

            print()
            print(
                "  [4] server log"
            )

            text = log.read_text(
                encoding="utf-8",
                errors="replace",
            )

            missing = [
                line
                for line in text.splitlines()
                if " 404 " in line
                or " 500 " in line
            ]

            if missing:

                print(
                    f"      [FAIL] {len(missing)} request(s) "
                    "returned 404 or 500:"
                )

                for line in missing[:12]:
                    print(
                        f"             {line.strip()}"
                    )

                failures.append(
                    "server-errors"
                )

            else:

                print(
                    "      [ok] every request the browser "
                    "made was served"
                )

        (
            destination
            / "report.json"
        ).write_text(
            json.dumps(
                report,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print(
            "=" * 66
        )

        if failures:

            print(
                "BROWSER ACCEPTANCE FAILED: "
                + ", ".join(
                    failures
                )
            )
            print(
                "=" * 66
            )
            return 1

        print(
            "BROWSER ACCEPTANCE PASSED"
        )
        print(
            f"  {len(PAGES)} pages: overflow measured at "
            f"{len(MEASURED_WIDTHS)} widths, "
            f"{len(PAGES) * (len(DIRECT_VIEWPORTS) + len(FRAMED_VIEWPORTS))}"
            " screenshots"
        )
        print(
            f"  {destination}"
        )
        print()
        print(
            "WHAT THIS PROVES: every page painted in a real "
            "layout engine, was branded, served every asset, "
            "and has no page-level horizontal overflow "
            f"between {MEASURED_WIDTHS[0]} and "
            f"{MEASURED_WIDTHS[-1]}px."
        )
        print()
        print(
            "WHAT IT DOES NOT: it cannot click. Upload flows, "
            "review submission and tab switching are covered "
            "by the harness tests. Colour and visual balance "
            "still want a human look at the screenshots."
        )
        print(
            "=" * 66
        )

        return 0

    finally:

        if server is not None and server.poll() is None:

            server.terminate()

            try:
                server.wait(
                    timeout=30,
                )

            except Exception:
                server.kill()

        shutil.rmtree(
            profile,
            ignore_errors=True,
        )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
