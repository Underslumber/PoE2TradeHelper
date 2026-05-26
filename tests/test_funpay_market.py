import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, FunpayRubOffer
import app.funpay_market as funpay_market
from app.funpay_market import (
    aggregate_funpay_offers,
    build_funpay_calendar_recommendations,
    build_funpay_rub_context,
    funpay_league_key,
    parse_funpay_chips_html,
    save_funpay_rub_snapshot,
)


def test_parse_funpay_chips_html_extracts_public_offer_rows():
    html = """
    <select name="server"><option value="12280">Fate of the Vaal</option></select>
    <select name="side"><option value="106">Божественные сферы</option></select>
    <div class="tc table-hover showcase-table">
      <a href="https://funpay.com/chips/offer?id=2485611-582-209-12280-106" class="tc-item" data-server="12280" data-side="106" data-online="1">
        <div class="tc-server hidden-xxs">Fate of the Vaal</div>
        <div class="tc-side hidden-xxs">Божественные сферы 🔥</div>
        <div class="media media-user online">
          <div class="avatar-photo" data-href="https://funpay.com/users/2485611/"></div>
          <div class="media-user-name">seller</div>
          <span class="rating-mini-count">1041</span>
        </div>
        <div class="tc-amount" data-s="400">400</div>
        <div class="tc-price"><div>12.5 <span class="unit">₽</span></div></div>
      </a>
    </div>
    """

    parsed = parse_funpay_chips_html(html)

    assert len(parsed["offers"]) == 1
    offer = parsed["offers"][0]
    assert offer["offer_id"] == "2485611-582-209-12280-106"
    assert offer["league"] == "Fate of the Vaal"
    assert offer["currency_name"] == "Божественные сферы 🔥"
    assert offer["trade_item_id"] == "divine"
    assert offer["seller_id"] == "2485611"
    assert offer["seller_name"] == "seller"
    assert offer["seller_reviews"] == 1041
    assert offer["seller_online"] is True
    assert offer["stock"] == 400
    assert offer["rub_per_unit"] == 12.5


def test_save_funpay_rub_snapshot_deduplicates_repeated_offer_ids():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    offer = {
        "offer_id": "2485611-582-209-12280-106",
        "offer_url": "https://funpay.com/chips/offer?id=2485611-582-209-12280-106",
        "league": "Fate of the Vaal",
        "league_id": "12280",
        "currency_name": "Божественные сферы",
        "side_id": "106",
        "trade_item_id": "divine",
        "seller_id": "2485611",
        "seller_name": "seller",
        "seller_reviews": 1041,
        "seller_online": True,
        "stock": 400,
        "rub_per_unit": 12.5,
    }
    parsed = {
        "source_url": "https://funpay.com/chips/209/",
        "servers": {"12280": "Fate of the Vaal"},
        "sides": {"106": "Божественные сферы"},
        "offers": [offer, {**offer, "rub_per_unit": 99.9}],
    }

    with Session(engine) as db:
        snapshot = save_funpay_rub_snapshot(db, parsed, created_ts=1779101864.895)
        rows = db.scalars(select(FunpayRubOffer)).all()

    assert snapshot.offer_count == 1
    assert len(rows) == 1
    assert rows[0].offer_id == "2485611-582-209-12280-106"
    assert rows[0].rub_per_unit == 12.5


def test_ensure_funpay_rub_snapshot_uses_saved_snapshot_without_live_refresh(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    parsed = {
        "source_url": "https://funpay.com/chips/209/",
        "servers": {"12280": "Fate of the Vaal"},
        "sides": {"106": "Божественные сферы"},
        "offers": [
            {
                "offer_id": "2485611-582-209-12280-106",
                "offer_url": "https://funpay.com/chips/offer?id=2485611-582-209-12280-106",
                "league": "Fate of the Vaal",
                "league_id": "12280",
                "currency_name": "Божественные сферы",
                "side_id": "106",
                "trade_item_id": "divine",
                "seller_id": "2485611",
                "seller_name": "seller",
                "seller_reviews": 1041,
                "seller_online": True,
                "stock": 400,
                "rub_per_unit": 12.5,
            }
        ],
    }

    async def fail_collect(db):
        raise AssertionError("unexpected live FunPay refresh")

    monkeypatch.setattr(funpay_market, "collect_funpay_rub_snapshot", fail_collect)
    with Session(engine) as db:
        saved = save_funpay_rub_snapshot(db, parsed, created_ts=1.0)
        snapshot, cached = asyncio.run(funpay_market.ensure_funpay_rub_snapshot(db, refresh=True))

    assert cached is True
    assert snapshot.id == saved.id


def test_ensure_funpay_rub_snapshot_does_not_collect_when_empty(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)

    async def fail_collect(db):
        raise AssertionError("unexpected live FunPay refresh")

    monkeypatch.setattr(funpay_market, "collect_funpay_rub_snapshot", fail_collect)
    with Session(engine) as db:
        snapshot, cached = asyncio.run(funpay_market.ensure_funpay_rub_snapshot(db, refresh=True))

    assert cached is False
    assert snapshot is None


def test_funpay_league_key_matches_trade2_league_names():
    assert funpay_league_key("Fate of the Vaal") == funpay_league_key("Fate of the Vaal")
    assert funpay_league_key("HC Fate of the Vaal") == funpay_league_key("Fate of the Vaal [Hardcore]")
    assert funpay_league_key("Standard") == funpay_league_key("[Standard]")
    assert funpay_league_key("Hardcore") == funpay_league_key("[Hardcore]")


def test_funpay_context_uses_trade2_league_mapping_for_funpay_rows():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    base_offer = {
        "offer_id": "offer-softcore",
        "offer_url": "https://funpay.com/chips/offer?id=offer-softcore",
        "league": "Fate of the Vaal",
        "league_id": "12280",
        "currency_name": "Божественные сферы",
        "side_id": "106",
        "trade_item_id": "divine",
        "seller_id": "seller-softcore",
        "seller_name": "softcore",
        "seller_reviews": 100,
        "seller_online": True,
        "stock": 100,
        "rub_per_unit": 10.0,
    }
    parsed = {
        "source_url": "https://funpay.com/chips/209/",
        "servers": {
            "12280": "Fate of the Vaal",
            "12281": "Fate of the Vaal [Hardcore]",
            "10980": "[Hardcore]",
            "10979": "[Standard]",
        },
        "sides": {"106": "Божественные сферы"},
        "offers": [
            base_offer,
            {
                **base_offer,
                "offer_id": "offer-hardcore-challenge",
                "league": "Fate of the Vaal [Hardcore]",
                "league_id": "12281",
                "seller_id": "seller-hardcore-challenge",
                "seller_name": "hardcore-challenge",
                "rub_per_unit": 20.0,
            },
            {
                **base_offer,
                "offer_id": "offer-standard",
                "league": "[Standard]",
                "league_id": "10979",
                "seller_id": "seller-standard",
                "seller_name": "standard",
                "rub_per_unit": 30.0,
            },
            {
                **base_offer,
                "offer_id": "offer-hardcore",
                "league": "[Hardcore]",
                "league_id": "10980",
                "seller_id": "seller-hardcore",
                "seller_name": "hardcore",
                "rub_per_unit": 40.0,
            },
        ],
    }

    with Session(engine) as db:
        snapshot = save_funpay_rub_snapshot(db, parsed, created_ts=1779101864.895)
        hardcore_challenge = build_funpay_rub_context(db, snapshot, league="HC Fate of the Vaal")
        standard = build_funpay_rub_context(db, snapshot, league="Standard")
        hardcore = build_funpay_rub_context(db, snapshot, league="Hardcore")

    assert hardcore_challenge["focus"]["league"] == "Fate of the Vaal [Hardcore]"
    assert hardcore_challenge["focus"]["market_price"] == 20.0
    assert hardcore_challenge["funpay_league"]["matched"] is True
    assert hardcore_challenge["funpay_league"]["matched_leagues"][0]["league_id"] == "12281"
    assert standard["focus"]["league"] == "[Standard]"
    assert standard["focus"]["market_price"] == 30.0
    assert hardcore["focus"]["league"] == "[Hardcore]"
    assert hardcore["focus"]["market_price"] == 40.0


def test_funpay_context_builds_history_only_for_target_currency(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    base_offer = {
        "offer_id": "offer-divine",
        "offer_url": "https://funpay.com/chips/offer?id=offer-divine",
        "league": "Fate of the Vaal",
        "league_id": "12280",
        "currency_name": "Божественные сферы",
        "side_id": "106",
        "trade_item_id": "divine",
        "seller_id": "seller-divine",
        "seller_name": "divine",
        "seller_reviews": 100,
        "seller_online": True,
        "stock": 100,
        "rub_per_unit": 10.0,
    }
    parsed = {
        "source_url": "https://funpay.com/chips/209/",
        "servers": {"12280": "Fate of the Vaal"},
        "sides": {"106": "Божественные сферы", "105": "Сферы возвышения"},
        "offers": [
            base_offer,
            {
                **base_offer,
                "offer_id": "offer-exalted",
                "currency_name": "Сферы возвышения",
                "side_id": "105",
                "trade_item_id": "exalted",
                "seller_id": "seller-exalted",
                "seller_name": "exalted",
                "rub_per_unit": 1.0,
            },
        ],
    }
    history_calls = []

    def fake_history_points(db, *, league, trade_item_id, since_ts, limit=500):
        history_calls.append(trade_item_id)
        return []

    monkeypatch.setattr(funpay_market, "_history_points", fake_history_points)
    with Session(engine) as db:
        snapshot = save_funpay_rub_snapshot(db, parsed, created_ts=1779101864.895)
        context = build_funpay_rub_context(db, snapshot, league="Fate of the Vaal", target_currency="divine")

    assert history_calls == ["divine"]
    assert set(context["by_currency"]) == {"divine", "exalted"}


def test_aggregate_funpay_offers_trims_price_outlier():
    class Offer:
        def __init__(self, price, stock, seller, online=True):
            self.rub_per_unit = price
            self.stock = stock
            self.seller_name = seller
            self.seller_id = ""
            self.offer_id = seller
            self.seller_online = online

    offers = [
        Offer(price, 10, f"seller-{index}", index % 2 == 0)
        for index, price in enumerate([10, 11, 12, 13, 14, 15, 16, 100], start=1)
    ]

    stats = aggregate_funpay_offers(offers)

    assert stats["best"] == 10
    assert stats["median"] == 13.5
    assert stats["trimmed_median"] == 13.5
    assert stats["market_price"] == 13
    assert stats["low_market_offers"] == 7
    assert stats["ignored_high_offers"] == 1
    assert stats["offers"] == 8
    assert stats["seller_count"] == 8
    assert stats["online_sellers"] == 4
    assert stats["listed_stock"] == 80


def test_aggregate_funpay_offers_uses_liquid_low_market():
    class Offer:
        def __init__(self, price, stock, seller):
            self.rub_per_unit = price
            self.stock = stock
            self.seller_name = seller
            self.seller_id = ""
            self.offer_id = seller
            self.seller_online = True

    offers = [
        Offer(3.67, 100_000, "cheap-big"),
        Offer(6.11, 997, "cheap-small"),
        Offer(9.98, 4_472, "low-a"),
        Offer(10.0, 2_900, "low-b"),
        Offer(18.33, 2_000, "expensive-a"),
        Offer(36.66, 22, "expensive-b"),
        Offer(149.08, 45, "stale-a"),
        Offer(611.0, 10_000, "stale-b"),
    ]

    stats = aggregate_funpay_offers(offers)

    assert stats["best"] == 3.67
    assert stats["low_market_offers"] == 4
    assert stats["ignored_high_offers"] == 4
    assert stats["low_market_ceiling"] < 11
    assert stats["market_price"] < 4.5


def test_funpay_calendar_recommendations_find_buy_and_sell_windows():
    base = datetime(2026, 5, 4, 9, tzinfo=timezone.utc)
    points = []
    for week in range(3):
        monday = base + timedelta(days=week * 7)
        wednesday = monday + timedelta(days=2)
        for hour, price in [(9, 10), (10, 11), (18, 16)]:
            ts = (monday + timedelta(hours=hour - 9)).timestamp()
            points.append({"hour_ts": ts, "market_price": price})
        for hour, price in [(9, 20), (20, 31), (21, 32)]:
            ts = (wednesday + timedelta(hours=hour - 9)).timestamp()
            points.append({"hour_ts": ts, "market_price": price})

    recommendations = build_funpay_calendar_recommendations(points)

    expected_buy_weekday = datetime.fromtimestamp(points[0]["hour_ts"], tz=timezone.utc).astimezone().weekday()
    expected_sell_weekday = datetime.fromtimestamp(points[-1]["hour_ts"], tz=timezone.utc).astimezone().weekday()
    expected_buy_hour = datetime.fromtimestamp(points[0]["hour_ts"], tz=timezone.utc).astimezone().hour
    expected_sell_hour = datetime.fromtimestamp(points[-1]["hour_ts"], tz=timezone.utc).astimezone().hour

    assert recommendations["buy"]["weekday"] == expected_buy_weekday
    assert recommendations["sell"]["weekday"] == expected_sell_weekday
    assert any(item["start_hour"] <= expected_buy_hour < item["end_hour"] for item in recommendations["buy"]["hour_intervals"])
    assert any(item["start_hour"] <= expected_sell_hour < item["end_hour"] for item in recommendations["sell"]["hour_intervals"])
    assert recommendations["confidence"] == "insufficient"
