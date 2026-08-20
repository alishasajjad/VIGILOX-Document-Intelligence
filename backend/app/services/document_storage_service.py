import os
import re
import shutil
import tempfile

from pathlib import Path

from backend.app.core.paths import (
    DEFAULT_STORAGE_ROOT,
)


# ==========================================================
# DOCUMENT STORAGE SECURITY ERROR
# PHASE 7C.6
# ==========================================================

class DocumentStorageSecurityError(
    ValueError
):
    """
    Raised when a storage path or document identifier
    violates the managed storage boundary.
    """

    pass


# ==========================================================
# DOCUMENT STORAGE SERVICE
# PHASE 7B + PHASE 7C.6
# ==========================================================

class DocumentStorageService:

    # ======================================================
    # CONTENT TYPE → FILE EXTENSION
    # ======================================================

    CONTENT_TYPE_SUFFIXES = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }


    # ======================================================
    # SAFE DOCUMENT ID
    # ======================================================
    #
    # PostgreSQL-generated document IDs currently use
    # UUID-compatible characters.
    #
    # We intentionally allow only:
    #
    #   A-Z
    #   a-z
    #   0-9
    #   -
    #   _
    #
    # This prevents:
    #
    #   ../
    #   ..\
    #   /
    #   \
    #   drive paths
    #   absolute paths
    #   path separators
    #
    # Maximum length is also bounded.
    # ======================================================

    DOCUMENT_ID_PATTERN = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )


    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        storage_root: str | Path | None = None,
    ):

        configured_root = (
            storage_root
            or os.getenv(
                "DOCUMENT_STORAGE_DIR"
            )
            or DEFAULT_STORAGE_ROOT
        )


        # Resolve storage root once.
        #
        # All managed paths must remain underneath this
        # canonical directory.

        self.storage_root = (
            Path(
                configured_root
            )
            .expanduser()
            .resolve()
        )


        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )


        # Root itself must be a directory.

        if not self.storage_root.is_dir():

            raise ValueError(
                "Document storage root "
                "is not a directory: "
                f"{self.storage_root}"
            )


    # ======================================================
    # VALIDATE DOCUMENT ID
    # ======================================================

    def validate_document_id(
        self,
        document_id: str,
    ) -> str:

        if not isinstance(
            document_id,
            str,
        ):

            raise DocumentStorageSecurityError(
                "document_id must be a string."
            )


        if not document_id:

            raise DocumentStorageSecurityError(
                "document_id is required."
            )


        # Do not silently normalize whitespace.
        #
        # A caller passing:
        #
        #   " abc "
        #
        # should not unexpectedly access:
        #
        #   "abc"
        #
        # Reject it instead.

        if (
            document_id
            != document_id.strip()
        ):

            raise DocumentStorageSecurityError(
                "document_id contains "
                "leading or trailing whitespace."
            )


        if not self.DOCUMENT_ID_PATTERN.fullmatch(
            document_id
        ):

            raise DocumentStorageSecurityError(
                "Unsafe document_id. "
                "Only letters, numbers, "
                "hyphens and underscores "
                "are allowed."
            )


        return document_id


    # ======================================================
    # ASSERT DOCUMENT DIRECTORY IS SAFE
    # ======================================================

    def _resolve_safe_document_directory(
        self,
        document_id: str,
    ) -> Path:

        safe_document_id = (
            self.validate_document_id(
                document_id
            )
        )


        candidate = (
            self.storage_root
            / safe_document_id
        )


        # --------------------------------------------------
        # SYMLINK PROTECTION
        # --------------------------------------------------
        #
        # Example:
        #
        # storage/documents/abc
        #
        # must never be a symbolic link pointing to:
        #
        # C:\Users\...
        #
        # Otherwise recursive deletion could escape our
        # managed storage boundary.
        # --------------------------------------------------

        if candidate.is_symlink():

            raise DocumentStorageSecurityError(
                "Document storage directory "
                "must not be a symbolic link."
            )


        resolved = (
            candidate.resolve(
                strict=False
            )
        )


        # Every document directory must be a DIRECT child
        # of storage_root.
        #
        # This is deliberately stricter than simply checking
        # whether the path is somewhere underneath the root.

        if (
            resolved.parent
            != self.storage_root
        ):

            raise DocumentStorageSecurityError(
                "Resolved document directory "
                "is outside the managed "
                "storage root."
            )


        if (
            resolved
            == self.storage_root
        ):

            raise DocumentStorageSecurityError(
                "Document directory cannot "
                "be the storage root itself."
            )


        return resolved


    # ======================================================
    # ASSERT FILE PATH IS SAFE
    # ======================================================

    def _resolve_safe_file_path(
        self,
        *,
        document_directory: Path,
        filename: str,
    ) -> Path:

        candidate = (
            document_directory
            / filename
        )


        # Existing managed files must never be symlinks.
        #
        # This protects load_original() from serving files
        # located outside managed storage.

        if candidate.is_symlink():

            raise DocumentStorageSecurityError(
                "Managed document file "
                "must not be a symbolic link."
            )


        resolved = (
            candidate.resolve(
                strict=False
            )
        )


        if (
            resolved.parent
            != document_directory
        ):

            raise DocumentStorageSecurityError(
                "Resolved document file "
                "is outside its managed "
                "document directory."
            )


        return resolved


    # ======================================================
    # GET FILE SUFFIX
    # ======================================================

    def get_suffix(
        self,
        content_type: str,
    ) -> str:

        suffix = (
            self.CONTENT_TYPE_SUFFIXES
            .get(
                content_type
            )
        )


        if suffix is None:

            raise ValueError(
                "Unsupported document "
                "content type: "
                f"{content_type}"
            )


        return suffix


    # ======================================================
    # GET DOCUMENT DIRECTORY
    # ======================================================

    def get_document_directory(
        self,
        document_id: str,
    ) -> Path:

        return (
            self
            ._resolve_safe_document_directory(
                document_id
            )
        )


    # ======================================================
    # GET ORIGINAL DOCUMENT PATH
    # ======================================================

    def get_original_path(
        self,
        *,
        document_id: str,
        content_type: str,
    ) -> Path:

        suffix = (
            self.get_suffix(
                content_type
            )
        )


        document_directory = (
            self.get_document_directory(
                document_id
            )
        )


        return (
            self._resolve_safe_file_path(
                document_directory=(
                    document_directory
                ),

                filename=(
                    f"original{suffix}"
                ),
            )
        )


    # ======================================================
    # SAVE ORIGINAL DOCUMENT
    # ======================================================

    def save_original(
        self,
        *,
        document_id: str,
        source_path: str | Path,
        content_type: str,
    ) -> Path:

        # --------------------------------------------------
        # Resolve source file
        # --------------------------------------------------
        #
        # Source files are allowed to exist outside the
        # document storage directory because they normally
        # come from FastAPI temporary upload processing.
        # --------------------------------------------------

        source = (
            Path(
                source_path
            )
            .expanduser()
            .resolve()
        )


        # --------------------------------------------------
        # Validate source file
        # --------------------------------------------------

        if not source.exists():

            raise FileNotFoundError(
                "Source document does "
                "not exist: "
                f"{source}"
            )


        if not source.is_file():

            raise ValueError(
                "Source document path "
                "is not a file."
            )


        # --------------------------------------------------
        # Build safe destination directory
        # --------------------------------------------------

        document_directory = (
            self.get_document_directory(
                document_id
            )
        )


        document_directory.mkdir(
            parents=True,
            exist_ok=True,
        )


        # Re-check after directory creation.
        #
        # This ensures the managed directory remains
        # a normal directory and not a symlink.

        if document_directory.is_symlink():

            raise DocumentStorageSecurityError(
                "Document storage directory "
                "must not be a symbolic link."
            )


        if not document_directory.is_dir():

            raise ValueError(
                "Document storage path "
                "is not a directory."
            )


        destination = (
            self.get_original_path(
                document_id=(
                    document_id
                ),

                content_type=(
                    content_type
                ),
            )
        )


        temp_path: Path | None = None


        try:

            # ==============================================
            # ATOMIC FILE WRITE
            # ==============================================
            #
            # 1. Write to temporary file.
            # 2. Flush Python buffer.
            # 3. fsync OS file buffer.
            # 4. Atomically replace destination.
            #
            # Temporary file is created inside the same
            # directory, allowing os.replace() to remain
            # atomic on the same filesystem.
            # ==============================================

            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=document_directory,
                prefix=".upload_",
                suffix=".tmp",
            ) as temp_file:

                temp_path = Path(
                    temp_file.name
                )


                with source.open(
                    "rb"
                ) as source_file:

                    shutil.copyfileobj(
                        source_file,
                        temp_file,
                    )


                temp_file.flush()


                os.fsync(
                    temp_file.fileno()
                )


            # --------------------------------------------------
            # Temporary file must remain inside document dir.
            # --------------------------------------------------

            resolved_temp_path = (
                temp_path.resolve(
                    strict=True
                )
            )


            if (
                resolved_temp_path.parent
                != document_directory
            ):

                raise DocumentStorageSecurityError(
                    "Temporary document file "
                    "escaped its managed "
                    "document directory."
                )


            # --------------------------------------------------
            # Atomic finalization
            # --------------------------------------------------

            os.replace(
                resolved_temp_path,
                destination,
            )


            temp_path = None


            # --------------------------------------------------
            # Final storage verification
            # --------------------------------------------------

            if (
                not destination.exists()
                or not destination.is_file()
            ):

                raise IOError(
                    "Stored original document "
                    "could not be verified."
                )


            if destination.is_symlink():

                raise DocumentStorageSecurityError(
                    "Stored original document "
                    "must not be a symbolic link."
                )


            return destination


        except Exception:

            # ==============================================
            # REMOVE INCOMPLETE TEMP FILE
            # ==============================================

            if (
                temp_path is not None
                and temp_path.exists()
            ):

                try:

                    temp_path.unlink()

                except OSError:

                    # Preserve original failure.
                    pass


            # ==============================================
            # REMOVE EMPTY DOCUMENT DIRECTORY
            # ==============================================

            if (
                document_directory.exists()
                and document_directory.is_dir()
                and not document_directory.is_symlink()
            ):

                try:

                    if not any(
                        document_directory.iterdir()
                    ):

                        document_directory.rmdir()

                except OSError:

                    # Preserve original failure.
                    pass


            raise


    # ======================================================
    # DOCUMENT EXISTS
    # ======================================================

    def original_exists(
        self,
        *,
        document_id: str,
        content_type: str,
    ) -> bool:

        path = (
            self.get_original_path(
                document_id=(
                    document_id
                ),

                content_type=(
                    content_type
                ),
            )
        )


        if path.is_symlink():

            raise DocumentStorageSecurityError(
                "Managed original document "
                "must not be a symbolic link."
            )


        return (
            path.exists()
            and path.is_file()
        )


    # ======================================================
    # LOAD ORIGINAL PATH
    # ======================================================

    def load_original(
        self,
        *,
        document_id: str,
        content_type: str,
    ) -> Path | None:

        path = (
            self.get_original_path(
                document_id=(
                    document_id
                ),

                content_type=(
                    content_type
                ),
            )
        )


        if path.is_symlink():

            raise DocumentStorageSecurityError(
                "Managed original document "
                "must not be a symbolic link."
            )


        if (
            not path.exists()
            or not path.is_file()
        ):

            return None


        # Final containment check.

        resolved = (
            path.resolve(
                strict=True
            )
        )


        document_directory = (
            self.get_document_directory(
                document_id
            )
        )


        if (
            resolved.parent
            != document_directory
        ):

            raise DocumentStorageSecurityError(
                "Stored original resolved "
                "outside its managed "
                "document directory."
            )


        return resolved


    # ======================================================
    # DELETE DOCUMENT STORAGE
    # PHASE 7C.6
    # ======================================================

    def delete_document(
        self,
        document_id: str,
    ) -> bool:

        document_directory = (
            self.get_document_directory(
                document_id
            )
        )


        # --------------------------------------------------
        # Missing directory is safe/idempotent.
        # --------------------------------------------------

        if not document_directory.exists():

            return False


        # --------------------------------------------------
        # Never recurse through symlinks.
        # --------------------------------------------------

        if document_directory.is_symlink():

            raise DocumentStorageSecurityError(
                "Refusing to delete symbolic "
                "link document directory."
            )


        # --------------------------------------------------
        # Must be a directory.
        # --------------------------------------------------

        if not document_directory.is_dir():

            raise DocumentStorageSecurityError(
                "Refusing to recursively delete "
                "a non-directory storage path."
            )


        # --------------------------------------------------
        # Last containment check immediately before delete.
        # --------------------------------------------------

        resolved = (
            document_directory.resolve(
                strict=True
            )
        )


        if (
            resolved.parent
            != self.storage_root
        ):

            raise DocumentStorageSecurityError(
                "Refusing to delete directory "
                "outside managed storage root."
            )


        if (
            resolved
            == self.storage_root
        ):

            raise DocumentStorageSecurityError(
                "Refusing to delete storage "
                "root directory."
            )


        # --------------------------------------------------
        # SAFE RECURSIVE DELETE
        # --------------------------------------------------

        shutil.rmtree(
            resolved
        )


        return True