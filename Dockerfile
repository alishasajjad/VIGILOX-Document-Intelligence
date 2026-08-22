# ==========================================================
# VIGILOX DOCUMENT INTELLIGENCE
# PHASE 11.8
# ==========================================================
#
# ONE IMAGE, THREE ROLES
# ----------------------------------------------------------
# The API, the worker and the migration step all run from this
# image and differ only in the command:
#
#     docker run vigilox api
#     docker run vigilox worker
#     docker run vigilox migrate
#
# They share the same code, the same dependency set and the
# same PaddleOCR install, so one image is the honest answer.
# Separate images would mean the worker running a different
# build of the pipeline than the API was tested against, and
# would duplicate a ~1 GB dependency tree to save nothing.
#
# The API and the worker do use PaddleOCR differently -- see
# the OCR INITIALISATION note below -- but that is a runtime
# policy, not a reason for a second image.
#
#
# WHAT IS NOT VERIFIED HERE
# ----------------------------------------------------------
# Docker is not installed in the environment this file was
# written in, so THIS IMAGE HAS NEVER BEEN BUILT.
#
# Everything below is derived from the dependency set that is
# actually installed and verified on Python 3.13.9, and the
# structure is statically asserted by
# tests/deployment/test_phase11_containerization.py. But
# `docker build` has not run, and the following in particular
# are unverified:
#
#   - that paddlepaddle 3.3.1 publishes a cp313 wheel for
#     linux/amd64. It is installed and working on cp313
#     Windows here. If the Linux wheel is missing, the pip
#     install fails loudly at build time rather than
#     mis-running later.
#
#   - the final image size
#
#   - the PaddleOCR model download during build
#
# Phase 12's deployment smoke covers all of it, and reports
# EXTERNAL_BLOCKED while no Docker is available. Nothing here
# is claimed as passing.
# ==========================================================


# ==========================================================
# STAGE 1 - DEPENDENCIES
# ==========================================================
#
# 3.13-slim-bookworm: 3.13 because that is the interpreter the
# whole project is verified on, and slim because the build
# tools needed to compile anything are added here and left
# behind in this stage.
# ==========================================================

FROM python:3.13-slim-bookworm AS dependencies


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1


# ----------------------------------------------------------
# BUILD DEPENDENCIES
# ----------------------------------------------------------
# Present for any package without a prebuilt wheel for this
# platform. Confined to this stage: none of it reaches the
# runtime image, where a compiler is only an attacker's tool.
# ----------------------------------------------------------

RUN apt-get update \
 && apt-get install --no-install-recommends --yes \
        build-essential \
        libpq-dev \
 && rm -rf /var/lib/apt/lists/*


WORKDIR /build

COPY requirements.txt ./

# Into a virtualenv rather than the system interpreter, so the
# whole dependency tree is one directory that can be copied
# into the runtime stage as a unit.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --requirement requirements.txt


# ==========================================================
# STAGE 2 - RUNTIME
# ==========================================================

FROM python:3.13-slim-bookworm AS runtime


# ----------------------------------------------------------
# RUNTIME SYSTEM LIBRARIES
# ----------------------------------------------------------
# opencv-python -- not the headless build -- links against
# libGL and glib. The pinned opencv-python 5.0.0.93 is the
# version the pipeline is verified against, so the OS
# libraries are installed rather than the dependency swapped
# for opencv-python-headless. Changing a verified imaging
# dependency to save two packages is the wrong trade at this
# point in a release.
#
# libpq5 is the PostgreSQL client library psycopg needs at
# run time (libpq-dev, which is only needed to build, stayed
# in stage 1).
# ----------------------------------------------------------

RUN apt-get update \
 && apt-get install --no-install-recommends --yes \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libpq5 \
        curl \
 && rm -rf /var/lib/apt/lists/*


# ----------------------------------------------------------
# NON-ROOT USER
# ----------------------------------------------------------
# A fixed uid/gid, because the volumes are bind-mountable and
# a host directory's ownership has to be predictable. 10001 is
# outside the range Debian assigns to system accounts.
#
# Ownership is granted only where the process must write:
# the storage roots and the model cache. The application code
# is left owned by root and read-only to this user, so a
# compromised process cannot rewrite its own code.
# ----------------------------------------------------------

RUN groupadd --gid 10001 vigilox \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin vigilox


ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    # ------------------------------------------------------
    # PADDLEOCR MODEL CACHE
    # ------------------------------------------------------
    # PaddleOCR downloads its models on first use and caches
    # them here. Pointed at a fixed path so it can be a
    # VOLUME.
    #
    # WHY THE MODELS ARE BAKED INTO THE IMAGE BELOW rather
    # than downloaded at run time:
    #
    #   a container that downloads ~150 MB of models on every
    #   start is a container that cannot start when the model
    #   host is unreachable, and a worker that cannot start
    #   is a queue that stops draining. It also pays the
    #   download on every restart and every replica.
    #
    # The cost is image size. That is the right way round: an
    # image is pulled rarely, a container starts often.
    #
    # THIS DIRECTORY MUST NEVER HOLD DOCUMENT DATA. It is a
    # cache of public model weights and is safe to share
    # between replicas and to discard. Managed documents live
    # under /data, which is separate.
    # ------------------------------------------------------
    PADDLE_PDX_MODEL_SOURCE=BOS \
    PADDLE_PDX_CACHE_HOME=/opt/paddle-cache \
    # ------------------------------------------------------
    # STORAGE
    # ------------------------------------------------------
    # Two SEPARATE roots, and they must stay separate.
    #
    # Phase 9.2 established why: a pending upload has no
    # document row yet, by definition. If pending lived inside
    # the managed root, the storage integrity scan would
    # classify every in-flight upload as ORPHAN_STORAGE --
    # the one category reconciliation deletes automatically --
    # and documents would disappear mid-processing.
    #
    # The application refuses to start if pending is nested
    # inside managed, so the mistake is loud. These paths keep
    # them siblings.
    # ------------------------------------------------------
    DOCUMENT_STORAGE_DIR=/data/documents \
    DOCUMENT_PENDING_DIR=/data/pending \
    # ------------------------------------------------------
    # DEPLOYMENT POSTURE
    # ------------------------------------------------------
    # production turns on the Phase 11.5 startup checks that
    # REFUSE TO START with local_env reviewer identity, or
    # with trusted_headers and no VIGILOX_TRUSTED_PROXIES.
    #
    # Set in the image rather than left to compose, so an
    # image run without a full environment fails closed
    # instead of quietly attributing every review decision to
    # one configured reviewer.
    # ------------------------------------------------------
    VIGILOX_ENVIRONMENT=production \
    # ------------------------------------------------------
    # OCR INITIALISATION IN THE API
    # ------------------------------------------------------
    # MEASURED (Phase 9.5, Phase 11.8):
    #
    #     eager API startup   about 2929 ms
    #     lazy  API startup   about 3 ms
    #
    # The API does not run OCR. The worker does. The only
    # route in the API process that needs a pipeline is the
    # synchronous POST /api/v1/documents/analyze kept for
    # compatibility, and a deployment on the job API may never
    # call it.
    #
    # So the API is lazy: it does not load a few hundred
    # megabytes of model per replica for a route that may
    # never be used, and a rolling deploy is not gated on
    # three seconds of model loading per replica.
    #
    # CONSEQUENCE, STATED PLAINLY: readiness on the API no
    # longer means "OCR is loaded in this process". It never
    # meant "OCR works" -- readiness deliberately does not run
    # OCR -- but with lazy loading it does not even mean the
    # model is resident. The first /analyze call after start
    # pays the load.
    #
    # The worker overrides this to eager in its own command,
    # because for the worker the model is the job.
    # ------------------------------------------------------
    VIGILOX_API_EAGER_PIPELINE=false


# ----------------------------------------------------------
# DEPENDENCIES
# ----------------------------------------------------------

COPY --from=dependencies /opt/venv /opt/venv


# ----------------------------------------------------------
# APPLICATION
# ----------------------------------------------------------
# Explicit paths, not "COPY . .". .dockerignore is the
# security boundary and this is the second one: a file that
# is neither excluded there nor named here cannot reach the
# image by accident.
# ----------------------------------------------------------

WORKDIR /app

COPY backend/            /app/backend/
COPY database/           /app/database/
COPY frontend/           /app/frontend/
COPY migrations/         /app/migrations/
COPY alembic.ini         /app/alembic.ini
COPY scripts/maintenance/ /app/scripts/maintenance/
COPY docker/entrypoint.sh /usr/local/bin/vigilox-entrypoint

RUN chmod 0755 /usr/local/bin/vigilox-entrypoint


# ----------------------------------------------------------
# MODEL CACHE, BAKED
# ----------------------------------------------------------
# Downloaded here so a container start needs no outbound
# network. See the PADDLE_PDX_CACHE_HOME note above.
#
# Importing the OCR service is what triggers the download,
# which means this step also proves at BUILD time that
# PaddleOCR can initialise in this image -- a failure here is
# a failed build rather than a worker that starts and cannot
# process anything.
# ----------------------------------------------------------

RUN mkdir -p /opt/paddle-cache \
 && python -c "from backend.app.services.ocr_service import OCRService; OCRService()" \
 && chown -R vigilox:vigilox /opt/paddle-cache


# ----------------------------------------------------------
# WRITABLE STATE
# ----------------------------------------------------------
# Created and owned here so the container works even when no
# volume is mounted, and so a mounted volume has a predictable
# owner to match.
#
# 0750, not 0777: these directories hold identity documents.
# ----------------------------------------------------------

RUN mkdir -p /data/documents /data/pending \
 && chown -R vigilox:vigilox /data \
 && chmod 0750 /data /data/documents /data/pending


VOLUME ["/data"]


USER vigilox


EXPOSE 8000


# ----------------------------------------------------------
# HEALTHCHECK
# ----------------------------------------------------------
# /health is process liveness and touches no dependency, on
# purpose: an orchestrator must never restart a healthy
# process because PostgreSQL blinked. Readiness --
# /health/ready -- is what a load balancer should poll, and
# it is checked by the compose healthcheck instead, where a
# failure means "stop sending traffic" rather than "restart".
#
# Only meaningful for the api role. The worker serves no HTTP,
# and its health is the heartbeat row -- see Phase 11.14.
# ----------------------------------------------------------

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/health || exit 1


ENTRYPOINT ["/usr/local/bin/vigilox-entrypoint"]

CMD ["api"]
