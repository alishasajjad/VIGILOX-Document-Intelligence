"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

READ THIS BEFORE APPLYING
----------------------------------------------------------
If this file was produced by --autogenerate, check it against
what you actually changed. Autogenerate reports a RENAME as a
drop plus an add, and applying that deletes the column's data.

Then write the downgrade. An upgrade with no working downgrade
is a one-way door.
"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
