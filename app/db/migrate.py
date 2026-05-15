import os

from sqlalchemy import select

from app.account import hash_password, normalize_email, normalize_username, now_iso
from app.db.models import Base, CacheEntry, MarketHistory, User
from app.db.session import engine


USER_COLUMNS = {
    "email": "VARCHAR",
    "email_verified_at": "VARCHAR",
    "email_verification_token": "VARCHAR",
    "email_verification_sent_at": "VARCHAR",
    "is_admin": "INTEGER DEFAULT 0",
    "can_use_ai": "INTEGER DEFAULT 0",
    "fiat_rub_enabled": "INTEGER DEFAULT 0",
    "account_target_currency": "VARCHAR DEFAULT 'exalted'",
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

MARKET_HISTORY_COLUMNS = {
    "status": "VARCHAR DEFAULT 'any'",
    "source": "VARCHAR",
    "change": "FLOAT",
    "sparkline_json": "TEXT",
    "sparkline_kind": "VARCHAR",
    "max_volume_currency": "VARCHAR",
    "max_volume_rate": "FLOAT",
    "query_ids_json": "TEXT",
    "errors_json": "TEXT",
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
        conn.exec_driver_sql("UPDATE users SET is_admin = 0 WHERE is_admin IS NULL")
        conn.exec_driver_sql("UPDATE users SET can_use_ai = 0 WHERE can_use_ai IS NULL")
        conn.exec_driver_sql("UPDATE users SET fiat_rub_enabled = 0 WHERE fiat_rub_enabled IS NULL")
        conn.exec_driver_sql("UPDATE users SET account_target_currency = 'exalted' WHERE account_target_currency IS NULL OR account_target_currency = ''")


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


def _migrate_market_history_table() -> None:
    _add_missing_columns("market_history", MARKET_HISTORY_COLUMNS)
    if not _table_columns("market_history"):
        return
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE market_history SET status = 'any' WHERE status IS NULL OR status = ''")


def _ensure_bootstrap_admin() -> None:
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        return
    username = normalize_username(os.environ.get("ADMIN_USERNAME", "admin")) or "admin"
    email = normalize_email(os.environ.get("ADMIN_EMAIL", "admin@example.local")) or "admin@example.local"
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "Admin").strip() or "Admin"
    with get_session_for_migration() as db:
        user = db.scalars(select(User).where((User.username == username) | (User.email == email))).first()
        if not user:
            user = User(
                username=username,
                email=email,
                display_name=display_name,
                password_hash=hash_password(password),
                email_verified_at=now_iso(),
                created_at=now_iso(),
            )
            db.add(user)
        else:
            user.username = username
            user.email = email
            user.display_name = display_name
            user.password_hash = hash_password(password)
            user.email_verified_at = user.email_verified_at or now_iso()
        user.is_admin = 1
        user.can_use_ai = 1
        user.email_verification_token = None
        user.email_verification_sent_at = None
        db.commit()


def _ensure_existing_admin() -> None:
    with get_session_for_migration() as db:
        existing_admin = db.scalars(select(User).where(User.is_admin == 1)).first()
        if existing_admin:
            return
        first_user = db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())).first()
        if not first_user:
            return
        first_user.is_admin = 1
        first_user.can_use_ai = 1
        db.commit()


def get_session_for_migration():
    from app.db.session import get_session

    return get_session()


def migrate() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_users_table()
    _migrate_trade_journal_table()
    _migrate_market_history_table()
    from app.db.migrate_jsonl_to_sqlite import migrate_history

    migrate_history(verbose=False)
    _ensure_bootstrap_admin()
    _ensure_existing_admin()


if __name__ == "__main__":
    migrate()
