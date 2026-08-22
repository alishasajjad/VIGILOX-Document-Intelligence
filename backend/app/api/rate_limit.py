"""
==========================================================
PER-PROCESS UPLOAD RATE LIMIT
PHASE 11.7
==========================================================

READ THIS FIRST: WHAT THIS IS NOT
----------------------------------------------------------
This is NOT a globally reliable production rate limit, and
nothing in this file or the deployment documentation should
describe it as one.

It is a dictionary in the memory of one process. That has
four consequences, all of them real:

  1. N replicas allow N times the configured limit. Two API
     processes at 30 uploads a minute allow 60.

  2. A restart forgets everything. Every client's budget is
     back to full.

  3. It cannot see a distributed client. One caller from
     fifty addresses is fifty separate budgets.

  4. It keys on an IP address, which behind a proxy is
     whatever the proxy forwards -- and forwarded headers are
     only trusted from a configured proxy, so behind a
     misconfigured one every request looks like it came from
     the same place.

A real global limit lives in front of the application: the
reverse proxy, an API gateway, or a shared counter in Redis.
That is where a limit that actually bounds total load
belongs, and Phase 11.10 covers the proxy.


SO WHY HAVE IT AT ALL
----------------------------------------------------------
Because it bounds what ONE process will accept, and that is
worth something specific: an upload spends a worker for
roughly thirty seconds of OCR. A loop posting uploads can
fill the queue faster than any number of workers can drain
it, and the queue is durable -- the backlog survives the
restart that stops the loop.

This makes that expensive by default rather than free. It is
a guard rail on a single process, honestly labelled, not a
capacity control.


WHY ONLY THE UPLOAD ROUTES
----------------------------------------------------------
They are the ones that cost something. A GET reads a row; a
POST to a document job takes bytes onto disk and books
seconds of a worker. Limiting reads as well would add a
failure mode to the dashboard for no benefit.
"""

import os
import threading
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.api.security_headers import (
    is_trusted_peer,
)


# ==========================================================
# CONFIGURATION
# ==========================================================

def _configured_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:

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


# Uploads per window, per client, per PROCESS.
#
# 30 a minute is about ten times the rate a single worker can
# actually drain -- roughly three documents a minute at a 28
# second OCR median. So it does not interfere with a real
# intake session, including a 20-file batch, and it does stop
# an unattended loop.
DEFAULT_LIMIT = 30

DEFAULT_WINDOW_SECONDS = 60


# A cap on how many client keys are tracked. Without it, a
# caller cycling through addresses grows the dictionary until
# the process runs out of memory -- turning a rate limiter
# into the denial of service it was added to reduce.
MAX_TRACKED_CLIENTS = 10_000


# The routes worth protecting. Exact paths: a prefix match
# would also cover GET /api/v1/document-jobs/{id}, which is a
# cheap read that the dashboard polls.
LIMITED_ROUTES = (
    (
        "POST",
        "/api/v1/document-jobs",
    ),
    (
        "POST",
        "/api/v1/document-batches",
    ),
    (
        "POST",
        "/api/v1/documents/analyze",
    ),
)


class SlidingWindowCounter:

    """
    Request timestamps per client, trimmed to a window.

    A sliding window rather than a fixed one: a fixed window
    lets a client send the whole allowance at the end of one
    window and again at the start of the next, which is twice
    the limit in an instant.

    Lock-guarded because the application runs synchronous
    routes in a thread pool, so two requests really do touch
    this at the same time.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        max_clients: int = MAX_TRACKED_CLIENTS,
    ):

        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients

        self._lock = threading.Lock()

        self._events: dict[
            str,
            list[float],
        ] = {}


    def check(
        self,
        client: str,
        now: float | None = None,
    ) -> tuple[bool, int]:

        """
        Record an attempt.

        Returns (allowed, retry_after_seconds).
        """

        moment = (
            now
            if now is not None
            else time.monotonic()
        )

        cutoff = (
            moment
            - self.window_seconds
        )

        with self._lock:

            timestamps = [
                stamp
                for stamp in self._events.get(
                    client,
                    [],
                )
                if stamp > cutoff
            ]

            if len(
                timestamps
            ) >= self.limit:

                # How long until the oldest attempt in the
                # window falls out of it.
                retry_after = max(
                    1,
                    int(
                        timestamps[0]
                        + self.window_seconds
                        - moment
                    )
                    + 1,
                )

                self._events[client] = timestamps

                return (
                    False,
                    retry_after,
                )

            timestamps.append(
                moment
            )

            self._events[client] = timestamps

            self._evict(
                cutoff
            )

            return (
                True,
                0,
            )


    def _evict(
        self,
        cutoff: float,
    ) -> None:

        """
        Drop clients with nothing left in the window.

        Called while holding the lock. Only does real work
        once the dictionary is large, so the common path stays
        cheap.
        """

        if len(
            self._events
        ) <= self.max_clients:
            return

        stale = [
            client
            for client, stamps in self._events.items()
            if not stamps
            or stamps[-1] <= cutoff
        ]

        for client in stale:
            del self._events[client]

        # Still over the cap even with nothing stale: a real
        # flood of distinct clients. Drop the oldest rather
        # than grow without bound. This loses their budgets,
        # which is the correct thing to lose.
        if len(
            self._events
        ) > self.max_clients:

            ordered = sorted(
                self._events.items(),
                key=lambda item: (
                    item[1][-1]
                    if item[1]
                    else 0
                ),
            )

            for client, _ in ordered[
                : len(
                    self._events
                )
                - self.max_clients
            ]:
                del self._events[client]


def client_key(
    scope: Scope,
) -> str:

    """
    Who this request is attributed to.

    The immediate peer address, unless the peer is a
    configured trusted proxy -- in which case the first
    address in X-Forwarded-For, which is the client the proxy
    saw.

    An untrusted peer's X-Forwarded-For is IGNORED. Honouring
    it would let any caller send a different value on every
    request and never hit the limit at all, which is the
    standard way this kind of limiter is defeated.
    """

    client = scope.get(
        "client"
    )

    peer = (
        client[0]
        if client
        else None
    )

    if is_trusted_peer(
        peer
    ):

        for name, value in scope.get(
            "headers",
            [],
        ):

            if name == b"x-forwarded-for":

                forwarded = value.decode(
                    "latin-1"
                ).split(
                    ","
                )[0].strip()

                if forwarded:
                    return forwarded

    return (
        peer
        or "unknown"
    )


class UploadRateLimitMiddleware:

    """
    Refuses an upload that exceeds this process's allowance.
    """

    def __init__(
        self,
        app: ASGIApp,
    ):

        self.app = app

        self.enabled = os.getenv(
            "VIGILOX_RATE_LIMIT_ENABLED",
            "true",
        ).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

        self.counter = SlidingWindowCounter(
            limit=_configured_int(
                "VIGILOX_UPLOAD_RATE_LIMIT",
                DEFAULT_LIMIT,
                1,
                100_000,
            ),
            window_seconds=_configured_int(
                "VIGILOX_UPLOAD_RATE_WINDOW_SECONDS",
                DEFAULT_WINDOW_SECONDS,
                1,
                3600,
            ),
        )


    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:

        if (
            not self.enabled
            or scope["type"] != "http"
        ):
            await self.app(
                scope,
                receive,
                send,
            )
            return

        route = (
            scope.get(
                "method",
                "",
            ),
            scope.get(
                "path",
                "",
            ),
        )

        if route not in LIMITED_ROUTES:
            await self.app(
                scope,
                receive,
                send,
            )
            return

        allowed, retry_after = self.counter.check(
            client_key(
                scope
            )
        )

        if allowed:
            await self.app(
                scope,
                receive,
                send,
            )
            return

        await self._refuse(
            scope,
            send,
            retry_after,
        )


    async def _refuse(
        self,
        scope: Scope,
        send: Send,
        retry_after: int,
    ) -> None:

        """
        The same error envelope every other refusal uses.

        Built here rather than raised as an APIError because
        this runs before the router, so no exception handler
        is in scope yet. The shape has to match
        backend/app/api/error_handlers.py, or a client that
        parses errors breaks on this one.
        """

        import json

        request_id = None

        state = scope.get(
            "state"
        )

        if isinstance(
            state,
            dict,
        ):
            request_id = state.get(
                "request_id"
            )

        body = json.dumps(
            {
                "status": "error",

                "error": {
                    "code": "RATE_LIMITED",

                    "message": (
                        "Too many uploads. Wait "
                        f"{retry_after} second(s) and try "
                        "again."
                    ),

                    "details": {
                        "retry_after_seconds": (
                            retry_after
                        ),
                    },
                },

                "request_id": request_id,
            }
        ).encode(
            "utf-8"
        )

        headers = [
            (
                b"content-type",
                b"application/json",
            ),
            (
                b"content-length",
                str(
                    len(
                        body
                    )
                ).encode(
                    "ascii"
                ),
            ),
            (
                b"retry-after",
                str(
                    retry_after
                ).encode(
                    "ascii"
                ),
            ),
        ]

        if request_id:
            headers.append(
                (
                    b"x-request-id",
                    str(
                        request_id
                    ).encode(
                        "latin-1"
                    ),
                )
            )

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )


def register_upload_rate_limit_middleware(
    app,
) -> None:

    app.add_middleware(
        UploadRateLimitMiddleware
    )
