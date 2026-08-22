"""
==========================================================
PHASE 11.16 - BROWSER BRANDING
==========================================================

Before this phase the application had no icon at all. Five
tabs of it showed the browser's generic blank page mark, and
every page load logged a 404 for /favicon.ico that no page
had asked for.

WHAT THIS SUITE IS PROTECTING

  1. THE ICON EXISTS, IS SERVED, AND IS THE SAME EVERYWHERE.
     Five pages linking four different icons is worse than
     none: the tab changes as the reviewer navigates.

  2. /favicon.ico DOES NOT 404.
     Browsers request it unprompted, at the root, with no
     link telling them to. Some fall back to a blank icon for
     the whole origin after one 404 -- which is the exact
     outcome this phase exists to remove.

  3. NO EXTERNAL ICON URL.
     A favicon fetched from a CDN is a third-party request on
     every page load of an application that handles identity
     documents, and the Content Security Policy would have to
     allow that host.

  4. THE TITLES ARE USEFUL AT TAB WIDTH.
     A tab shows perhaps fifteen characters. With the product
     name first, five tabs all read "VIGILOX ..." and are
     indistinguishable at exactly the moment a reviewer is
     looking for one of them.

  5. THE ICON IS LEGIBLE AT 16 PIXELS.
     Checked by rendering it, not by trusting the file
     extension.
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile

from pathlib import Path


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


CANONICAL_SVG = "/review/static/favicon.svg"

CANONICAL_ICO = "/review/static/favicon.ico"

APPLE_ICON = "/review/static/apple-touch-icon.png"


PAGES = {
    "dashboard.html": (
        "/dashboard",
        "Dashboard",
    ),
    "upload.html": (
        "/upload",
        "Upload Document",
    ),
    "documents.html": (
        "/documents",
        "Documents",
    ),
    "index.html": (
        "/review",
        "Review Queue",
    ),
    "review_detail.html": (
        "/review/abc-123",
        "Document Review",
    ),
}


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
# TEST 1 - THE ASSETS EXIST AND ARE WHAT THEY CLAIM
# ==========================================================

def test_assets_exist():

    section(
        "TEST 1 - THE ICON FILES EXIST AND ARE REAL IMAGES"
    )

    static = (
        PROJECT_ROOT
        / "frontend"
        / "static"
    )

    svg = static / "favicon.svg"

    ico = static / "favicon.ico"

    apple = static / "apple-touch-icon.png"

    for path in (
        svg,
        ico,
        apple,
    ):

        assert_true(
            path.is_file(),
            (
                f"{path.relative_to(PROJECT_ROOT).as_posix()} "
                f"must exist."
            ),
        )

        assert_true(
            path.stat().st_size > 0,
            f"{path.name} must not be empty.",
        )


    # ------------------------------------------------------
    # THE SVG IS AN SVG, AND SELF-CONTAINED
    # ------------------------------------------------------

    svg_text = svg.read_text(
        encoding="utf-8"
    )

    assert_true(
        "<svg" in svg_text,
        "favicon.svg must contain an svg element.",
    )

    assert_true(
        "viewBox" in svg_text,
        (
            "favicon.svg must declare a viewBox, or it does "
            "not scale."
        ),
    )

    for forbidden, why in (
        (
            "<image",
            (
                "an embedded raster defeats the point of a "
                "vector icon"
            ),
        ),
        (
            "http://",
            "an external reference",
        ),
        (
            "https://",
            "an external reference",
        ),
        (
            "<script",
            "script in an icon",
        ),
    ):

        # xmlns is a namespace declaration, not a fetch.
        occurrences = [
            match
            for match in re.findall(
                re.escape(
                    forbidden
                )
                + r"[^\s\"'>]*",
                svg_text,
            )
            if "www.w3.org" not in match
        ]

        assert_equal(
            occurrences,
            [],
            (
                f"favicon.svg contains {forbidden!r} "
                f"({why}): {occurrences}"
            ),
        )

    ok(
        f"favicon.svg ({svg.stat().st_size} bytes) is a "
        f"self-contained vector with a viewBox and no external "
        f"reference"
    )


    # ------------------------------------------------------
    # THE ICO IS A REAL MULTI-SIZE ICO
    # ------------------------------------------------------
    # Read with an image library rather than trusting the
    # extension. A renamed PNG has a .ico name and does not
    # render in the address bar.
    # ------------------------------------------------------

    from PIL import Image

    with Image.open(
        ico
    ) as image:

        assert_equal(
            image.format,
            "ICO",
            (
                "favicon.ico must actually be an ICO. A "
                "renamed PNG carries the right extension and "
                "does not render."
            ),
        )

        sizes = sorted(
            image.info.get(
                "sizes",
                [],
            )
        )

    assert_true(
        (
            16,
            16,
        )
        in sizes,
        (
            f"favicon.ico must contain a 16x16 image -- the "
            f"size a browser tab actually uses. Sizes present: "
            f"{sizes}"
        ),
    )

    assert_true(
        len(
            sizes
        )
        >= 2,
        (
            f"favicon.ico should carry more than one size, so "
            f"the address bar and a bookmark bar are not both "
            f"scaling the same bitmap. Sizes: {sizes}"
        ),
    )

    ok(
        f"favicon.ico is a real ICO carrying "
        f"{len(sizes)} sizes: "
        + ", ".join(
            f"{width}x{height}"
            for width, height in sizes
        )
    )


# ==========================================================
# TEST 2 - THE MARK IS LEGIBLE AT 16 PIXELS
# ==========================================================

def test_legible_at_tab_size():

    section(
        "TEST 2 - THE MARK STILL READS AT 16 PIXELS"
    )

    from PIL import Image

    ico = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "favicon.ico"
    )

    with Image.open(
        ico
    ) as image:

        image.size = (
            16,
            16,
        )

        small = image.convert(
            "RGBA"
        )

    pixels = list(
        small.getdata()
    )

    assert_equal(
        len(
            pixels
        ),
        256,
        "The 16x16 image must have 256 pixels.",
    )


    # ------------------------------------------------------
    # IT IS NOT BLANK
    # ------------------------------------------------------
    # The failure this catches: an icon that is technically
    # present and renders as nothing.
    # ------------------------------------------------------

    opaque = [
        pixel
        for pixel in pixels
        if pixel[3] > 32
    ]

    assert_true(
        len(
            opaque
        )
        > 128,
        (
            f"Only {len(opaque)} of 256 pixels are opaque at "
            f"16x16. A mostly transparent icon reads as the "
            f"browser's blank mark, which is what this phase "
            f"is removing."
        ),
    )


    # ------------------------------------------------------
    # THERE IS REAL CONTRAST INSIDE IT
    # ------------------------------------------------------
    # A filled tile with no legible mark on it would pass the
    # opacity check above. What makes a favicon readable is
    # that it has a light part and a dark part.
    # ------------------------------------------------------

    def luminance(
        pixel,
    ) -> float:

        red, green, blue, _ = pixel

        return (
            0.2126 * red
            + 0.7152 * green
            + 0.0722 * blue
        )

    values = [
        luminance(
            pixel
        )
        for pixel in opaque
    ]

    darkest = min(
        values
    )

    brightest = max(
        values
    )

    spread = brightest - darkest

    assert_true(
        spread > 100,
        (
            f"The luminance spread inside the icon is "
            f"{spread:.0f} out of 255. A mark needs a light "
            f"part and a dark part to read at 16 pixels; a "
            f"flat tile is a coloured square."
        ),
    )

    # And enough of the icon is the light mark, so the V is a
    # shape rather than a few stray pixels.
    light = [
        value
        for value in values
        if value > (
            darkest
            + spread * 0.6
        )
    ]

    share = len(
        light
    ) / len(
        opaque
    )

    assert_true(
        0.05 < share < 0.6,
        (
            f"The light part of the mark is {share:.0%} of the "
            f"icon. Below 5% it is a few pixels and reads as "
            f"noise; above 60% the mark has swallowed the "
            f"tile and there is no shape left."
        ),
    )

    ok(
        f"at 16x16: {len(opaque)}/256 pixels opaque, "
        f"luminance spread {spread:.0f}/255, light mark "
        f"{share:.0%} of the icon"
    )


    # ------------------------------------------------------
    # THE COLOUR IS THE PRODUCT'S
    # ------------------------------------------------------

    tokens = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "css"
        / "tokens.css"
    ).read_text(
        encoding="utf-8"
    )

    primary = re.search(
        r"--primary:\s*#([0-9a-fA-F]{6})",
        tokens,
    )

    assert_true(
        primary is not None,
        "tokens.css must define --primary.",
    )

    brand = primary.group(
        1
    ).lower()

    svg_text = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "favicon.svg"
    ).read_text(
        encoding="utf-8"
    )

    assert_true(
        brand in svg_text.lower(),
        (
            f"The icon must use the product's brand colour "
            f"#{brand} from tokens.css, so the tab matches "
            f"the application rather than approximating it."
        ),
    )

    ok(
        f"the icon uses #{brand}, the --primary token from "
        f"the design system"
    )


# ==========================================================
# TEST 3 - EVERY PAGE LINKS THE SAME ICON
# ==========================================================

def test_pages_link_the_canonical_icon():

    section(
        "TEST 3 - ALL FIVE PAGES LINK THE SAME ICON AND "
        "CARRY A USEFUL TITLE"
    )

    for name, (
        route,
        expected_label,
    ) in PAGES.items():

        path = (
            PROJECT_ROOT
            / "frontend"
            / "pages"
            / name
        )

        html = path.read_text(
            encoding="utf-8"
        )


        # --------------------------------------------------
        # THE ICON
        # --------------------------------------------------

        assert_true(
            CANONICAL_SVG in html,
            (
                f"{name} must link the canonical SVG icon "
                f"{CANONICAL_SVG}. Five pages linking "
                f"different icons means the tab changes as "
                f"the reviewer navigates."
            ),
        )

        assert_true(
            CANONICAL_ICO in html,
            (
                f"{name} must link the ICO fallback, which is "
                f"what anything not taking the SVG fetches "
                f"for the address bar and bookmarks."
            ),
        )

        assert_true(
            APPLE_ICON in html,
            (
                f"{name} must link the apple-touch-icon. iOS "
                f"ignores both of the others when a page is "
                f"added to the home screen and renders a "
                f"screenshot instead."
            ),
        )


        # --------------------------------------------------
        # NO EXTERNAL ICON
        # --------------------------------------------------

        external = re.findall(
            r'<link[^>]*rel="[^"]*icon[^"]*"[^>]*href="'
            r'(https?:)?//[^"]*"',
            html,
        )

        assert_equal(
            external,
            [],
            (
                f"{name} links an icon from an external host: "
                f"{external}\n"
                "That is a third-party request on every page "
                "load of an application handling identity "
                "documents, and the Content Security Policy "
                "would have to allow the host."
            ),
        )


        # --------------------------------------------------
        # THE TITLE
        # --------------------------------------------------

        title = re.search(
            r"<title>\s*(.*?)\s*</title>",
            html,
            re.DOTALL,
        )

        assert_true(
            title is not None,
            f"{name} must have a title.",
        )

        text = " ".join(
            title.group(
                1
            ).split()
        )

        assert_true(
            "VIGILOX" in text,
            (
                f"{name}'s title must contain VIGILOX, got "
                f"{text!r}."
            ),
        )

        assert_true(
            expected_label in text,
            (
                f"{name}'s title must name the page "
                f"({expected_label!r}), got {text!r}."
            ),
        )

        # The distinguishing word FIRST. A tab shows perhaps
        # fifteen characters; with the product name first, all
        # five tabs read "VIGILOX ..." and are
        # indistinguishable.
        assert_true(
            text.startswith(
                expected_label
            ),
            (
                f"{name}'s title is {text!r}. The page name "
                f"must come FIRST.\n"
                "A browser tab truncates to roughly fifteen "
                "characters. With the product name leading, "
                "every tab of this application reads "
                "'VIGILOX ...' and a reviewer cannot tell "
                "them apart -- at exactly the moment they are "
                "looking for one."
            ),
        )

    ok(
        f"all {len(PAGES)} pages link the same 3 icon assets "
        f"and lead with the page name"
    )


    # ------------------------------------------------------
    # AND THE TITLES ARE DISTINCT
    # ------------------------------------------------------

    titles = []

    for name in PAGES:

        html = (
            PROJECT_ROOT
            / "frontend"
            / "pages"
            / name
        ).read_text(
            encoding="utf-8"
        )

        titles.append(
            " ".join(
                re.search(
                    r"<title>\s*(.*?)\s*</title>",
                    html,
                    re.DOTALL,
                )
                .group(
                    1
                )
                .split()
            )
        )

    assert_equal(
        len(
            set(
                titles
            )
        ),
        len(
            titles
        ),
        (
            f"Two pages share a title: {titles}\n"
            "Distinct titles are the point of having them."
        ),
    )

    ok(
        "5 distinct titles: "
        + "; ".join(
            titles
        )
    )


# ==========================================================
# TEST 4 - THE SERVER ACTUALLY SERVES THEM
# ==========================================================

def test_icons_are_served():

    section(
        "TEST 4 - THE ICONS RETURN 200 AND /favicon.ico DOES "
        "NOT 404"
    )

    probe = """
import json
import re

from fastapi.testclient import TestClient

from backend.app.main import app


out = {"assets": {}, "pages": {}}

with TestClient(app) as client:

    for path in (
        "/favicon.ico",
        "/review/static/favicon.svg",
        "/review/static/favicon.ico",
        "/review/static/apple-touch-icon.png",
    ):

        response = client.get(path)

        out["assets"][path] = {
            "status": response.status_code,
            "content_type": response.headers.get(
                "content-type"
            ),
            "bytes": len(response.content),
        }

    for route in (
        "/dashboard",
        "/upload",
        "/documents",
        "/review",
        "/review/abc-123",
    ):

        response = client.get(route)

        title = re.search(
            r"<title>\\s*(.*?)\\s*</title>",
            response.text,
            re.DOTALL,
        )

        out["pages"][route] = {
            "status": response.status_code,
            "title": (
                " ".join(title.group(1).split())
                if title
                else None
            ),
            "svg": "/review/static/favicon.svg"
            in response.text,
            "ico": "/review/static/favicon.ico"
            in response.text,
        }

print(json.dumps(out))
"""

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "iconprobe.py"
        )

        script.write_text(
            probe,
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(
                PROJECT_ROOT
            ),
            env=environment,
        )

    assert_equal(
        completed.returncode,
        0,
        (
            "The icon probe must run.\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    observed = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )


    # ------------------------------------------------------
    # THE UNPROMPTED REQUEST
    # ------------------------------------------------------

    root = observed["assets"][
        "/favicon.ico"
    ]

    assert_equal(
        root["status"],
        200,
        (
            "GET /favicon.ico must not 404.\n"
            "Browsers request it unprompted, at the root, with "
            "no link telling them to. A 404 fills the access "
            "log on every cold page load, and some browsers "
            "fall back to a blank icon for the whole origin "
            "after one -- the exact outcome this phase is "
            "removing."
        ),
    )

    assert_true(
        root["bytes"] > 0,
        "The served icon must have content.",
    )

    for path, expected_type in (
        (
            "/review/static/favicon.svg",
            "image/svg+xml",
        ),
        (
            "/review/static/favicon.ico",
            "image/x-icon",
        ),
        (
            "/review/static/apple-touch-icon.png",
            "image/png",
        ),
    ):

        asset = observed["assets"][path]

        assert_equal(
            asset["status"],
            200,
            f"{path} must be served.",
        )

        assert_true(
            expected_type
            in (
                asset["content_type"]
                or ""
            ),
            (
                f"{path} must be served as {expected_type}, "
                f"got {asset['content_type']!r}. A browser "
                f"that does not recognise the type will not "
                f"render it."
            ),
        )

    ok(
        f"/favicon.ico returns 200 ({root['bytes']} bytes); "
        f"all 3 linked assets serve with the right content "
        f"type"
    )


    # ------------------------------------------------------
    # THE SAME ICON EVERYWHERE, SERVED
    # ------------------------------------------------------
    # Checked against the RENDERED page rather than the source
    # file, because a page can be served from somewhere other
    # than the file that was read above.
    # ------------------------------------------------------

    for route, page in observed["pages"].items():

        assert_equal(
            page["status"],
            200,
            f"{route} must render.",
        )

        assert_true(
            page["svg"] and page["ico"],
            (
                f"The page served at {route} must link the "
                f"canonical icon. svg={page['svg']} "
                f"ico={page['ico']}"
            ),
        )

        assert_true(
            page["title"]
            and "VIGILOX" in page["title"],
            (
                f"The page served at {route} must have a "
                f"VIGILOX title, got {page['title']!r}."
            ),
        )

    served_titles = sorted(
        page["title"]
        for page in observed["pages"].values()
    )

    ok(
        f"all {len(observed['pages'])} served pages link the "
        f"canonical icon and carry a VIGILOX title"
    )

    for title in served_titles:
        print(
            f"       {title}"
        )


# ==========================================================
# TEST 5 - THE ICON SHIPS IN THE IMAGE
# ==========================================================

def test_icon_ships_with_the_deployment():

    section(
        "TEST 5 - THE ICON IS INSIDE THE CONTAINER IMAGE"
    )

    dockerfile = (
        PROJECT_ROOT
        / "Dockerfile"
    ).read_text(
        encoding="utf-8"
    )

    # The icons live under frontend/static/, and the Dockerfile
    # copies frontend/ wholesale. What matters is that nothing
    # excludes them.
    assert_true(
        "COPY frontend/" in dockerfile,
        (
            "The image must copy frontend/, which is where "
            "the icon assets live."
        ),
    )

    ignore = (
        PROJECT_ROOT
        / ".dockerignore"
    ).read_text(
        encoding="utf-8"
    )

    rules = [
        line.strip()
        for line in ignore.splitlines()
        if line.strip()
        and not line.strip().startswith(
            "#"
        )
    ]

    blocking = [
        rule
        for rule in rules
        if rule.rstrip(
            "/"
        )
        in (
            "frontend",
            "frontend/static",
        )
        or rule
        in (
            "*.svg",
            "*.ico",
            "*.png",
        )
    ]

    assert_equal(
        blocking,
        [],
        (
            f".dockerignore excludes the icon assets from the "
            f"build context: {blocking}\n"
            "The image would serve a 404 for its own favicon."
        ),
    )

    ok(
        "the image copies frontend/ and .dockerignore "
        "excludes no icon asset"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.16 - BROWSER BRANDING"
    )
    print(
        "=" * 74
    )

    test_assets_exist()
    test_legible_at_tab_size()
    test_pages_link_the_canonical_icon()
    test_icons_are_served()
    test_icon_ships_with_the_deployment()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.16 BROWSER BRANDING TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
