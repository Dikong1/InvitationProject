"""add invited guests with personal link tokens

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "i8j9k0l1m2n3"
down_revision: Union[str, None] = "h7i8j9k0l1m2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rsvp_invitees",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rsvp_invitees_invitation_id", "rsvp_invitees", ["invitation_id"])
    op.create_index("ix_rsvp_invitees_token", "rsvp_invitees", ["token"], unique=True)

    op.add_column(
        "rsvp_responses",
        sa.Column("invitee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_rsvp_responses_invitee_id",
        "rsvp_responses",
        "rsvp_invitees",
        ["invitee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_rsvp_responses_invitee_id",
        "rsvp_responses",
        ["invitee_id"],
        unique=True,
        postgresql_where=sa.text("invitee_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_rsvp_responses_invitee_id", table_name="rsvp_responses")
    op.drop_constraint("fk_rsvp_responses_invitee_id", "rsvp_responses", type_="foreignkey")
    op.drop_column("rsvp_responses", "invitee_id")
    op.drop_index("ix_rsvp_invitees_token", table_name="rsvp_invitees")
    op.drop_index("ix_rsvp_invitees_invitation_id", table_name="rsvp_invitees")
    op.drop_table("rsvp_invitees")
