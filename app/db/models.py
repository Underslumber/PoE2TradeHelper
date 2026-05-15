from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(String, primary_key=True)
    created_at = Column(String, nullable=False)
    league = Column(String, nullable=False)
    category = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    method = Column(String, nullable=False)


class Row(Base):
    __tablename__ = "rows"

    snapshot_id = Column(String, primary_key=True)
    row_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    icon_url = Column(String)
    icon_local = Column(String)
    columns_json = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"

    snapshot_id = Column(String, primary_key=True)
    kind = Column(String, primary_key=True)
    url = Column(String)
    path = Column(String, primary_key=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    email_verified_at = Column(String)
    email_verification_token = Column(String, unique=True, index=True)
    email_verification_sent_at = Column(String)
    is_admin = Column(Integer, nullable=False, default=0)
    can_use_ai = Column(Integer, nullable=False, default=0)
    fiat_rub_enabled = Column(Integer, nullable=False, default=0)
    account_target_currency = Column(String, nullable=False, default="exalted")
    created_at = Column(String, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    feature = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False, index=True)
    success = Column(Integer, nullable=False, default=0)
    status_code = Column(Integer)
    duration_ms = Column(Integer)


class PinnedPosition(Base):
    __tablename__ = "pinned_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "league", "category", "item_id", name="uq_user_pin_item"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    league = Column(String, nullable=False)
    category = Column(String, nullable=False)
    item_id = Column(String, nullable=False)
    item_name = Column(String, nullable=False)
    item_name_ru = Column(String)
    icon_url = Column(String)
    target_currency = Column(String, nullable=False)
    last_price = Column(Float)
    last_source = Column(String)
    note = Column(Text)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class TradeJournalEntry(Base):
    __tablename__ = "trade_journal_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pin_id = Column(Integer, ForeignKey("pinned_positions.id"))
    league = Column(String, nullable=False)
    category = Column(String, nullable=False)
    item_id = Column(String, nullable=False)
    item_name = Column(String, nullable=False)
    item_name_ru = Column(String)
    icon_url = Column(String)
    quantity = Column(Float, nullable=False, default=1.0)
    entry_price = Column(Float, nullable=False)
    entry_currency = Column(String, nullable=False)
    entry_at = Column(String, nullable=False)
    benchmark_currency = Column(String, default="divine")
    entry_benchmark_price = Column(Float)
    exit_price = Column(Float)
    exit_currency = Column(String)
    exit_at = Column(String)
    exit_benchmark_price = Column(Float)
    status = Column(String, nullable=False, default="open")
    notes = Column(Text)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class TelegramNotificationRule(Base):
    __tablename__ = "telegram_notification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pin_id = Column(Integer, ForeignKey("pinned_positions.id"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    threshold_value = Column(Float)
    enabled = Column(Integer, nullable=False, default=1)
    last_price = Column(Float)
    last_triggered_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class MarketHistory(Base):
    __tablename__ = "market_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    target = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="any", index=True)
    source = Column(String)
    item_id = Column(String, nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Float)
    offers = Column(Integer)
    change = Column(Float)
    sparkline_json = Column(Text)
    sparkline_kind = Column(String)
    max_volume_currency = Column(String)
    max_volume_rate = Column(Float)
    query_ids_json = Column(Text)
    errors_json = Column(Text)
    timestamp = Column(Float, nullable=False, index=True)
    created_at = Column(String, nullable=False)


class FunpayRubSnapshot(Base):
    __tablename__ = "funpay_rub_snapshots"

    id = Column(String, primary_key=True)
    created_at = Column(String, nullable=False)
    created_ts = Column(Float, nullable=False, index=True)
    source_url = Column(String, nullable=False)
    offer_count = Column(Integer, nullable=False, default=0)
    mapped_offer_count = Column(Integer, nullable=False, default=0)
    raw_json = Column(Text)


class FunpayRubOffer(Base):
    __tablename__ = "funpay_rub_offers"

    snapshot_id = Column(String, ForeignKey("funpay_rub_snapshots.id"), primary_key=True)
    offer_id = Column(String, primary_key=True)
    league = Column(String, nullable=False, index=True)
    league_id = Column(String, index=True)
    currency_name = Column(String, nullable=False)
    side_id = Column(String, nullable=False, index=True)
    trade_item_id = Column(String, index=True)
    seller_id = Column(String)
    seller_name = Column(String)
    seller_reviews = Column(Integer)
    seller_online = Column(Integer, nullable=False, default=0)
    stock = Column(Float)
    rub_per_unit = Column(Float, nullable=False)
    raw_json = Column(Text)


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    key = Column(String, primary_key=True)
    data_json = Column(Text, nullable=False)
    created_ts = Column(Float, nullable=False)
    expires_ts = Column(Float, nullable=False, index=True)
