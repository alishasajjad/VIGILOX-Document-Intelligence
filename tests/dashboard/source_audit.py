# ==========================================================
# SOURCE AUDIT HELPERS
# PHASE 8.9
# ==========================================================
#
# Assertions about code must inspect code, not prose.
#
# This is not a hypothetical. Every rebuilt Phase 8 module
# carries a header explaining what it replaced, and those
# headers name the thing they removed:
#
#     "innerHTML string templates -> safe node building"
#     "raw fetch + detail errors  -> shared client"
#
# A naive `"innerHTML" in source` check matches the sentence
# that documents its removal, and fails for exactly the wrong
# reason. Comments are stripped first.
#
# The stripper is string-aware, so a quoted "/*" inside a
# regular string literal does not start a comment.
# ==========================================================


def strip_js_comments(
    source: str,
) -> str:

    result = []

    index = 0
    length = len(
        source
    )

    in_string = None


    while index < length:

        char = source[
            index
        ]


        # ==================================================
        # INSIDE A STRING LITERAL
        # ==================================================

        if in_string is not None:

            result.append(
                char
            )


            if char == "\\":

                if index + 1 < length:

                    result.append(
                        source[
                            index + 1
                        ]
                    )

                    index += 2

                    continue


            elif char == in_string:

                in_string = None


            index += 1

            continue


        # ==================================================
        # STRING START
        # ==================================================

        if char in (
            '"',
            "'",
            "`",
        ):

            in_string = char

            result.append(
                char
            )

            index += 1

            continue


        # ==================================================
        # BLOCK COMMENT
        # ==================================================

        if (
            char == "/"
            and index + 1 < length
            and source[
                index + 1
            ]
            == "*"
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


        # ==================================================
        # LINE COMMENT
        # ==================================================

        if (
            char == "/"
            and index + 1 < length
            and source[
                index + 1
            ]
            == "/"
        ):

            newline = (
                source.find(
                    "\n",
                    index,
                )
            )


            if newline == -1:

                break


            index = newline

            continue


        result.append(
            char
        )

        index += 1


    return "".join(
        result
    )


def strip_css_comments(
    source: str,
) -> str:

    result = []

    index = 0
    length = len(
        source
    )


    while index < length:

        if (
            source[
                index
            ]
            == "/"
            and index + 1 < length
            and source[
                index + 1
            ]
            == "*"
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
            source[
                index
            ]
        )

        index += 1


    return "".join(
        result
    )


# ==========================================================
# SHARED FRONTEND AUDIT
# ==========================================================
#
# The same set of prohibitions applies to every Phase 8
# frontend module, so it is expressed once.
#
#     no HTML-string injection sink
#     no console logging, because payloads carry OCR text and
#         extracted identity values
#     no raw fetch, so error normalisation and request-id
#         handling stay in the shared client
#     no credential material
# ==========================================================

UNSAFE_SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
)


CONSOLE_CALLS = (
    "console.log",
    "console.info",
    "console.warn",
    "console.error",
    "console.debug",
    "console.trace",
)


SECRET_MARKERS = (
    "GROQ_API_KEY",
    "DATABASE_URL",
    "postgresql://",
    "Authorization:",
)


def audit_frontend_module(
    source: str,
    module_name: str,
    allow_fetch: bool = False,
) -> list:

    """
    Returns a list of violation messages. Empty means clean.
    """

    code = (
        strip_js_comments(
            source
        )
    )


    problems = []


    for sink in UNSAFE_SINKS:

        if sink in code:

            problems.append(
                (
                    f"{module_name} uses the unsafe "
                    f"sink {sink}. Untrusted document "
                    "values must be rendered with "
                    "textContent."
                )
            )


    for call in CONSOLE_CALLS:

        if call in code:

            problems.append(
                (
                    f"{module_name} logs to the "
                    f"console via {call}. Frontend "
                    "payloads carry OCR text and "
                    "extracted identity values."
                )
            )


    if (
        not allow_fetch
        and "fetch(" in code
    ):

        problems.append(
            (
                f"{module_name} calls fetch "
                "directly. Requests should go "
                "through the shared API client so "
                "error normalisation and request-id "
                "handling stay in one place."
            )
        )


    lowered = code.lower()


    for marker in SECRET_MARKERS:

        if marker.lower() in lowered:

            problems.append(
                (
                    f"{module_name} contains "
                    f"credential material: {marker}"
                )
            )


    return problems
