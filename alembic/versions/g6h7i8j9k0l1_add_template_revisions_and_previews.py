"""add template lifecycle, revisions, and preview sessions

Revision ID: g6h7i8j9k0l1
Revises: f5g6h7i8j9k0
Create Date: 2026-07-29 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g6h7i8j9k0l1"
down_revision: Union[str, None] = "f5g6h7i8j9k0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    template_status = postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="templatestatus",
    )
    template_status.create(bind, checkfirst=True)
    existing_template_status = postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="templatestatus",
        create_type=False,
    )

    op.create_table(
        "template_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "template_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["invitation_templates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "revision_number",
            name="uq_template_revisions_template_number",
        ),
    )
    op.create_index(
        "ix_template_revisions_template_id",
        "template_revisions",
        ["template_id"],
    )

    op.add_column(
        "invitation_templates",
        sa.Column("status", existing_template_status, nullable=True),
    )
    op.add_column(
        "invitation_templates",
        sa.Column(
            "latest_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "invitation_templates",
        sa.Column(
            "published_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "invitation_templates",
        sa.Column("latest_revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "invitation_templates",
        sa.Column("published_revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "invitation_templates",
        sa.Column("has_unpublished_changes", sa.Boolean(), nullable=True),
    )

    revision_table = sa.table(
        "template_revisions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("template_id", postgresql.UUID(as_uuid=True)),
        sa.column("revision_number", sa.Integer()),
        sa.column("config", postgresql.JSONB()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by_id", sa.Integer()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("published_by_id", sa.Integer()),
    )
    templates = bind.execute(
        sa.text(
            """
            SELECT id, config, created_at, created_by_id
            FROM invitation_templates
            """
        )
    ).mappings()
    for template in templates:
        revision_id = uuid.uuid4()
        created_at = template["created_at"]
        bind.execute(
            revision_table.insert().values(
                id=revision_id,
                template_id=template["id"],
                revision_number=1,
                config=template["config"] or {},
                created_at=created_at,
                created_by_id=template["created_by_id"],
                published_at=created_at,
                published_by_id=template["created_by_id"],
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE invitation_templates
                SET status = 'published',
                    latest_revision_id = :revision_id,
                    published_revision_id = :revision_id,
                    latest_revision_number = 1,
                    published_revision_number = 1,
                    has_unpublished_changes = false
                WHERE id = :template_id
                """
            ),
            {
                "revision_id": revision_id,
                "template_id": template["id"],
            },
        )

    op.alter_column(
        "invitation_templates",
        "status",
        existing_type=existing_template_status,
        nullable=False,
        server_default="draft",
    )
    op.alter_column(
        "invitation_templates",
        "latest_revision_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "invitation_templates",
        "latest_revision_number",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    op.alter_column(
        "invitation_templates",
        "has_unpublished_changes",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("false"),
    )

    op.create_table(
        "template_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "template_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "revision_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=True),
        sa.Column("sample_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["invitation_templates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["template_revisions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_template_previews_template_id",
        "template_previews",
        ["template_id"],
    )
    op.create_index(
        "ix_template_previews_expires_at",
        "template_previews",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_template_previews_expires_at",
        table_name="template_previews",
    )
    op.drop_index(
        "ix_template_previews_template_id",
        table_name="template_previews",
    )
    op.drop_table("template_previews")

    op.drop_column("invitation_templates", "has_unpublished_changes")
    op.drop_column("invitation_templates", "published_revision_number")
    op.drop_column("invitation_templates", "latest_revision_number")
    op.drop_column("invitation_templates", "published_revision_id")
    op.drop_column("invitation_templates", "latest_revision_id")
    op.drop_column("invitation_templates", "status")

    op.drop_index(
        "ix_template_revisions_template_id",
        table_name="template_revisions",
    )
    op.drop_table("template_revisions")
    postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="templatestatus",
    ).drop(op.get_bind(), checkfirst=True)
