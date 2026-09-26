"""Append-only operational receipts and bounded statement corrections."""
from alembic import op
import sqlalchemy as sa
from packages.infrastructure.schema_v5 import CLOSURE_TABLES, APPEND_ONLY_TABLES

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in CLOSURE_TABLES:
        table.create(bind, checkfirst=False)
    for table in APPEND_ONLY_TABLES:
        if bind.dialect.name == 'postgresql':
            op.execute(f'CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION saup_append_only()')
        elif bind.dialect.name == 'sqlite':
            for action in ('UPDATE', 'DELETE'):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_RECORD'); END")


def downgrade():
    bind = op.get_bind()
    for table in CLOSURE_TABLES:
        if bind.execute(sa.select(sa.func.count()).select_from(table)).scalar():
            raise RuntimeError('CLOSURE_DATA_PRESENT_DOWNGRADE_BLOCKED')
    for table in reversed(CLOSURE_TABLES):
        table.drop(bind, checkfirst=False)
