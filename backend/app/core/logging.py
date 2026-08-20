import json
import logging
import os
import sys

from datetime import (
    datetime,
    timezone,
)
from typing import Any


# ==========================================================
# CONFIGURATION
# PHASE 7C.7d
# ==========================================================

LOGGER_ROOT_NAME = (
    "vigilox"
)


DEFAULT_LOG_LEVEL = (
    "INFO"
)


SUPPORTED_LOG_LEVELS = {
    "DEBUG":
        logging.DEBUG,

    "INFO":
        logging.INFO,

    "WARNING":
        logging.WARNING,

    "ERROR":
        logging.ERROR,

    "CRITICAL":
        logging.CRITICAL,
}


STRUCTURED_FIELDS = (
    "event",
    "request_id",
    "document_id",
    "reviewer_id",
    "status_code",
    "error_code",
    "error_type",
)


# ==========================================================
# UTC TIMESTAMP
# ==========================================================

def utc_timestamp() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat(
            timespec="milliseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


# ==========================================================
# STRUCTURED JSON FORMATTER
# ==========================================================

class StructuredJSONFormatter(
    logging.Formatter
):

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:

        payload: dict[str, Any] = {
            "timestamp":
                utc_timestamp(),

            "level":
                record.levelname,

            "logger":
                record.name,

            "event":
                getattr(
                    record,
                    "event",
                    "log",
                ),

            "message":
                record.getMessage(),
        }


        # ==================================================
        # OPTIONAL STRUCTURED CONTEXT
        # ==================================================

        for field_name in (
            STRUCTURED_FIELDS
        ):

            if field_name == "event":

                continue


            value = getattr(
                record,
                field_name,
                None,
            )


            if value is not None:

                payload[
                    field_name
                ] = value


        # ==================================================
        # EXCEPTION TRACE
        # ==================================================
        #
        # Exception information is intentionally available
        # server-side.
        #
        # It must never be returned directly to the API
        # client.
        # ==================================================

        if record.exc_info:

            payload[
                "exception"
            ] = (
                self.formatException(
                    record.exc_info
                )
            )


        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


# ==========================================================
# RESOLVE LOG LEVEL
# ==========================================================

def resolve_log_level() -> int:

    configured_level = (
        os.getenv(
            "VIGILOX_LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        )
        .strip()
        .upper()
    )


    return (
        SUPPORTED_LOG_LEVELS.get(
            configured_level,
            logging.INFO,
        )
    )


# ==========================================================
# CONFIGURE VIGILOX LOGGING
# ==========================================================

def configure_operational_logging() -> None:

    root_logger = (
        logging.getLogger(
            LOGGER_ROOT_NAME
        )
    )


    # ======================================================
    # IDEMPOTENT CONFIGURATION
    # ======================================================
    #
    # Importing FastAPI application multiple times during
    # TestClient runs must not create duplicate handlers.
    # ======================================================

    if getattr(
        root_logger,
        "_vigilox_configured",
        False,
    ):

        root_logger.setLevel(
            resolve_log_level()
        )

        return


    handler = (
        logging.StreamHandler(
            sys.stderr
        )
    )


    handler.setFormatter(
        StructuredJSONFormatter()
    )


    root_logger.addHandler(
        handler
    )


    root_logger.setLevel(
        resolve_log_level()
    )


    # Prevent duplicate propagation through Python's root
    # logger.

    root_logger.propagate = (
        False
    )


    root_logger._vigilox_configured = (
        True
    )


# ==========================================================
# GET CHILD LOGGER
# ==========================================================

def get_operational_logger(
    name: str,
) -> logging.Logger:

    normalized_name = (
        name.strip()
        if name
        else "application"
    )


    return logging.getLogger(
        (
            f"{LOGGER_ROOT_NAME}."
            f"{normalized_name}"
        )
    )


# ==========================================================
# SAFE EXTRA BUILDER
# ==========================================================

def build_log_extra(
    *,
    event: str,
    request_id: str | None = None,
    document_id: str | None = None,
    reviewer_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:

    return {
        "event":
            event,

        "request_id":
            request_id,

        "document_id":
            document_id,

        "reviewer_id":
            reviewer_id,

        "status_code":
            status_code,

        "error_code":
            error_code,

        "error_type":
            error_type,
    }


# ==========================================================
# STRUCTURED ERROR LOG
# ==========================================================

def log_exception(
    logger: logging.Logger,
    *,
    event: str,
    message: str,
    exc: Exception,
    request_id: str | None = None,
    document_id: str | None = None,
    reviewer_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
) -> None:

    logger.error(
        message,

        extra=(
            build_log_extra(
                event=(
                    event
                ),

                request_id=(
                    request_id
                ),

                document_id=(
                    document_id
                ),

                reviewer_id=(
                    reviewer_id
                ),

                status_code=(
                    status_code
                ),

                error_code=(
                    error_code
                ),

                error_type=(
                    type(
                        exc
                    ).__name__
                ),
            )
        ),

        exc_info=(
            type(
                exc
            ),
            exc,
            exc.__traceback__,
        ),
    )


# ==========================================================
# STRUCTURED EVENT LOG
# ==========================================================

def log_event(
    logger: logging.Logger,
    *,
    event: str,
    message: str,
    level: int = logging.INFO,
    request_id: str | None = None,
    document_id: str | None = None,
    reviewer_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
) -> None:

    logger.log(
        level,
        message,

        extra=(
            build_log_extra(
                event=(
                    event
                ),

                request_id=(
                    request_id
                ),

                document_id=(
                    document_id
                ),

                reviewer_id=(
                    reviewer_id
                ),

                status_code=(
                    status_code
                ),

                error_code=(
                    error_code
                ),

                error_type=(
                    error_type
                ),
            )
        ),
    )