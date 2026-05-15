from app.funpay_market import aggregate_funpay_offers, parse_funpay_chips_html


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
