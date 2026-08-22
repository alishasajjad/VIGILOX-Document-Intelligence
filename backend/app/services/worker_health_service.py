"""
==========================================================
WORKER HEALTH
PHASE 11.14
==========================================================

THE PROBLEM THIS SOLVES
----------------------------------------------------------
A healthy API does not prove a worker exists.

/health says the process is alive. /health/ready says the
database and the storage root are reachable. Neither says
anything about whether anything is draining the queue.

So a deployment could return 202 to every upload for hours
with every worker dead: uploads accepted, queue growing, not
one document processed, and every health check green. That is
the worst shape of outage -- all the individual signals
correct, the product not working.


WHAT COUNTS AS A HEARTBEAT
----------------------------------------------------------
Not "a worker container is running". Not
"VIGILOX_WORKER_CONCURRENCY is set". Both describe intent, and
a worker that is running but wedged -- stuck on a socket,
deadlocked, thrashing -- satisfies both while draining
nothing.

A heartbeat has to be something a worker can only produce by
actually turning its loop. This service writes the row from
inside that loop, so a stale timestamp means the loop stopped,
whatever the orchestrator reports.


FOUR STATES AN OPERATOR HAS TO BE ABLE TO TELL APART
----------------------------------------------------------
    HEALTHY        a worker checked in recently
    DRAINING       a worker is shutting down on purpose
    STALE          a worker checked in, but not lately
    NO_WORKER      nothing has ever checked in

The distinction that matters most is STALE versus NO_WORKER.
The first is a worker that died; the second is a deployment
where the worker was never started -- a missing service in
compose, a typo in a command. They need different responses
and they look identical if all you have is "no recent
heartbeat".

DRAINING matters for a different reason: without it, every
rolling deploy looks like a worker failure for the length of
the grace period, and an alert that fires on every deploy is
an alert that gets muted.
"""

import os
import socket

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from database.database import SessionLocal

from database.models import (
    DocumentJobModel,
    WorkerHeartbeatModel,
)

from backend.app.domain.job_states import (
    ACTIVE_STATUSES,
    PROCESSING,
    QUEUED,
    RETRY_WAIT,
)


# ==========================================================
# STATES
# ==========================================================

HEALTHY = "HEALTHY"

DRAINING = "DRAINING"

STALE = "STALE"

NO_WORKER = "NO_WORKER"


STATUS_RUNNING = "RUNNING"

STATUS_DRAINING = "DRAINING"

STATUS_STOPPED = "STOPPED"


# ==========================================================
# HOW LATE IS LATE
# ==========================================================
#
# The worker writes a heartbeat every time round its loop.
# The loop's period is the poll interval when idle -- 5
# seconds by default -- but while PROCESSING a document the
# loop is inside the pipeline, which measured out at a 268
# second worst case.
#
# So the staleness threshold cannot be a small multiple of
# the poll interval: it has to clear the longest a legitimate
# worker can go without coming round. Anything tighter alarms
# on a worker doing exactly what it is supposed to.
#
# 420 seconds is the 268 second worst case plus room. It is
# deliberately close to the 400 second SIGTERM grace period
# in compose, which is derived from the same measurement.
#
# The cost of a threshold this wide is that a worker which
# dies silently takes up to seven minutes to be reported. That
# is the right trade against alarming on every slow document,
# and the queue-depth signal below fills the gap: a queue
# growing with no completions is visible sooner than a stale
# heartbeat.
# ==========================================================

DEFAULT_STALE_AFTER_SECONDS = 420


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


def stale_after_seconds() -> int:

    return _configured_int(
        "VIGILOX_WORKER_STALE_AFTER_SECONDS",
        DEFAULT_STALE_AFTER_SECONDS,
        30,
        86400,
    )


# ==========================================================
# THERE IS NO WORKER-ID GENERATOR HERE, ON PURPOSE
# ==========================================================
#
# The first version of this module had one, and it was wrong.
#
# document_worker.default_worker_id() already exists and
# already decided this question: host, pid, and a short random
# suffix. The suffix is deliberate -- two workers in one
# container share a hostname, and a pid repeats across
# restarts, so without it a restarted worker could be mistaken
# for the one that just died and could extend its stale lease.
#
# A second generator here produced a DIFFERENT id from the one
# in the job rows. The heartbeat would then have named a
# worker that appeared nowhere else, and correlating "which
# worker is stuck on this job" would have been impossible --
# which is most of the value of having the table.
#
# So the writer takes the worker id it is given, and the
# runner gives it the id of the worker that actually claims
# jobs.
#
# The cost of the random suffix is that a restart leaves the
# old row behind. prune_stale() below bounds that.
# ==========================================================


# ==========================================================
# WRITING THE HEARTBEAT
# ==========================================================

class WorkerHeartbeatWriter:

    """
    Records that this worker is turning its loop.

    Every method swallows database errors on purpose. A
    heartbeat is an OBSERVATION of the work, not part of it: a
    worker that cannot write its heartbeat because the
    database blinked should carry on processing documents, not
    stop. Failing loudly here would turn a monitoring outage
    into a processing outage, which is the wrong way round.

    The heartbeat going stale is itself the signal that
    something is wrong, so a swallowed error is not a silent
    one.
    """

    def __init__(
        self,
        *,
        worker_id: str,
        concurrency: int = 1,
    ) -> None:

        """
        worker_id is REQUIRED and must be the id the worker
        uses in job rows. See the note above on why there is
        no default.
        """

        if not str(
            worker_id
        ).strip():

            raise ValueError(
                "worker_id is required. The heartbeat has to "
                "name the same worker that claims jobs, or "
                "correlating a stuck job to a worker is "
                "impossible."
            )

        self.worker_id = worker_id

        self.concurrency = concurrency

        self.started_at = datetime.now(
            timezone.utc
        )

        self.completed = 0

        self.failed = 0


    def _write(
        self,
        **values,
    ) -> bool:

        try:
            with SessionLocal.begin() as session:

                existing = session.get(
                    WorkerHeartbeatModel,
                    self.worker_id,
                )

                if existing is None:

                    session.add(
                        WorkerHeartbeatModel(
                            worker_id=(
                                self.worker_id
                            ),
                            started_at=(
                                self.started_at
                            ),
                            concurrency=(
                                self.concurrency
                            ),
                            **values,
                        )
                    )

                    return True

                for name, value in values.items():
                    setattr(
                        existing,
                        name,
                        value,
                    )

                existing.concurrency = (
                    self.concurrency
                )

                return True

        except Exception:
            # See the class docstring. Monitoring must not be
            # able to stop processing.
            return False


    def beat(
        self,
        *,
        current_job_id: str | None = None,
        status: str = STATUS_RUNNING,
    ) -> bool:

        return self._write(
            last_seen_at=datetime.now(
                timezone.utc
            ),
            status=status,
            current_job_id=current_job_id,
            jobs_completed=self.completed,
            jobs_failed=self.failed,
        )


    def draining(
        self,
    ) -> bool:

        """
        SIGTERM received; finishing the current document.

        Recorded so a rolling deploy does not look like a
        worker failure for the length of the grace period.
        """

        return self.beat(
            status=STATUS_DRAINING,
        )


    def stopped(
        self,
    ) -> bool:

        """
        Clean exit.

        The row is kept rather than deleted: "a worker stopped
        cleanly two minutes ago" is useful, and an absent row
        would be indistinguishable from a worker that was
        never started.
        """

        return self.beat(
            status=STATUS_STOPPED,
        )


    def prune_stale(
        self,
        *,
        older_than_seconds: int = 86400,
    ) -> int:

        """
        Delete heartbeat rows nothing has touched in a day.

        Needed because a worker id carries a random suffix, so
        a restart leaves the previous row behind. A container
        in a restart loop would otherwise add a row every few
        seconds and turn a health signal into a table that
        needs cleaning.

        A day is long enough that "a worker died this morning"
        is still visible, and short enough that the table
        stays small. Returns how many rows were removed.

        Errors are swallowed for the same reason as the rest
        of this class: a monitoring write must never be able
        to stop a worker processing documents.
        """

        cutoff = datetime.now(
            timezone.utc
        ) - timedelta(
            seconds=older_than_seconds,
        )

        try:
            with SessionLocal.begin() as session:

                rows = session.execute(
                    select(
                        WorkerHeartbeatModel
                    ).where(
                        WorkerHeartbeatModel
                        .last_seen_at
                        < cutoff,
                        WorkerHeartbeatModel
                        .worker_id
                        != self.worker_id,
                    )
                ).scalars().all()

                for row in rows:
                    session.delete(
                        row
                    )

                return len(
                    rows
                )

        except Exception:
            return 0


# ==========================================================
# READING WORKER HEALTH
# ==========================================================

class WorkerHealthService:

    """
    Answers whether anything is draining the queue.

    Read-only. Used by the operational endpoints and by the
    metrics endpoint, and deliberately NOT by /health/ready:
    see the note on evaluate().
    """

    def __init__(
        self,
        *,
        stale_seconds: int | None = None,
    ) -> None:

        self.stale_seconds = (
            stale_seconds
            if stale_seconds is not None
            else stale_after_seconds()
        )


    def queue_depth(
        self,
    ) -> dict:

        """
        How many jobs are in each state.

        Counts, never identifiers. Nothing here names a
        document, a filename or a person.
        """

        depth = {}

        with SessionLocal() as session:

            rows = session.execute(
                select(
                    DocumentJobModel.status,
                    func.count(),
                ).group_by(
                    DocumentJobModel.status
                )
            ).all()

        for status, count in rows:
            depth[status] = count

        for status in (
            QUEUED,
            PROCESSING,
            RETRY_WAIT,
        ):
            depth.setdefault(
                status,
                0,
            )

        depth["ACTIVE_TOTAL"] = sum(
            depth.get(
                status,
                0,
            )
            for status in ACTIVE_STATUSES
        )

        return depth


    def workers(
        self,
    ) -> list[dict]:

        now = datetime.now(
            timezone.utc
        )

        cutoff = now - timedelta(
            seconds=self.stale_seconds,
        )

        with SessionLocal() as session:

            rows = session.execute(
                select(
                    WorkerHeartbeatModel
                ).order_by(
                    WorkerHeartbeatModel
                    .last_seen_at
                    .desc()
                )
            ).scalars().all()

            observed = []

            for row in rows:

                last_seen = row.last_seen_at

                # A naive timestamp cannot be compared with an
                # aware one. Postgres returns aware for
                # timestamptz, but a row written by an older
                # path might not be.
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(
                        tzinfo=timezone.utc,
                    )

                observed.append(
                    {
                        "worker_id":
                            row.worker_id,

                        "status":
                            row.status,

                        "last_seen_at":
                            last_seen.isoformat(),

                        "seconds_since_last_seen":
                            round(
                                (
                                    now - last_seen
                                ).total_seconds(),
                                1,
                            ),

                        "stale":
                            last_seen < cutoff,

                        "current_job_id":
                            row.current_job_id,

                        "jobs_completed":
                            row.jobs_completed,

                        "jobs_failed":
                            row.jobs_failed,

                        "concurrency":
                            row.concurrency,
                    }
                )

        return observed


    def evaluate(
        self,
    ) -> dict:

        """
        The operational answer.

        NOT called by /health/ready, on purpose. Readiness
        answers "should this API process receive traffic", and
        the API can serve uploads, reads and reviews perfectly
        with no worker running -- the uploads simply queue.
        Failing readiness would take the API out of the load
        balancer and make a worker problem into an API outage.

        So this is reported separately, and monitoring alerts
        on it.
        """

        observed = self.workers()

        depth = self.queue_depth()

        live = [
            worker
            for worker in observed
            if not worker["stale"]
            and worker["status"] != STATUS_STOPPED
        ]

        draining = [
            worker
            for worker in live
            if worker["status"] == STATUS_DRAINING
        ]

        running = [
            worker
            for worker in live
            if worker["status"] == STATUS_RUNNING
        ]

        if running:
            state = HEALTHY

        elif draining:
            state = DRAINING

        elif observed:
            # Something checked in once and has not lately.
            # A worker that died, as distinct from one that
            # was never started.
            state = STALE

        else:
            state = NO_WORKER

        return {
            "state": state,

            "worker_count": len(
                observed
            ),

            "running_count": len(
                running
            ),

            "draining_count": len(
                draining
            ),

            "stale_count": len(
                [
                    worker
                    for worker in observed
                    if worker["stale"]
                ]
            ),

            "stale_after_seconds":
                self.stale_seconds,

            "queue": depth,

            # The signal that fills the gap left by a wide
            # staleness threshold: work waiting with nothing
            # healthy to do it is actionable immediately,
            # without waiting seven minutes for a heartbeat to
            # age out.
            "queue_waiting_with_no_worker": (
                state
                in (
                    STALE,
                    NO_WORKER,
                )
                and depth["ACTIVE_TOTAL"] > 0
            ),

            "workers": observed,
        }
