"""Initial schema uses a frozen, versioned snapshot, not evolving ORM metadata."""
from alembic import op
from packages.infrastructure.schema_v1 import metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata.create_all(bind=bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION saup_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'APPEND_ONLY_RECORD'; END; $$""")
        for table in ("audit_events", "supplier_price_history", "journals", "postings"):
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION saup_append_only()")
        op.execute("""CREATE FUNCTION saup_balanced_journal() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE total bigint; n integer; jid varchar;
        BEGIN
          IF TG_TABLE_NAME='journals' THEN jid=NEW.id; ELSE jid=NEW.journal_id; END IF;
          SELECT COALESCE(SUM(delta),0),COUNT(*) INTO total,n FROM postings WHERE journal_id=jid;
          IF total <> 0 OR n < 2 THEN RAISE EXCEPTION 'UNBALANCED_JOURNAL'; END IF;
          RETURN NEW;
        END; $$""")
        op.execute("CREATE CONSTRAINT TRIGGER postings_balanced AFTER INSERT ON postings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION saup_balanced_journal()")
        op.execute("CREATE CONSTRAINT TRIGGER journals_nonempty AFTER INSERT ON journals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION saup_balanced_journal()")
    elif bind.dialect.name == "sqlite":
        for table in ("audit_events", "supplier_price_history", "journals", "postings"):
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_RECORD'); END;")


def downgrade():
    bind = op.get_bind()
    metadata.drop_all(bind=bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION saup_append_only()")
        op.execute("DROP FUNCTION saup_balanced_journal()")
