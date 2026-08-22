from typing import BinaryIO

from backend.app.api.error_handlers import (
    APIError,
)


# ==========================================================
# UPLOAD VALIDATION
# PHASE 7C.7b
# ==========================================================

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


CONTENT_TYPE_SUFFIXES = {
    "image/jpeg":
        ".jpg",

    "image/png":
        ".png",

    "image/webp":
        ".webp",
}


# ==========================================================
# MAXIMUM UPLOAD SIZE
# ==========================================================
#
# 10 MiB per file.
#
# Content-Length is not trusted as the authoritative size --
# copy_upload_with_limit() counts the actual multipart bytes
# while streaming them, so a lying header buys nothing.
#
# Defined here rather than in main.py because it is an upload
# rule and because both the synchronous analyze route and the
# async job routes have to agree on it. Two modules each with
# their own idea of the limit is how one endpoint quietly
# accepts what the other rejects.
#
# backend.app.main re-exports it, so the existing import path
# still resolves.
# ==========================================================

MAX_UPLOAD_BYTES = (
    10 * 1024 * 1024
)


MAX_FILENAME_LENGTH = (
    255
)


UPLOAD_COPY_CHUNK_SIZE = (
    1024 * 1024
)


# ==========================================================
# VALIDATE CONTENT TYPE
# ==========================================================

def validate_upload_content_type(
    content_type: str | None,
) -> tuple[str, str]:

    normalized_content_type = (
        (
            content_type
            or ""
        )
        .strip()
        .lower()
    )


    if (
        normalized_content_type
        not in ALLOWED_CONTENT_TYPES
    ):

        raise APIError(
            status_code=400,

            code=(
                "UNSUPPORTED_FILE_TYPE"
            ),

            message=(
                "Unsupported file type. "
                "Supported formats are "
                "JPG, PNG and WEBP."
            ),
        )


    return (
        normalized_content_type,
        CONTENT_TYPE_SUFFIXES[
            normalized_content_type
        ],
    )


# ==========================================================
# NORMALIZE ORIGINAL FILENAME
# ==========================================================

def normalize_upload_filename(
    filename: str | None,
) -> str:

    # ======================================================
    # DEFAULT NAME
    # ======================================================

    if filename is None:

        return (
            "uploaded_document"
        )


    normalized = (
        filename.strip()
    )


    if not normalized:

        return (
            "uploaded_document"
        )


    # ======================================================
    # REMOVE CLIENT-SIDE PATH COMPONENTS
    # ======================================================
    #
    # Browsers normally send only a filename, but clients
    # can manually send values such as:
    #
    #     C:\fakepath\badge.jpg
    #     /tmp/badge.jpg
    #
    # The original filename is metadata only and must never
    # be treated as a filesystem path.
    # ======================================================

    normalized = (
        normalized.replace(
            "\\",
            "/",
        )
    )


    normalized = (
        normalized
        .rsplit(
            "/",
            1,
        )[-1]
        .strip()
    )


    if (
        not normalized
        or normalized
        in {
            ".",
            "..",
        }
    ):

        raise APIError(
            status_code=400,

            code=(
                "INVALID_UPLOAD_FILENAME"
            ),

            message=(
                "Uploaded file has an "
                "invalid filename."
            ),
        )


    # ======================================================
    # CONTROL CHARACTER REJECTION
    # ======================================================

    if any(
        ord(character) < 32
        for character
        in normalized
    ):

        raise APIError(
            status_code=400,

            code=(
                "INVALID_UPLOAD_FILENAME"
            ),

            message=(
                "Uploaded file has an "
                "invalid filename."
            ),
        )


    # ======================================================
    # DATABASE LENGTH PROTECTION
    # ======================================================
    #
    # documents.original_filename is String(255).
    #
    # Reject here instead of letting PostgreSQL generate an
    # avoidable persistence error.
    # ======================================================

    if (
        len(
            normalized
        )
        > MAX_FILENAME_LENGTH
    ):

        raise APIError(
            status_code=400,

            code=(
                "UPLOAD_FILENAME_TOO_LONG"
            ),

            message=(
                "Uploaded filename exceeds "
                "the maximum allowed length."
            ),

            details={
                "maximum_length":
                    MAX_FILENAME_LENGTH,
            },
        )


    return normalized


# ==========================================================
# COPY UPLOAD WITH SIZE LIMIT
# ==========================================================

def copy_upload_with_limit(
    *,
    source: BinaryIO,
    destination: BinaryIO,
    max_bytes: int,
) -> int:

    # ======================================================
    # CONFIGURATION VALIDATION
    # ======================================================

    if (
        not isinstance(
            max_bytes,
            int,
        )
        or isinstance(
            max_bytes,
            bool,
        )
        or max_bytes <= 0
    ):

        raise RuntimeError(
            (
                "Upload size limit must "
                "be a positive integer."
            )
        )


    total_bytes = 0


    while True:

        chunk = (
            source.read(
                UPLOAD_COPY_CHUNK_SIZE
            )
        )


        if not chunk:

            break


        total_bytes += (
            len(
                chunk
            )
        )


        # ==================================================
        # SIZE LIMIT
        # ==================================================
        #
        # Do not trust Content-Length.
        #
        # The server counts the actual bytes read from the
        # multipart upload.
        # ==================================================

        if (
            total_bytes
            > max_bytes
        ):

            raise APIError(
                status_code=413,

                code=(
                    "UPLOAD_TOO_LARGE"
                ),

                message=(
                    "Uploaded file exceeds "
                    "the maximum allowed size."
                ),

                details={
                    "maximum_bytes":
                        max_bytes,
                },
            )


        destination.write(
            chunk
        )


    # ======================================================
    # EMPTY DOCUMENT
    # ======================================================

    if total_bytes == 0:

        raise APIError(
            status_code=400,

            code=(
                "EMPTY_UPLOAD"
            ),

            message=(
                "Uploaded file is empty."
            ),
        )


    return total_bytes