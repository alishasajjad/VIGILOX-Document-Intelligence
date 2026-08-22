"""
==========================================================
REQUEST METRICS MIDDLEWARE
PHASE 11.11
==========================================================

Records one counter and one duration observation per request.

Pure ASGI, like the other three, so it sees the real status
code of every response including the ones the error handlers
build, and so it does not buffer a response body -- which
matters for the document image endpoint.

WHERE IT SITS
----------------------------------------------------------
Outermost of the application middlewares, so the duration it
measures includes everything below it: the rate limiter, the
security headers, the router and the handler. That is the
number a client experiences.

Placing it innermost would measure only the handler and
silently exclude a rate-limited 429 -- which would make the
one thing worth alerting on invisible in the metrics.
"""

import time

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.services.metrics_service import (
    record_request,
)


class RequestMetricsMiddleware:

    def __init__(
        self,
        app: ASGIApp,
    ) -> None:

        self.app = app


    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:

        if scope["type"] != "http":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        # perf_counter, not time(): a wall clock can step
        # backwards over an NTP correction and produce a
        # negative duration, which lands in the first
        # histogram bucket and quietly skews the distribution.
        started = time.perf_counter()

        observed = {
            "status": 500,
        }

        async def send_with_metrics(
            message,
        ) -> None:

            if message["type"] == "http.response.start":
                observed["status"] = message.get(
                    "status",
                    500,
                )

            await send(
                message
            )

        try:
            await self.app(
                scope,
                receive,
                send_with_metrics,
            )

        finally:

            # In a finally block so a request that raises is
            # still counted. An exception that escapes to
            # ServerErrorMiddleware never reaches the send
            # wrapper, so without this the 500s -- the ones
            # worth knowing about -- would be the only
            # requests missing from the metrics.
            try:
                record_request(
                    method=scope.get(
                        "method",
                        "",
                    ),
                    path=scope.get(
                        "path",
                        "",
                    ),
                    status_code=observed[
                        "status"
                    ],
                    seconds=(
                        time.perf_counter()
                        - started
                    ),
                )

            except Exception:
                # Metrics must never be able to fail a
                # request. Same rule as the heartbeat.
                pass


def register_request_metrics_middleware(
    app,
) -> None:

    app.add_middleware(
        RequestMetricsMiddleware
    )
