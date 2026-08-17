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
    Request,
    UploadFile,
)

from src.pipeline_service import (
    DocumentPipelineService,
)


# ==========================================================
# CONFIGURATION
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
# APPLICATION LIFESPAN
# ==========================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # ------------------------------------------------------
    # Load environment variables
    # ------------------------------------------------------

    load_dotenv()

    # ------------------------------------------------------
    # Initialize complete document pipeline once
    # ------------------------------------------------------

    app.state.pipeline = (
        DocumentPipelineService()
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
        "evidence validation, field confidence, "
        "date validation, anomaly detection "
        "and human-review decision API."
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
# ANALYZE DOCUMENT
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
    # 2. DETERMINE SAFE TEMP FILE SUFFIX
    # ======================================================

    suffix = (
        CONTENT_TYPE_SUFFIXES[
            content_type
        ]
    )


    temp_path = None


    try:

        # ==================================================
        # 3. SAVE UPLOADED IMAGE TEMPORARILY
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


        result = pipeline.process(
            temp_path
        )


        # ==================================================
        # 5. RETURN API RESULT
        # ==================================================

        return {
            "status": "success",

            "filename":
                file.filename,

            "content_type":
                content_type,

            "analysis":
                result,
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
                "Document processing failed."
            ),
        ) from exc


    finally:

        # ==================================================
        # 6. REMOVE TEMP FILE
        # ==================================================

        if temp_path:

            path = Path(
                temp_path
            )

            if path.exists():

                path.unlink()

        file.file.close()