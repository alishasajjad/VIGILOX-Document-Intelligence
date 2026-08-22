# ==========================================================
# EXACT DUPLICATE SOURCE DETECTION
# PHASE 10.3
# ==========================================================
#
# WHAT "DUPLICATE" MEANS HERE
# ----------------------------------------------------------
#
# Byte-for-byte identical upload. Nothing else.
#
# NOT the filename: a-copy.jpg and a.jpg are the same source,
# and report.jpg from two different people usually is not.
#
# NOT the OCR text: two photographs of the same licence
# produce different bytes and often different OCR, and calling
# them one source would silently discard a real second reading.
#
# NOT the extracted fields: two genuinely different documents
# can carry the same licence number, and treating that as a
# duplicate would hide the second one.
#
# A SHA-256 over the original bytes answers exactly one
# question -- "have I already processed this exact file?" --
# and answers it without interpretation.
#
#
# THIS IS NOT A FRAUD SIGNAL
# ----------------------------------------------------------
#
# Somebody uploading the same file twice is, overwhelmingly,
# somebody uploading the same file twice. A duplicate carries
# no severity, no score, and none of the words fraud,
# tampering, suspicious or fake. It is a workflow fact.
# ==========================================================

from __future__ import annotations

import hashlib

from pathlib import Path


# ==========================================================
# THE ALGORITHM
# ==========================================================
#
# SHA-256, named in one place so the column width, the tests
# and the documentation cannot disagree about it.
#
# 64 lowercase hex characters.
# ==========================================================

SOURCE_FINGERPRINT_ALGORITHM = "sha256"

SOURCE_FINGERPRINT_LENGTH = 64


# 1 MiB. Large enough that a 10 MB upload is ten reads, small
# enough that nothing here holds a document in memory.
_CHUNK_BYTES = 1024 * 1024


def fingerprint_path(
    path: str | Path,
) -> str:

    """
    SHA-256 over the bytes of a file, streamed.

    Never loads the file into memory, because the caller is
    holding an upload and the point of the bounded temporary
    file was to avoid exactly that.
    """

    digest = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as handle:

        while True:

            chunk = handle.read(
                _CHUNK_BYTES
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ==========================================================
# THE THREE OUTCOMES
# ==========================================================
#
# Stable codes. They reach the API and the interface, so they
# are contract.
# ==========================================================

# An identical source already has a completed document.
DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"


# An identical source is being processed right now.
DUPLICATE_IN_PROGRESS = "DUPLICATE_IN_PROGRESS"


DUPLICATE_CODES = (
    DUPLICATE_DOCUMENT,
    DUPLICATE_IN_PROGRESS,
)


DUPLICATE_DOCUMENT_MESSAGE = (
    "This exact document has already been "
    "processed. Open the existing document, or "
    "request reprocessing if it needs to be "
    "analysed again."
)


DUPLICATE_IN_PROGRESS_MESSAGE = (
    "This exact document is being processed right "
    "now. Follow the existing job rather than "
    "starting a second one."
)


# ==========================================================
# WHY THE EXISTING REFERENCE IS SAFE TO RETURN
# ==========================================================
#
# Returning an existing document_id to whoever uploaded the
# identical bytes discloses nothing they do not already hold:
# possession of the exact file is possession of the document.
#
# It does reveal that the file was processed before, which is
# the entire point -- withholding it would mean answering
# "rejected" with no way to act on it, which is the silent
# discard this policy exists to avoid.
#
# THE CONDITION THIS DEPENDS ON, STATED
# ----------------------------------------------------------
#
# VIGILOX has no per-document ownership or tenancy model. Any
# authenticated viewer can read any document, so there is no
# boundary for this reference to cross.
#
# If per-owner document visibility is ever introduced, this
# decision has to be revisited: the reference would then have
# to be filtered to documents the caller may already see, and
# a duplicate of somebody else's document would have to report
# the conflict without naming the record.
# ==========================================================


def describe_duplicate_source(
    *,
    document_id: str,
    same_source_document_ids: list[str],
) -> dict:

    """
    Describe how one document relates to other documents made
    from identical bytes.

    Derived at read time from an indexed lookup, not stored. A
    stored copy would need updating every time another upload
    of the same bytes arrived, and would be wrong in between.

    same_source_document_ids is every document sharing this
    fingerprint, OLDEST FIRST. The caller does the query
    because only the caller has a session.

    THE FINGERPRINT ITSELF IS NEVER IN THE RESULT.
    ------------------------------------------------------
    A hash of the bytes is a stable identifier for the
    document's content. Publishing it would let anyone holding
    a candidate file confirm, offline and without access, that
    VIGILOX holds that exact document. Nothing in the
    interface needs it, so nothing in the interface gets it.
    """

    others = [
        identifier
        for identifier in same_source_document_ids
        if identifier != document_id
    ]


    # Position among the documents made from these bytes.
    # 1 means this is the original.
    try:
        attempt = (
            same_source_document_ids.index(
                document_id
            )
            + 1
        )

    except ValueError:
        # The caller passed a list this document is not in.
        # Reported as unknown rather than guessed.
        attempt = None


    first = (
        same_source_document_ids[0]
        if same_source_document_ids
        else None
    )


    return {
        # True when an EARLIER document was made from the same
        # bytes -- so this one is a re-analysis of a source
        # already on file, rather than a new source.
        "is_reprocess":
            attempt is not None
            and attempt > 1,

        # The original. None when this document is it.
        "first_document_id":
            (
                first
                if first != document_id
                else None
            ),

        "same_source_document_ids":
            others,

        "same_source_count":
            len(
                others
            ),

        "attempt":
            attempt,

        # Said plainly, because a duplicate is a workflow fact
        # and a reader should not have to wonder whether the
        # system is implying something about it.
        "note":
            (
                "Identical source bytes were processed "
                "before. This is a repeat analysis of the "
                "same file, which is not by itself a sign "
                "of anything wrong."
            )
            if attempt is not None
            and attempt > 1
            else None,
    }
