import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    sessionmaker,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================
#
# load_dotenv does NOT override variables already present in
# the environment, which is the behaviour a container needs: a
# .env file is a development convenience, and real deployment
# values arrive as environment variables and win.
# ==========================================================

load_dotenv()


# ==========================================================
# DATABASE URL
# ==========================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


if not DATABASE_URL:

    raise RuntimeError(
        "DATABASE_URL is not configured. "
        "Add it to the .env file."
    )


# ==========================================================
# DECLARATIVE BASE
# ==========================================================

class Base(
    DeclarativeBase
):
    pass


# ==========================================================
# CONNECTION POOL
# PHASE 11.2
# ==========================================================
#
# WHAT WAS WRONG WITH THE DEFAULTS
# ----------------------------------------------------------
# The engine was created with pool_pre_ping and nothing else,
# so it inherited SQLAlchemy's QueuePool defaults:
#
#     pool_size       5
#     max_overflow    10      -> 15 connections
#     pool_timeout    30 seconds
#     pool_recycle    -1      -> never
#
# Every route in this application is a synchronous `def`.
# FastAPI runs those in Starlette's AnyIO worker thread pool,
# whose default capacity is 40 threads. So the server admits
# 40 concurrent requests into code that each opens a session.
#
# 40 requests competing for 15 connections means requests
# 16-40 block on the pool for pool_timeout and then raise
# TimeoutError -- a 500, under load, from a healthy database.
#
# The defect was not the pool size. It was that the two
# numbers were set independently and nothing made them agree.
#
#
# HOW THEY AGREE NOW
# ----------------------------------------------------------
# REQUEST_CONCURRENCY is the one number. The pool is sized to
# serve it, and backend/app/main.py caps the AnyIO thread pool
# to the same value at startup, so the server never admits
# more concurrent work than it has connections for.
#
# A request then waits for a THREAD -- which frees the moment
# any in-flight request finishes -- instead of waiting for a
# connection and timing out. Under overload the behaviour is
# queueing, not failure.
#
#
# WHAT POSTGRESQL HAS TO ALLOW
# ----------------------------------------------------------
# Connections are per PROCESS, not per deployment:
#
#     each API process      up to REQUEST_CONCURRENCY
#     each worker process    up to worker concurrency + 1
#
# So 2 API processes and 1 worker at the defaults is
# 2 x 20 + 2 = 42 connections. PostgreSQL's max_connections
# defaults to 100, and a portion of that is reserved for
# superuser connections.
#
# Multiply before scaling out. This is the number that turns a
# horizontal scale-up into "FATAL: sorry, too many clients
# already".
# ==========================================================

def _configured_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:

    """
    An integer from the environment, clamped.

    An unset, blank or unparseable value falls back to the
    default rather than raising. A pool that refuses to be
    created takes the whole process down, and a typo in an
    environment variable is not worth that -- the clamp keeps
    a mistake survivable instead.
    """

    raw = os.getenv(
        name,
        "",
    ).strip()

    if not raw:
        return default

    try:
        value = int(
            raw
        )

    except ValueError:
        return default

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


# How many requests this process will run at once.
#
# 20 rather than the framework's 40: every request in this
# application does database work, and 20 concurrent
# connections per process leaves room to run two API processes
# and a worker inside a default PostgreSQL max_connections of
# 100 without arithmetic gymnastics.
#
# Raising it means raising max_connections, or putting a
# connection pooler in front.
REQUEST_CONCURRENCY = _configured_int(
    "VIGILOX_REQUEST_CONCURRENCY",
    20,
    1,
    200,
)


# Kept open between requests. The rest of REQUEST_CONCURRENCY
# is overflow: opened on demand under load and closed again
# when it passes, so an idle process does not hold twenty
# connections it is not using.
POOL_SIZE = _configured_int(
    "VIGILOX_DB_POOL_SIZE",
    min(
        10,
        REQUEST_CONCURRENCY,
    ),
    1,
    200,
)


MAX_OVERFLOW = max(
    0,
    REQUEST_CONCURRENCY - POOL_SIZE,
)


# Short on purpose. With the thread pool capped to the same
# concurrency, waiting for a connection should be close to
# impossible -- so if it happens, something is wrong and a
# fast error is more useful than a request that hangs for
# thirty seconds and then fails anyway.
POOL_TIMEOUT_SECONDS = _configured_int(
    "VIGILOX_DB_POOL_TIMEOUT_SECONDS",
    10,
    1,
    120,
)


# Reopen a connection older than this.
#
# pool_pre_ping already catches a connection a firewall or
# proxy killed while idle, at the cost of a round trip. This
# stops them reaching that age in the first place, and bounds
# how long one process can hold a single server-side session
# open -- which matters when the database is behind anything
# that ages connections out, and when a deploy needs old
# connections to drain.
POOL_RECYCLE_SECONDS = _configured_int(
    "VIGILOX_DB_POOL_RECYCLE_SECONDS",
    1800,
    60,
    86400,
)


# libpq connect timeout, in seconds.
#
# Without it, a TCP connect to an unreachable database can
# hang for the operating system's timeout -- minutes on some
# platforms -- holding the request thread the whole time. The
# readiness endpoint exists to report that the database is
# unreachable, and it cannot do that if checking blocks
# indefinitely.
CONNECT_TIMEOUT_SECONDS = _configured_int(
    "VIGILOX_DB_CONNECT_TIMEOUT_SECONDS",
    10,
    1,
    120,
)


# ==========================================================
# DATABASE ENGINE
# ==========================================================

engine = create_engine(
    DATABASE_URL,

    # Verify a pooled connection before handing it out. One
    # extra round trip; the alternative is a stale connection
    # surfacing as a request failure.
    pool_pre_ping=True,

    pool_size=POOL_SIZE,

    max_overflow=MAX_OVERFLOW,

    pool_timeout=POOL_TIMEOUT_SECONDS,

    pool_recycle=POOL_RECYCLE_SECONDS,

    connect_args={
        "connect_timeout": (
            CONNECT_TIMEOUT_SECONDS
        ),
    },
)


# ==========================================================
# SESSION FACTORY
# ==========================================================

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def pool_configuration() -> dict:

    """
    What this process is configured to use.

    Reported by the readiness endpoint and asserted by the
    Phase 11.2 tests, so the numbers in the deployment
    documentation are the numbers the process actually holds
    rather than the ones someone wrote down.
    """

    return {
        "request_concurrency":
            REQUEST_CONCURRENCY,

        "pool_size":
            POOL_SIZE,

        "max_overflow":
            MAX_OVERFLOW,

        "max_connections_per_process":
            POOL_SIZE
            + MAX_OVERFLOW,

        "pool_timeout_seconds":
            POOL_TIMEOUT_SECONDS,

        "pool_recycle_seconds":
            POOL_RECYCLE_SECONDS,

        "connect_timeout_seconds":
            CONNECT_TIMEOUT_SECONDS,

        "pool_pre_ping":
            True,
    }
