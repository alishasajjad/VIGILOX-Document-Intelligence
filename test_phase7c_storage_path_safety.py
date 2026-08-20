import tempfile

from pathlib import Path
from uuid import uuid4

from src.document_storage_service import (
    DocumentStorageSecurityError,
    DocumentStorageService,
)


# ==========================================================
# ASSERT HELPERS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
):

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


def assert_false(
    condition: bool,
    message: str,
):

    if condition:

        raise AssertionError(
            message
        )


def assert_raises(
    expected_exception,
    callback,
    message: str,
):

    try:

        callback()

    except expected_exception:

        return


    except Exception as exc:

        raise AssertionError(
            f"{message}\n"
            "Unexpected exception: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


    raise AssertionError(
        message
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.6a — STORAGE PATH "
        "SAFETY + LIFECYCLE INVARIANTS TEST"
    )
    print("=" * 76)


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_root = (
            temp_root
            / "managed-storage"
        )


        outside_root = (
            temp_root
            / "outside"
        )


        outside_root.mkdir(
            parents=True,
            exist_ok=True,
        )


        service = (
            DocumentStorageService(
                storage_root=(
                    storage_root
                )
            )
        )


        # ==================================================
        # TEST 1 — STORAGE ROOT
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — CANONICAL STORAGE ROOT"
        )
        print("-" * 76)


        assert_true(
            service.storage_root.exists(),
            (
                "Storage root should "
                "exist after initialization."
            ),
        )


        assert_true(
            service.storage_root.is_dir(),
            (
                "Storage root should "
                "be a directory."
            ),
        )


        assert_equal(
            service.storage_root,
            storage_root.resolve(),
            (
                "Storage root should use "
                "canonical resolved path."
            ),
        )


        print(
            "[PASS] Canonical storage "
            "root initialized"
        )


        # ==================================================
        # TEST 2 — VALID DOCUMENT ID
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — VALID DOCUMENT ID"
        )
        print("-" * 76)


        document_id = str(
            uuid4()
        )


        document_directory = (
            service.get_document_directory(
                document_id
            )
        )


        assert_equal(
            document_directory.parent,
            service.storage_root,
            (
                "Document directory must "
                "remain directly under "
                "storage root."
            ),
        )


        assert_equal(
            document_directory.name,
            document_id,
            (
                "Document directory name "
                "is incorrect."
            ),
        )


        print(
            "[PASS] Valid document ID "
            "resolves inside storage root"
        )


        # ==================================================
        # TEST 3 — MALICIOUS DOCUMENT IDS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — PATH TRAVERSAL REJECTION"
        )
        print("-" * 76)


        unsafe_document_ids = [
            "",
            " ",
            ".",
            "..",
            "../outside",
            "../../outside",
            "..\\outside",
            "folder/document",
            "folder\\document",
            "/absolute",
            "\\absolute",
            "C:\\Windows",
            "C:/Windows",
            "document:evil",
            "document id",
            " document",
            "document ",
        ]


        for unsafe_id in unsafe_document_ids:

            assert_raises(
                DocumentStorageSecurityError,

                lambda unsafe_id=unsafe_id:
                    service.get_document_directory(
                        unsafe_id
                    ),

                (
                    "Unsafe document ID "
                    f"was accepted: "
                    f"{unsafe_id!r}"
                ),
            )


        print(
            "[PASS] Traversal and unsafe "
            "document IDs rejected"
        )


        # ==================================================
        # TEST 4 — UNSUPPORTED CONTENT TYPE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — CONTENT TYPE VALIDATION"
        )
        print("-" * 76)


        assert_raises(
            ValueError,

            lambda:
                service.get_original_path(
                    document_id=(
                        document_id
                    ),

                    content_type=(
                        "application/pdf"
                    ),
                ),

            (
                "Unsupported content type "
                "should be rejected."
            ),
        )


        print(
            "[PASS] Unsupported content "
            "type rejected"
        )


        # ==================================================
        # TEST 5 — ATOMIC ORIGINAL STORAGE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — ATOMIC ORIGINAL STORAGE"
        )
        print("-" * 76)


        source_file = (
            temp_root
            / "source.jpg"
        )


        source_bytes = (
            b"VIGILOX-PHASE-7C-6-"
            b"STORAGE-PATH-SAFETY"
        )


        source_file.write_bytes(
            source_bytes
        )


        stored_path = (
            service.save_original(
                document_id=(
                    document_id
                ),

                source_path=(
                    source_file
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
        )


        assert_true(
            stored_path.exists(),
            (
                "Stored original file "
                "does not exist."
            ),
        )


        assert_true(
            stored_path.is_file(),
            (
                "Stored original path "
                "should be a file."
            ),
        )


        assert_equal(
            stored_path.parent,
            document_directory,
            (
                "Stored original escaped "
                "document directory."
            ),
        )


        assert_equal(
            stored_path.read_bytes(),
            source_bytes,
            (
                "Stored original bytes "
                "do not match source."
            ),
        )


        assert_equal(
            stored_path.name,
            "original.jpg",
            (
                "Stored original filename "
                "is incorrect."
            ),
        )


        print(
            "[PASS] Original document "
            "stored atomically"
        )

        print(
            "[PASS] Stored bytes preserved"
        )


        # ==================================================
        # TEST 6 — NO TEMP FILE LEFT
        # ==================================================

        temp_files = list(
            document_directory.glob(
                ".upload_*.tmp"
            )
        )


        assert_equal(
            temp_files,
            [],
            (
                "Successful storage should "
                "not leave temporary files."
            ),
        )


        print(
            "[PASS] No temporary upload "
            "file left behind"
        )


        # ==================================================
        # TEST 7 — EXISTS / LOAD
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 6 — SAFE LOAD"
        )
        print("-" * 76)


        assert_true(
            service.original_exists(
                document_id=(
                    document_id
                ),

                content_type=(
                    "image/jpeg"
                ),
            ),
            (
                "original_exists() should "
                "detect stored source."
            ),
        )


        loaded_path = (
            service.load_original(
                document_id=(
                    document_id
                ),

                content_type=(
                    "image/jpeg"
                ),
            )
        )


        assert_equal(
            loaded_path,
            stored_path,
            (
                "load_original() returned "
                "unexpected path."
            ),
        )


        assert_equal(
            loaded_path.read_bytes(),
            source_bytes,
            (
                "Loaded source bytes "
                "are incorrect."
            ),
        )


        print(
            "[PASS] Stored original loads "
            "from managed path"
        )


        # ==================================================
        # TEST 8 — OUTSIDE SENTINEL
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 7 — DELETE BOUNDARY PROTECTION"
        )
        print("-" * 76)


        sentinel = (
            outside_root
            / "DO_NOT_DELETE.txt"
        )


        sentinel.write_text(
            "outside managed storage",
            encoding="utf-8",
        )


        malicious_delete_ids = [
            "../outside",
            "..\\outside",
            "../../outside",
            "C:\\Windows",
            "/",
            "..",
        ]


        for malicious_id in malicious_delete_ids:

            assert_raises(
                DocumentStorageSecurityError,

                lambda malicious_id=malicious_id:
                    service.delete_document(
                        malicious_id
                    ),

                (
                    "Unsafe delete identifier "
                    f"was accepted: "
                    f"{malicious_id!r}"
                ),
            )


            assert_true(
                sentinel.exists(),
                (
                    "Unsafe delete operation "
                    "modified a file outside "
                    "managed storage."
                ),
            )


        print(
            "[PASS] Unsafe recursive delete "
            "attempts rejected"
        )

        print(
            "[PASS] Outside sentinel preserved"
        )


        # ==================================================
        # TEST 9 — VALID DELETE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 8 — SAFE VALID DELETE"
        )
        print("-" * 76)


        deleted = (
            service.delete_document(
                document_id
            )
        )


        assert_equal(
            deleted,
            True,
            (
                "Existing document storage "
                "should return True on delete."
            ),
        )


        assert_false(
            document_directory.exists(),
            (
                "Document directory still "
                "exists after delete."
            ),
        )


        assert_true(
            service.storage_root.exists(),
            (
                "Deleting one document must "
                "not delete storage root."
            ),
        )


        assert_true(
            sentinel.exists(),
            (
                "Deleting valid document "
                "must not affect outside data."
            ),
        )


        print(
            "[PASS] Valid document directory "
            "deleted safely"
        )

        print(
            "[PASS] Storage root preserved"
        )

        print(
            "[PASS] Outside data preserved"
        )


        # ==================================================
        # TEST 10 — IDEMPOTENT DELETE
        # ==================================================

        deleted_again = (
            service.delete_document(
                document_id
            )
        )


        assert_equal(
            deleted_again,
            False,
            (
                "Deleting missing document "
                "should safely return False."
            ),
        )


        print(
            "[PASS] Repeated delete is "
            "safe and idempotent"
        )


        # ==================================================
        # TEST 11 — MISSING SOURCE FILE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 9 — MISSING SOURCE FILE"
        )
        print("-" * 76)


        missing_document_id = str(
            uuid4()
        )


        missing_source = (
            temp_root
            / "missing.jpg"
        )


        assert_raises(
            FileNotFoundError,

            lambda:
                service.save_original(
                    document_id=(
                        missing_document_id
                    ),

                    source_path=(
                        missing_source
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                ),

            (
                "Missing source file should "
                "raise FileNotFoundError."
            ),
        )


        missing_directory = (
            service.get_document_directory(
                missing_document_id
            )
        )


        assert_false(
            missing_directory.exists(),
            (
                "Missing source failure "
                "should not leave document "
                "storage directory."
            ),
        )


        print(
            "[PASS] Missing source rejected"
        )

        print(
            "[PASS] Missing-source failure "
            "left no storage artifact"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.6a STORAGE "
            "PATH SAFETY TEST PASSED"
        )
        print("=" * 76)


if __name__ == "__main__":

    main()