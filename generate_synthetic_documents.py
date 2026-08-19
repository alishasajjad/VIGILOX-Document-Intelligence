import json
import random

from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ==========================================================
# CONFIGURATION
# ==========================================================

BASE_DIR = Path("evaluation")
GROUND_TRUTH_PATH = (
    BASE_DIR / "ground_truth" / "labels.jsonl"
)

SIA_DIR = (
    BASE_DIR / "images" / "sia_badge"
)

GUARD_DIR = (
    BASE_DIR / "images" / "guard_license"
)


NUM_SIA_TO_GENERATE = 20
NUM_GUARD_TO_GENERATE = 20


FIRST_NAMES = [
    "JANE", "JOHN", "ALI", "SARA", "OMAR",
    "EMMA", "NOAH", "MASON", "AVA", "LUCAS",
    "ZARA", "ADAM", "AMY", "ISLA", "ETHAN",
    "MIA", "LEO", "CHLOE", "BEN", "ELLA",
]

LAST_NAMES = [
    "SMITH", "GREEN", "KHAN", "BROWN", "DAVIS",
    "WILSON", "TAYLOR", "CLARKE", "LEE", "WHITE",
    "HARRIS", "HALL", "YOUNG", "KING", "SCOTT",
    "COOPER", "WARD", "HUGHES", "PERRY", "REED",
]


# ==========================================================
# HELPERS
# ==========================================================

def ensure_directories():
    SIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    GUARD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    GROUND_TRUTH_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def load_font(
    size: int,
):
    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
    ]

    for font_path in font_candidates:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(
                str(path),
                size=size,
            )

    return ImageFont.load_default()


def random_date(
    start_date: date,
    end_date: date,
):
    delta_days = (
        end_date - start_date
    ).days

    random_days = random.randint(
        0,
        delta_days,
    )

    return start_date + timedelta(
        days=random_days
    )


def format_date_slash(
    d: date,
):
    return d.strftime(
        "%d/%m/%Y"
    )


def format_date_iso(
    d: date,
):
    return d.strftime(
        "%Y-%m-%d"
    )


def random_full_name():
    first = random.choice(
        FIRST_NAMES
    )
    last = random.choice(
        LAST_NAMES
    )
    return first, last


def make_sia_full_name():
    first, last = random_full_name()
    return f"{first[0]}.{last}"


def make_guard_full_name():
    first, last = random_full_name()
    return f"{last},{first}"


def make_sia_licence_number():
    groups = [
        str(
            random.randint(
                1000,
                9999,
            )
        )
        for _ in range(4)
    ]
    return " ".join(groups)


def make_guard_licence_number():
    return str(
        random.randint(
            10000000,
            99999999,
        )
    )


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
                json.loads(line)
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


def remove_old_generated_records(
    records,
):
    cleaned = []

    for record in records:
        sample_id = record.get(
            "sample_id",
            ""
        )

        # keep original seed samples like
        # guard_001, sia_001, id_001
        if sample_id.startswith(
            "sia_"
        ):
            try:
                number = int(
                    sample_id.split("_")[1]
                )
                if number >= 2:
                    continue
            except Exception:
                pass

        if sample_id.startswith(
            "guard_"
        ):
            try:
                number = int(
                    sample_id.split("_")[1]
                )
                if number >= 2:
                    continue
            except Exception:
                pass

        cleaned.append(record)

    return cleaned


# ==========================================================
# IMAGE RENDERING
# ==========================================================

def render_sia_badge(
    image_path: Path,
    licence_number: str,
    full_name: str,
    expiry_date: str,
    issuer: str,
):
    width = 1000
    height = 600

    image = Image.new(
        "RGB",
        (width, height),
        color=(245, 248, 252),
    )

    draw = ImageDraw.Draw(
        image
    )

    title_font = load_font(36)
    label_font = load_font(24)
    value_font = load_font(32)
    small_font = load_font(20)

    # Card outline
    draw.rounded_rectangle(
        [(20, 20), (980, 580)],
        radius=20,
        outline=(40, 70, 100),
        width=4,
        fill=(250, 252, 255),
    )

    # Header
    draw.rectangle(
        [(20, 20), (980, 120)],
        fill=(216, 229, 245),
    )

    draw.text(
        (40, 45),
        "SECURITY INDUSTRY AUTHORITY",
        font=title_font,
        fill=(20, 40, 70),
    )

    draw.text(
        (40, 155),
        "LICENCE NUMBER",
        font=label_font,
        fill=(70, 70, 70),
    )
    draw.text(
        (40, 190),
        licence_number,
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (40, 280),
        "EXPIRES",
        font=label_font,
        fill=(70, 70, 70),
    )
    draw.text(
        (40, 315),
        date.fromisoformat(
            expiry_date
        ).strftime("%d %b %Y").upper(),
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (40, 410),
        "NAME",
        font=label_font,
        fill=(70, 70, 70),
    )
    draw.text(
        (40, 445),
        full_name,
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (700, 520),
        issuer,
        font=small_font,
        fill=(50, 50, 50),
    )

    image.save(
        image_path,
        format="JPEG",
        quality=95,
    )


def render_guard_license(
    image_path: Path,
    licence_number: str,
    full_name: str,
    issue_date: str,
    expiry_date: str,
    date_of_birth: str,
    issuer: str,
):
    width = 1200
    height = 700

    image = Image.new(
        "RGB",
        (width, height),
        color=(252, 252, 252),
    )

    draw = ImageDraw.Draw(
        image
    )

    title_font = load_font(40)
    section_font = load_font(24)
    value_font = load_font(32)
    small_font = load_font(22)

    # Outer card
    draw.rounded_rectangle(
        [(20, 20), (1180, 680)],
        radius=18,
        outline=(50, 60, 90),
        width=4,
        fill=(255, 255, 255),
    )

    # Header bar
    draw.rectangle(
        [(20, 20), (1180, 120)],
        fill=(220, 228, 242),
    )

    draw.text(
        (40, 40),
        "TEXAS PRIVATE SECURITY LICENSE",
        font=title_font,
        fill=(25, 40, 75),
    )

    draw.text(
        (60, 160),
        "PRINT DATE",
        font=section_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (240, 160),
        format_date_slash(
            date.fromisoformat(
                issue_date
            )
        ),
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 230),
        "LICENSE",
        font=section_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (240, 230),
        licence_number,
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 300),
        "EXPIRES",
        font=section_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (240, 300),
        format_date_slash(
            date.fromisoformat(
                expiry_date
            )
        ),
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 370),
        "DOB",
        font=section_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (240, 370),
        format_date_slash(
            date.fromisoformat(
                date_of_birth
            )
        ),
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 450),
        "NAME",
        font=section_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (240, 450),
        full_name,
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 540),
        f"ISSUED BY {issuer}",
        font=value_font,
        fill=(10, 10, 10),
    )

    draw.text(
        (60, 590),
        "PO BOX 4087",
        font=small_font,
        fill=(45, 45, 45),
    )

    draw.text(
        (60, 625),
        "AUSTIN, TX 78773",
        font=small_font,
        fill=(45, 45, 45),
    )

    image.save(
        image_path,
        format="JPEG",
        quality=95,
    )


# ==========================================================
# RECORD BUILDERS
# ==========================================================

def build_sia_record(
    sample_number: int,
):
    sample_id = (
        f"sia_{sample_number:03d}"
    )

    image_filename = (
        f"{sample_id}.jpg"
    )

    image_path = (
        SIA_DIR / image_filename
    )

    full_name = make_sia_full_name()
    licence_number = (
        make_sia_licence_number()
    )

    expiry_date = random_date(
        date(2020, 1, 1),
        date(2028, 12, 31),
    )

    issuer = (
        "Security Industry Authority"
    )

    render_sia_badge(
        image_path=image_path,
        licence_number=licence_number,
        full_name=full_name,
        expiry_date=format_date_iso(
            expiry_date
        ),
        issuer=issuer,
    )

    record = {
        "sample_id": sample_id,
        "image_path": str(
            image_path.as_posix()
        ),
        "document_type": "sia_badge",
        "fields": {
            "full_name": full_name,
            "licence_number": licence_number,
            "id_number": None,
            "expiry_date": format_date_iso(
                expiry_date
            ),
            "date_of_birth": None,
            "issue_date": None,
            "issuer": issuer,
        },
        "quality": "clean",
        "notes": "synthetic generated sample",
    }

    return record


def build_guard_record(
    sample_number: int,
):
    sample_id = (
        f"guard_{sample_number:03d}"
    )

    image_filename = (
        f"{sample_id}.jpg"
    )

    image_path = (
        GUARD_DIR / image_filename
    )

    full_name = make_guard_full_name()
    licence_number = (
        make_guard_licence_number()
    )

    issue_date = random_date(
        date(2024, 1, 1),
        date(2026, 12, 31),
    )

    expiry_date = (
        issue_date
        + timedelta(days=365)
    )

    birth_date = random_date(
        date(1970, 1, 1),
        date(2003, 12, 31),
    )

    issuer = "TX DPS"

    render_guard_license(
        image_path=image_path,
        licence_number=licence_number,
        full_name=full_name,
        issue_date=format_date_iso(
            issue_date
        ),
        expiry_date=format_date_iso(
            expiry_date
        ),
        date_of_birth=format_date_iso(
            birth_date
        ),
        issuer=issuer,
    )

    record = {
        "sample_id": sample_id,
        "image_path": str(
            image_path.as_posix()
        ),
        "document_type": "guard_license",
        "fields": {
            "full_name": full_name,
            "licence_number": licence_number,
            "id_number": None,
            "expiry_date": format_date_iso(
                expiry_date
            ),
            "date_of_birth": format_date_iso(
                birth_date
            ),
            "issue_date": format_date_iso(
                issue_date
            ),
            "issuer": issuer,
        },
        "quality": "clean",
        "notes": "synthetic generated sample",
    }

    return record


# ==========================================================
# MAIN
# ==========================================================

def main():
    random.seed(42)

    ensure_directories()

    existing_records = (
        load_existing_records()
    )

    existing_records = (
        remove_old_generated_records(
            existing_records
        )
    )

    generated_records = []

    # Generate 20 SIA:
    # sia_002 ... sia_021
    for i in range(
        2,
        2 + NUM_SIA_TO_GENERATE,
    ):
        generated_records.append(
            build_sia_record(i)
        )

    # Generate 20 Guard:
    # guard_002 ... guard_021
    for i in range(
        2,
        2 + NUM_GUARD_TO_GENERATE,
    ):
        generated_records.append(
            build_guard_record(i)
        )

    final_records = (
        existing_records
        + generated_records
    )

    save_records(
        final_records
    )

    sia_count = sum(
        1
        for record in final_records
        if record["document_type"]
        == "sia_badge"
    )

    guard_count = sum(
        1
        for record in final_records
        if record["document_type"]
        == "guard_license"
    )

    id_count = sum(
        1
        for record in final_records
        if record["document_type"]
        == "id_card"
    )

    print()
    print("=" * 70)
    print(
        "PHASE 6D — SYNTHETIC DATASET GENERATION"
    )
    print("=" * 70)

    print(
        f"Generated SIA samples:   {NUM_SIA_TO_GENERATE}"
    )
    print(
        f"Generated Guard samples: {NUM_GUARD_TO_GENERATE}"
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
        "Ground truth file updated:"
    )
    print(
        f"  {GROUND_TRUTH_PATH}"
    )

    print()
    print(
        "[PASS] Synthetic dataset generation complete."
    )
    print("=" * 70)


if __name__ == "__main__":
    main()