import logging
import tempfile

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)

from fastapi.responses import (
    FileResponse,
    HTMLResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from backend.app.core.paths import (
    FRONTEND_PAGES_DIRECTORY as FRONTEND_PAGES_DIRECTORY_PATH,
    FRONTEND_STATIC_DIRECTORY as FRONTEND_STATIC_DIRECTORY_PATH,
)

from backend.app.api.error_handlers import (
    APIError,
    get_request_id,
    register_error_handlers,
)

from backend.app.api.request_context import (
    register_request_context_middleware,
)

from backend.app.api.request_validation import (
    copy_upload_with_limit,
    normalize_upload_filename,
    validate_upload_content_type,
)

from backend.app.api.schemas import (
    HumanReviewRequest,
    ReviewQueueResponse,
)

from backend.app.services.persistence_service import (
    DuplicateHumanReviewError,
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from backend.app.services.document_storage_service import (
    DocumentStorageSecurityError,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from backend.app.core.logging import (
    configure_operational_logging,
    get_operational_logger,
    log_event,
    log_exception,
)

from backend.app.services.pipeline_service import (
    DocumentPipelineService,
)

from backend.app.services.readiness_service import (
    ReadinessService,
)

from backend.app.services.reviewer_identity_service import (
    ReviewerAuthenticationRequired,
    ReviewerAuthorizationError,
    ReviewerIdentityService,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


# ==========================================================
# STRUCTURED OPERATIONAL LOGGING
# PHASE 7C.7d
# ==========================================================
#
# Configuration is idempotent.
#
# Repeated imports of this module, and repeated TestClient
# construction, must never install duplicate handlers.
# ==========================================================

configure_operational_logging()


logger = (
    get_operational_logger(
        "api"
    )
)


# ==========================================================
# FILE CONFIGURATION
# PHASE 7C.7b
# ==========================================================
#
# Maximum source document upload size:
#
#     10 MiB
#
# Actual multipart bytes are counted while streaming.
# Content-Length is not trusted as the authoritative size.
# ==========================================================

MAX_UPLOAD_BYTES = (
    10 * 1024 * 1024
)


# ==========================================================
# REVIEW QUEUE CONFIGURATION
# PHASE 7A
# ==========================================================

ALLOWED_REVIEW_PRIORITIES = {
    "HIGH",
    "MEDIUM",
    "LOW",
}


ALLOWED_DOCUMENT_TYPES = {
    "guard_license",
    "sia_badge",
    "id_card",
}


# ==========================================================
# FRONTEND CONFIGURATION
# PHASE 7B.5 / 7B.7 / PHASE 8.1
# ==========================================================
#
# PHASE 8.1
#
# The dashboard used to live inside the backend Python
# package at src/dashboard, and was resolved relative to
# src/api/main.py.
#
# Frontend assets now live in the top-level frontend/
# directory and are resolved from the single project-root
# anchor in backend.app.core.paths.
#
# The served URLs are deliberately UNCHANGED:
#
#     /review
#     /review/{document_id}
#     /review/static/...
# ==========================================================

FRONTEND_PAGES_DIRECTORY = (
    FRONTEND_PAGES_DIRECTORY_PATH
)


FRONTEND_STATIC_DIRECTORY = (
    FRONTEND_STATIC_DIRECTORY_PATH
)


# ==========================================================
# APPLICATION LIFESPAN
# ==========================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # ------------------------------------------------------
    # Complete OCR + LLM + validation pipeline
    # ------------------------------------------------------

    app.state.pipeline = (
        DocumentPipelineService()
    )


    # ------------------------------------------------------
    # Database write + original document storage service
    # ------------------------------------------------------

    app.state.persistence = (
        PersistenceService()
    )


    # ------------------------------------------------------
    # Database read/query service
    # ------------------------------------------------------

    app.state.document_query = (
        DocumentQueryService()
    )


    # ------------------------------------------------------
    # Human review validation service
    # ------------------------------------------------------

    app.state.human_review = (
        HumanReviewService()
    )


    # ------------------------------------------------------
    # Reviewer identity / authorization foundation
    # PHASE 7C.5
    # ------------------------------------------------------

    app.state.reviewer_identity = (
        ReviewerIdentityService()
    )


    # ------------------------------------------------------
    # Dependency readiness service
    # PHASE 7C.7f
    # ------------------------------------------------------

    app.state.readiness = (
        ReadinessService()
    )


    yield


    # ------------------------------------------------------
    # Cleanup application state
    # ------------------------------------------------------

    if hasattr(
        app.state,
        "pipeline",
    ):

        del app.state.pipeline


    if hasattr(
        app.state,
        "persistence",
    ):

        del app.state.persistence


    if hasattr(
        app.state,
        "document_query",
    ):

        del app.state.document_query


    if hasattr(
        app.state,
        "human_review",
    ):

        del app.state.human_review


    if hasattr(
        app.state,
        "reviewer_identity",
    ):

        del app.state.reviewer_identity


    if hasattr(
        app.state,
        "readiness",
    ):

        del app.state.readiness


# ==========================================================
# FASTAPI APPLICATION
# ==========================================================

app = FastAPI(
    title=(
        "VIGILOX Document Intelligence API"
    ),

    version="0.1.0",

    description=(
        "OCR, structured extraction, "
        "evidence validation, confidence, "
        "anomaly detection, persistent "
        "document storage, PostgreSQL "
        "persistence, human review, "
        "reviewer authorization and "
        "audit-history API."
    ),

    lifespan=lifespan,
)


# ==========================================================
# CENTRAL API ERROR CONTRACT
# PHASE 7C.7a
# ==========================================================

register_error_handlers(
    app
)


# ==========================================================
# REQUEST CORRELATION ID
# PHASE 7C.7e
# ==========================================================
#
# Registered after the error handlers so every request,
# including failing ones, carries an authoritative
# server-generated correlation ID.
# ==========================================================

register_request_context_middleware(
    app
)


# ==========================================================
# REVIEW DASHBOARD STATIC FILES
# PHASE 7B.5
# ==========================================================

app.mount(
    "/review/static",

    StaticFiles(
        directory=(
            FRONTEND_STATIC_DIRECTORY
        )
    ),

    name="review-static",
)


# ==========================================================
# REVIEW DASHBOARD
# PHASE 7B.5
# ==========================================================

@app.get(
    "/review",
    response_class=HTMLResponse,
    tags=["Dashboard"],
    include_in_schema=False,
)
def review_dashboard():

    dashboard_file = (
        FRONTEND_PAGES_DIRECTORY
        / "index.html"
    )


    if not dashboard_file.exists():

        raise HTTPException(
            status_code=500,
            detail=(
                "Review dashboard "
                "is not available."
            ),
        )


    return FileResponse(
        path=(
            dashboard_file
        ),

        media_type=(
            "text/html"
        ),
    )


# ==========================================================
# REVIEW DOCUMENT DETAIL PAGE
# PHASE 7B.7
# ==========================================================

@app.get(
    "/review/{document_id}",
    response_class=HTMLResponse,
    tags=["Dashboard"],
    include_in_schema=False,
)
def review_document_detail(
    document_id: str,
):

    detail_file = (
        FRONTEND_PAGES_DIRECTORY
        / "review_detail.html"
    )


    if not detail_file.exists():

        raise HTTPException(
            status_code=500,
            detail=(
                "Document review page "
                "is not available."
            ),
        )


    return FileResponse(
        path=(
            detail_file
        ),

        media_type=(
            "text/html"
        ),
    )


# ==========================================================
# HEALTH CHECK
# ==========================================================

@app.get(
    "/health",
    tags=["System"],
)
def health_check():

    # ======================================================
    # PROCESS LIVENESS ONLY
    # PHASE 7C.7f
    # ======================================================
    #
    # Intentionally dependency-free.
    #
    # An orchestrator must never restart an otherwise
    # healthy process because PostgreSQL or storage is
    # briefly unavailable. That is what readiness is for.
    # ======================================================

    return {
        "status":
            "ok",

        "service":
            "vigilox-document-intelligence",

        "version":
            "0.1.0",
    }


# ==========================================================
# READINESS CHECK
# PHASE 7C.7f
# ==========================================================
#
# ENDPOINT CHOICE
# ----------------------------------------------------------
#
#     GET /health/ready
#
# The existing API reserves /api/v1/* for versioned business
# resources and keeps process-level probes unversioned.
#
# Readiness is infrastructure rather than a business
# resource, so it belongs inside the existing /health
# namespace instead of becoming a new top-level route beside
# /review and /api/v1.
#
# This also maps directly onto standard probe configuration:
#
#     livenessProbe   -> /health
#     readinessProbe  -> /health/ready
# ==========================================================

@app.get(
    "/health/ready",
    tags=["System"],
)
def readiness_check(
    request: Request,
):

    readiness_service = (
        getattr(
            request.app.state,
            "readiness",
            None,
        )
    )


    # ======================================================
    # READINESS SERVICE ITSELF MISSING
    # ======================================================

    if readiness_service is None:

        raise APIError(
            status_code=503,

            code=(
                "SERVICE_NOT_READY"
            ),

            message=(
                "The service is not ready "
                "to accept requests."
            ),

            details={
                "checks": {
                    "services": {
                        "status":
                            "error",

                        "reason":
                            (
                                "SERVICE_NOT"
                                "_INITIALIZED"
                            ),
                    },
                },
            },
        )


    evaluation = (
        readiness_service
        .evaluate(
            app_state=(
                request.app.state
            )
        )
    )


    checks = (
        evaluation[
            "checks"
        ]
    )


    # ======================================================
    # READY
    # ======================================================

    if evaluation[
        "ready"
    ]:

        return {
            "status":
                "ready",

            "service":
                "vigilox-document-intelligence",

            "checks":
                checks,
        }


    # ======================================================
    # NOT READY
    # ======================================================
    #
    # Each failing dependency is logged server-side with the
    # request correlation ID and the real exception trace.
    #
    # The HTTP response receives only stable reason codes.
    # ======================================================

    request_id = (
        get_request_id(
            request
        )
    )


    for (
        check_name,
        failure,
    ) in evaluation[
        "failures"
    ].items():

        log_exception(
            logger,

            event=(
                "readiness_dependency_failed"
            ),

            message=(
                "Readiness dependency check "
                f"failed: {check_name}"
            ),

            exc=failure,

            request_id=(
                request_id
            ),

            status_code=503,

            error_code=(
                "SERVICE_NOT_READY"
            ),
        )


    log_event(
        logger,

        event=(
            "readiness_check_failed"
        ),

        message=(
            "Service readiness check "
            "failed."
        ),

        level=(
            logging.ERROR
        ),

        request_id=(
            request_id
        ),

        status_code=503,

        error_code=(
            "SERVICE_NOT_READY"
        ),
    )


    raise APIError(
        status_code=503,

        code=(
            "SERVICE_NOT_READY"
        ),

        message=(
            "The service is not ready "
            "to accept requests."
        ),

        details={
            "checks":
                checks,
        },
    )


# ==========================================================
# CURRENT REVIEWER IDENTITY
# PHASE 7C.5 / PHASE 7C.7c
# ==========================================================

@app.get(
    "/api/v1/reviewer/me",
    tags=["Reviews"],
)
def get_current_reviewer(
    request: Request,
):

    identity_service = (
        request.app.state
        .reviewer_identity
    )


    try:

        identity = (
            identity_service
            .resolve(
                headers=(
                    request.headers
                )
            )
        )


    # ======================================================
    # AUTHENTICATION REQUIRED
    # ======================================================

    except ReviewerAuthenticationRequired as exc:

        raise APIError(
            status_code=401,

            code=(
                "REVIEWER_AUTHENTICATION_REQUIRED"
            ),

            message=(
                "Reviewer authentication "
                "is required."
            ),
        ) from exc


    # ======================================================
    # INVALID / UNSUPPORTED ROLE
    # ======================================================

    except ReviewerAuthorizationError as exc:

        raise APIError(
            status_code=403,

            code=(
                "REVIEWER_NOT_AUTHORIZED"
            ),

            message=str(
                exc
            ),
        ) from exc


    can_review = (
        identity.role
        in identity_service
        .REVIEW_WRITE_ROLES
    )


    return {
        "status":
            "success",

        "reviewer": {
            "reviewer_id":
                identity.reviewer_id,

            "role":
                identity.role,

            "source":
                identity.source,

            "can_review":
                can_review,
        },
    }


# ==========================================================
# ANALYZE + PERSIST DOCUMENT
# PHASE 6 / 7B / 7C.6 / 7C.7b / 7C.7c
# ==========================================================

@app.post(
    "/api/v1/documents/analyze",
    tags=["Documents"],
)
def analyze_document(
    request: Request,

    file: Annotated[
        UploadFile,

        File(
            description=(
                "Document image to analyze. "
                "Supported formats: "
                "JPG, PNG, WEBP."
            )
        ),
    ],
):

    temp_path = None


    try:

        # ==================================================
        # 1. VALIDATE CONTENT TYPE
        # PHASE 7C.7b
        # ==================================================

        (
            content_type,
            suffix,
        ) = (
            validate_upload_content_type(
                file.content_type
            )
        )


        # ==================================================
        # 2. NORMALIZE ORIGINAL FILENAME
        # PHASE 7C.7b
        # ==================================================

        original_filename = (
            normalize_upload_filename(
                file.filename
            )
        )


        # ==================================================
        # 3. BOUNDED TEMPORARY UPLOAD
        # PHASE 7C.7b
        # ==================================================

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            # Capture before copy so even failed copies
            # can be cleaned in finally.

            temp_path = (
                temp_file.name
            )


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


        # ==================================================
        # 4. DOCUMENT PIPELINE
        # ==================================================

        pipeline = (
            request.app.state.pipeline
        )


        pipeline_result = (
            pipeline.process(
                temp_path
            )
        )


        # ==================================================
        # 5. PERSISTENCE + PERMANENT SOURCE STORAGE
        # ==================================================

        persistence_service = (
            request.app.state.persistence
        )


        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    original_filename
                ),

                content_type=(
                    content_type
                ),

                pipeline_result=(
                    pipeline_result
                ),

                source_path=(
                    temp_path
                ),
            )
        )


        # ==================================================
        # 6. SUCCESS RESPONSE
        # ==================================================

        return {
            "status":
                "success",

            "document_id":
                stored[
                    "document_id"
                ],

            "analysis_id":
                stored[
                    "analysis_id"
                ],

            "machine_audit_id":
                stored[
                    "machine_audit_id"
                ],

            "filename":
                original_filename,

            "content_type":
                content_type,

            "processing_status":
                stored[
                    "processing_status"
                ],

            "original_document_stored":
                stored[
                    "original_document_stored"
                ],

            "analysis":
                pipeline_result,
        }


    # ======================================================
    # STRUCTURED REQUEST / DOMAIN ERROR
    # ======================================================

    except APIError:

        raise


    # ======================================================
    # EXISTING FASTAPI HTTP ERROR
    # ======================================================

    except HTTPException:

        raise


    # ======================================================
    # UNEXPECTED PROCESSING / PERSISTENCE FAILURE
    # PHASE 7C.7c
    # ======================================================

    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_processing_failed"
            ),

            message=(
                "Document processing "
                "or persistence failed."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_PROCESSING_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_PROCESSING_FAILED"
            ),

            message=(
                "Document processing "
                "or persistence failed."
            ),
        ) from exc


    finally:

        # ==================================================
        # TEMPORARY FILE CLEANUP
        # ==================================================

        if temp_path:

            path = Path(
                temp_path
            )


            if path.exists():

                path.unlink()


        # ==================================================
        # UPLOAD STREAM CLEANUP
        # ==================================================

        file.file.close()


# ==========================================================
# GET STORED DOCUMENT + ANALYSIS
# PHASE 7C.7c
# ==========================================================

@app.get(
    "/api/v1/documents/{document_id}",
    tags=["Documents"],
)
def get_document(
    document_id: str,
    request: Request,
):

    query_service = (
        request.app.state.document_query
    )


    # ======================================================
    # DATABASE QUERY
    # ======================================================

    try:

        result = (
            query_service
            .get_document(
                document_id
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_query_failed"
            ),

            message=(
                "Failed to load document."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_QUERY_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_QUERY_FAILED"
            ),

            message=(
                "Failed to load document."
            ),
        ) from exc


    # ======================================================
    # DOCUMENT DOES NOT EXIST
    # ======================================================

    if result is None:

        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_NOT_FOUND"
            ),

            message=(
                "Document not found."
            ),
        )


    # ======================================================
    # DATABASE INTEGRITY CHECK
    # ======================================================

    processing_status = (
        result[
            "document"
        ][
            "processing_status"
        ]
    )


    analysis = (
        result[
            "analysis"
        ]
    )


    if (
        processing_status
        == "PROCESSED"
        and analysis is None
    ):

        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_ANALYSIS_INTEGRITY_ERROR"
            ),

            message=(
                "Stored document analysis "
                "is missing."
            ),
        )


    # ======================================================
    # SUCCESS RESPONSE
    # ======================================================

    return {
        "status":
            "success",

        **result,
    }


# ==========================================================
# GET ORIGINAL DOCUMENT IMAGE
# PHASE 7B.4 / PHASE 7C.7c
# ==========================================================

@app.get(
    "/api/v1/documents/{document_id}/image",
    tags=["Documents"],
)
def get_document_image(
    document_id: str,
    request: Request,
):

    query_service = (
        request.app.state.document_query
    )


    # ======================================================
    # 1. LOAD DATABASE DOCUMENT
    # ======================================================

    try:

        stored_document = (
            query_service
            .get_document(
                document_id
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_image_query_failed"
            ),

            message=(
                "Failed to load document "
                "for original image request."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_QUERY_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_QUERY_FAILED"
            ),

            message=(
                "Failed to load document."
            ),
        ) from exc


    # ======================================================
    # 2. DOCUMENT DOES NOT EXIST
    # ======================================================

    if stored_document is None:

        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_NOT_FOUND"
            ),

            message=(
                "Document not found."
            ),
        )


    # ======================================================
    # 3. TRUSTED STORED METADATA
    # ======================================================

    document_metadata = (
        stored_document[
            "document"
        ]
    )


    content_type = (
        document_metadata[
            "content_type"
        ]
    )


    original_filename = (
        document_metadata[
            "original_filename"
        ]
    )


    # ======================================================
    # 4. STORAGE SERVICE
    # ======================================================

    persistence_service = (
        request.app.state.persistence
    )


    storage_service = (
        persistence_service
        .storage_service
    )


    # ======================================================
    # 5. LOAD MANAGED ORIGINAL
    # ======================================================

    try:

        original_path = (
            storage_service
            .load_original(
                document_id=(
                    document_id
                ),

                content_type=(
                    content_type
                ),
            )
        )


    # ======================================================
    # STORAGE SECURITY / PATH INTEGRITY ERROR
    # ======================================================

    except DocumentStorageSecurityError as exc:

        log_exception(
            logger,

            event=(
                "document_storage_integrity_error"
            ),

            message=(
                "Stored document storage "
                "metadata is invalid."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_STORAGE_INTEGRITY_ERROR"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_STORAGE_INTEGRITY_ERROR"
            ),

            message=(
                "Stored document storage "
                "metadata is invalid."
            ),
        ) from exc


    # ======================================================
    # STORED UNSUPPORTED CONTENT TYPE
    # ======================================================

    except ValueError as exc:

        raise APIError(
            status_code=500,

            code=(
                "STORED_DOCUMENT_CONTENT_TYPE_INVALID"
            ),

            message=(
                "Stored document has an "
                "unsupported content type."
            ),
        ) from exc


    # ======================================================
    # OTHER STORAGE READ FAILURE
    # ======================================================

    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_storage_read_failed"
            ),

            message=(
                "Failed to load original "
                "document image."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_STORAGE_READ_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_STORAGE_READ_FAILED"
            ),

            message=(
                "Failed to load original "
                "document image."
            ),
        ) from exc


    # ======================================================
    # 6. ORIGINAL FILE DOES NOT EXIST
    # ======================================================

    if original_path is None:

        raise APIError(
            status_code=404,

            code=(
                "ORIGINAL_DOCUMENT_NOT_AVAILABLE"
            ),

            message=(
                "Original document image "
                "is not available."
            ),
        )


    # ======================================================
    # 7. RETURN ORIGINAL SOURCE
    # ======================================================

    return FileResponse(
        path=(
            original_path
        ),

        media_type=(
            content_type
        ),

        filename=(
            original_filename
        ),

        content_disposition_type=(
            "inline"
        ),
    )


# ==========================================================
# GET REVIEW QUEUE
# PHASE 7A / 7B.6 / 7C.7c
# ==========================================================

@app.get(
    "/api/v1/reviews/queue",
    tags=["Reviews"],
    response_model=ReviewQueueResponse,
)
def get_review_queue(
    request: Request,

    priority: Annotated[
        str | None,

        Query(
            description=(
                "Optional review priority filter. "
                "Allowed values: "
                "HIGH, MEDIUM, LOW."
            )
        ),
    ] = None,

    document_type: Annotated[
        str | None,

        Query(
            description=(
                "Optional document-type filter. "
                "Allowed values: "
                "guard_license, "
                "sia_badge, id_card."
            )
        ),
    ] = None,
):

    # ======================================================
    # 1. NORMALIZE PRIORITY FILTER
    # ======================================================

    normalized_priority = None


    if priority is not None:

        normalized_priority = (
            priority
            .strip()
            .upper()
        )


        if (
            normalized_priority
            not in ALLOWED_REVIEW_PRIORITIES
        ):

            raise APIError(
                status_code=400,

                code=(
                    "INVALID_REVIEW_PRIORITY"
                ),

                message=(
                    "Invalid priority. "
                    "Allowed values are "
                    "HIGH, MEDIUM and LOW."
                ),
            )


    # ======================================================
    # 2. NORMALIZE DOCUMENT TYPE
    # ======================================================

    normalized_document_type = None


    if document_type is not None:

        normalized_document_type = (
            document_type
            .strip()
            .lower()
        )


        if (
            normalized_document_type
            not in ALLOWED_DOCUMENT_TYPES
        ):

            raise APIError(
                status_code=400,

                code=(
                    "INVALID_DOCUMENT_TYPE"
                ),

                message=(
                    "Invalid document_type. "
                    "Allowed values are "
                    "guard_license, "
                    "sia_badge and id_card."
                ),
            )


    # ======================================================
    # 3. LOAD REVIEW QUEUE
    # ======================================================

    query_service = (
        request.app.state.document_query
    )


    try:

        result = (
            query_service
            .get_review_queue(
                priority=(
                    normalized_priority
                ),

                document_type=(
                    normalized_document_type
                ),
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "review_queue_load_failed"
            ),

            message=(
                "Failed to load "
                "review queue."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "REVIEW_QUEUE_LOAD_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "REVIEW_QUEUE_LOAD_FAILED"
            ),

            message=(
                "Failed to load "
                "review queue."
            ),
        ) from exc


    return result


# ==========================================================
# SUBMIT HUMAN REVIEW
# PHASE 7B / 7C.1 / 7C.5 / 7C.7c
# ==========================================================

@app.post(
    "/api/v1/documents/{document_id}/reviews",
    tags=["Reviews"],
)
def submit_human_review(
    document_id: str,
    payload: HumanReviewRequest,
    request: Request,
):

    # ======================================================
    # 1. RESOLVE TRUSTED REVIEWER IDENTITY
    # ======================================================

    identity_service = (
        request.app.state
        .reviewer_identity
    )


    try:

        reviewer_identity = (
            identity_service
            .resolve_reviewer(
                headers=(
                    request.headers
                )
            )
        )


    # ======================================================
    # AUTHENTICATION REQUIRED
    # ======================================================

    except ReviewerAuthenticationRequired as exc:

        raise APIError(
            status_code=401,

            code=(
                "REVIEWER_AUTHENTICATION_REQUIRED"
            ),

            message=(
                "Reviewer authentication "
                "is required."
            ),
        ) from exc


    # ======================================================
    # REVIEW WRITE NOT AUTHORIZED
    # ======================================================

    except ReviewerAuthorizationError as exc:

        raise APIError(
            status_code=403,

            code=(
                "REVIEWER_NOT_AUTHORIZED"
            ),

            message=(
                "Reviewer is not authorized "
                "to submit human reviews."
            ),
        ) from exc


    # ======================================================
    # 2. LOAD DOCUMENT
    # ======================================================

    query_service = (
        request.app.state
        .document_query
    )


    try:

        stored_document = (
            query_service
            .get_document(
                document_id
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "review_document_query_failed"
            ),

            message=(
                "Failed to load document "
                "for human review."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_QUERY_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_QUERY_FAILED"
            ),

            message=(
                "Failed to load document."
            ),
        ) from exc


    # ======================================================
    # DOCUMENT NOT FOUND
    # ======================================================

    if stored_document is None:

        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_NOT_FOUND"
            ),

            message=(
                "Document not found."
            ),
        )


    # ======================================================
    # 3. LOAD STORED MACHINE ANALYSIS
    # ======================================================

    analysis = (
        stored_document[
            "analysis"
        ]
    )


    if analysis is None:

        raise APIError(
            status_code=409,

            code=(
                "DOCUMENT_ANALYSIS_MISSING"
            ),

            message=(
                "Document does not have "
                "a stored analysis."
            ),
        )


    # ======================================================
    # 4. LOAD MACHINE REVIEW DECISION
    # ======================================================

    machine_review_result = (
        analysis[
            "review_decision"
        ]
    )


    if machine_review_result is None:

        raise APIError(
            status_code=409,

            code=(
                "MACHINE_REVIEW_DECISION_MISSING"
            ),

            message=(
                "Stored document does not "
                "have a machine review "
                "decision."
            ),
        )


    # ======================================================
    # 5. VALIDATE HUMAN REVIEW
    # ======================================================

    human_review_service = (
        request.app.state
        .human_review
    )


    try:

        review_result = (
            human_review_service
            .submit_review(
                document_id=(
                    document_id
                ),

                reviewer_id=(
                    reviewer_identity
                    .reviewer_id
                ),

                review_result=(
                    machine_review_result
                ),

                action=(
                    payload.action
                ),

                notes=(
                    payload.notes
                ),

                corrections=(
                    payload.corrections
                ),
            )
        )


    except ValueError as exc:

        raise APIError(
            status_code=400,

            code=(
                "INVALID_HUMAN_REVIEW"
            ),

            message=str(
                exc
            ),
        ) from exc


    # ======================================================
    # 6. PERSIST HUMAN REVIEW + AUDIT
    # ======================================================

    persistence_service = (
        request.app.state
        .persistence
    )


    try:

        persisted = (
            persistence_service
            .save_human_review(
                review_result=(
                    review_result
                )
            )
        )


    # ======================================================
    # DUPLICATE / CONCURRENT HUMAN REVIEW
    # ======================================================

    except DuplicateHumanReviewError as exc:

        raise APIError(
            status_code=409,

            code=(
                "DOCUMENT_ALREADY_REVIEWED"
            ),

            message=(
                "Document has already "
                "been reviewed."
            ),
        ) from exc


    # ======================================================
    # DOMAIN PERSISTENCE REJECTION
    # ======================================================

    except ValueError as exc:

        raise APIError(
            status_code=400,

            code=(
                "HUMAN_REVIEW_PERSISTENCE_REJECTED"
            ),

            message=str(
                exc
            ),
        ) from exc


    # ======================================================
    # UNEXPECTED REVIEW PERSISTENCE FAILURE
    # ======================================================

    except Exception as exc:

        log_exception(
            logger,

            event=(
                "human_review_persistence_failed"
            ),

            message=(
                "Human review persistence "
                "failed."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            reviewer_id=(
                reviewer_identity
                .reviewer_id
            ),

            status_code=500,

            error_code=(
                "HUMAN_REVIEW_PERSISTENCE_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "HUMAN_REVIEW_PERSISTENCE_FAILED"
            ),

            message=(
                "Human review persistence "
                "failed."
            ),
        ) from exc


    # ======================================================
    # 7. SUCCESS RESPONSE
    # ======================================================

    return {
        "status":
            "success",

        "document_id":
            document_id,

        "review_id":
            persisted[
                "review_id"
            ],

        "audit_event_id":
            persisted[
                "audit_event_id"
            ],

        "human_action":
            persisted[
                "human_action"
            ],

        "authenticated_reviewer": {
            "reviewer_id":
                reviewer_identity
                .reviewer_id,

            "role":
                reviewer_identity
                .role,

            "source":
                reviewer_identity
                .source,
        },

        "review":
            review_result,
    }


# ==========================================================
# GET DOCUMENT AUDIT HISTORY
# PHASE 7C.7c
# ==========================================================

@app.get(
    "/api/v1/documents/{document_id}/history",
    tags=["Audit"],
)
def get_document_history(
    document_id: str,
    request: Request,
):

    query_service = (
        request.app.state.document_query
    )


    # ======================================================
    # LOAD HISTORY
    # ======================================================

    try:

        history = (
            query_service
            .get_document_history(
                document_id
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_history_load_failed"
            ),

            message=(
                "Failed to load "
                "document history."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            document_id=(
                document_id
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_HISTORY_LOAD_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_HISTORY_LOAD_FAILED"
            ),

            message=(
                "Failed to load "
                "document history."
            ),
        ) from exc


    # ======================================================
    # DOCUMENT NOT FOUND
    # ======================================================

    if history is None:

        raise APIError(
            status_code=404,

            code=(
                "DOCUMENT_NOT_FOUND"
            ),

            message=(
                "Document not found."
            ),
        )


    # ======================================================
    # SUCCESS RESPONSE
    # ======================================================

    return {
        "status":
            "success",

        **history,
    }