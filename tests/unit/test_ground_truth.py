import json
from pathlib import Path


# ==========================================================
# CONFIGURATION
# ==========================================================

GROUND_TRUTH_PATH = Path(
    "evaluation/ground_truth/labels.jsonl"
)


ALLOWED_DOCUMENT_TYPES = {
    "sia_badge",
    "id_card",
    "guard_license",
}


ALLOWED_QUALITY_VALUES = {
    "clean",
    "rotated",
    "blurred",
    "low_light",
    "small_text",
    "compressed",
    "other",
}


REQUIRED_FIELDS = {
    "full_name",
    "licence_number",
    "id_number",
    "expiry_date",
    "date_of_birth",
    "issue_date",
    "issuer",
}


# ==========================================================
# LOAD JSONL
# ==========================================================

print()
print("=" * 70)
print(
    "PHASE 6D — GROUND TRUTH VALIDATION"
)
print("=" * 70)


assert (
    GROUND_TRUTH_PATH.exists()
), (
    "Ground truth file does not exist: "
    f"{GROUND_TRUTH_PATH}"
)


records = []


with GROUND_TRUTH_PATH.open(
    "r",
    encoding="utf-8",
) as file:

    for line_number, line in enumerate(
        file,
        start=1,
    ):

        line = line.strip()


        # Skip blank lines
        if not line:
            continue


        try:

            record = json.loads(
                line
            )

        except json.JSONDecodeError as exc:

            raise AssertionError(
                f"Invalid JSON on line "
                f"{line_number}: {exc}"
            ) from exc


        records.append(
            record
        )


# ==========================================================
# BASIC DATASET CHECK
# ==========================================================

assert records, (
    "Ground truth dataset is empty."
)


print(
    "Ground truth records:",
    len(records),
)


# ==========================================================
# UNIQUE SAMPLE IDS
# ==========================================================

sample_ids = [
    record.get(
        "sample_id"
    )
    for record
    in records
]


assert all(
    sample_ids
), (
    "Every record must contain "
    "a non-empty sample_id."
)


assert (
    len(sample_ids)
    == len(set(sample_ids))
), (
    "Duplicate sample_id detected."
)


print(
    "Unique sample IDs:",
    "OK"
)


# ==========================================================
# VALIDATE EACH RECORD
# ==========================================================

for index, record in enumerate(
    records,
    start=1,
):

    sample_id = (
        record.get(
            "sample_id"
        )
    )


    # ======================================================
    # REQUIRED TOP-LEVEL KEYS
    # ======================================================

    required_keys = {
        "sample_id",
        "image_path",
        "document_type",
        "fields",
        "quality",
        "notes",
    }


    missing_keys = (
        required_keys
        - set(
            record.keys()
        )
    )


    assert not missing_keys, (
        f"{sample_id}: missing "
        f"top-level keys: "
        f"{sorted(missing_keys)}"
    )


    # ======================================================
    # DOCUMENT TYPE
    # ======================================================

    document_type = (
        record[
            "document_type"
        ]
    )


    assert (
        document_type
        in ALLOWED_DOCUMENT_TYPES
    ), (
        f"{sample_id}: invalid "
        f"document_type "
        f"'{document_type}'"
    )


    # ======================================================
    # QUALITY CATEGORY
    # ======================================================

    quality = (
        record[
            "quality"
        ]
    )


    assert (
        quality
        in ALLOWED_QUALITY_VALUES
    ), (
        f"{sample_id}: invalid "
        f"quality '{quality}'"
    )


    # ======================================================
    # IMAGE EXISTS
    # ======================================================

    image_path = Path(
        record[
            "image_path"
        ]
    )


    assert (
        image_path.exists()
    ), (
        f"{sample_id}: image does "
        f"not exist: {image_path}"
    )


    assert (
        image_path.is_file()
    ), (
        f"{sample_id}: image_path "
        "is not a file."
    )


    # ======================================================
    # FIELD OBJECT
    # ======================================================

    fields = (
        record[
            "fields"
        ]
    )


    assert isinstance(
        fields,
        dict,
    ), (
        f"{sample_id}: fields "
        "must be an object."
    )


    field_names = set(
        fields.keys()
    )


    missing_fields = (
        REQUIRED_FIELDS
        - field_names
    )


    extra_fields = (
        field_names
        - REQUIRED_FIELDS
    )


    assert not missing_fields, (
        f"{sample_id}: missing "
        f"fields: "
        f"{sorted(missing_fields)}"
    )


    assert not extra_fields, (
        f"{sample_id}: unsupported "
        f"fields: "
        f"{sorted(extra_fields)}"
    )


    # ======================================================
    # FIELD VALUE TYPES
    # ======================================================

    for field_name, value in (
        fields.items()
    ):

        assert (
            value is None
            or isinstance(
                value,
                str,
            )
        ), (
            f"{sample_id}: "
            f"{field_name} must "
            "be string or null."
        )


        if isinstance(
            value,
            str,
        ):

            assert (
                value.strip()
                == value
            ), (
                f"{sample_id}: "
                f"{field_name} has "
                "leading/trailing spaces."
            )


            assert value, (
                f"{sample_id}: "
                f"{field_name} cannot "
                "be an empty string. "
                "Use null instead."
            )


    print(
        f"[OK] {sample_id}"
    )


# ==========================================================
# DOCUMENT TYPE COUNTS
# ==========================================================

type_counts = {
    document_type: 0
    for document_type
    in ALLOWED_DOCUMENT_TYPES
}


for record in records:

    type_counts[
        record[
            "document_type"
        ]
    ] += 1


print()
print(
    "Document type counts:"
)


for document_type in sorted(
    type_counts
):

    print(
        f"  {document_type}: "
        f"{type_counts[document_type]}"
    )


# ==========================================================
# SUCCESS
# ==========================================================

print()
print("=" * 70)
print(
    "[PASS] Ground truth dataset "
    "validation passed."
)
print("=" * 70)