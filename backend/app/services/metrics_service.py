"""
==========================================================
OPERATIONAL METRICS
PHASE 11.11
==========================================================

Prometheus text format, from an in-process registry plus a
few values read from PostgreSQL at scrape time.

No prometheus_client dependency. The exposition format is a
few lines of text and the registry needed here is a dict
behind a lock; adding a library to emit forty lines of text
would be more surface than it saves.


THE CARDINALITY RULE, WHICH IS THE WHOLE DESIGN
----------------------------------------------------------
A Prometheus label value creates a separate time series.
Every series costs memory in the scraper, forever, and a
label with unbounded values is the standard way to take a
monitoring system down.

So NO label here may carry:

    document_id         one series per document
    job_id              one series per upload
    filename            one series per upload, and it is
                        user-controlled text
    reviewer identity   a person's name in a metric
    OCR text            all of the above and worse
    an error message    provider messages vary by request

Every label value in this module comes from a FIXED, SMALL
set defined in code: a job status, a stage name, an HTTP
method, a status class, an outcome. That is checkable, and
test_phase11_observability checks it.

The identifiers are not lost -- they are in the structured
log, correlated by request_id. That is the right place for
high-cardinality detail: a log line is written once and read
when needed, a metric series is held forever.


WHY /metrics IS NOT PUBLIC
----------------------------------------------------------
Queue depth, failure rates, provider rate-limit counts and
worker health are not secrets in the credential sense, and
they are all useful to somebody probing the service: they say
how loaded it is, when it is struggling, and whether anyone
is watching. The proxy restricts the endpoint to private
ranges (see docker/nginx/vigilox-locations.conf) and the
application refuses it in production unless explicitly
enabled.
"""

import os
import threading
import time

from collections import defaultdict


# ==========================================================
# THE REGISTRY
# ==========================================================
#
# Process-local, and stated plainly for the same reason the
# rate limiter says it: N replicas produce N sets of counters.
#
# For metrics that is CORRECT rather than a limitation --
# Prometheus scrapes each replica separately and sums across
# them, which is how counters are meant to work. It is only a
# problem if somebody reads one replica's numbers as the whole
# deployment's.
# ==========================================================

class MetricsRegistry:

    def __init__(
        self,
    ) -> None:

        self._lock = threading.Lock()

        self._counters: dict = defaultdict(
            float
        )

        # Histograms as cumulative bucket counts, which is what
        # the Prometheus format wants and what makes
        # quantiles computable across replicas. Storing
        # observations and computing a local p95 would give a
        # number that cannot be aggregated.
        self._histograms: dict = defaultdict(
            lambda: {
                "buckets": defaultdict(
                    int
                ),
                "sum": 0.0,
                "count": 0,
            }
        )

        self.started_at = time.time()


    def increment(
        self,
        name: str,
        labels: tuple = (),
        amount: float = 1.0,
    ) -> None:

        with self._lock:
            self._counters[
                (
                    name,
                    labels,
                )
            ] += amount


    def observe(
        self,
        name: str,
        seconds: float,
        labels: tuple = (),
        buckets: tuple = (),
    ) -> None:

        edges = (
            buckets
            or DEFAULT_BUCKETS
        )

        with self._lock:

            histogram = self._histograms[
                (
                    name,
                    labels,
                )
            ]

            histogram["sum"] += seconds

            histogram["count"] += 1

            for edge in edges:

                if seconds <= edge:
                    histogram["buckets"][
                        edge
                    ] += 1

            histogram["buckets"]["+Inf"] += 1


    def snapshot(
        self,
    ) -> tuple:

        with self._lock:

            return (
                dict(
                    self._counters
                ),
                {
                    key: {
                        "buckets": dict(
                            value["buckets"]
                        ),
                        "sum": value["sum"],
                        "count": value["count"],
                    }
                    for key, value in (
                        self._histograms.items()
                    )
                },
            )


    def reset(
        self,
    ) -> None:

        """For tests. Never called by the application."""

        with self._lock:
            self._counters.clear()
            self._histograms.clear()


# ==========================================================
# BUCKETS
# ==========================================================
#
# Two very different scales, because the things being measured
# are orders of magnitude apart and one set of edges cannot
# describe both.
#
# HTTP: milliseconds to a few seconds. A read is an indexed
# row.
#
# PIPELINE: seconds to minutes. OCR alone measured a 28 second
# median and a 43 second maximum, and the whole pipeline's
# worst case is 268 seconds. Edges are chosen around those
# measurements rather than as round numbers, so a bucket
# boundary sits where a real change in behaviour would show.
# ==========================================================

DEFAULT_BUCKETS = (
    0.005,
    0.025,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


PIPELINE_BUCKETS = (
    1.0,
    5.0,
    15.0,
    30.0,
    45.0,
    60.0,
    120.0,
    300.0,
)


REGISTRY = MetricsRegistry()


# ==========================================================
# ALLOWED LABEL VALUES
# ==========================================================
#
# Every label value the application may emit, enumerated.
#
# This is not documentation -- test_phase11_observability
# asserts that the rendered output contains no label value
# outside these sets, which is what makes the cardinality rule
# enforceable rather than aspirational.
# ==========================================================

HTTP_METHODS = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "OTHER",
)


# The STATUS CLASS, not the code. 2xx rather than 200, 201,
# 202 -- three series instead of dozens, and the question
# anyone actually asks is "how many failures".
STATUS_CLASSES = (
    "2xx",
    "3xx",
    "4xx",
    "5xx",
)


# A route TEMPLATE, never a concrete path. /api/v1/documents/
# {id} rather than the id, or there is one series per document
# -- the exact mistake this rule exists to prevent.
ROUTE_TEMPLATES = (
    "/api/v1/document-jobs",
    "/api/v1/document-jobs/{id}",
    "/api/v1/document-batches",
    "/api/v1/document-batches/{id}",
    "/api/v1/documents",
    "/api/v1/documents/analyze",
    "/api/v1/documents/{id}",
    "/api/v1/documents/{id}/history",
    "/api/v1/documents/{id}/image",
    "/api/v1/documents/{id}/reviews",
    "/api/v1/dashboard/summary",
    "/api/v1/reviews/queue",
    "/api/v1/reviewer/me",
    "/health",
    "/health/ready",
    "/metrics",
    "page",
    "static",
    "other",
)


PIPELINE_STAGES = (
    "quality",
    "ocr",
    "extraction",
    "evidence",
    "confidence",
    "dates",
    "anomalies",
    "persistence",
    "total",
)


PROVIDER_OUTCOMES = (
    "success",
    "rate_limited",
    "transient",
    "invalid_response",
    "model_unavailable",
    "failed",
)


JOB_OUTCOMES = (
    "completed",
    "failed",
    "retried",
)


def route_template(
    path: str,
) -> str:

    """
    Collapse a concrete path to a template.

    The single most important function in this module for
    cardinality: without it, /api/v1/documents/<uuid> would
    create one time series per document that has ever been
    read.

    Anything unrecognised becomes "other" rather than being
    passed through. A path this does not know is exactly the
    case that would otherwise leak an identifier.
    """

    if not path:
        return "other"

    if path.startswith(
        "/review/static/"
    ):
        return "static"

    exact = {
        "/api/v1/document-jobs",
        "/api/v1/document-batches",
        "/api/v1/documents",
        "/api/v1/documents/analyze",
        "/api/v1/dashboard/summary",
        "/api/v1/reviews/queue",
        "/api/v1/reviewer/me",
        "/health",
        "/health/ready",
        "/metrics",
    }

    if path in exact:
        return path

    if path in (
        "/dashboard",
        "/documents",
        "/upload",
        "/review",
        "/",
        "/favicon.ico",
    ):
        return "page"

    parts = [
        part
        for part in path.split(
            "/"
        )
        if part
    ]

    # /api/v1/<collection>/<id>[/<sub>]
    if (
        len(
            parts
        )
        >= 4
        and parts[0] == "api"
        and parts[1] == "v1"
    ):

        collection = parts[2]

        if len(
            parts
        ) == 4:
            candidate = (
                f"/api/v1/{collection}/{{id}}"
            )

        else:
            candidate = (
                f"/api/v1/{collection}/{{id}}/{parts[4]}"
                if len(
                    parts
                )
                > 4
                else f"/api/v1/{collection}/{{id}}"
            )

        if candidate in ROUTE_TEMPLATES:
            return candidate

    # A document review page: /review/<id>
    if (
        len(
            parts
        )
        == 2
        and parts[0] == "review"
    ):
        return "page"

    return "other"


def status_class(
    status_code: int,
) -> str:

    if 200 <= status_code < 300:
        return "2xx"

    if 300 <= status_code < 400:
        return "3xx"

    if 400 <= status_code < 500:
        return "4xx"

    return "5xx"


def http_method(
    method: str,
) -> str:

    candidate = str(
        method
        or ""
    ).upper()

    return (
        candidate
        if candidate in HTTP_METHODS
        else "OTHER"
    )


# ==========================================================
# RECORDING
# ==========================================================

def record_request(
    *,
    method: str,
    path: str,
    status_code: int,
    seconds: float,
) -> None:

    labels = (
        (
            "method",
            http_method(
                method
            ),
        ),
        (
            "route",
            route_template(
                path
            ),
        ),
        (
            "status",
            status_class(
                status_code
            ),
        ),
    )

    REGISTRY.increment(
        "vigilox_http_requests_total",
        labels,
    )

    REGISTRY.observe(
        "vigilox_http_request_duration_seconds",
        seconds,
        labels[:2],
    )


def record_stage(
    *,
    stage: str,
    seconds: float,
) -> None:

    if stage not in PIPELINE_STAGES:
        return

    REGISTRY.observe(
        "vigilox_pipeline_stage_duration_seconds",
        seconds,
        (
            (
                "stage",
                stage,
            ),
        ),
        PIPELINE_BUCKETS,
    )


def record_job_outcome(
    outcome: str,
) -> None:

    if outcome not in JOB_OUTCOMES:
        return

    REGISTRY.increment(
        "vigilox_jobs_total",
        (
            (
                "outcome",
                outcome,
            ),
        ),
    )


def record_provider_outcome(
    outcome: str,
) -> None:

    if outcome not in PROVIDER_OUTCOMES:
        return

    REGISTRY.increment(
        "vigilox_extraction_provider_total",
        (
            (
                "outcome",
                outcome,
            ),
        ),
    )


# ==========================================================
# EXPOSITION
# ==========================================================

def _escape(
    value: str,
) -> str:

    return (
        str(
            value
        )
        .replace(
            "\\",
            "\\\\",
        )
        .replace(
            '"',
            '\\"',
        )
        .replace(
            "\n",
            "",
        )
    )


def _render_labels(
    labels: tuple,
    extra: tuple = (),
) -> str:

    pairs = list(
        labels
    ) + list(
        extra
    )

    if not pairs:
        return ""

    return (
        "{"
        + ",".join(
            f'{name}="{_escape(value)}"'
            for name, value in pairs
        )
        + "}"
    )


def render(
    *,
    include_database: bool = True,
) -> str:

    """
    The Prometheus text exposition.

    include_database=False renders only the in-process
    registry. Used when the database is unreachable: a
    /metrics endpoint that fails because PostgreSQL is down is
    a /metrics endpoint that goes dark exactly when it is most
    needed.
    """

    counters, histograms = REGISTRY.snapshot()

    lines = []


    # ------------------------------------------------------
    # COUNTERS
    # ------------------------------------------------------

    grouped = defaultdict(
        list
    )

    for (
        name,
        labels,
    ), value in counters.items():
        grouped[name].append(
            (
                labels,
                value,
            )
        )

    descriptions = {
        "vigilox_http_requests_total": (
            "HTTP requests by method, route template and "
            "status class."
        ),
        "vigilox_jobs_total": (
            "Document jobs by terminal outcome."
        ),
        "vigilox_extraction_provider_total": (
            "Extraction provider calls by outcome."
        ),
    }

    for name in sorted(
        grouped
    ):

        lines.append(
            f"# HELP {name} "
            f"{descriptions.get(name, name)}"
        )

        lines.append(
            f"# TYPE {name} counter"
        )

        for labels, value in sorted(
            grouped[name]
        ):
            lines.append(
                f"{name}{_render_labels(labels)} "
                f"{value:g}"
            )


    # ------------------------------------------------------
    # HISTOGRAMS
    # ------------------------------------------------------

    histogram_names = defaultdict(
        list
    )

    for (
        name,
        labels,
    ), value in histograms.items():
        histogram_names[name].append(
            (
                labels,
                value,
            )
        )

    for name in sorted(
        histogram_names
    ):

        lines.append(
            f"# HELP {name} Duration in seconds."
        )

        lines.append(
            f"# TYPE {name} histogram"
        )

        for labels, value in sorted(
            histogram_names[name]
        ):

            finite = sorted(
                edge
                for edge in value["buckets"]
                if edge != "+Inf"
            )

            for edge in finite:
                lines.append(
                    f"{name}_bucket"
                    + _render_labels(
                        labels,
                        (
                            (
                                "le",
                                f"{edge:g}",
                            ),
                        ),
                    )
                    + f" {value['buckets'][edge]}"
                )

            lines.append(
                f"{name}_bucket"
                + _render_labels(
                    labels,
                    (
                        (
                            "le",
                            "+Inf",
                        ),
                    ),
                )
                + f" {value['buckets'].get('+Inf', 0)}"
            )

            lines.append(
                f"{name}_sum"
                + _render_labels(
                    labels
                )
                + f" {value['sum']:g}"
            )

            lines.append(
                f"{name}_count"
                + _render_labels(
                    labels
                )
                + f" {value['count']}"
            )


    # ------------------------------------------------------
    # QUEUE AND WORKER HEALTH
    # ------------------------------------------------------
    # Read at scrape time rather than counted in process,
    # because queue depth is a property of the DATABASE, not
    # of this replica. Two API processes each counting uploads
    # would each see part of the queue; one SELECT sees all of
    # it.
    # ------------------------------------------------------

    if include_database:

        try:
            from backend.app.services.worker_health_service import (
                WorkerHealthService,
            )

            health = (
                WorkerHealthService()
                .evaluate()
            )

            lines.append(
                "# HELP vigilox_job_queue_depth Jobs by "
                "status."
            )

            lines.append(
                "# TYPE vigilox_job_queue_depth gauge"
            )

            for status, count in sorted(
                health["queue"].items()
            ):

                if status == "ACTIVE_TOTAL":
                    continue

                lines.append(
                    f'vigilox_job_queue_depth'
                    f'{{status="{_escape(status)}"}} '
                    f"{count}"
                )

            lines.append(
                "# HELP vigilox_workers Workers by state."
            )

            lines.append(
                "# TYPE vigilox_workers gauge"
            )

            for state, count in (
                (
                    "running",
                    health["running_count"],
                ),
                (
                    "draining",
                    health["draining_count"],
                ),
                (
                    "stale",
                    health["stale_count"],
                ),
            ):
                lines.append(
                    f'vigilox_workers{{state="{state}"}} '
                    f"{count}"
                )

            # The one number an alert should page on. A queue
            # with work and nothing healthy to do it is the
            # outage where every other check is green.
            lines.append(
                "# HELP vigilox_queue_waiting_with_no_worker "
                "1 when jobs are waiting and no healthy "
                "worker exists."
            )

            lines.append(
                "# TYPE vigilox_queue_waiting_with_no_worker "
                "gauge"
            )

            lines.append(
                "vigilox_queue_waiting_with_no_worker "
                + (
                    "1"
                    if health[
                        "queue_waiting_with_no_worker"
                    ]
                    else "0"
                )
            )

        except Exception:

            # A scrape must not fail because the database is
            # unreachable. The in-process metrics above are
            # still worth having, and this gauge is the signal
            # that the rest is missing.
            lines.append(
                "# HELP vigilox_metrics_database_available "
                "1 when queue metrics could be read."
            )

            lines.append(
                "# TYPE vigilox_metrics_database_available "
                "gauge"
            )

            lines.append(
                "vigilox_metrics_database_available 0"
            )

        else:
            lines.append(
                "# HELP vigilox_metrics_database_available "
                "1 when queue metrics could be read."
            )

            lines.append(
                "# TYPE vigilox_metrics_database_available "
                "gauge"
            )

            lines.append(
                "vigilox_metrics_database_available 1"
            )


    lines.append(
        "# HELP vigilox_process_uptime_seconds Seconds "
        "since this process started."
    )

    lines.append(
        "# TYPE vigilox_process_uptime_seconds gauge"
    )

    lines.append(
        "vigilox_process_uptime_seconds "
        f"{time.time() - REGISTRY.started_at:.1f}"
    )

    return (
        "\n".join(
            lines
        )
        + "\n"
    )


# ==========================================================
# WHETHER TO EXPOSE IT AT ALL
# ==========================================================

def metrics_enabled() -> bool:

    """
    Whether /metrics answers.

    Enabled by default in development, because a metric nobody
    can see is a metric nobody uses.

    In PRODUCTION it must be turned on deliberately, with
    VIGILOX_METRICS_ENABLED. The proxy already restricts the
    path to private ranges, and this is the second control:
    a deployment that exposes the API without that proxy in
    front does not hand out queue depth, failure rates and
    provider behaviour to anyone who asks.
    """

    raw = os.getenv(
        "VIGILOX_METRICS_ENABLED",
        "",
    ).strip().lower()

    if raw:
        return raw in (
            "1",
            "true",
            "yes",
            "on",
        )

    environment = os.getenv(
        "VIGILOX_ENVIRONMENT",
        "development",
    ).strip().lower()

    return environment != "production"
