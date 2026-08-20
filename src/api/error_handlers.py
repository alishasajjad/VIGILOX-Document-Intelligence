from typing import Any

from fastapi import (
    FastAPI,
    Request,
)

from fastapi.encoders import (
    jsonable_encoder,
)

from fastapi.exceptions import (
    RequestValidationError,
)

from fastapi.responses import (
    JSONResponse,
)

from starlette.exceptions import (
    HTTPException as StarletteHTTPException,
)

from src.api.request_context import (
    REQUEST_ID_HEADER,
)

from src.operational_logging import (
    configure_operational_logging,
    get_operational_logger,
    log_exception,
)


# ==========================================================
# LOGGER
# PHASE 7C.7d
# ==========================================================
#
# Configuration is idempotent, so importing this module
# directly (without src.api.main) still produces structured
# operational logs.
# ==========================================================

configure_operational_logging()


logger = (
    get_operational_logger(
        "api.errors"
    )
)


# ==========================================================
# STANDARD HTTP ERROR CODES
# PHASE 7C.7a
# ==========================================================

HTTP_ERROR_CODES = {
    400:
        "BAD_REQUEST",

    401:
        "AUTHENTICATION_REQUIRED",

    403:
        "FORBIDDEN",

    404:
        "NOT_FOUND",

    405:
        "METHOD_NOT_ALLOWED",

    409:
        "CONFLICT",

    413:
        "PAYLOAD_TOO_LARGE",

    415:
        "UNSUPPORTED_MEDIA_TYPE",

    422:
        "REQUEST_VALIDATION_ERROR",

    429:
        "RATE_LIMITED",

    500:
        "INTERNAL_SERVER_ERROR",

    503:
        "SERVICE_UNAVAILABLE",
}


# ==========================================================
# DOMAIN API ERROR
# PHASE 7C.7a
# ==========================================================

class APIError(
    RuntimeError
):
    """
    Structured application-level API error.

    This exception gives application services / endpoints
    a stable way to expose:

        HTTP status
        machine-readable error code
        safe human-readable message
        optional structured details

    Phase 7C.7c will progressively migrate domain-specific
    persistence, storage and review failures to this class.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
    ):

        self.status_code = (
            status_code
        )


        self.code = (
            code
        )


        self.message = (
            message
        )


        self.details = (
            details
        )


        super().__init__(
            message
        )


# ==========================================================
# REQUEST ID
# ==========================================================

def get_request_id(
    request: Request,
) -> str | None:

    # ======================================================
    # PHASE 7C.7e FORWARD COMPATIBILITY
    # ======================================================
    #
    # Request-ID middleware does not exist yet.
    #
    # Once 7C.7e adds:
    #
    #     request.state.request_id
    #
    # every error response automatically starts exposing it
    # without changing the error handlers again.
    # ======================================================

    return getattr(
        request.state,
        "request_id",
        None,
    )


# ==========================================================
# REQUEST ID RESPONSE HEADERS
# PHASE 7C.7e
# ==========================================================
#
# Starlette builds its middleware stack as:
#
#     ServerErrorMiddleware
#       -> user middleware (RequestIDMiddleware)
#         -> ExceptionMiddleware
#           -> router
#
# An unhandled exception is rendered by
# ServerErrorMiddleware, which sits OUTSIDE the correlation
# middleware. Its response therefore never passes through
# that middleware's header injection.
#
# Attaching the header here guarantees X-Request-ID is
# present on every error response, including unexpected
# HTTP 500 responses.
# ==========================================================

def build_request_id_headers(
    request: Request,
    existing_headers: dict | None = None,
) -> dict:

    headers = (
        dict(
            existing_headers
        )
        if existing_headers
        else {}
    )


    request_id = (
        get_request_id(
            request
        )
    )


    if request_id:

        headers[
            REQUEST_ID_HEADER
        ] = request_id


    return headers


# ==========================================================
# DEFAULT MESSAGE
# ==========================================================

def get_default_http_message(
    status_code: int,
) -> str:

    messages = {
        400:
            "The request is invalid.",

        401:
            "Authentication is required.",

        403:
            (
                "You are not authorized "
                "to perform this action."
            ),

        404:
            "The requested resource was not found.",

        405:
            (
                "The requested HTTP method "
                "is not allowed."
            ),

        409:
            (
                "The request conflicts with "
                "the current resource state."
            ),

        413:
            "The request payload is too large.",

        415:
            (
                "The request media type "
                "is not supported."
            ),

        422:
            "Request validation failed.",

        429:
            "Too many requests.",

        500:
            "An internal server error occurred.",

        503:
            (
                "The service is temporarily "
                "unavailable."
            ),
    }


    return messages.get(
        status_code,
        "The request could not be completed.",
    )


# ==========================================================
# ERROR PAYLOAD BUILDER
# ==========================================================

def build_error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: Any = None,
    details: Any = None,
) -> dict:

    # ======================================================
    # BACKWARD-COMPATIBLE DETAIL
    # ======================================================
    #
    # Existing VIGILOX API tests and clients currently use:
    #
    #     response.json()["detail"]
    #
    # We preserve that field during Phase 7C.7 instead of
    # breaking the existing API in one step.
    #
    # New integrations should use:
    #
    #     response["error"]["code"]
    #     response["error"]["message"]
    # ======================================================

    legacy_detail = (
        message
        if detail is None
        else detail
    )


    error_object = {
        "code":
            code,

        "message":
            message,

        "request_id":
            get_request_id(
                request
            ),
    }


    if details is not None:

        error_object[
            "details"
        ] = details


    return {
        "status":
            "error",

        "detail":
            legacy_detail,

        "error":
            error_object,
    }


# ==========================================================
# API ERROR HANDLER
# ==========================================================

async def api_error_handler(
    request: Request,
    exc: APIError,
) -> JSONResponse:

    payload = (
        build_error_response(
            request=(
                request
            ),

            status_code=(
                exc.status_code
            ),

            code=(
                exc.code
            ),

            message=(
                exc.message
            ),

            detail=(
                exc.message
            ),

            details=(
                exc.details
            ),
        )
    )


    return JSONResponse(
        status_code=(
            exc.status_code
        ),

        content=(
            jsonable_encoder(
                payload
            )
        ),

        headers=(
            build_request_id_headers(
                request
            )
        ),
    )


# ==========================================================
# HTTP EXCEPTION HANDLER
# ==========================================================

async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:

    status_code = (
        exc.status_code
    )


    code = (
        HTTP_ERROR_CODES.get(
            status_code,
            "HTTP_ERROR",
        )
    )


    detail = (
        exc.detail
    )


    # ======================================================
    # STRING DETAIL
    # ======================================================

    if isinstance(
        detail,
        str,
    ):

        message = (
            detail
        )


    # ======================================================
    # STRUCTURED DETAIL
    # ======================================================

    elif isinstance(
        detail,
        dict,
    ):

        message = (
            detail.get(
                "message"
            )
            or get_default_http_message(
                status_code
            )
        )


        # Allows future endpoints to raise:
        #
        # HTTPException(
        #     404,
        #     detail={
        #         "code": "DOCUMENT_NOT_FOUND",
        #         "message": "Document not found."
        #     }
        # )
        #
        # without changing this central handler.

        code = (
            detail.get(
                "code"
            )
            or code
        )


    else:

        message = (
            get_default_http_message(
                status_code
            )
        )


    payload = (
        build_error_response(
            request=(
                request
            ),

            status_code=(
                status_code
            ),

            code=(
                code
            ),

            message=(
                message
            ),

            detail=(
                detail
            ),
        )
    )


    return JSONResponse(
        status_code=(
            status_code
        ),

        content=(
            jsonable_encoder(
                payload
            )
        ),

        headers=(
            build_request_id_headers(
                request,
                exc.headers,
            )
        ),
    )


# ==========================================================
# REQUEST VALIDATION ERROR HANDLER
# ==========================================================

async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:

    validation_errors = (
        jsonable_encoder(
            exc.errors()
        )
    )


    payload = (
        build_error_response(
            request=(
                request
            ),

            status_code=422,

            code=(
                "REQUEST_VALIDATION_ERROR"
            ),

            message=(
                "Request validation failed."
            ),

            # ==============================================
            # LEGACY FASTAPI COMPATIBILITY
            # ==============================================

            detail=(
                validation_errors
            ),

            details={
                "validation_errors":
                    validation_errors,
            },
        )
    )


    return JSONResponse(
        status_code=422,

        content=(
            jsonable_encoder(
                payload
            )
        ),

        headers=(
            build_request_id_headers(
                request
            )
        ),
    )


# ==========================================================
# UNHANDLED EXCEPTION HANDLER
# ==========================================================

async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    # ======================================================
    # SECURITY RULE
    # ======================================================
    #
    # Full Python exception information is logged server-side.
    #
    # It is NOT returned to the client.
    #
    # This prevents leaking:
    #
    #     filesystem paths
    #     SQL details
    #     database connection details
    #     internal class names
    #     stack traces
    #     environment data
    # ======================================================

    log_exception(
        logger,

        event=(
            "unhandled_api_exception"
        ),

        message=(
            "Unhandled API exception."
        ),

        exc=exc,

        request_id=(
            get_request_id(
                request
            )
        ),

        status_code=500,

        error_code=(
            "INTERNAL_SERVER_ERROR"
        ),
    )


    payload = (
        build_error_response(
            request=(
                request
            ),

            status_code=500,

            code=(
                "INTERNAL_SERVER_ERROR"
            ),

            message=(
                "An internal server error occurred."
            ),

            detail=(
                "An internal server error occurred."
            ),
        )
    )


    return JSONResponse(
        status_code=500,

        content=(
            jsonable_encoder(
                payload
            )
        ),

        headers=(
            build_request_id_headers(
                request
            )
        ),
    )


# ==========================================================
# REGISTER ERROR HANDLERS
# ==========================================================

def register_error_handlers(
    app: FastAPI,
) -> None:

    app.add_exception_handler(
        APIError,
        api_error_handler,
    )


    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )


    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )


    app.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )