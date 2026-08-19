import shutil
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

from src.api.schemas import (
    HumanReviewRequest,
    ReviewQueueResponse,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.query_service import (
    DocumentQueryService,
)

from src.human_review_service import (
    HumanReviewService,
)

from src.pipeline_service import (
    DocumentPipelineService,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


# ==========================================================
# FILE CONFIGURATION
# ==========================================================

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


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
    # Database write service
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
        "storage, human review and "
        "audit-history API."
    ),
    lifespan=lifespan,
)


# ==========================================================
# HEALTH CHECK
# ==========================================================

@app.get(
    "/health",
    tags=["System"],
)
def health_check():

    return {
        "status": "ok",
        "service":
            "vigilox-document-intelligence",
        "version": "0.1.0",
    }


# ==========================================================
# ANALYZE + PERSIST DOCUMENT
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
                "Supported formats: JPG, PNG, WEBP."
            )
        ),
    ],
):

    # ======================================================
    # 1. VALIDATE CONTENT TYPE
    # ======================================================

    content_type = (
        file.content_type
        or ""
    )


    if (
        content_type
        not in ALLOWED_CONTENT_TYPES
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Supported formats are "
                "JPG, PNG and WEBP."
            ),
        )


    # ======================================================
    # 2. DETERMINE TEMPORARY FILE SUFFIX
    # ======================================================

    suffix = (
        CONTENT_TYPE_SUFFIXES[
            content_type
        ]
    )


    temp_path = None


    try:

        # ==================================================
        # 3. SAVE UPLOADED DOCUMENT TEMPORARILY
        # ==================================================

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            shutil.copyfileobj(
                file.file,
                temp_file,
            )

            temp_path = (
                temp_file.name
            )


        # ==================================================
        # 4. RUN COMPLETE DOCUMENT PIPELINE
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
        # 5. PERSIST COMPLETE RESULT TO POSTGRESQL
        # ==================================================

        persistence_service = (
            request.app.state.persistence
        )


        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    file.filename
                    or "uploaded_document"
                ),

                content_type=(
                    content_type
                ),

                pipeline_result=(
                    pipeline_result
                ),
            )
        )


        # ==================================================
        # 6. RETURN PERSISTED API RESPONSE
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
                file.filename,

            "content_type":
                content_type,

            "processing_status":
                stored[
                    "processing_status"
                ],

            "analysis":
                pipeline_result,
        }


    except HTTPException:

        raise


    except Exception as exc:

        print(
            "[DOCUMENT ANALYSIS ERROR]",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Document processing "
                "or persistence failed."
            ),
        ) from exc


    finally:

        # ==================================================
        # 7. REMOVE TEMPORARY FILE
        # ==================================================

        if temp_path:

            path = Path(
                temp_path
            )

            if path.exists():

                path.unlink()


        file.file.close()


# ==========================================================
# GET STORED DOCUMENT + ANALYSIS
# ==========================================================

@app.get(
    "/api/v1/documents/{document_id}",
    tags=["Documents"],
)
def get_document(
    document_id: str,
    request: Request,
):

    # ======================================================
    # 1. QUERY POSTGRESQL
    # ======================================================

    query_service = (
        request.app.state.document_query
    )


    result = (
        query_service.get_document(
            document_id
        )
    )


    # ======================================================
    # 2. DOCUMENT DOES NOT EXIST
    # ======================================================

    if result is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Document not found."
            ),
        )


    # ======================================================
    # 3. DATABASE INTEGRITY CHECK
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

        raise HTTPException(
            status_code=500,
            detail=(
                "Stored document analysis "
                "is missing."
            ),
        )


    # ======================================================
    # 4. RETURN STORED DOCUMENT
    # ======================================================

    return {
        "status":
            "success",

        **result,
    }


# ==========================================================
# GET REVIEW QUEUE
# PHASE 7A
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
                "Allowed values: HIGH, MEDIUM, LOW."
            )
        ),
    ] = None,

    document_type: Annotated[
        str | None,
        Query(
            description=(
                "Optional document-type filter. "
                "Allowed values: guard_license, "
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
            priority.strip().upper()
        )


        if (
            normalized_priority
            not in ALLOWED_REVIEW_PRIORITIES
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid priority. "
                    "Allowed values are "
                    "HIGH, MEDIUM and LOW."
                ),
            )


    # ======================================================
    # 2. NORMALIZE DOCUMENT TYPE FILTER
    # ======================================================

    normalized_document_type = None


    if document_type is not None:

        normalized_document_type = (
            document_type.strip().lower()
        )


        if (
            normalized_document_type
            not in ALLOWED_DOCUMENT_TYPES
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid document_type. "
                    "Allowed values are "
                    "guard_license, "
                    "sia_badge and id_card."
                ),
            )


    # ======================================================
    # 3. QUERY PENDING REVIEW DOCUMENTS
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

        print(
            "[REVIEW QUEUE ERROR]",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to load review queue."
            ),
        ) from exc


    # ======================================================
    # 4. RETURN QUEUE
    # ======================================================

    return result


# ==========================================================
# SUBMIT HUMAN REVIEW
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
    # 1. LOAD DOCUMENT FROM POSTGRESQL
    # ======================================================

    query_service = (
        request.app.state.document_query
    )


    stored_document = (
        query_service.get_document(
            document_id
        )
    )


    # ======================================================
    # 2. DOCUMENT DOES NOT EXIST
    # ======================================================

    if stored_document is None:

        raise HTTPException(
            status_code=404,
            detail=(
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

        raise HTTPException(
            status_code=409,
            detail=(
                "Document does not have "
                "a stored analysis."
            ),
        )


    # ======================================================
    # 4. USE TRUSTED MACHINE REVIEW RESULT
    # ======================================================

    machine_review_result = (
        analysis[
            "review_decision"
        ]
    )


    if machine_review_result is None:

        raise HTTPException(
            status_code=409,
            detail=(
                "Stored document does not "
                "have a machine review decision."
            ),
        )


    # ======================================================
    # 5. VALIDATE HUMAN REVIEW
    # ======================================================

    human_review_service = (
        request.app.state.human_review
    )


    try:

        review_result = (
            human_review_service
            .submit_review(
                document_id=(
                    document_id
                ),

                reviewer_id=(
                    payload.reviewer_id
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

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


    # ======================================================
    # 6. PERSIST HUMAN REVIEW + HUMAN AUDIT EVENT
    # ======================================================

    persistence_service = (
        request.app.state.persistence
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


    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


    except Exception as exc:

        print(
            "[HUMAN REVIEW PERSISTENCE ERROR]",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Human review persistence "
                "failed."
            ),
        ) from exc


    # ======================================================
    # 7. RETURN PERSISTED REVIEW
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

        "review":
            review_result,
    }


# ==========================================================
# GET DOCUMENT AUDIT HISTORY
# ==========================================================

@app.get(
    "/api/v1/documents/{document_id}/history",
    tags=["Audit"],
)
def get_document_history(
    document_id: str,
    request: Request,
):

    # ======================================================
    # 1. QUERY DOCUMENT AUDIT HISTORY
    # ======================================================

    query_service = (
        request.app.state.document_query
    )


    history = (
        query_service
        .get_document_history(
            document_id
        )
    )


    # ======================================================
    # 2. DOCUMENT DOES NOT EXIST
    # ======================================================

    if history is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Document not found."
            ),
        )


    # ======================================================
    # 3. RETURN COMPLETE AUDIT TIMELINE
    # ======================================================

    return {
        "status":
            "success",

        **history,
    }