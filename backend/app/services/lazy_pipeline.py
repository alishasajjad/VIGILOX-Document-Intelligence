import os
import threading


# ==========================================================
# LAZY PIPELINE HOLDER
# PHASE 9.5
# ==========================================================
#
# WHY THIS EXISTS
# ----------------------------------------------------------
#
# DocumentPipelineService constructs PaddleOCR. The Phase 9.5
# measurement put that at 1.7 seconds of process startup and a
# few hundred megabytes resident.
#
# The worker needs it: OCR is 100% of its work. The API does
# not. In the async architecture the API accepts uploads and
# answers questions, and the only route in that process which
# touches a pipeline is the synchronous
#
#     POST /api/v1/documents/analyze
#
# kept for compatibility. A deployment that has migrated to
# the job API may never call it, and would still be paying for
# the model in every API replica.
#
# So the API holds this instead of the service itself, and the
# model is built on first use.
#
#
# WHY THE DEFAULT IS STILL EAGER
# ----------------------------------------------------------
#
# Deferring has a visible consequence: the first analyze call
# pays the load, and readiness stops meaning "OCR is loaded".
# Both are fine, and both are decisions somebody should make
# on purpose rather than inherit from a refactor.
#
# VIGILOX_API_EAGER_PIPELINE therefore defaults to true, which
# is exactly what this process did before, and the measured
# saving is available by setting it to false.
#
#
# WHY IT IS NOT JUST functools.lru_cache
# ----------------------------------------------------------
#
# Two requests can arrive at an unbuilt pipeline at the same
# moment. Without a lock both would construct one, which means
# two PaddleOCR instances, twice the memory, and a race over
# which one ends up stored. A cached function decorated onto a
# method would have the same problem: lru_cache is not a lock.
# ==========================================================


def eager_pipeline_enabled() -> bool:

    """
    Whether the API should build the pipeline at startup.

    Defaults to true. Anything other than an explicit
    false-ish value is treated as true, so a typo in the
    environment cannot silently defer the model load and turn
    the first analyze request into a twenty second one.
    """

    raw = os.getenv(
        "VIGILOX_API_EAGER_PIPELINE",
        "",
    ).strip().lower()


    if raw in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False


    return True


class LazyPipeline:

    """
    Holds a DocumentPipelineService, building it on first use.

    Exposes get() rather than pretending to be the service.
    A proxy that forwarded attribute access would make the
    call site read as though the model were already there,
    which is the one thing a reader needs to know it is not.
    """

    def __init__(
        self,
        factory=None,
    ) -> None:

        self._factory = factory

        self._service = None

        # Two simultaneous first requests must not build two
        # models.
        self._lock = (
            threading.Lock()
        )


    def get(
        self,
    ):

        if self._service is not None:
            return self._service


        with self._lock:

            # Checked again inside the lock: another thread
            # may have built it while this one was waiting.
            if self._service is not None:
                return self._service


            if self._factory is not None:
                self._service = (
                    self._factory()
                )

            else:
                from backend.app.services.pipeline_service import (
                    DocumentPipelineService,
                )

                self._service = (
                    DocumentPipelineService()
                )


        return self._service


    @staticmethod
    def resolve(
        value,
    ):

        """
        Return a usable pipeline from whatever is on
        app.state.pipeline.

        A holder is asked to build; anything else is assumed
        to already be a pipeline and is handed back.

        The second case is not a hack, it is the point. Ten
        test suites assign a fake pipeline straight onto
        app.state to control what analyze does, and none of
        them care that the API defers a model load. Making
        every one of them wrap its fake in a holder would
        couple them to an internal detail of a process they
        are not testing, and the coupling would have to be
        maintained forever.

        So the resolver accepts both, and the compatibility is
        asserted rather than assumed.
        """

        if hasattr(
            value,
            "get",
        ) and not hasattr(
            value,
            "process",
        ):
            return value.get()


        return value


    @property
    def is_loaded(
        self,
    ) -> bool:

        """
        Whether the model has actually been built.

        Read by the readiness check, which reports it rather
        than requiring it -- an API that has not yet needed a
        pipeline is ready to do everything it is for.
        """

        return self._service is not None
