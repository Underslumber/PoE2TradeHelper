from app.db.models import Base
from app.db.session import engine


USER_COLUMNS = {
    "email": "VARCHAR",
    "email_verified_at": "VARCHAR",
    "email_verification_token": "VARCHAR",
    "email_verification_sent_at": "VARCHAR",
}

USER_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_verification_token ON users (email_verification_token)",
]

TRADE_JOURNAL_COLUMNS = {
    "benchmark_currency": "VARCHAR",
    "entry_benchmark_price": "FLOAT",
    "exit_benchmark_price": "FLOAT",
}


def _table_columns(table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").mappings().all()
    return {str(row["name"]) for row in rows}


def _add_missing_columns(table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(table)
    if not existing:
        return
    with engine.begin() as conn:
        for name, column_type in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")


def _migrate_users_table() -> None:
    columns = _table_columns("users")
    if not columns:
        return
    _add_missing_columns("users", USER_COLUMNS)
    with engine.begin() as conn:
        for statement in USER_INDEXES:
            conn.exec_driver_sql(statement)


def _migrate_trade_journal_table() -> None:
    _add_missing_columns("trade_journal_entries", TRADE_JOURNAL_COLUMNS)
    if not _table_columns("trade_journal_entries"):
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE trade_journal_entries "
            "SET benchmark_currency = 'divine' "
            "WHERE benchmark_currency IS NULL OR benchmark_currency = ''"
        )


def migrate() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_users_table()
    _migrate_trade_journal_table()


if __name__ == "__main__":
    migrate()
