import json
import random

from datetime import date, timedelta
from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
)


# ==========================================================
# CONFIGURATION
# ==========================================================

BASE_DIR = Path(
    "evaluation"
)

GROUND_TRUTH_PATH = (
    BASE_DIR
    / "ground_truth"
    / "labels.jsonl"
)

ID_CARD_DIR = (
    BASE_DIR
    / "images"
    / "id_card"
)

NUM_ID_CARDS = 20


# ==========================================================
# SYNTHETIC DATA
# ==========================================================

FIRST_NAMES = [
    "ADAM",
    "ALICE",
    "AMELIA",
    "BENJAMIN",
    "CHARLOTTE",
    "DANIEL",
    "EMILY",
    "ETHAN",
    "FATIMA",
    "GEORGE",
    "HANNAH",
    "ISAAC",
    "JAMES",
    "LILY",
    "MAYA",
    "NOAH",
    "OLIVIA",
    "RYAN",
    "SARAH",
    "ZARA",
]


LAST_NAMES = [
    "ANDERSON",
    "BROWN",
    "CLARK",
    "COOPER",
    "DAVIS",
    "EVANS",
    "GREEN",
    "HARRIS",
    "HILL",
    "JACKSON",
    "KING",
    "LEWIS",
    "MARTIN",
    "MILLER",
    "PARKER",
    "ROBERTS",
    "SCOTT",
    "THOMAS",
    "WALKER",
    "WILSON",
]


ISSUERS = [
    "National Identity Authority",
    "Civil Registration Authority",
    "Department of Identity Services",
    "National Population Registry",
]


# ==========================================================
# HELPERS
# ==========================================================

def ensure_directories():

    ID_CARD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    GROUND_TRUTH_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def load_font(
    size: int,
    bold: bool = False,
):

    if bold:

        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
        ]

    else:

        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
        ]


    for font_path in candidates:

        path = Path(
            font_path
        )

        if path.exists():

            return ImageFont.truetype(
                str(path),
                size=size,
            )


    return ImageFont.load_default()


def load_existing_records():

    if not GROUND_TRUTH_PATH.exists():

        return []


    records = []


    with GROUND_TRUTH_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = line.strip()


            if not line:

                continue


            records.append(
                json.loads(
                    line
                )
            )


    return records


def save_records(
    records,
):

    with GROUND_TRUTH_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        for record in records:

            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


def remove_old_generated_id_records(
    records,
):

    cleaned = []


    for record in records:

        sample_id = record.get(
            "sample_id",
            ""
        )


        if sample_id.startswith(
            "id_"
        ):

            try:

                number = int(
                    sample_id.split(
                        "_"
                    )[1]
                )


                # Preserve original id_001.
                # Remove generated id_002+
                # so the script can safely rerun.

                if number >= 2:

                    continue


            except (
                ValueError,
                IndexError,
            ):

                pass


        cleaned.append(
            record
        )


    return cleaned


def random_date(
    start_date: date,
    end_date: date,
):

    number_of_days = (
        end_date
        - start_date
    ).days


    return (
        start_date
        + timedelta(
            days=random.randint(
                0,
                number_of_days,
            )
        )
    )


def to_iso(
    value: date,
):

    return value.strftime(
        "%Y-%m-%d"
    )


def to_display_date(
    value: date,
):

    return value.strftime(
        "%d/%m/%Y"
    )


def create_full_name():

    first_name = random.choice(
        FIRST_NAMES
    )

    last_name = random.choice(
        LAST_NAMES
    )


    return (
        f"{first_name} "
        f"{last_name}"
    )


def create_unique_id_number(
    sample_number: int,
):

    # Sample number forms part
    # of the identifier so IDs
    # cannot collide.

    random_part = random.randint(
        100000000,
        999999999,
    )


    return (
        f"9{sample_number:02d}"
        f"{random_part}"
    )


# ==========================================================
# IMAGE RENDERING
# ==========================================================

def render_id_card(
    image_path: Path,
    full_name: str,
    id_number: str,
    date_of_birth: str,
    issue_date: str,
    expiry_date: str,
    issuer: str,
    template_number: int,
):

    width = 1100
    height = 680


    # ======================================================
    # SIMPLE TEMPLATE VARIATION
    # ======================================================

    backgrounds = [
        (242, 247, 252),
        (247, 245, 238),
        (240, 248, 244),
        (247, 242, 249),
    ]


    header_backgrounds = [
        (210, 226, 242),
        (231, 220, 199),
        (207, 231, 217),
        (228, 211, 235),
    ]


    background = backgrounds[
        template_number
        % len(backgrounds)
    ]


    header_background = (
        header_backgrounds[
            template_number
            % len(
                header_backgrounds
            )
        ]
    )


    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        color=background,
    )


    draw = ImageDraw.Draw(
        image
    )


    title_font = load_font(
        38,
        bold=True,
    )

    subtitle_font = load_font(
        25,
        bold=True,
    )

    label_font = load_font(
        21,
        bold=True,
    )

    value_font = load_font(
        28,
    )

    small_font = load_font(
        19,
    )

    warning_font = load_font(
        24,
        bold=True,
    )


    # ======================================================
    # CARD OUTLINE
    # ======================================================

    draw.rounded_rectangle(
        [
            (20, 20),
            (
                width - 20,
                height - 20,
            ),
        ],
        radius=22,
        fill=background,
        outline=(
            60,
            70,
            85,
        ),
        width=4,
    )


    # ======================================================
    # HEADER
    # ======================================================

    draw.rounded_rectangle(
        [
            (20, 20),
            (
                width - 20,
                145,
            ),
        ],
        radius=20,
        fill=header_background,
    )


    draw.text(
        (
            50,
            42,
        ),
        "REPUBLIC OF UTOPIA",
        font=title_font,
        fill=(
            25,
            40,
            65,
        ),
    )


    draw.text(
        (
            52,
            95,
        ),
        "NATIONAL IDENTITY CARD",
        font=subtitle_font,
        fill=(
            45,
            55,
            70,
        ),
    )


    # ======================================================
    # CLEAR SYNTHETIC MARKING
    # ======================================================

    draw.rectangle(
        [
            (
                730,
                38,
            ),
            (
                1040,
                112,
            ),
        ],
        outline=(
            150,
            40,
            40,
        ),
        width=3,
    )


    draw.text(
        (
            760,
            52,
        ),
        "SYNTHETIC",
        font=warning_font,
        fill=(
            150,
            30,
            30,
        ),
    )


    draw.text(
        (
            780,
            82,
        ),
        "NOT VALID",
        font=small_font,
        fill=(
            150,
            30,
            30,
        ),
    )


    # ======================================================
    # PHOTO PLACEHOLDER
    # ======================================================

    draw.rectangle(
        [
            (
                55,
                190,
            ),
            (
                305,
                500,
            ),
        ],
        outline=(
            100,
            110,
            120,
        ),
        width=3,
        fill=(
            225,
            229,
            233,
        ),
    )


    draw.ellipse(
        [
            (
                125,
                225,
            ),
            (
                235,
                335,
            ),
        ],
        outline=(
            130,
            135,
            140,
        ),
        width=4,
    )


    draw.rectangle(
        [
            (
                105,
                345,
            ),
            (
                255,
                450,
            ),
        ],
        outline=(
            130,
            135,
            140,
        ),
        width=4,
    )


    draw.text(
        (
            135,
            465,
        ),
        "PHOTO",
        font=small_font,
        fill=(
            90,
            90,
            90,
        ),
    )


    # ======================================================
    # FULL NAME
    # ======================================================

    draw.text(
        (
            350,
            185,
        ),
        "FULL NAME",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    draw.text(
        (
            350,
            220,
        ),
        full_name,
        font=value_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # ID NUMBER
    # ======================================================

    draw.text(
        (
            350,
            285,
        ),
        "ID NUMBER",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    draw.text(
        (
            350,
            320,
        ),
        id_number,
        font=value_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # DATE OF BIRTH
    # ======================================================

    draw.text(
        (
            350,
            385,
        ),
        "DATE OF BIRTH",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    dob = date.fromisoformat(
        date_of_birth
    )


    draw.text(
        (
            350,
            420,
        ),
        to_display_date(
            dob
        ),
        font=value_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # ISSUE DATE
    # ======================================================

    draw.text(
        (
            350,
            485,
        ),
        "ISSUE DATE",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    issue = date.fromisoformat(
        issue_date
    )


    draw.text(
        (
            350,
            520,
        ),
        to_display_date(
            issue
        ),
        font=value_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # EXPIRY DATE
    # ======================================================

    draw.text(
        (
            700,
            385,
        ),
        "EXPIRY DATE",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    expiry = date.fromisoformat(
        expiry_date
    )


    draw.text(
        (
            700,
            420,
        ),
        to_display_date(
            expiry
        ),
        font=value_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # ISSUER
    # ======================================================

    draw.text(
        (
            700,
            485,
        ),
        "ISSUED BY",
        font=label_font,
        fill=(
            80,
            80,
            80,
        ),
    )


    draw.text(
        (
            700,
            520,
        ),
        issuer,
        font=small_font,
        fill=(
            15,
            15,
            15,
        ),
    )


    # ======================================================
    # FOOTER
    # ======================================================

    draw.line(
        [
            (
                50,
                590,
            ),
            (
                1050,
                590,
            ),
        ],
        fill=(
            130,
            135,
            140,
        ),
        width=2,
    )


    draw.text(
        (
            55,
            610,
        ),
        (
            "FICTIONAL DOCUMENT FOR "
            "RESEARCH AND TESTING ONLY"
        ),
        font=small_font,
        fill=(
            110,
            45,
            45,
        ),
    )


    # ======================================================
    # SAVE
    # ======================================================

    image.save(
        image_path,
        format="JPEG",
        quality=95,
    )


# ==========================================================
# BUILD RECORD
# ==========================================================

def build_id_record(
    sample_number: int,
):

    sample_id = (
        f"id_{sample_number:03d}"
    )


    image_path = (
        ID_CARD_DIR
        / f"{sample_id}.jpg"
    )


    full_name = (
        create_full_name()
    )


    id_number = (
        create_unique_id_number(
            sample_number
        )
    )


    date_of_birth = random_date(
        date(
            1970,
            1,
            1,
        ),
        date(
            2004,
            12,
            31,
        ),
    )


    issue_date = random_date(
        date(
            2020,
            1,
            1,
        ),
        date(
            2025,
            12,
            31,
        ),
    )


    # National ID validity:
    # 10 years after issue.

    expiry_date = (
        issue_date
        + timedelta(
            days=3650
        )
    )


    issuer = random.choice(
        ISSUERS
    )


    render_id_card(
        image_path=image_path,

        full_name=full_name,

        id_number=id_number,

        date_of_birth=to_iso(
            date_of_birth
        ),

        issue_date=to_iso(
            issue_date
        ),

        expiry_date=to_iso(
            expiry_date
        ),

        issuer=issuer,

        template_number=(
            sample_number
            - 2
        ),
    )


    return {

        "sample_id":
            sample_id,

        "image_path":
            image_path.as_posix(),

        "document_type":
            "id_card",

        "fields": {

            "full_name":
                full_name,

            "licence_number":
                None,

            "id_number":
                id_number,

            "expiry_date":
                to_iso(
                    expiry_date
                ),

            "date_of_birth":
                to_iso(
                    date_of_birth
                ),

            "issue_date":
                to_iso(
                    issue_date
                ),

            "issuer":
                issuer,
        },

        "quality":
            "clean",

        "notes":
            (
                "Synthetic fictional ID "
                "document generated for "
                "research evaluation."
            ),
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    random.seed(
        20260818
    )


    ensure_directories()


    records = (
        load_existing_records()
    )


    # Remove previous generated
    # id_002+ records if rerunning.

    records = (
        remove_old_generated_id_records(
            records
        )
    )


    # Remove previous generated
    # ID image files.

    for number in range(
        2,
        22,
    ):

        old_image = (
            ID_CARD_DIR
            / f"id_{number:03d}.jpg"
        )


        if old_image.exists():

            old_image.unlink()


    generated_records = []


    # id_002 ... id_021

    for number in range(
        2,
        2 + NUM_ID_CARDS,
    ):

        record = (
            build_id_record(
                number
            )
        )


        generated_records.append(
            record
        )


    final_records = (
        records
        + generated_records
    )


    save_records(
        final_records
    )


    # ======================================================
    # COUNTS
    # ======================================================

    guard_count = sum(

        1

        for record
        in final_records

        if record[
            "document_type"
        ]
        == "guard_license"
    )


    sia_count = sum(

        1

        for record
        in final_records

        if record[
            "document_type"
        ]
        == "sia_badge"
    )


    id_count = sum(

        1

        for record
        in final_records

        if record[
            "document_type"
        ]
        == "id_card"
    )


    print()
    print(
        "=" * 70
    )

    print(
        "PHASE 6D — SYNTHETIC "
        "ID CARD GENERATION"
    )

    print(
        "=" * 70
    )


    print(
        "Generated ID cards:",
        NUM_ID_CARDS,
    )


    print()
    print(
        "Final dataset counts:"
    )


    print(
        f"  guard_license: {guard_count}"
    )

    print(
        f"  sia_badge:     {sia_count}"
    )

    print(
        f"  id_card:       {id_count}"
    )

    print(
        f"  total:         {len(final_records)}"
    )


    print()
    print(
        "Ground truth updated:"
    )

    print(
        f"  {GROUND_TRUTH_PATH}"
    )


    print()
    print(
        "[PASS] Synthetic ID "
        "dataset generation complete."
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":

    main()