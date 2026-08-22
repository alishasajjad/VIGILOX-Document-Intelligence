"""
==========================================================
SECURITY RESPONSE HEADERS AND ORIGIN POLICY
PHASE 11.6
==========================================================

The application shipped with no middleware at all: no
security headers, no framing protection, no content policy,
no origin policy. This adds them.


WHY A PURE ASGI MIDDLEWARE
----------------------------------------------------------
The same reason RequestIDMiddleware is one. Starlette builds
the stack as

    ServerErrorMiddleware
      -> user middleware (this)
        -> ExceptionMiddleware
          -> router

so a header injected in the send wrapper here reaches every
response the router produces, including the ones the error
handlers build. BaseHTTPMiddleware would buffer the body,
which matters for the document image endpoint.

An unhandled 500 rendered by ServerErrorMiddleware sits
OUTSIDE this middleware and does not pass through the wrapper
-- exactly as documented for the request ID. That response is
a bare error page with no document data in it, so the missing
headers carry no information. Worth knowing rather than
worth solving here.


THE CONTENT SECURITY POLICY IS STRICT BECAUSE IT CAN BE
----------------------------------------------------------
Measured against what the pages actually load, not copied
from a template:

    every <script> is src="/review/static/..."   same origin
    every stylesheet is same origin
    no inline <script> anywhere
    no onclick / onload / javascript: anywhere
    no external host referenced by any page
    no inline style attribute -- the five in upload.html
      were removed in Phase 11.6 specifically so this policy
      would not need style-src 'unsafe-inline'

So:

    script-src 'self'    no unsafe-inline, no unsafe-eval
    style-src  'self'    no unsafe-inline
    img-src    'self' data:
                         data: because the upload page
                         previews a selected file before it
                         is sent, which is a data URL
    connect-src 'self'   the API is same-origin
    frame-ancestors 'none'
    object-src 'none'
    base-uri 'none'

If a future page needs a CDN, the policy has to change
deliberately rather than being loose enough already.


CORS: THERE IS NONE, AND THAT IS THE CORRECT POSTURE
----------------------------------------------------------
The frontend is served by this same application from the same
origin. A browser therefore never performs a cross-origin
request, and no Access-Control-Allow-Origin header is needed.

Adding a permissive one would be a downgrade, not a feature:
with credentials in play, Access-Control-Allow-Origin: * is
the difference between an API only your own pages can call
and one any page on the internet can call on behalf of a
logged-in reviewer.

So no CORS headers are emitted at all. VIGILOX_CORS_ORIGINS
exists for a deployment that genuinely serves the frontend
from a different origin, it takes an explicit allowlist, and
it refuses "*". test_phase11_security_headers asserts both
the absence and the refusal.


HSTS IS OPT-IN
----------------------------------------------------------
Strict-Transport-Security tells a browser to refuse plain
HTTP to this host for months. Sent from a deployment that is
not actually behind TLS, it locks users out of their own
service, and it cannot be taken back quickly -- the browser
remembers.

TLS is terminated at the reverse proxy, so this process
cannot tell whether the connection was secure. It therefore
sends HSTS only when told to, by a deployment that knows.
"""

import ipaddress
import os

from starlette.types import ASGIApp, Receive, Scope, Send


# ==========================================================
# CONFIGURATION
# ==========================================================

def _environment() -> str:

    """
    development or production.

    Read here as well as in the identity service because a
    couple of headers are only correct in one of them.
    """

    raw = os.getenv(
        "VIGILOX_ENVIRONMENT",
        "development",
    ).strip().lower()

    return (
        "production"
        if raw == "production"
        else "development"
    )


def _flag(
    name: str,
    default: bool = False,
) -> bool:

    raw = os.getenv(
        name,
        "",
    ).strip().lower()

    if not raw:
        return default

    return raw in (
        "1",
        "true",
        "yes",
        "on",
    )


def cors_origins() -> tuple[str, ...]:

    """
    Explicit allowlist, or empty.

    "*" is rejected rather than honoured. An allowlist that
    allows everything is not an allowlist, and this API is
    called with a reviewer identity attached.
    """

    raw = os.getenv(
        "VIGILOX_CORS_ORIGINS",
        "",
    ).strip()

    if not raw:
        return ()

    origins = tuple(
        origin.strip()
        for origin in raw.split(
            ","
        )
        if origin.strip()
        and origin.strip() != "*"
    )

    return origins


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'none'",
    )
)


# Sent on every response.
BASE_HEADERS = (
    (
        # Stops a browser guessing that a JSON error body is
        # HTML and rendering it.
        b"x-content-type-options",
        b"nosniff",
    ),
    (
        # Redundant beside frame-ancestors 'none' for modern
        # browsers, and the thing that protects older ones.
        b"x-frame-options",
        b"DENY",
    ),
    (
        # A document URL contains a document id. It should not
        # travel to anywhere the user navigates next.
        b"referrer-policy",
        b"no-referrer",
    ),
    (
        # Nothing here needs a camera, a microphone or a
        # location.
        b"permissions-policy",
        b"camera=(), microphone=(), geolocation=()",
    ),
    (
        b"cross-origin-opener-policy",
        b"same-origin",
    ),
    (
        b"content-security-policy",
        CONTENT_SECURITY_POLICY.encode(
            "ascii"
        ),
    ),
)


HSTS_HEADER = (
    b"strict-transport-security",
    b"max-age=31536000; includeSubDomains",
)


# ==========================================================
# TRUSTED PROXIES
# ==========================================================
#
# Defined in backend/app/core/trusted_peers.py and re-exported
# here.
#
# The definitions moved in 12.1 because a SERVICE needed them
# and importing them from backend/app/api/ made the service
# depend upward on the API layer -- the one layering inversion
# the structure audit found. "Is this peer trusted" is a
# question about the network, not about HTTP, so it now lives
# below both callers.
#
# Re-exported rather than relocated outright: these names are
# imported by the rate-limit middleware and by a dozen tests,
# and a rename in the same change as a move makes the move
# hard to review.
# ==========================================================

from backend.app.core.trusted_peers import (  # noqa: F401
    is_trusted_peer,
    parse_trusted_proxies,
    trusted_proxy_networks,
)


# ==========================================================
# MIDDLEWARE
# ==========================================================

class SecurityHeadersMiddleware:

    """
    Attaches security headers, and CORS only if configured.
    """

    def __init__(
        self,
        app: ASGIApp,
    ):

        self.app = app

        # Resolved once at construction. These are deployment
        # configuration, not per-request state, and reading
        # the environment on every response would be a
        # syscall per request for a value that cannot change.
        self.headers = list(
            BASE_HEADERS
        )

        self.send_hsts = _flag(
            "VIGILOX_HSTS_ENABLED",
            default=False,
        )

        if self.send_hsts:
            self.headers.append(
                HSTS_HEADER
            )

        self.allowed_origins = cors_origins()


    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:

        if scope["type"] != "http":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        request_origin = None

        if self.allowed_origins:

            for name, value in scope.get(
                "headers",
                [],
            ):

                if name == b"origin":
                    request_origin = value.decode(
                        "latin-1"
                    )
                    break

        async def send_with_headers(
            message,
        ) -> None:

            if message["type"] != "http.response.start":
                await send(
                    message
                )
                return

            headers = list(
                message.get(
                    "headers",
                    [],
                )
            )

            existing = {
                name.lower()
                for name, _ in headers
            }

            for name, value in self.headers:

                # A route that set its own value keeps it.
                # Nothing does today; this stops a future
                # route being silently overridden.
                if name not in existing:
                    headers.append(
                        (
                            name,
                            value,
                        )
                    )

            # CORS only for an origin on the allowlist, and
            # echoed back specifically rather than as "*".
            if (
                request_origin
                and request_origin
                in self.allowed_origins
            ):
                headers.append(
                    (
                        b"access-control-allow-origin",
                        request_origin.encode(
                            "latin-1"
                        ),
                    )
                )

                headers.append(
                    (
                        b"vary",
                        b"Origin",
                    )
                )

            message["headers"] = headers

            await send(
                message
            )

        await self.app(
            scope,
            receive,
            send_with_headers,
        )


def register_security_headers_middleware(
    app,
) -> None:

    app.add_middleware(
        SecurityHeadersMiddleware
    )
