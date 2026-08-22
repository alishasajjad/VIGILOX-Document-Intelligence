import time

from typing import Any


# ==========================================================
# STAGE TIMING
# PHASE 9.1
# ==========================================================
#
# WHY THIS MODULE EXISTS
# ----------------------------------------------------------
#
# Phase 9 makes document processing asynchronous, and the
# whole point of that work is that the pipeline is slow. Which
# means the first thing to establish is where the time
# actually goes -- before anything is redesigned around a
# guess.
#
# "OCR is probably the slow part" is a hypothesis. A number is
# evidence, and the two are not interchangeable when the
# decision on the table is whether to add a queue, a worker
# process and a job table.
#
#
# WHY IT IS AN OUT-PARAMETER
# ----------------------------------------------------------
#
# DocumentPipelineService.process() returns a dict that is
# persisted more or less verbatim. Adding a "timings" key to
# it would put operational measurement inside the document
# intelligence record, where it would end up in the database,
# in API responses and in the raw JSON tab.
#
# Timing is not part of what was extracted from a document. So
# the caller passes a StageTimer in and reads it afterwards,
# and process() returns exactly what it returned before. The
# extraction contract does not move.
#
#
# WHAT IT DOES NOT DO
# ----------------------------------------------------------
#
# No PII. A StageTimer holds stage names and durations and has
# no route to document contents, extracted fields, filenames
# or OCR text. That is deliberate: these numbers are meant to
# be logged, and anything logged is assumed to be readable by
# whoever operates the system.
# ==========================================================


class StageTimer:

    """
    Records how long each named stage took, in milliseconds.

    Usage:

        timer = StageTimer()

        with timer.stage("ocr"):
            ...

        timer.durations()   ->  {"ocr": 812.4}
        timer.total_ms()    ->  812.4
    """

    def __init__(
        self,
    ) -> None:

        self._durations: dict[str, float] = {}

        self._order: list[str] = []

        # A wall-clock total, taken across the whole run rather
        # than summed from the stages. The two differ by
        # whatever happens between stages, and a gap between
        # them is itself worth seeing.
        self._started_at: float | None = None

        self._finished_at: float | None = None


    # ======================================================
    # STAGE CONTEXT
    # ======================================================

    def stage(
        self,
        name: str,
    ) -> "_StageContext":

        if not isinstance(
            name,
            str,
        ) or not name:

            raise ValueError(
                "A stage needs a name."
            )


        return _StageContext(
            timer=self,
            name=name,
        )


    def _record(
        self,
        name: str,
        elapsed_ms: float,
    ) -> None:

        # A repeated stage accumulates rather than overwrites.
        # A retry inside one run should read as time spent, not
        # as the last attempt only.
        if name in self._durations:
            self._durations[name] += elapsed_ms

        else:
            self._durations[name] = elapsed_ms
            self._order.append(name)


        now = (
            time.perf_counter()
        )

        if self._started_at is None:
            self._started_at = now - (elapsed_ms / 1000.0)

        self._finished_at = now


        # ==================================================
        # PHASE 11.11. THE SAME MEASUREMENT, AS A METRIC.
        # ==================================================
        #
        # Recorded here rather than at each of the eight call
        # sites in the pipeline, so a stage cannot be timed
        # and then forgotten in the metrics -- which is what
        # would happen the first time somebody adds a stage.
        #
        # record_stage IGNORES a name outside its allowed set,
        # which is deliberate: a stage name is a metric label,
        # and an unbounded label is one time series per
        # distinct value. Better a missing series than an
        # unbounded one.
        #
        # Imported inside the function on purpose.
        # backend/app/core/ is a cross-cutting layer that
        # nothing above it may depend on; a module-level
        # import of a service would invert that. The metrics
        # registry is a dict behind a lock, so the import cost
        # after the first call is a dictionary lookup.
        #
        # Failure is swallowed. A measurement must never be
        # able to fail the thing it measures.
        # ==================================================

        try:
            from backend.app.services.metrics_service import (
                record_stage,
            )

            record_stage(
                stage=name,
                seconds=elapsed_ms / 1000.0,
            )

        except Exception:
            pass


    # ======================================================
    # READING
    # ======================================================

    def durations(
        self,
    ) -> dict[str, float]:

        return {
            name: round(
                self._durations[name],
                1,
            )
            for name in self._order
        }


    def total_ms(
        self,
    ) -> float:

        return round(
            sum(
                self._durations.values()
            ),
            1,
        )


    def wall_ms(
        self,
    ) -> float:

        if (
            self._started_at is None
            or self._finished_at is None
        ):
            return 0.0


        return round(
            (
                self._finished_at
                - self._started_at
            )
            * 1000.0,
            1,
        )


    def slowest(
        self,
    ) -> tuple[str, float] | None:

        if not self._durations:
            return None


        name = max(
            self._durations,
            key=lambda key: self._durations[key],
        )

        return (
            name,
            round(
                self._durations[name],
                1,
            ),
        )


    def as_log_fields(
        self,
    ) -> dict[str, Any]:

        """
        A flat, log-safe view. Stage names become
        duration_<stage>_ms so a log aggregator can index them
        without parsing a nested object.
        """

        fields: dict[str, Any] = {
            "duration_ms":
                self.total_ms(),
        }


        for name in self._order:

            fields[
                f"duration_{name}_ms"
            ] = round(
                self._durations[name],
                1,
            )


        return fields


class _StageContext:

    __slots__ = (
        "_timer",
        "_name",
        "_started",
    )

    def __init__(
        self,
        timer: StageTimer,
        name: str,
    ) -> None:

        self._timer = timer

        self._name = name

        self._started = 0.0


    def __enter__(
        self,
    ) -> "_StageContext":

        self._started = (
            time.perf_counter()
        )

        return self


    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> bool:

        elapsed_ms = (
            (
                time.perf_counter()
                - self._started
            )
            * 1000.0
        )

        # Recorded even when the stage raised. A stage that
        # failed after eight seconds is exactly the thing worth
        # knowing about, and discarding the measurement on the
        # error path would hide it.
        self._timer._record(
            self._name,
            elapsed_ms,
        )

        return False
