import argparse
import sys

from pathlib import Path

from sqlalchemy import (
    func,
    select,
)


# ==========================================================
# PROJECT ROOT ON sys.path
# ==========================================================
#
# This is an operational maintenance script, not production
# application code, and it is intended to be runnable
# directly:
#
#     python scripts\maintenance\clean_test_residue.py
#
# Adding the project root here keeps that ergonomic without
# requiring PYTHONPATH to be exported first.
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from database.database import (  # noqa: E402
    SessionLocal,
)

from database.models import (  # noqa: E402
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


# ==========================================================
# TEST RESIDUE CLEANUP
# PHASE 8.1
# ==========================================================
#
# WHY THIS EXISTS
# ----------------------------------------------------------
#
# The Phase 8.0 repository audit found leftover documents in
# PostgreSQL created by older real-pipeline test runs that
# did not clean up after themselves.
#
# That residue is not harmless. It is the direct cause of the
# failure in:
#
#     tests/legacy/test_phase7a_review_queue.py
#
# which asserts an exact GLOBAL review-queue ordering and
# therefore breaks as soon as unrelated documents exist.
#
#
# SAFETY RULES
# ----------------------------------------------------------
#
# 1. Default mode is a read-only report. Nothing is deleted
#    unless --delete is passed explicitly.
#
# 2. Only documents matching a recognised test filename are
#    ever considered. Real business documents are never
#    touched.
#
# 3. Documents that already carry a human review are skipped
#    by default, because a reviewed document is an auditable
#    business record rather than obvious residue.
#    Use --include-reviewed to override deliberately.
#
# 4. Deletion is database-only and relies on the existing
#    foreign-key cascades. It intentionally does NOT touch
#    managed storage, so any resulting orphan can still be
#    detected and reconciled by the existing storage
#    integrity tooling.
# ==========================================================

# ==========================================================
# WHAT THIS LIST CANNOT TELL APART
# ==========================================================
#
# READ THIS BEFORE PASSING --delete.
#
# The first three entries are the filenames of the sample
# documents. The test suites upload those samples, and so does
# anybody trying the product for real -- the file they pick is
# usually the same one, with the same name.
#
# So this heuristic CANNOT distinguish test residue from a
# genuine upload of a file with the same name. During the
# Phase 12 audit the report listed two real uploads as
# deletion candidates alongside twenty-three genuine test
# rows, and nothing in the row itself separated them.
#
# There is no marker to fix that with: the application does
# not record "a test made this", and inventing one would put
# test awareness into production code.
#
# The guard is therefore procedural rather than clever.
# --delete now requires either
#
#     --id <document id> ...     delete exactly these
#     --all-candidates           delete everything reported,
#                                having read the list
#
# Report first, always. The list is the point of the tool; the
# deletion is the easy part.
# ==========================================================

TEST_FILENAME_PATTERNS = (
    # Also the real sample filenames. See above.
    "guard_license.jpg",
    "id_card.jpg",
    "sia_badge.jpg",

    # These are unambiguous: nothing but a test creates them.
    "phase7a_",
    "phase7b",
    "phase7c",
    "phase6c",
    "phase7c8_",
    "uploaded_document",
)


# Patterns that only a test produces. A candidate matching one
# of these is safe to delete unattended; a candidate matching
# only a sample filename is not.
UNAMBIGUOUS_TEST_PATTERNS = (
    "phase7a_",
    "phase7b",
    "phase7c",
    "phase6c",
    "phase7c8_",
    "uploaded_document",
)


def is_unambiguously_test(
    original_filename: str | None,
) -> bool:

    if not original_filename:
        return False

    name = original_filename.strip().lower()

    return any(
        pattern in name
        for pattern in UNAMBIGUOUS_TEST_PATTERNS
    )


def looks_like_test_document(
    original_filename: str | None,
) -> bool:

    if not original_filename:

        return False


    name = (
        original_filename
        .strip()
        .lower()
    )


    return any(
        pattern in name
        for pattern in (
            TEST_FILENAME_PATTERNS
        )
    )


# ==========================================================
# REPORT
# ==========================================================

def build_report(
    *,
    include_reviewed: bool,
) -> list[dict]:

    candidates = []


    with SessionLocal() as session:

        documents = (
            session.scalars(
                select(
                    DocumentModel
                )
            )
            .all()
        )


        for document in documents:

            if not looks_like_test_document(
                document.original_filename
            ):

                continue


            review_count = (
                session.scalar(
                    select(
                        func.count(
                            HumanReviewModel.id
                        )
                    )
                    .where(
                        HumanReviewModel
                        .document_id
                        == document.id
                    )
                )
                or 0
            )


            if (
                review_count > 0
                and not include_reviewed
            ):

                continue


            analysis_count = (
                session.scalar(
                    select(
                        func.count(
                            DocumentAnalysisModel.id
                        )
                    )
                    .where(
                        DocumentAnalysisModel
                        .document_id
                        == document.id
                    )
                )
                or 0
            )


            audit_count = (
                session.scalar(
                    select(
                        func.count(
                            AuditEventModel.id
                        )
                    )
                    .where(
                        AuditEventModel
                        .document_id
                        == document.id
                    )
                )
                or 0
            )


            candidates.append(
                {
                    "document_id":
                        document.id,

                    "original_filename":
                        document.original_filename,

                    "processing_status":
                        document.processing_status,

                    "created_at":
                        document.created_at,

                    "analyses":
                        analysis_count,

                    "reviews":
                        review_count,

                    "audits":
                        audit_count,
                }
            )


    return candidates


# ==========================================================
# DELETE
# ==========================================================

def delete_documents(
    document_ids,
) -> int:

    deleted = 0


    for document_id in document_ids:

        with SessionLocal.begin() as session:

            document = (
                session.get(
                    DocumentModel,
                    document_id,
                )
            )


            if document is None:

                continue


            session.delete(
                document
            )


            deleted += 1


    return deleted


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Report, and optionally delete, "
                "PostgreSQL document rows left "
                "behind by older test runs."
            )
        )
    )


    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually delete the reported "
            "documents. Without this flag the "
            "script only reports."
        ),
    )


    parser.add_argument(
        "--id",
        nargs="+",
        default=None,
        metavar="DOCUMENT_ID",
        help=(
            "Delete exactly these document ids, "
            "and only if they appear in the "
            "report. The safe way to use "
            "--delete."
        ),
    )


    parser.add_argument(
        "--all-candidates",
        action="store_true",
        help=(
            "Delete every reported candidate. "
            "Required for an untargeted "
            "--delete, because filename "
            "matching cannot distinguish test "
            "residue from a real upload of the "
            "same name."
        ),
    )


    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help=(
            "Also consider documents that "
            "already have a human review. Off "
            "by default, because a reviewed "
            "document is an auditable record."
        ),
    )


    arguments = (
        parser.parse_args()
    )


    print()
    print("=" * 76)
    print(
        "VIGILOX TEST RESIDUE REPORT"
    )
    print("=" * 76)


    candidates = (
        build_report(
            include_reviewed=(
                arguments.include_reviewed
            )
        )
    )


    if not candidates:

        print()
        print(
            "No test residue found. "
            "Nothing to do."
        )

        return 0


    print()
    print(
        f"{'DOCUMENT ID':38} "
        f"{'FILENAME':24} "
        f"{'AN':>3} "
        f"{'RV':>3} "
        f"{'AU':>3}"
    )
    print("-" * 76)


    for item in candidates:

        print(
            f"{item['document_id']:38} "
            f"{str(item['original_filename'])[:24]:24} "
            f"{item['analyses']:>3} "
            f"{item['reviews']:>3} "
            f"{item['audits']:>3}"
        )


    print("-" * 76)
    print(
        f"Candidate documents: "
        f"{len(candidates)}"
    )


    # ======================================================
    # REPORT ONLY
    # ======================================================

    if not arguments.delete:

        print()
        print(
            "Report-only mode. Nothing was "
            "deleted."
        )

        print(
            "Re-run with --delete to remove "
            "these rows and their cascades."
        )

        return 0


    # ======================================================
    # DELETE
    # ======================================================

    # ------------------------------------------------------
    # THE GUARD
    # ------------------------------------------------------
    #
    # Ambiguous candidates are the ones matched only by a
    # sample filename, which a real upload shares. They are
    # named individually so the operator sees exactly what is
    # at stake before choosing.

    ambiguous = [
        item
        for item in candidates
        if not is_unambiguously_test(
            item.get(
                "original_filename"
            )
        )
    ]

    if arguments.id:

        wanted = set(
            arguments.id
        )

        known = {
            item["document_id"]
            for item in candidates
        }

        unknown = sorted(
            wanted - known
        )

        if unknown:

            print()
            print(
                "REFUSING: these ids are not in the report "
                "above:"
            )

            for value in unknown:
                print(
                    f"  {value}"
                )

            print()
            print(
                "Only a reported candidate can be deleted. "
                "Re-run without --delete to see the list."
            )
            return 1

        targets = sorted(
            wanted
        )

    elif arguments.all_candidates:

        targets = [
            item["document_id"]
            for item in candidates
        ]

    else:

        print()
        print(
            "REFUSING: --delete needs to be told what to "
            "delete."
        )
        print()
        print(
            "Filename matching cannot tell test residue from "
            "a real upload of the same name. Three of the "
            "patterns this tool matches -- guard_license.jpg, "
            "id_card.jpg, sia_badge.jpg -- are the sample "
            "filenames, and a person trying the product "
            "uploads exactly those."
        )

        if ambiguous:

            print()
            print(
                f"{len(ambiguous)} of {len(candidates)} "
                "candidate(s) are matched ONLY by a sample "
                "filename, so they could be either:"
            )

            for item in ambiguous:
                print(
                    f"  {item['document_id']}  "
                    f"{item.get('original_filename')}"
                )

        print()
        print(
            "Choose one:"
        )
        print(
            "  --delete --id <id> [<id> ...]   delete exactly "
            "these"
        )
        print(
            "  --delete --all-candidates       delete all "
            "of the above, having read the list"
        )
        return 1

    print()
    print(
        f"Deleting {len(targets)} document(s) and their "
        "cascades..."
    )


    deleted = (
        delete_documents(
            targets
        )
    )


    print()
    print(
        f"Deleted {deleted} document(s)."
    )

    print(
        "Managed storage was intentionally "
        "left untouched. Any resulting "
        "orphan is detectable by the storage "
        "integrity tooling."
    )


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
