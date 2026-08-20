import uuid

from typing import Any

from starlette.types import (
    ASGIApp,
    Message,
    Receive,
    Scope,
    Send,
)


# ==========================================================
# REQUEST CORRELATION ID
# PHASE 7C.7e
# ==========================================================
#
# Every HTTP request receives exactly one authoritative
# correlation ID.
#
# The ID is:
#
#     generated server-side
#     stored on request.state.request_id
#     returned as the X-Request-ID response header
#     embedded in structured API error payloads
#     attached to structured operational logs
#
#
# TRUST BOUNDARY
# ----------------------------------------------------------
#
# The client is NOT authoritative for correlation identity.
#
# This mirrors the Phase 7C.5 reviewer-identity rule:
#
#     the browser/client never supplies trusted values.
#
# A client-supplied X-Request-ID is therefore never promoted
# to the authoritative request ID. It is retained separately
# and defensively sanitized so a future trusted-proxy
# tracing contract can consume it without creating a
# trust-boundary regression today.
# ==========================================================

REQUEST_ID_HEADER = (
    "X-Request-ID"
)


CLIENT_REQUEST_ID_MAX_LENGTH = (
    128
)


CLIENT_REQUEST_ID_ALLOWED_CHARACTERS = (
    set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "-_."
    )
)


# ==========================================================
# GENERATE AUTHORITATIVE REQUEST ID
# ==========================================================

def generate_request_id() -> str:

    # ======================================================
    # uuid4 is generated from os.urandom, so a client
    # cannot predict or collide with a server request ID.
    # ======================================================

    return str(
        uuid.uuid4()
    )


# ==========================================================
# SANITIZE CLIENT-SUPPLIED TRACING ID
# ==========================================================

def sanitize_client_request_id(
    raw_value: str | None,
) -> str | None:

    if not raw_value:

        return None


    stripped = (
        raw_value.strip()
    )


    if not stripped:

        return None


    # ======================================================
    # BOUNDED LENGTH
    # ======================================================
    #
    # An unbounded client header must never be able to
    # inflate log records or response headers.
    # ======================================================

    if (
        len(
            stripped
        )
        > CLIENT_REQUEST_ID_MAX_LENGTH
    ):

        return None


    # ======================================================
    # CHARACTER ALLOWLIST
    # ======================================================
    #
    # Rejects header injection, control characters and
    # newline-based log forging.
    # ======================================================

    for character in stripped:

        if (
            character
            not in CLIENT_REQUEST_ID_ALLOWED_CHARACTERS
        ):

            return None


    return stripped


# ==========================================================
# SCOPE STATE ACCESS
# ==========================================================

def get_scope_state(
    scope: Scope,
) -> dict[str, Any]:

    # ======================================================
    # Starlette exposes request.state through:
    #
    #     scope["state"]
    #
    # Writing here before the application runs makes the
    # request ID visible to:
    #
    #     endpoints
    #     ExceptionMiddleware error handlers
    #     ServerErrorMiddleware 500 handler
    #
    # because all of them build their Request object from
    # this same scope.
    # ======================================================

    return scope.setdefault(
        "state",
        {},
    )


# ==========================================================
# REQUEST ID ASGI MIDDLEWARE
# ==========================================================

class RequestIDMiddleware:
    """
    Pure ASGI correlation-ID middleware.

    A pure ASGI implementation is used instead of
    BaseHTTPMiddleware so that:

        the request ID is written into the scope before any
        application code or exception handler runs

        response headers are injected without buffering the
        response body

    IMPORTANT MIDDLEWARE ORDERING NOTE
    ------------------------------------------------------

    Starlette builds the stack as:

        ServerErrorMiddleware
          -> user middleware (this class)
            -> ExceptionMiddleware
              -> router

    An unhandled exception is therefore rendered by
    ServerErrorMiddleware, which sits OUTSIDE this
    middleware. That response never passes through the send
    wrapper below.

    For that reason the central error handlers in
    src/api/error_handlers.py attach the X-Request-ID header
    themselves. Together the two mechanisms guarantee the
    header is present on:

        successful responses
        APIError responses
        HTTPException responses
        validation 422 responses
        unexpected 500 responses
    """

    def __init__(
        self,
        app: ASGIApp,
    ):

        self.app = app


    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:

        # ==================================================
        # NON-HTTP SCOPES
        # ==================================================

        if (
            scope["type"]
            != "http"
        ):

            await self.app(
                scope,
                receive,
                send,
            )


            return


        # ==================================================
        # AUTHORITATIVE SERVER-GENERATED ID
        # ==================================================

        request_id = (
            generate_request_id()
        )


        state = (
            get_scope_state(
                scope
            )
        )


        state[
            "request_id"
        ] = request_id


        # ==================================================
        # NON-AUTHORITATIVE CLIENT TRACING ID
        # ==================================================
        #
        # Retained separately. It never replaces, and never
        # influences, the authoritative request ID.
        # ==================================================

        state[
            "client_request_id"
        ] = (
            sanitize_client_request_id(
                read_incoming_request_id(
                    scope
                )
            )
        )


        # ==================================================
        # RESPONSE HEADER INJECTION
        # ==================================================

        async def send_with_request_id(
            message: Message,
        ) -> None:

            if (
                message["type"]
                == "http.response.start"
            ):

                headers = (
                    list(
                        message.get(
                            "headers",
                            [],
                        )
                    )
                )


                # ==========================================
                # AUTHORITATIVE HEADER
                # ==========================================
                #
                # Any pre-existing X-Request-ID value is
                # replaced so a downstream component can
                # never emit a competing correlation ID.
                # ==========================================

                header_name = (
                    REQUEST_ID_HEADER
                    .lower()
                    .encode(
                        "latin-1"
                    )
                )


                headers = [
                    (
                        existing_name,
                        existing_value,
                    )
                    for (
                        existing_name,
                        existing_value,
                    ) in headers
                    if (
                        existing_name.lower()
                        != header_name
                    )
                ]


                headers.append(
                    (
                        header_name,
                        request_id.encode(
                            "latin-1"
                        ),
                    )
                )


                message = {
                    **message,

                    "headers":
                        headers,
                }


            await send(
                message
            )


        await self.app(
            scope,
            receive,
            send_with_request_id,
        )


# ==========================================================
# READ INCOMING HEADER
# ==========================================================

def read_incoming_request_id(
    scope: Scope,
) -> str | None:

    target_name = (
        REQUEST_ID_HEADER
        .lower()
        .encode(
            "latin-1"
        )
    )


    for (
        header_name,
        header_value,
    ) in scope.get(
        "headers",
        [],
    ):

        if (
            header_name.lower()
            == target_name
        ):

            try:

                return header_value.decode(
                    "latin-1"
                )


            except UnicodeDecodeError:

                return None


    return None


# ==========================================================
# REGISTER MIDDLEWARE
# ==========================================================

def register_request_context_middleware(
    app,
) -> None:

    app.add_middleware(
        RequestIDMiddleware
    )
