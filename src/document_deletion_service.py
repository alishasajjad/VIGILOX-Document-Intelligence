from src.db.database import (
    SessionLocal,
)

from src.db.repositories import (
    DocumentRepository,
)

from src.document_storage_service import (
    DocumentStorageService,
)


# ==========================================================
# DOCUMENT STORAGE CLEANUP ERROR
# PHASE 7C.6
# ==========================================================

class DocumentStorageCleanupError(
    RuntimeError
):
    """
    Raised when the PostgreSQL document deletion has
    committed successfully but physical document storage
    could not be removed.

    Important lifecycle state:

        database_deleted = True
        filesystem cleanup = failed

    This leaves a recoverable orphan file instead of a
    database record pointing to a missing source document.
    """

    def __init__(
        self,
        *,
        document_id: str,
        original_error: Exception,
    ):

        self.document_id = (
            document_id
        )


        self.original_error = (
            original_error
        )


        self.database_deleted = (
            True
        )


        self.storage_cleanup_completed = (
            False
        )


        super().__init__(
            (
                "Document database deletion "
                "completed, but filesystem "
                "cleanup failed for document "
                f"{document_id}: "
                f"{original_error}"
            )
        )


# ==========================================================
# DOCUMENT DELETION SERVICE
# PHASE 7C.6
# ==========================================================

class DocumentDeletionService:

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        storage_service: (
            DocumentStorageService
            | None
        ) = None,
    ):

        self.storage_service = (
            storage_service
            or DocumentStorageService()
        )


    # ======================================================
    # DELETE DOCUMENT
    # ======================================================

    def delete_document(
        self,
        document_id: str,
    ) -> dict:

        # ==================================================
        # 1. SECURITY VALIDATION
        # ==================================================
        #
        # Validate before touching PostgreSQL or filesystem.
        #
        # Invalid identifiers such as:
        #
        #   ../outside
        #   C:\Windows
        #   folder/document
        #
        # fail immediately.
        # ==================================================

        safe_document_id = (
            self.storage_service
            .validate_document_id(
                document_id
            )
        )


        # ==================================================
        # 2. DATABASE TRANSACTION
        # ==================================================
        #
        # PostgreSQL is the authoritative lifecycle record.
        #
        # Delete database first.
        #
        # Why?
        #
        # If DB deletion fails:
        #     filesystem remains untouched.
        #
        # If filesystem deletion later fails:
        #     only an orphan file remains.
        #
        # An orphan is recoverable by the later storage
        # reconciliation phase.
        #
        # The dangerous opposite state:
        #
        #     DB row exists
        #     source file missing
        #
        # is intentionally avoided.
        # ==================================================

        with SessionLocal.begin() as session:

            document_repository = (
                DocumentRepository(
                    session
                )
            )


            document = (
                document_repository
                .get_document(
                    safe_document_id
                )
            )


            # ==============================================
            # DOCUMENT DOES NOT EXIST
            # ==============================================
            #
            # Do NOT automatically delete filesystem data.
            #
            # A directory without a DB document is an orphan
            # and will be handled by the dedicated orphan /
            # reconciliation phase.
            # ==============================================

            if document is None:

                return {
                    "document_id":
                        safe_document_id,

                    "status":
                        "NOT_FOUND",

                    "deleted":
                        False,

                    "database_deleted":
                        False,

                    "storage_deleted":
                        False,

                    "storage_status":
                        "NOT_CHECKED",
                }


            # ==============================================
            # MATERIALIZE METADATA BEFORE SESSION CLOSE
            # ==============================================

            original_filename = (
                document.original_filename
            )


            content_type = (
                document.content_type
            )


            document_type = (
                document.document_type
            )


            # ==============================================
            # DELETE AUTHORITATIVE DB RECORD
            # ==============================================

            document_repository.delete_document(
                document
            )


            # SessionLocal.begin() commits when leaving
            # this block.
            #
            # PostgreSQL ON DELETE CASCADE removes:
            #
            #   document_analyses
            #   human_reviews
            #   audit_events


        # ==================================================
        # 3. FILESYSTEM CLEANUP
        # ==================================================
        #
        # Reached only after successful PostgreSQL commit.
        # ==================================================

        try:

            storage_deleted = (
                self.storage_service
                .delete_document(
                    safe_document_id
                )
            )


        except Exception as exc:

            # ==============================================
            # IMPORTANT
            # ==============================================
            #
            # Never silently swallow filesystem cleanup
            # failures.
            #
            # Database deletion has already committed.
            #
            # The remaining filesystem directory is now an
            # orphan and can later be detected / reconciled.
            # ==============================================

            raise DocumentStorageCleanupError(
                document_id=(
                    safe_document_id
                ),

                original_error=(
                    exc
                ),
            ) from exc


        # ==================================================
        # 4. STRUCTURED RESULT
        # ==================================================

        storage_status = (
            "DELETED"
            if storage_deleted
            else "MISSING"
        )


        return {
            "document_id":
                safe_document_id,

            "status":
                "DELETED",

            "deleted":
                True,

            "database_deleted":
                True,

            "storage_deleted":
                storage_deleted,

            "storage_status":
                storage_status,

            "original_filename":
                original_filename,

            "content_type":
                content_type,

            "document_type":
                document_type,
        }