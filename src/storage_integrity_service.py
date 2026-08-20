from pathlib import Path

from sqlalchemy import (
    select,
)

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    DocumentModel,
)

from src.document_storage_service import (
    DocumentStorageSecurityError,
    DocumentStorageService,
)


# ==========================================================
# STORAGE INTEGRITY SERVICE
# PHASE 7C.6d
# ==========================================================

class StorageIntegrityService:

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
    # LOAD DATABASE DOCUMENTS
    # ======================================================

    def _load_database_documents(
        self,
    ) -> dict[str, dict]:

        with SessionLocal() as session:

            statement = (
                select(
                    DocumentModel
                )
            )


            documents = (
                session
                .scalars(
                    statement
                )
                .all()
            )


            return {
                document.id: {
                    "document_id":
                        document.id,

                    "content_type":
                        document.content_type,

                    "original_filename":
                        document.original_filename,

                    "document_type":
                        document.document_type,

                    "processing_status":
                        document.processing_status,
                }

                for document
                in documents
            }


    # ======================================================
    # INSPECT DATABASE-BACKED DOCUMENT
    # ======================================================

    def _inspect_database_document(
        self,
        document: dict,
    ) -> dict:

        document_id = (
            document[
                "document_id"
            ]
        )


        content_type = (
            document[
                "content_type"
            ]
        )


        try:

            document_directory = (
                self.storage_service
                .get_document_directory(
                    document_id
                )
            )


            original_path = (
                self.storage_service
                .load_original(
                    document_id=(
                        document_id
                    ),

                    content_type=(
                        content_type
                    ),
                )
            )


        except (
            DocumentStorageSecurityError,
            ValueError,
        ) as exc:

            return {
                **document,

                "status":
                    "INVALID_STORAGE",

                "storage_exists":
                    False,

                "original_exists":
                    False,

                "storage_path":
                    None,

                "original_path":
                    None,

                "error":
                    str(
                        exc
                    ),
            }


        storage_exists = (
            document_directory.exists()
            and document_directory.is_dir()
            and not document_directory.is_symlink()
        )


        original_exists = (
            original_path is not None
        )


        if (
            storage_exists
            and original_exists
        ):

            status = (
                "HEALTHY"
            )


        else:

            status = (
                "MISSING_STORAGE"
            )


        return {
            **document,

            "status":
                status,

            "storage_exists":
                storage_exists,

            "original_exists":
                original_exists,

            "storage_path":
                str(
                    document_directory
                ),

            "original_path":
                (
                    str(
                        original_path
                    )
                    if original_path is not None
                    else None
                ),

            "error":
                None,
        }


    # ======================================================
    # SCAN FILESYSTEM ROOT
    # ======================================================

    def _scan_storage_root(
        self,
        database_ids: set[str],
    ) -> tuple[
        list[dict],
        list[dict],
    ]:

        orphan_storage = []

        unmanaged_entries = []


        storage_root = (
            self.storage_service
            .storage_root
        )


        for entry in (
            storage_root.iterdir()
        ):

            # ==============================================
            # SYMBOLIC LINK
            # ==============================================

            if entry.is_symlink():

                unmanaged_entries.append(
                    {
                        "name":
                            entry.name,

                        "path":
                            str(
                                entry
                            ),

                        "entry_type":
                            "SYMLINK",

                        "reason":
                            (
                                "Symbolic links are not "
                                "valid managed document "
                                "storage entries."
                            ),
                    }
                )


                continue


            # ==============================================
            # NON-DIRECTORY ROOT ENTRY
            # ==============================================

            if not entry.is_dir():

                unmanaged_entries.append(
                    {
                        "name":
                            entry.name,

                        "path":
                            str(
                                entry
                            ),

                        "entry_type":
                            "FILE",

                        "reason":
                            (
                                "Files directly under the "
                                "storage root are unmanaged."
                            ),
                    }
                )


                continue


            # ==============================================
            # VALIDATE DIRECTORY NAME AS DOCUMENT ID
            # ==============================================

            try:

                document_id = (
                    self.storage_service
                    .validate_document_id(
                        entry.name
                    )
                )


            except DocumentStorageSecurityError as exc:

                unmanaged_entries.append(
                    {
                        "name":
                            entry.name,

                        "path":
                            str(
                                entry
                            ),

                        "entry_type":
                            "DIRECTORY",

                        "reason":
                            str(
                                exc
                            ),
                    }
                )


                continue


            # ==============================================
            # KNOWN DATABASE DOCUMENT
            # ==============================================

            if (
                document_id
                in database_ids
            ):

                continue


            # ==============================================
            # ORPHAN STORAGE
            # ==============================================
            #
            # Valid managed document directory exists on
            # disk, but PostgreSQL has no matching document.
            #
            # Detection only.
            #
            # DO NOT DELETE HERE.
            # ==============================================

            orphan_storage.append(
                {
                    "document_id":
                        document_id,

                    "status":
                        "ORPHAN_STORAGE",

                    "storage_path":
                        str(
                            entry.resolve()
                        ),

                    "entry_count":
                        sum(
                            1
                            for _
                            in entry.iterdir()
                        ),
                }
            )


        return (
            orphan_storage,
            unmanaged_entries,
        )


    # ======================================================
    # RUN INTEGRITY SCAN
    # ======================================================

    def scan(
        self,
    ) -> dict:

        # ==================================================
        # DATABASE SNAPSHOT
        # ==================================================

        database_documents = (
            self._load_database_documents()
        )


        database_ids = set(
            database_documents.keys()
        )


        # ==================================================
        # DATABASE → STORAGE CHECK
        # ==================================================

        document_results = [
            self._inspect_database_document(
                document
            )

            for document
            in database_documents.values()
        ]


        healthy_documents = [
            item
            for item
            in document_results
            if (
                item[
                    "status"
                ]
                == "HEALTHY"
            )
        ]


        missing_storage = [
            item
            for item
            in document_results
            if (
                item[
                    "status"
                ]
                == "MISSING_STORAGE"
            )
        ]


        invalid_storage = [
            item
            for item
            in document_results
            if (
                item[
                    "status"
                ]
                == "INVALID_STORAGE"
            )
        ]


        # ==================================================
        # STORAGE → DATABASE CHECK
        # ==================================================

        (
            orphan_storage,
            unmanaged_entries,
        ) = (
            self._scan_storage_root(
                database_ids
            )
        )


        # ==================================================
        # SUMMARY
        # ==================================================

        issue_count = (
            len(
                missing_storage
            )
            + len(
                invalid_storage
            )
            + len(
                orphan_storage
            )
            + len(
                unmanaged_entries
            )
        )


        return {
            "status":
                (
                    "HEALTHY"
                    if issue_count == 0
                    else "ISSUES_FOUND"
                ),

            "summary": {
                "database_documents":
                    len(
                        database_documents
                    ),

                "healthy_documents":
                    len(
                        healthy_documents
                    ),

                "missing_storage":
                    len(
                        missing_storage
                    ),

                "invalid_storage":
                    len(
                        invalid_storage
                    ),

                "orphan_storage":
                    len(
                        orphan_storage
                    ),

                "unmanaged_entries":
                    len(
                        unmanaged_entries
                    ),

                "issue_count":
                    issue_count,
            },

            "healthy_documents":
                healthy_documents,

            "missing_storage":
                missing_storage,

            "invalid_storage":
                invalid_storage,

            "orphan_storage":
                orphan_storage,

            "unmanaged_entries":
                unmanaged_entries,
        }