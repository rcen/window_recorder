"""Add local_date column to activity table

Revision ID: add_local_date_column
Revises: de33c7c0bcf3
Create Date: 2025-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_local_date_column'
down_revision: Union[str, Sequence[str], None] = 'de33c7c0bcf3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Try to add local_date to both possible table names for compatibility
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if 'activity' in tables:
        op.add_column('activity', sa.Column('local_date', sa.String(length=10), nullable=True))
    if 'activities' in tables:
        op.add_column('activities', sa.Column('local_date', sa.String(length=10), nullable=True))

def downgrade() -> None:
    # Remove local_date from both possible table names
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if 'activity' in tables:
        op.drop_column('activity', 'local_date')
    if 'activities' in tables:
        op.drop_column('activities', 'local_date')
