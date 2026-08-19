import os
import shutil
import tempfile

from pathlib import Path


# ==========================================================
# DOCUMENT STORAGE SERVICE
# PHASE 7B
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
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        storage_root: str | Path | None = None,
    ):

        # Environment variable can override the default.
        #
        # Example:
        #
        # DOCUMENT_STORAGE_DIR=C:\vigilox\data\documents
        #
        # If it is not configured, local development uses:
        #
        # storage/documents/

        configured_root = (
            storage_root
            or os.getenv(
                "DOCUMENT_STORAGE_DIR"
            )
            or (
                Path("storage")
                / "documents"
            )
        )


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
                f"content type: "
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

        if not document_id:

            raise ValueError(
                "document_id is required."
            )


        return (
            self.storage_root
            / document_id
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


        return (
            self.get_document_directory(
                document_id
            )
            / f"original{suffix}"
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
        # Build destination
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


        temp_path = None


        try:

            # ==============================================
            # ATOMIC FILE WRITE
            # ==============================================
            #
            # Copy into a temporary file inside the same
            # directory, then atomically replace the final
            # destination.
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


            os.replace(
                temp_path,
                destination,
            )


            return destination


        except Exception:

            # Remove incomplete temporary file.

            if (
                temp_path is not None
                and temp_path.exists()
            ):

                temp_path.unlink()


            # Remove empty document directory created
            # by this failed operation.

            if (
                document_directory.exists()
                and not any(
                    document_directory.iterdir()
                )
            ):

                document_directory.rmdir()


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


        if (
            not path.exists()
            or not path.is_file()
        ):

            return None


        return path


    # ======================================================
    # DELETE DOCUMENT STORAGE
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


        if not document_directory.exists():

            return False


        shutil.rmtree(
            document_directory
        )


        return True