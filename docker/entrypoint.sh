#!/bin/sh
# ==========================================================
# VIGILOX CONTAINER ENTRYPOINT
# PHASE 11.8
# ==========================================================
#
# One image, three roles. This selects which.
#
#     api       the FastAPI application
#     worker    the document job worker
#     migrate   apply Alembic migrations, then exit
#     shell     a shell, for looking at a running deployment
#
# Anything else is passed through unchanged, so
# `docker run vigilox python -c ...` still works for an
# operator who needs it.
#
#
# WHY exec
# ----------------------------------------------------------
# Every branch below uses exec, which REPLACES this shell with
# the real process. That makes the application PID 1, which
# means it receives SIGTERM directly when the container is
# stopped.
#
# Without exec, the shell stays PID 1, and a shell does not
# forward signals to its children. Docker would send SIGTERM,
# nothing would happen, and ten seconds later the container
# would be SIGKILLed -- killing a worker in the middle of a
# document.
#
# That is not a theoretical tidiness point. The worker's
# graceful shutdown (Phase 11.13) is the difference between
# finishing the document in hand and leaving a job to sit
# until its lease expires.
# ==========================================================

set -eu


# ----------------------------------------------------------
# CONFIGURATION WITH DEFAULTS
# ----------------------------------------------------------
# : "${NAME:=value}" sets NAME only if it is unset, so
# anything provided by compose or the orchestrator wins.
# ----------------------------------------------------------

: "${VIGILOX_HOST:=0.0.0.0}"
: "${VIGILOX_PORT:=8000}"

# Worker processes per container.
#
# 1, and that default is measured rather than cautious. OCR is
# essentially all of local pipeline time -- an 18.4 second
# median over the benchmark images -- and PaddleOCR is
# CPU-bound and already multi-threaded internally. Two
# parallel passes on one container contend for the same cores
# and each gets slower, so total throughput barely moves while
# peak memory doubles.
#
# Scale by adding worker CONTAINERS, not by raising this.
: "${VIGILOX_WORKER_CONCURRENCY:=1}"


case "${1:-api}" in

    api)
        # --------------------------------------------------
        # THE API
        # --------------------------------------------------
        # One uvicorn worker per container, deliberately.
        #
        # Scaling is horizontal, by replica, because the
        # process-local pieces do not share state between
        # processes: the rate limiter is a dictionary in one
        # process (Phase 11.7) and the connection pool is per
        # process (Phase 11.2). Multiple uvicorn workers
        # inside one container would multiply both invisibly
        # -- N times the rate limit and N times the
        # connections -- from a single "replicas: 1" in
        # compose.
        #
        # One process per container keeps the multiplication
        # visible in the replica count, which is where an
        # operator can see it and where PostgreSQL
        # max_connections has to be planned against.
        #
        # --no-access-log, NOT --log-config /dev/null.
        #
        # Two reasons, and the first is a privacy one.
        #
        # uvicorn's access log writes the full request PATH,
        # and this application's paths contain document ids:
        #
        #     GET /api/v1/documents/<uuid>/image
        #     GET /review/<uuid>
        #
        # Every document a reviewer opened would be recorded
        # in a plain-text log with no structure and no
        # retention policy of its own. The reverse proxy
        # already keeps an access log with a deliberately
        # chosen format, and the application keeps its own
        # structured log correlated by request id. A third
        # copy adds nothing and spreads the identifiers
        # further.
        #
        # The second reason: --log-config expects a real
        # dictConfig file. Handing it /dev/null does not
        # disable logging, it fails to parse -- so the first
        # version of this line would have stopped the
        # container from starting.
        #
        # --proxy-headers with --forwarded-allow-ips is what
        # makes request.client.host the address the PROXY saw
        # rather than the proxy's own. The Phase 11.5 identity
        # boundary depends on that value, so the allowed
        # forwarder list has to be the proxy and nothing else.
        # It defaults to empty -- trusting nobody -- rather
        # than to "*", because "*" here would let any client
        # set its own apparent address and walk straight
        # through the identity boundary.
        # --------------------------------------------------

        : "${VIGILOX_FORWARDED_ALLOW_IPS:=}"

        if [ -n "${VIGILOX_FORWARDED_ALLOW_IPS}" ]; then

            exec uvicorn backend.app.main:app \
                --host "${VIGILOX_HOST}" \
                --port "${VIGILOX_PORT}" \
                --proxy-headers \
                --forwarded-allow-ips "${VIGILOX_FORWARDED_ALLOW_IPS}" \
                --no-server-header \
                --no-access-log
        fi

        # No forwarder configured: do NOT enable proxy header
        # handling. The application then sees the real peer,
        # which is the safe reading.
        exec uvicorn backend.app.main:app \
            --host "${VIGILOX_HOST}" \
            --port "${VIGILOX_PORT}" \
            --no-server-header \
            --no-access-log
        ;;

    worker)
        # --------------------------------------------------
        # THE WORKER
        # --------------------------------------------------
        # Eager OCR, unlike the API.
        #
        # For the worker the model IS the job, so paying the
        # measured ~2929 ms load at startup is right: once per
        # container instead of on the first document, and NOT
        # while already holding a lease on real work.
        #
        # A model that cannot load then makes the container
        # fail to start, which is visible. Lazily it would
        # instead fail the FIRST CLAIMED JOB -- consuming an
        # attempt, delaying that document by a retry backoff,
        # and leaving the container looking healthy throughout.
        #
        # This is the WORKER's flag, not the API's.
        # VIGILOX_API_EAGER_PIPELINE controls the API's
        # LazyPipeline and has no effect here, because the
        # worker builds its own pipeline. Setting that
        # variable in this branch would look like it did
        # something and do nothing.
        # --------------------------------------------------

        : "${VIGILOX_WORKER_EAGER_PIPELINE:=true}"
        export VIGILOX_WORKER_EAGER_PIPELINE

        exec python -m backend.worker \
            --concurrency "${VIGILOX_WORKER_CONCURRENCY}"
        ;;

    migrate)
        # --------------------------------------------------
        # MIGRATIONS
        # --------------------------------------------------
        # Runs to completion and exits, so it works as an
        # init container or a one-shot compose service.
        #
        # NOT run automatically by the api or worker role. Two
        # replicas starting together would both try to
        # migrate, and a schema change applied twice
        # concurrently is how a deploy corrupts a database.
        # Migration is one deliberate step.
        # --------------------------------------------------

        exec alembic upgrade head
        ;;

    shell)
        exec /bin/sh
        ;;

    *)
        # Anything else runs as given.
        exec "$@"
        ;;

esac
