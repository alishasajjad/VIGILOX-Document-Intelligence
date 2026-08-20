import tempfile

from pathlib import Path
from uuid import uuid4

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)


def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7B.1 — ORIGINAL DOCUMENT "
        "STORAGE TEST"
    )
    print("=" * 72)


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        # ==================================================
        # TEST STORAGE ROOT
        # ==================================================

        storage_root = (
            temp_root
            / "documents"
        )


        storage_service = (
            DocumentStorageService(
                storage_root=storage_root
            )
        )


        # ==================================================
        # CREATE SOURCE IMAGE
        # ==================================================
        #
        # Storage service does not decode the image.
        # The API already performs file-type validation.
        # For this unit test, byte preservation is enough.
        # ==================================================

        source_path = (
            temp_root
            / "source.jpg"
        )


        original_bytes = (
            b"PHASE-7B-TEST-IMAGE-DATA"
        )


        source_path.write_bytes(
            original_bytes
        )


        document_id = str(
            uuid4()
        )


        # ==================================================
        # SAVE ORIGINAL
        # ==================================================

        stored_path = (
            storage_service
            .save_original(
                document_id=(
                    document_id
                ),

                source_path=(
                    source_path
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
        )


        expected_path = (
            storage_root.resolve()
            / document_id
            / "original.jpg"
        )


        assert (
            stored_path
            == expected_path
        )


        assert (
            stored_path.exists()
        )


        assert (
            stored_path.read_bytes()
            == original_bytes
        )


        print(
            "[PASS] Original document saved"
        )

        print(
            "[PASS] Deterministic storage "
            "path verified"
        )

        print(
            "[PASS] File bytes preserved"
        )


        # ==================================================
        # EXISTS CHECK
        # ==================================================

        assert (
            storage_service
            .original_exists(
                document_id=(
                    document_id
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
            is True
        )


        print(
            "[PASS] Original existence "
            "check"
        )


        # ==================================================
        # LOAD ORIGINAL
        # ==================================================

        loaded_path = (
            storage_service
            .load_original(
                document_id=(
                    document_id
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
        )


        assert (
            loaded_path
            == stored_path
        )


        print(
            "[PASS] Original document "
            "retrieval"
        )


        # ==================================================
        # UNSUPPORTED CONTENT TYPE
        # ==================================================

        try:

            storage_service.save_original(
                document_id=(
                    str(uuid4())
                ),

                source_path=(
                    source_path
                ),

                content_type=(
                    "application/pdf"
                ),
            )


        except ValueError:

            print(
                "[PASS] Unsupported content "
                "type rejected"
            )


        else:

            raise AssertionError(
                "Unsupported content type "
                "should raise ValueError."
            )


        # ==================================================
        # MISSING SOURCE FILE
        # ==================================================

        try:

            storage_service.save_original(
                document_id=(
                    str(uuid4())
                ),

                source_path=(
                    temp_root
                    / "missing.jpg"
                ),

                content_type=(
                    "image/jpeg"
                ),
            )


        except FileNotFoundError:

            print(
                "[PASS] Missing source "
                "file rejected"
            )


        else:

            raise AssertionError(
                "Missing source file should "
                "raise FileNotFoundError."
            )


        # ==================================================
        # DELETE STORAGE
        # ==================================================

        deleted = (
            storage_service
            .delete_document(
                document_id
            )
        )


        assert (
            deleted
            is True
        )


        assert (
            not stored_path.exists()
        )


        assert (
            storage_service
            .original_exists(
                document_id=(
                    document_id
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
            is False
        )


        print(
            "[PASS] Document storage "
            "deleted"
        )


        # Repeated delete should be safe.

        deleted_again = (
            storage_service
            .delete_document(
                document_id
            )
        )


        assert (
            deleted_again
            is False
        )


        print(
            "[PASS] Repeated deletion "
            "handled safely"
        )


    print()
    print("=" * 72)
    print(
        "[PASS] PHASE 7B.1 DOCUMENT "
        "STORAGE TEST PASSED"
    )
    print("=" * 72)


if __name__ == "__main__":

    main()