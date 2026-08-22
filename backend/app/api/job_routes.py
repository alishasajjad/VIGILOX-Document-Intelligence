import tempfile

from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    Request,
    UploadFile,
)

from fastapi.responses import (
    JSONResponse,
)

from backend.app.api.error_handlers import (
    APIError,
    build_request_id_headers,
    get_request_id,
)

from backend.app.api.request_validation import (
    MAX_UPLOAD_BYTES,
    copy_upload_with_limit,
    normalize_upload_filename,
    validate_upload_content_type,
)

from backend.app.core.logging import (
    get_operational_logger,
    log_exception,
)

from backend.app.services.job_service import (
    DuplicateSourceError,
    BatchTooLargeError,
    JobNotFoundError,
)


# ==========================================================
# ASYNC DOCUMENT JOB ROUTES
# PHASE 9.4
# ==========================================================
#
# The production path for submitting documents.
#
#   POST /api/v1/document-jobs        202, one document
#   GET  /api/v1/document-jobs/{id}   job state
#   POST /api/v1/document-batches     202, several documents
#   GET  /api/v1/document-batches/{id}
#
# POST /api/v1/documents/analyze stays exactly as it is. It is
# synchronous, it blocks for the eighteen second median, and it
# is still the right tool for a script that wants one answer
# from one call. Nothing about it changes and nothing about it
# is deprecated here.
#
#
# WHY THIS IS ITS OWN MODULE
# ----------------------------------------------------------
#
# main.py is already three thousand lines and nineteen routes.
# Adding four more to it would make a known problem worse for
# no reason, and the async job lifecycle is a genuine boundary
# rather than an arbitrary slice -- these four routes share a
# service, a vocabulary and a lifecycle that nothing else in
# main.py touches.
#
# Phase 11 decomposes the rest along the same kind of line.
#
#
# WHY 202 AND NOT 200
# ----------------------------------------------------------
#
# 202 Accepted means "this is a valid request and I have not
# done it yet", which is exactly true. Returning 200 with a
# job id would tell every HTTP client that the work was
# finished.
#
#
# WHAT IS NEVER IN A RESPONSE
# ----------------------------------------------------------
#
# JobService.serialize() is a whitelist and it is the only
# route from a row to a response, so filesystem paths, worker
# identities, lease timestamps and exception text cannot
# appear here. Failure reasons are vocabulary codes with
# pre-written sentences, which is the same rule the HTTP error
# contract already follows.
# ==========================================================

logger = (
    get_operational_logger(
        "api.jobs"
    )
)


router = (
    APIRouter(
        prefix="/api/v1",
        tags=[
            "Document Jobs"
        ],
    )
)


# ==========================================================
# UPLOAD RECEIPT
# ==========================================================

def _receive_upload(
    file: UploadFile,
    request: Request,
) -> dict:

    """
    Validate one uploaded file and stream it to a bounded
    temporary file.

    Identical rules to the synchronous route, because they read
    the same constants from the same module. An async endpoint
    that accepted a file type the sync one rejected would be a
    way around the validation rather than a second entrance to
    it.

    The temporary file is handed to JobService, which moves it
    into the pending store and takes ownership. On any failure
    here it is removed before the exception leaves.
    """

    (
        content_type,
        suffix,
    ) = (
        validate_upload_content_type(
            file.content_type
        )
    )

    original_filename = (
        normalize_upload_filename(
            file.filename
        )
    )

    temp_path = None


    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            # Captured before the copy so a failed copy is
            # still cleaned up below.
            temp_path = (
                temp_file.name
            )

            size_bytes = (
                copy_upload_with_limit(
                    source=(
                        file.file
                    ),

                    destination=(
                        temp_file
                    ),

                    max_bytes=(
                        MAX_UPLOAD_BYTES
                    ),
                )
            )


        return {
            "original_filename":
                original_filename,

            "content_type":
                content_type,

            "size_bytes":
                (
                    size_bytes
                    if isinstance(
                        size_bytes,
                        int,
                    )
                    else (
                        Path(
                            temp_path
                        ).stat().st_size
                    )
                ),

            "upload_path":
                temp_path,
        }


    except Exception:

        if temp_path is not None:
            Path(
                temp_path
            ).unlink(
                missing_ok=True,
            )

        raise


def _accepted(
    payload: dict,
    request: Request,
) -> JSONResponse:

    """
    202 with the server-authoritative request id on the
    response, the same as every other route here.
    """

    return (
        JSONResponse(
            status_code=202,
            content=payload,
            headers=(
                build_request_id_headers(
                    request
                )
            ),
        )
    )


# ==========================================================
# CREATE ONE JOB
# ==========================================================

@router.post(
    "/document-jobs",
    status_code=202,
)
def create_document_job(
    request: Request,

    file: Annotated[
        UploadFile,

        File(
            description=(
                "Document image to process. "
                "Supported formats: JPG, PNG, WEBP. "
                "Maximum 10 MiB."
            )
        ),
    ],

    # ==================================================
    # DELIBERATE REPROCESSING
    # PHASE 10.3
    # ==================================================
    #
    # Defaults to false, and that default is the safety
    # property rather than a convenience.
    #
    # A browser retrying a failed upload, a double-clicked
    # button, a flaky connection replaying a request -- none
    # of those are a request to analyse a stored source again,
    # and all of them would look like one if the default were
    # permissive. Each accidental reprocess costs a second
    # document, a PaddleOCR pass and a Groq completion.
    #
    # Sent as a form field rather than a query parameter
    # because the request is already multipart, and a caller
    # should not have to put half of one submission in the URL.
    # ==================================================

    reprocess: Annotated[
        bool,

        Form(
            description=(
                "Set true to deliberately analyse a "
                "document whose exact bytes have "
                "already been processed. Defaults to "
                "false, which rejects an exact "
                "duplicate and returns a reference to "
                "the existing document."
            )
        ),
    ] = False,
):

    upload = (
        _receive_upload(
            file,
            request,
        )
    )

    job_service = (
        request.app.state.jobs
    )


    try:

        payload = (
            job_service.create_job(
                original_filename=(
                    upload[
                        "original_filename"
                    ]
                ),

                content_type=(
                    upload[
                        "content_type"
                    ]
                ),

                size_bytes=(
                    upload[
                        "size_bytes"
                    ]
                ),

                upload_path=(
                    upload[
                        "upload_path"
                    ]
                ),

                reprocess=reprocess,
            )
        )


    except DuplicateSourceError as duplicate:

        # ==================================================
        # AN EXACT DUPLICATE IS A 409, NOT A 500
        # PHASE 10.3
        # ==================================================
        #
        # 409 Conflict, because nothing failed. The request was
        # understood, and it conflicts with something already
        # on file. A 4xx also tells any client library not to
        # retry, which is exactly right: retrying will conflict
        # again.
        #
        # The temporary file is ours to remove -- JobService
        # cleans up the pending copy it made, but the upload
        # this route streamed is still here.
        #
        # details carries the reference so the caller can act.
        # A rejection with nothing actionable in it is the
        # silent discard this policy exists to prevent.
        #
        # No hash. See backend/app/domain/duplicates.py for why
        # the fingerprint never leaves the service.
        # ==================================================

        Path(
            upload[
                "upload_path"
            ]
        ).unlink(
            missing_ok=True,
        )


        logger.info(
            "Duplicate source rejected.",
            extra={
                "event":
                    "document_job_duplicate",

                "request_id":
                    get_request_id(
                        request
                    ),

                "error_code":
                    duplicate.code,
            },
        )


        raise APIError(
            status_code=409,

            code=duplicate.code,

            message=duplicate.message,

            details=(
                duplicate.payload()
            ),
        ) from duplicate


    except Exception as exc:

        # JobService removes the pending bytes itself when the
        # row fails, so there is nothing to clean up here --
        # but the temporary file is ours if it never got that
        # far.
        Path(
            upload[
                "upload_path"
            ]
        ).unlink(
            missing_ok=True,
        )

        log_exception(
            logger,

            event=(
                "document_job_create_failed"
            ),

            message=(
                "Failed to queue a document for "
                "processing."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_JOB_CREATE_FAILED"
            ),
        )

        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_JOB_CREATE_FAILED"
            ),

            message=(
                "Failed to queue the document for "
                "processing."
            ),
        ) from exc


    logger.info(
        "Document queued.",
        extra={
            "event":
                "document_job_created",

            "request_id":
                get_request_id(
                    request
                ),

            "job_id":
                payload[
                    "job_id"
                ],
        },
    )

    return (
        _accepted(
            payload,
            request,
        )
    )


# ==========================================================
# READ ONE JOB
# ==========================================================

@router.get(
    "/document-jobs/{job_id}",
)
def get_document_job(
    job_id: str,
    request: Request,
):

    job_service = (
        request.app.state.jobs
    )


    try:
        return (
            job_service.get_job(
                job_id
            )
        )


    except JobNotFoundError as exc:

        # 404 with no echo of the id. A job id is a
        # capability: anything that can be guessed should not
        # be confirmed.
        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_JOB_NOT_FOUND"
            ),

            message=(
                "No such processing job."
            ),
        ) from exc


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_job_load_failed"
            ),

            message=(
                "Failed to load a document job."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_JOB_LOAD_FAILED"
            ),
        )

        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_JOB_LOAD_FAILED"
            ),

            message=(
                "Failed to load the processing job."
            ),
        ) from exc


# ==========================================================
# CREATE A BATCH
# ==========================================================

@router.post(
    "/document-batches",
    status_code=202,
)
def create_document_batch(
    request: Request,

    files: Annotated[
        list[UploadFile],

        File(
            description=(
                "Document images to process. Each file "
                "is validated and queued "
                "independently. Supported formats: "
                "JPG, PNG, WEBP. Maximum 10 MiB per "
                "file."
            )
        ),
    ],

    # PHASE 10.3. Applies to every file in the batch. Same
    # conservative default as the single-file route, and for
    # the same reason: a retried batch upload is not a request
    # to re-analyse twenty stored sources.
    reprocess: Annotated[
        bool,

        Form(
            description=(
                "Set true to deliberately re-analyse "
                "files whose exact bytes have already "
                "been processed. Defaults to false, "
                "which reports each duplicate against "
                "its own file and queues the rest."
            )
        ),
    ] = False,
):

    job_service = (
        request.app.state.jobs
    )

    limit = (
        job_service.max_batch_files
    )


    if not files:

        raise APIError(
            status_code=400,

            code=(
                "BATCH_EMPTY"
            ),

            message=(
                "A batch needs at least one file."
            ),
        )


    # Checked before a single byte is read. Streaming twenty
    # one files to disk and then rejecting the batch would
    # spend the disk and the time anyway.
    if len(files) > limit:

        raise APIError(
            status_code=400,

            code=(
                "BATCH_TOO_LARGE"
            ),

            message=(
                "A batch may contain at most "
                f"{limit} files."
            ),
        )


    accepted: list[dict] = []

    rejected: list[dict] = []


    for upload_file in files:

        try:
            accepted.append(
                _receive_upload(
                    upload_file,
                    request,
                )
            )


        except APIError as error:

            # One unsupported or oversized file does not
            # invalidate the rest. It is reported, by name,
            # with the code the validator produced.
            rejected.append(
                {
                    "original_filename":
                        (
                            upload_file.filename
                            or ""
                        )[:255],

                    "error_code":
                        error.code,

                    "error_message":
                        error.message,
                }
            )


    if not accepted:

        raise APIError(
            status_code=400,

            code=(
                "BATCH_NO_VALID_FILES"
            ),

            message=(
                "None of the submitted files could be "
                "accepted."
            ),
        )


    try:
        result = (
            job_service.create_batch(
                uploads=(
                    accepted
                ),

                reprocess=reprocess,
            )
        )


    except BatchTooLargeError as exc:

        for upload in accepted:
            Path(
                upload[
                    "upload_path"
                ]
            ).unlink(
                missing_ok=True,
            )

        raise APIError(
            status_code=400,

            code=(
                "BATCH_TOO_LARGE"
            ),

            message=(
                str(
                    exc
                )
            ),
        ) from exc


    except Exception as exc:

        for upload in accepted:
            Path(
                upload[
                    "upload_path"
                ]
            ).unlink(
                missing_ok=True,
            )

        log_exception(
            logger,

            event=(
                "document_batch_create_failed"
            ),

            message=(
                "Failed to queue a document batch."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_BATCH_CREATE_FAILED"
            ),
        )

        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_BATCH_CREATE_FAILED"
            ),

            message=(
                "Failed to queue the document batch."
            ),
        ) from exc


    # Files rejected at validation are merged with any the
    # service could not queue, so the caller gets one list and
    # does not have to reconcile two.
    result["rejected"] = (
        rejected
        + result.get(
            "rejected",
            [],
        )
    )

    result["submitted_count"] = (
        len(files)
    )

    result["status_url"] = (
        "/api/v1/document-batches/"
        + result[
            "batch_id"
        ]
    )

    logger.info(
        "Document batch queued.",
        extra={
            "event":
                "document_batch_created",

            "request_id":
                get_request_id(
                    request
                ),

            "batch_id":
                result[
                    "batch_id"
                ],

            "queued":
                result[
                    "queued_count"
                ],

            "rejected":
                len(
                    result[
                        "rejected"
                    ]
                ),
        },
    )

    return (
        _accepted(
            result,
            request,
        )
    )


# ==========================================================
# READ A BATCH
# ==========================================================

@router.get(
    "/document-batches/{batch_id}",
)
def get_document_batch(
    batch_id: str,
    request: Request,
):

    job_service = (
        request.app.state.jobs
    )


    try:
        return (
            job_service.get_batch(
                batch_id
            )
        )


    except JobNotFoundError as exc:

        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_BATCH_NOT_FOUND"
            ),

            message=(
                "No such batch."
            ),
        ) from exc


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_batch_load_failed"
            ),

            message=(
                "Failed to load a document batch."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_BATCH_LOAD_FAILED"
            ),
        )

        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_BATCH_LOAD_FAILED"
            ),

            message=(
                "Failed to load the batch."
            ),
        ) from exc
