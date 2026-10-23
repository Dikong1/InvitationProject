"""add wishes (public messages approved by the host) to rsvp_responses

Revision ID: h7i8j9k0l1m2
Revises: g6h7i8j9k0l1
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h7i8j9k0l1m2"
down_revision: Union[str, None] = "g6h7i8j9k0l1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rsvp_responses",
        sa.Column("wish_public", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "rsvp_responses",
        sa.Column("wish_visible", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_rsvp_responses_invitation_wish_visible",
        "rsvp_responses",
        ["invitation_id", "wish_visible"],
    )


def downgrade() -> None:
    op.drop_index("ix_rsvp_responses_invitation_wish_visible", table_name="rsvp_responses")
    op.drop_column("rsvp_responses", "wish_visible")
    op.drop_column("rsvp_responses", "wish_public")
