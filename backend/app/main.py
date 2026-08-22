import logging
import os
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
    PlainTextResponse,
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

from backend.app.api.security_headers import (
    register_security_headers_middleware,
)

from backend.app.api.rate_limit import (
    register_upload_rate_limit_middleware,
)

from backend.app.api.metrics_middleware import (
    register_request_metrics_middleware,
)

from backend.app.services.metrics_service import (
    metrics_enabled,
    render as render_metrics,
)

from backend.app.services.worker_health_service import (
    WorkerHealthService,
)

from backend.app.api.request_validation import (
    MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES,
    copy_upload_with_limit,
    normalize_upload_filename,
    validate_upload_content_type,
)

from backend.app.api.schemas import (
    DashboardSummaryResponse,
    DocumentListResponse,
    HumanReviewRequest,
    ReviewQueueResponse,
)

from backend.app.services.persistence_service import (
    DuplicateHumanReviewError,
    PersistenceService,
)

from backend.app.services.final_record_service import (
    FinalRecordService,
)

from backend.app.domain.classification import (
    MACHINE_DECISIONS,
)

from backend.app.services.job_service import (
    JobService,
)

from backend.app.services.lazy_pipeline import (
    LazyPipeline,
    eager_pipeline_enabled,
)

from backend.app.api.job_routes import (
    router as job_router,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from database.summary_repositories import (
    DocumentSummaryRepository,
)

from database.database import (
    REQUEST_CONCURRENCY,
    pool_configuration,
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
# DEPLOYMENT ENVIRONMENT
# PHASE 11.5
# ==========================================================
#
# development or production, and nothing else. An unrecognised
# value reads as development, so a typo cannot accidentally
# turn the production checks OFF -- it can only fail to turn
# them on, which is loud in a different way: the posture check
# does not run and the deployment documentation says it
# should have.
#
# The inverse default would be worse. Defaulting to production
# on an unrecognised value would stop a developer's machine
# starting because of a typo.
# ==========================================================

def deployment_environment() -> str:

    raw = os.getenv(
        "VIGILOX_ENVIRONMENT",
        "development",
    ).strip().lower()

    return (
        "production"
        if raw == "production"
        else "development"
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

# Re-exported. The definition moved to
# backend/app/api/request_validation.py so the synchronous
# analyze route and the async job routes read the same
# constant. This name is kept because it is imported from here
# by tests and by the upload suite.
MAX_UPLOAD_BYTES = (
    _MAX_UPLOAD_BYTES
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
# DOCUMENTS LIST CONFIGURATION
# PHASE 8.8A
# ==========================================================
#
# Every accepted value is taken from the authoritative
# producer rather than restated by hand:
#
#     final states       FinalRecordService.FINAL_STATUSES
#     machine decisions  review_decision_service
#     expiry statuses    date_logical_validator
#     sort fields        DocumentSummaryRepository.SORTABLE
#
# page_size is capped so no caller can request an unbounded
# page.
# ==========================================================

DEFAULT_PAGE_SIZE = 25

MAX_PAGE_SIZE = 100

DEFAULT_DOCUMENT_SORT = "created_at"

# PHASE 10.2 added UNSUPPORTED_DOCUMENT. Sourced from the
# domain rather than retyped, so a filter cannot go stale
# against the value the pipeline actually writes.
ALLOWED_MACHINE_DECISIONS = set(
    MACHINE_DECISIONS
)


# From date_logical_validator. NOT_AVAILABLE is the default
# when a document carries no expiry date.
ALLOWED_EXPIRY_STATUSES = {
    "EXPIRED",
    "EXPIRES_TODAY",
    "EXPIRING_SOON",
    "ACTIVE",
    "NOT_AVAILABLE",
}


ALLOWED_SORT_DIRECTIONS = {
    "asc",
    "desc",
}


MAX_SEARCH_LENGTH = 200


DASHBOARD_RECENT_LIMIT = 5


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
    # REQUEST CONCURRENCY
    # PHASE 11.2
    # ------------------------------------------------------
    #
    # Every route in this application is a synchronous `def`,
    # so Starlette runs each one in an AnyIO worker thread.
    # That thread pool defaults to 40, and every route touches
    # the database -- against a connection pool that, before
    # Phase 11.2, held 15.
    #
    # 40 concurrent requests and 15 connections means requests
    # 16-40 waited on the pool and then raised TimeoutError. A
    # 500, under load, from a database that was perfectly
    # healthy.
    #
    # Capping the thread pool to the same number the
    # connection pool is sized for makes the failure mode
    # queueing instead. A request waits for a THREAD, which
    # frees as soon as any in-flight request finishes, rather
    # than waiting for a connection that will not arrive.
    #
    # The two numbers now come from one place:
    # database.database.REQUEST_CONCURRENCY.
    #
    # Set here rather than at import time because the limiter
    # belongs to the running event loop, and there is no loop
    # until the application starts.
    # ------------------------------------------------------

    import anyio.to_thread

    anyio.to_thread.current_default_thread_limiter().total_tokens = (
        REQUEST_CONCURRENCY
    )

    app.state.pool = pool_configuration()

    # log_event takes a fixed set of fields on purpose -- see
    # backend/app/core/logging.py -- so the numbers go in the
    # message rather than as ad-hoc labels.
    log_event(
        logger,

        event=(
            "request_concurrency_configured"
        ),

        message=(
            "Request concurrency capped to "
            f"{REQUEST_CONCURRENCY}, matching a database "
            "pool of "
            f"{app.state.pool['max_connections_per_process']}"
            " connections for this process."
        ),
    )


    # ------------------------------------------------------
    # Complete OCR + LLM + validation pipeline
    # ------------------------------------------------------

    # ------------------------------------------------------
    # PHASE 9.5
    # ------------------------------------------------------
    #
    # The pipeline constructs PaddleOCR, which the Phase 9.5
    # measurement put at 1.7 seconds of startup and a few
    # hundred megabytes resident.
    #
    # In the async architecture the API never runs OCR. The
    # worker does. The only route in this process that needs
    # a pipeline is the synchronous POST
    # /api/v1/documents/analyze, kept for compatibility, and a
    # deployment may never call it.
    #
    # So it is wrapped in a holder that constructs on first
    # use. VIGILOX_API_EAGER_PIPELINE controls whether that
    # happens now or later, and it defaults to constructing
    # now -- the behaviour this has always had. Deferring it
    # is a deployment decision with a visible consequence
    # (the first analyze call pays the load), so it is opted
    # into rather than inherited.
    #
    # Either way the model is built at most once per process.
    # ------------------------------------------------------

    app.state.pipeline = (
        LazyPipeline()
    )


    if eager_pipeline_enabled():

        # Touching it builds it, here, while the process is
        # starting rather than during somebody's request.
        app.state.pipeline.get()


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
    # Async document job queue
    # PHASE 9.4
    # ------------------------------------------------------
    #
    # Cheap to construct: it holds a pending-upload store and
    # opens a transaction per call. The expensive services --
    # OCR above all -- belong to the worker process, not to
    # the API.
    # ------------------------------------------------------

    app.state.jobs = (
        JobService()
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
    # DEPLOYMENT POSTURE
    # PHASE 11.5
    # ------------------------------------------------------
    # Refusing to start is the point.
    #
    # A production service running with local_env identity
    # comes up perfectly and attributes every review decision
    # to the same configured reviewer id. Nothing fails,
    # nothing logs an error, and the problem is discovered by
    # auditing decisions after they were made -- which is far
    # worse than a service that would not start.
    #
    # Only enforced when VIGILOX_ENVIRONMENT is production, so
    # development is untouched.
    # ------------------------------------------------------

    posture = (
        app.state.reviewer_identity
        .posture_errors(
            environment=(
                deployment_environment()
            ),
        )
    )

    if posture:

        for problem in posture:

            log_event(
                logger,

                event=(
                    "production_posture_rejected"
                ),

                message=problem,

                level=logging.CRITICAL,
            )

        raise RuntimeError(
            "This configuration must not serve production "
            "traffic:\n  - "
            + "\n  - ".join(
                posture
            )
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
        "jobs",
    ):

        del app.state.jobs


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


    # ------------------------------------------------------
    # RELEASE THE CONNECTION POOL
    # PHASE 11.13
    # ------------------------------------------------------
    #
    # Deleting the service objects above drops the Python
    # references. It does NOT close the pooled database
    # connections: the pool belongs to the engine in
    # database/database.py, which is a module-level object
    # that outlives every one of them.
    #
    # Without this, the process exits with up to
    # REQUEST_CONCURRENCY sockets still open. The kernel
    # closes them, and PostgreSQL notices when it next reads
    # -- logging "unexpected EOF on client connection" for
    # each one, and holding the backend in pg_stat_activity
    # until then.
    #
    # It matters during a rolling deploy, which is when
    # shutdown happens on purpose. Each API replica holds up
    # to 20 connections. Start the replacement before the old
    # process's connections have been noticed as gone and the
    # server is briefly asked for double, against a
    # max_connections that was sized for one set. The failure
    # is "FATAL: sorry, too many clients already" during a
    # deploy that changed nothing about load.
    #
    # dispose() closes them politely and returns immediately;
    # checked-out connections are not waited for, which is
    # correct here because uvicorn has already finished the
    # in-flight requests by the time the lifespan resumes.
    try:

        from database.database import engine

        engine.dispose()

        logger.info(
            "Database connection pool disposed.",
            extra={
                "event":
                    "api.pool_disposed",
            },
        )

    except Exception as error:

        # A shutdown must not fail. An exception here would
        # propagate out of the lifespan and turn a clean stop
        # into a non-zero exit, which a container runtime
        # reports as a crash -- and a deploy that looks like a
        # crash gets rolled back.
        logger.warning(
            "Could not dispose the connection pool.",
            extra={
                "event":
                    "api.pool_dispose_failed",

                "error_type":
                    type(
                        error
                    ).__name__,
            },
        )


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

# ==========================================================
# SECURITY MIDDLEWARE
# PHASE 11.6 / 11.7
# ==========================================================
#
# ORDER MATTERS AND THIS IS THE ORDER.
#
# add_middleware puts each new one OUTSIDE the previous, so
# the LAST registered is the OUTERMOST. The registrations
# below therefore build:
#
#     ServerErrorMiddleware
#       -> RequestIDMiddleware          registered last
#         -> SecurityHeadersMiddleware
#           -> UploadRateLimitMiddleware
#             -> ExceptionMiddleware
#               -> router
#
# Which gives the two properties that matter:
#
#   1. The rate limiter runs inside the request-context
#      middleware, so scope["state"]["request_id"] already
#      exists when it refuses. A refused upload carries the
#      same correlation ID as any other response and is
#      traceable in the logs.
#
#   2. SECURITY HEADERS ARE OUTSIDE THE RATE LIMITER.
#
#      This is the part that was wrong first time round. The
#      rate limiter answers a refused upload ITSELF -- it
#      never calls the application below it. So anything
#      registered inside the limiter does not run for a 429,
#      and with the security middleware in that position the
#      429 came back with no CSP, no nosniff and no
#      framing protection.
#
#      test_phase11_security_boundary caught it and now
#      asserts the header is on the 429 specifically.
# ==========================================================

register_upload_rate_limit_middleware(
    app
)

register_security_headers_middleware(
    app
)

# ==========================================================
# REQUEST METRICS
# PHASE 11.11
# ==========================================================
#
# Registered LAST, which makes it the OUTERMOST application
# middleware, so the duration it measures covers everything
# below: the request context, the security headers, the rate
# limiter, the router and the handler. That is the number a
# client experiences.
#
# Registered innermost it would measure only the handler and
# would MISS a rate-limited 429 entirely -- the limiter
# answers without calling through -- which would hide the one
# response worth alerting on.
# ==========================================================

register_request_context_middleware(
    app
)

register_request_metrics_middleware(
    app
)


# ==========================================================
# ASYNC DOCUMENT JOB ROUTES
# PHASE 9.4
# ==========================================================
#
# Included after the error handlers and the request-context
# middleware, so these routes carry the same structured error
# contract and the same server-authoritative X-Request-ID as
# every route defined in this module.
#
# The synchronous POST /api/v1/documents/analyze below is
# unchanged and is not deprecated.
# ==========================================================

app.include_router(
    job_router
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
# HTML PAGE SERVING
# PHASE 8.6B
# ==========================================================
#
# Every product screen is a static HTML file under
# frontend/pages/ that boots its own JavaScript module. The
# four page routes differed only by filename, so the shared
# behaviour lives here once.
#
# The filename is a module-level literal at every call site.
# No request value reaches this function, so no page route can
# become a path-traversal read.
# ==========================================================

def serve_frontend_page(
    filename: str,
    description: str,
) -> FileResponse:

    page_file = (
        FRONTEND_PAGES_DIRECTORY
        / filename
    )


    if not page_file.exists():

        raise HTTPException(
            status_code=500,
            detail=(
                f"{description} "
                "is not available."
            ),
        )


    return FileResponse(
        path=(
            page_file
        ),

        media_type=(
            "text/html"
        ),
    )


# ==========================================================
# DASHBOARD
# PHASE 8.6B
# ==========================================================
#
# Consumes GET /api/v1/dashboard/summary. The aggregation
# itself is SQL; this route only serves the shell.
# ==========================================================

@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    tags=["Dashboard"],
    include_in_schema=False,
)
def dashboard_page():

    return serve_frontend_page(
        "dashboard.html",
        "Dashboard",
    )


# ==========================================================
# DOCUMENTS
# PHASE 8.8B
# ==========================================================

@app.get(
    "/documents",
    response_class=HTMLResponse,
    tags=["Documents"],
    include_in_schema=False,
)
def documents_page():

    return serve_frontend_page(
        "documents.html",
        "Documents page",
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

    return serve_frontend_page(
        "index.html",
        "Review dashboard",
    )


# ==========================================================
# UPLOAD DOCUMENT PAGE
# PHASE 8.7
# ==========================================================
#
# One authoritative URL: GET /upload
#
# HTML only. The page posts to the existing
# POST /api/v1/documents/analyze; no second analysis endpoint
# exists.
# ==========================================================

@app.get(
    "/upload",
    response_class=HTMLResponse,
    tags=["Dashboard"],
    include_in_schema=False,
)
def upload_document_page():

    return serve_frontend_page(
        "upload.html",
        "Upload page",
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

    # ======================================================
    # document_id is NOT used to choose a file.
    #
    # The same page is served for every id and the browser
    # reads the id back out of window.location, so no request
    # value can influence which file is read from disk.
    # ======================================================

    return serve_frontend_page(
        "review_detail.html",
        "Document review page",
    )


# ==========================================================
# BROWSER ICON
# PHASE 11.16
# ==========================================================
#
# Browsers request /favicon.ico unprompted, at the root, with
# no link telling them to. Every page already links the icon
# from /review/static/, so this route exists only so that the
# unprompted request does not 404.
#
# Why that matters beyond tidiness: a 404 here fills the
# access log with noise on every page load, and some browsers
# fall back to a blank icon for the whole origin after one --
# which is the exact "generic blank icon" outcome the branding
# work is meant to remove.
#
# Serves the same file the pages link, so there is one icon
# rather than two that can drift.
# ==========================================================

@app.get(
    "/favicon.ico",
    include_in_schema=False,
)
def favicon():

    icon = (
        FRONTEND_STATIC_DIRECTORY_PATH
        / "favicon.ico"
    )

    if not icon.is_file():

        # An absent icon must not be a 500. The application
        # works perfectly without it.
        raise APIError(
            status_code=404,

            code="NOT_FOUND",

            message="Not found.",
        )

    return FileResponse(
        icon,
        media_type="image/x-icon",

        # A month. The mark does not change between deploys,
        # and this is requested on every cold page load.
        headers={
            "Cache-Control": "public, max-age=2592000",
        },
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
# OPERATIONAL METRICS
# PHASE 11.11
# ==========================================================
#
# NOT under /api/v1: this is infrastructure, not a business
# resource, and a scraper should not have to know the API
# version. Same reasoning as /health.
#
# TWO controls on who can read it:
#
#   1. The proxy restricts the path to private ranges --
#      docker/nginx/vigilox-locations.conf.
#
#   2. In production the application refuses unless
#      VIGILOX_METRICS_ENABLED is set, so a deployment that
#      exposes the API without that proxy does not hand out
#      queue depth, failure rates and provider behaviour to
#      anyone who asks.
#
# Neither is a secret in the credential sense. All of it is
# useful to somebody probing the service.
# ==========================================================

@app.get(
    "/metrics",
    tags=["System"],
    include_in_schema=False,
)
def operational_metrics():

    if not metrics_enabled():

        raise APIError(
            status_code=404,

            code="NOT_FOUND",

            message=(
                "Not found."
            ),
        )

    return PlainTextResponse(
        content=render_metrics(),

        # The exposition format's own content type. A scraper
        # keys on it.
        media_type=(
            "text/plain; version=0.0.4; charset=utf-8"
        ),
    )


# ==========================================================
# WORKER HEALTH
# PHASE 11.14
# ==========================================================
#
# SEPARATE FROM /health/ready ON PURPOSE.
#
# Readiness answers "should this API process receive
# traffic". The API can serve uploads, reads and reviews
# perfectly well with no worker running -- the uploads simply
# queue. Failing readiness because a worker died would take
# the API out of the load balancer and turn a worker problem
# into an API outage.
#
# So this is its own endpoint, and monitoring alerts on it.
# It answers the question no other check does: is anything
# actually draining the queue.
# ==========================================================

@app.get(
    "/health/workers",
    tags=["System"],
)
def worker_health():

    evaluation = (
        WorkerHealthService()
        .evaluate()
    )

    return {
        "status":
            evaluation["state"],

        "service":
            "vigilox-document-intelligence",

        "workers": {
            "total":
                evaluation["worker_count"],

            "running":
                evaluation["running_count"],

            "draining":
                evaluation["draining_count"],

            "stale":
                evaluation["stale_count"],

            "stale_after_seconds":
                evaluation[
                    "stale_after_seconds"
                ],
        },

        "queue":
            evaluation["queue"],

        # The condition worth paging on: work waiting and
        # nothing healthy to do it.
        "queue_waiting_with_no_worker":
            evaluation[
                "queue_waiting_with_no_worker"
            ],

        # Per worker. worker_id and current_job_id are the
        # only identifiers, and both name a unit of work
        # rather than a person.
        "detail":
            evaluation["workers"],
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

            # PHASE 11.2. What this process is actually
            # configured to use, read from the live engine
            # configuration rather than restated.
            #
            # Reported because the number that matters in
            # production is per PROCESS: an operator sizing
            # PostgreSQL max_connections has to multiply this
            # by the number of replicas, and a value written
            # down in a runbook drifts from the value the
            # process holds. This one cannot.
            #
            # Contains no credentials and no host. The
            # DATABASE_URL is never exposed here.
            "capacity":
                (
                    getattr(
                        request.app.state,
                        "pool",
                        None,
                    )
                ),
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
                ),

                # PHASE 11.5. Where the request actually came
                # from. In trusted_headers mode the identity
                # arrives in a header, and a header can be
                # sent by anything that can reach the port --
                # so it is only honoured from a configured
                # proxy address.
                peer=(
                    request.client.host
                    if request.client
                    else None
                ),
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
            LazyPipeline.resolve(
                request.app.state.pipeline
            )
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
# LIST DOCUMENTS
# PHASE 8.8A
# ==========================================================
#
# Summary list for the Documents screen.
#
# Bounded by construction: page_size is validated against
# MAX_PAGE_SIZE and the query is a single LIMIT/OFFSET page
# plus one count. There is no code path that returns the
# whole table.
# ==========================================================

@app.get(
    "/api/v1/documents",
    tags=["Documents"],
    response_model=DocumentListResponse,
)
def list_documents(
    request: Request,

    page: Annotated[
        int,

        Query(
            description=(
                "1-based page number."
            )
        ),
    ] = 1,

    page_size: Annotated[
        int,

        Query(
            description=(
                "Items per page. "
                f"Maximum {MAX_PAGE_SIZE}."
            )
        ),
    ] = DEFAULT_PAGE_SIZE,

    document_type: Annotated[
        str | None,

        Query(
            description=(
                "guard_license, sia_badge "
                "or id_card."
            )
        ),
    ] = None,

    final_state: Annotated[
        str | None,

        Query(
            description=(
                "AUTO_ACCEPTED, PENDING_REVIEW, "
                "UNSUPPORTED, APPROVED, CORRECTED "
                "or REJECTED."
            )
        ),
    ] = None,

    machine_decision: Annotated[
        str | None,

        Query(
            description=(
                "AUTO_ACCEPT, REVIEW_REQUIRED or "
                "UNSUPPORTED_DOCUMENT."
            )
        ),
    ] = None,

    expiry_status: Annotated[
        str | None,

        Query(
            description=(
                "EXPIRED, EXPIRES_TODAY, "
                "EXPIRING_SOON, ACTIVE or "
                "NOT_AVAILABLE."
            )
        ),
    ] = None,

    search: Annotated[
        str | None,

        Query(
            description=(
                "Matches filename or document id "
                "only. Document contents are not "
                "searched."
            )
        ),
    ] = None,

    sort: Annotated[
        str,

        Query(
            description=(
                "created_at, filename, "
                "document_type, expiry_date "
                "or priority."
            )
        ),
    ] = DEFAULT_DOCUMENT_SORT,

    direction: Annotated[
        str,

        Query(
            description=(
                "asc or desc."
            )
        ),
    ] = "desc",
):

    # ======================================================
    # 1. PAGINATION
    # ======================================================

    if page < 1:

        raise APIError(
            status_code=400,

            code=(
                "INVALID_PAGE"
            ),

            message=(
                "page must be 1 or greater."
            ),
        )


    if page_size < 1:

        raise APIError(
            status_code=400,

            code=(
                "INVALID_PAGE_SIZE"
            ),

            message=(
                "page_size must be 1 or greater."
            ),
        )


    # ==================================================
    # An oversized page_size is REJECTED rather than
    # silently clamped, so a caller is never told it
    # received 500 rows when it received 100.
    # ==================================================

    if page_size > MAX_PAGE_SIZE:

        raise APIError(
            status_code=400,

            code=(
                "PAGE_SIZE_TOO_LARGE"
            ),

            message=(
                "page_size may not exceed "
                f"{MAX_PAGE_SIZE}."
            ),
        )


    # ======================================================
    # 2. ENUM FILTERS
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


    normalized_final_state = None


    if final_state is not None:

        normalized_final_state = (
            final_state
            .strip()
            .upper()
        )


        if (
            normalized_final_state
            not in FinalRecordService.FINAL_STATUSES
        ):

            raise APIError(
                status_code=400,

                code=(
                    "INVALID_FINAL_STATE"
                ),

                message=(
                    "Invalid final_state. Allowed "
                    "values are "
                    + ", ".join(
                        sorted(
                            FinalRecordService
                            .FINAL_STATUSES
                        )
                    )
                    + "."
                ),
            )


    normalized_machine_decision = None


    if machine_decision is not None:

        normalized_machine_decision = (
            machine_decision
            .strip()
            .upper()
        )


        if (
            normalized_machine_decision
            not in ALLOWED_MACHINE_DECISIONS
        ):

            raise APIError(
                status_code=400,

                code=(
                    "INVALID_MACHINE_DECISION"
                ),

                message=(
                    "Invalid machine_decision. "
                    "Allowed values are "
                    "AUTO_ACCEPT, "
                    "REVIEW_REQUIRED and "
                    "UNSUPPORTED_DOCUMENT."
                ),
            )


    normalized_expiry_status = None


    if expiry_status is not None:

        normalized_expiry_status = (
            expiry_status
            .strip()
            .upper()
        )


        if (
            normalized_expiry_status
            not in ALLOWED_EXPIRY_STATUSES
        ):

            raise APIError(
                status_code=400,

                code=(
                    "INVALID_EXPIRY_STATUS"
                ),

                message=(
                    "Invalid expiry_status. "
                    "Allowed values are "
                    + ", ".join(
                        sorted(
                            ALLOWED_EXPIRY_STATUSES
                        )
                    )
                    + "."
                ),
            )


    # ======================================================
    # 3. SORTING
    # ======================================================
    #
    # Whitelisted. A client sort key never reaches SQL.
    # ======================================================

    normalized_sort = (
        sort
        .strip()
        .lower()
    )


    if (
        normalized_sort
        not in DocumentSummaryRepository.SORTABLE
    ):

        raise APIError(
            status_code=400,

            code=(
                "INVALID_SORT_FIELD"
            ),

            message=(
                "Invalid sort field. Allowed "
                "values are "
                + ", ".join(
                    DocumentSummaryRepository
                    .SORTABLE
                )
                + "."
            ),
        )


    normalized_direction = (
        direction
        .strip()
        .lower()
    )


    if (
        normalized_direction
        not in ALLOWED_SORT_DIRECTIONS
    ):

        raise APIError(
            status_code=400,

            code=(
                "INVALID_SORT_DIRECTION"
            ),

            message=(
                "Invalid direction. Allowed "
                "values are asc and desc."
            ),
        )


    # ======================================================
    # 4. SEARCH
    # ======================================================

    normalized_search = None


    if search is not None:

        normalized_search = (
            search.strip()
        )


        if len(
            normalized_search
        ) > MAX_SEARCH_LENGTH:

            raise APIError(
                status_code=400,

                code=(
                    "SEARCH_TERM_TOO_LONG"
                ),

                message=(
                    "search may not exceed "
                    f"{MAX_SEARCH_LENGTH} "
                    "characters."
                ),
            )


        if not normalized_search:

            normalized_search = None


    # ======================================================
    # 5. QUERY
    # ======================================================

    query_service = (
        request.app.state.document_query
    )


    try:

        result = (
            query_service.list_documents(
                page=(
                    page
                ),

                page_size=(
                    page_size
                ),

                document_type=(
                    normalized_document_type
                ),

                final_state=(
                    normalized_final_state
                ),

                machine_decision=(
                    normalized_machine_decision
                ),

                expiry_status=(
                    normalized_expiry_status
                ),

                search=(
                    normalized_search
                ),

                sort=(
                    normalized_sort
                ),

                descending=(
                    normalized_direction
                    == "desc"
                ),
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "document_list_load_failed"
            ),

            message=(
                "Failed to load document list."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DOCUMENT_LIST_LOAD_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DOCUMENT_LIST_LOAD_FAILED"
            ),

            message=(
                "Failed to load documents."
            ),
        ) from exc


    return {
        "status":
            "success",

        **result,
    }


# ==========================================================
# DASHBOARD SUMMARY
# PHASE 8.6A
# ==========================================================
#
# Aggregate counts for the Dashboard screen.
#
# Every value is a SQL aggregate over persisted rows. No
# accuracy, risk, SLA or average-confidence metric is
# returned, because this system defines none.
# ==========================================================

@app.get(
    "/api/v1/dashboard/summary",
    tags=["Dashboard"],
    response_model=DashboardSummaryResponse,
)
def get_dashboard_summary(
    request: Request,
):

    query_service = (
        request.app.state.document_query
    )


    try:

        summary = (
            query_service
            .get_dashboard_summary(
                recent_limit=(
                    DASHBOARD_RECENT_LIMIT
                )
            )
        )


    except Exception as exc:

        log_exception(
            logger,

            event=(
                "dashboard_summary_load_failed"
            ),

            message=(
                "Failed to load dashboard "
                "summary."
            ),

            exc=exc,

            request_id=(
                get_request_id(
                    request
                )
            ),

            status_code=500,

            error_code=(
                "DASHBOARD_SUMMARY_LOAD_FAILED"
            ),
        )


        raise APIError(
            status_code=500,

            code=(
                "DASHBOARD_SUMMARY_LOAD_FAILED"
            ),

            message=(
                "Failed to load dashboard "
                "summary."
            ),
        ) from exc


    return {
        "status":
            "success",

        **summary,
    }


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
                ),

                # PHASE 11.5. See the note at
                # /api/v1/reviewer/me. This is the route that
                # WRITES a review decision into the audit
                # trail under the reviewer's name, so the
                # check matters most here.
                peer=(
                    request.client.host
                    if request.client
                    else None
                ),
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