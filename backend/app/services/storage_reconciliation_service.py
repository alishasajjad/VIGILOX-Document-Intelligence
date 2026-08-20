from sqlalchemy import (
    select,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from backend.app.services.document_storage_service import (
    DocumentStorageSecurityError,
    DocumentStorageService,
)

from backend.app.services.storage_integrity_service import (
    StorageIntegrityService,
)


# ==========================================================
# STORAGE RECONCILIATION SERVICE
# PHASE 7C.6e
# ==========================================================

class StorageReconciliationService:

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        *,
        storage_service: (
            DocumentStorageService
            | None
        ) = None,
        integrity_service: (
            StorageIntegrityService
            | None
        ) = None,
    ):

        self.storage_service = (
            storage_service
            or DocumentStorageService()
        )


        self.integrity_service = (
            integrity_service
            or StorageIntegrityService(
                storage_service=(
                    self.storage_service
                )
            )
        )


    # ======================================================
    # DATABASE DOCUMENT EXISTS
    # ======================================================

    def _database_document_exists(
        self,
        document_id: str,
    ) -> bool:

        with SessionLocal() as session:

            statement = (
                select(
                    DocumentModel.id
                )
                .where(
                    DocumentModel.id
                    == document_id
                )
            )


            return (
                session.scalar(
                    statement
                )
                is not None
            )


    # ======================================================
    # RECONCILE ORPHAN STORAGE
    # ======================================================

    def reconcile_orphans(
        self,
        *,
        dry_run: bool = True,
    ) -> dict:

        # ==================================================
        # 1. RUN FRESH READ-ONLY INTEGRITY SCAN
        # ==================================================

        integrity_report = (
            self.integrity_service.scan()
        )


        orphan_candidates = (
            integrity_report.get(
                "orphan_storage",
                [],
            )
        )


        results = []


        # ==================================================
        # 2. PROCESS ONLY ORPHAN STORAGE
        # ==================================================

        for orphan in orphan_candidates:

            document_id = (
                orphan.get(
                    "document_id"
                )
            )


            # ==============================================
            # INVALID CANDIDATE
            # ==============================================

            if not document_id:

                results.append(
                    {
                        "document_id":
                            None,

                        "status":
                            "SKIPPED_INVALID",

                        "deleted":
                            False,

                        "reason":
                            (
                                "Orphan candidate "
                                "has no document_id."
                            ),
                    }
                )


                continue


            # ==============================================
            # SECURITY VALIDATION
            # ==============================================

            try:

                safe_document_id = (
                    self.storage_service
                    .validate_document_id(
                        document_id
                    )
                )


            except DocumentStorageSecurityError as exc:

                results.append(
                    {
                        "document_id":
                            document_id,

                        "status":
                            "SKIPPED_INVALID",

                        "deleted":
                            False,

                        "reason":
                            str(
                                exc
                            ),
                    }
                )


                continue


            # ==============================================
            # TOCTOU DATABASE RE-CHECK
            # ==============================================
            #
            # Integrity scan is a snapshot.
            #
            # Between:
            #
            #   scan()
            #
            # and:
            #
            #   delete_document()
            #
            # a database document could theoretically
            # appear.
            #
            # Therefore re-check PostgreSQL immediately
            # before any filesystem deletion.
            # ==============================================

            if self._database_document_exists(
                safe_document_id
            ):

                results.append(
                    {
                        "document_id":
                            safe_document_id,

                        "status":
                            "SKIPPED_DB_PRESENT",

                        "deleted":
                            False,

                        "reason":
                            (
                                "Database document now "
                                "exists. Storage was "
                                "not deleted."
                            ),
                    }
                )


                continue


            # ==============================================
            # DRY RUN
            # ==============================================

            if dry_run:

                results.append(
                    {
                        "document_id":
                            safe_document_id,

                        "status":
                            "WOULD_DELETE",

                        "deleted":
                            False,

                        "storage_path":
                            orphan.get(
                                "storage_path"
                            ),
                    }
                )


                continue


            # ==============================================
            # REAL CLEANUP
            # ==============================================

            try:

                deleted = (
                    self.storage_service
                    .delete_document(
                        safe_document_id
                    )
                )


            except Exception as exc:

                results.append(
                    {
                        "document_id":
                            safe_document_id,

                        "status":
                            "FAILED",

                        "deleted":
                            False,

                        "reason":
                            str(
                                exc
                            ),
                    }
                )


                continue


            if deleted:

                results.append(
                    {
                        "document_id":
                            safe_document_id,

                        "status":
                            "DELETED",

                        "deleted":
                            True,
                    }
                )


            else:

                results.append(
                    {
                        "document_id":
                            safe_document_id,

                        "status":
                            "ALREADY_MISSING",

                        "deleted":
                            False,
                    }
                )


        # ==================================================
        # 3. SUMMARY
        # ==================================================

        deleted_count = sum(
            1
            for item
            in results
            if (
                item[
                    "status"
                ]
                == "DELETED"
            )
        )


        would_delete_count = sum(
            1
            for item
            in results
            if (
                item[
                    "status"
                ]
                == "WOULD_DELETE"
            )
        )


        skipped_count = sum(
            1
            for item
            in results
            if (
                item[
                    "status"
                ].startswith(
                    "SKIPPED_"
                )
            )
        )


        failed_count = sum(
            1
            for item
            in results
            if (
                item[
                    "status"
                ]
                == "FAILED"
            )
        )


        return {
            "mode":
                (
                    "DRY_RUN"
                    if dry_run
                    else "EXECUTE"
                ),

            "candidate_count":
                len(
                    orphan_candidates
                ),

            "deleted_count":
                deleted_count,

            "would_delete_count":
                would_delete_count,

            "skipped_count":
                skipped_count,

            "failed_count":
                failed_count,

            "results":
                results,

            # ----------------------------------------------
            # Explicitly expose categories that are NEVER
            # modified by this service.
            # ----------------------------------------------

            "protected": {
                "missing_storage":
                    len(
                        integrity_report.get(
                            "missing_storage",
                            [],
                        )
                    ),

                "unmanaged_entries":
                    len(
                        integrity_report.get(
                            "unmanaged_entries",
                            [],
                        )
                    ),

                "healthy_documents":
                    len(
                        integrity_report.get(
                            "healthy_documents",
                            [],
                        )
                    ),
            },
        }