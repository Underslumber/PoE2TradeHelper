from pathlib import Path
from html.parser import HTMLParser


class _VisibleTemplateTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"placeholder", "aria-label", "title"} and value:
                self.values.append(value)

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.values.append(value)


def test_best_operations_does_not_render_synthetic_market_chains() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "buildMarketChains" not in app_js
    assert "renderMarketChain" not in app_js
    assert "marketChains" not in app_js


def test_root_view_does_not_restore_cabinet_from_local_storage() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "localStorage.setItem(MAIN_VIEW_STORAGE_KEY" not in app_js
    assert "PUBLIC_MAIN_VIEWS.includes(storedView)" not in app_js
    assert "const storedView = localStorage.getItem(MAIN_VIEW_STORAGE_KEY)" not in app_js


def test_cabinet_view_is_not_persisted_in_url() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "state.mainView === 'market' || state.mainView === 'cabinet'" in app_js
    assert "params.delete('verified')" in app_js
    assert "params.delete('verify')" in app_js
    assert "params.delete('view')" in app_js
    assert "state.account.authenticated ? 'cabinet' : 'market'" not in app_js


def test_live_ui_keeps_navigation_when_static_reference_is_unavailable() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "LEAGUES_REFERENCE_TIMEOUT_MS" in app_js
    assert "STATIC_REFERENCE_TIMEOUT_MS" in app_js
    assert "fallbackTradeLeagues()" in app_js
    assert "fetchJsonWithTimeout('/api/trade/leagues', LEAGUES_REFERENCE_TIMEOUT_MS)" in app_js
    assert "fetchJsonWithTimeout('/api/trade/static', STATIC_REFERENCE_TIMEOUT_MS)" in app_js
    assert "fallbackStaticCategories()" in app_js
    assert "const leaguesLoadFailed = Boolean(leaguesResult.error) || !leaguesResponse?.ok || leaguesData.error" in app_js
    assert "const staticLoadFailed = Boolean(staticResult.error) || !staticResponse?.ok || staticData.error" in app_js
    assert "state.leagues = leaguesLoadFailed ? fallbackTradeLeagues()" in app_js
    assert "state.categories = staticLoadFailed ? fallbackStaticCategories()" in app_js
    assert "if (leaguesLoadFailed || staticLoadFailed)" in app_js


def test_live_ui_has_separate_base_tracking_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    template = (root / "app" / "web" / "templates" / "live.html").read_text(encoding="utf-8")
    i18n_js = (root / "app" / "web" / "static" / "i18n.js").read_text(encoding="utf-8")

    assert 'data-account-tab="bases"' in template
    assert 'id="base-pins-list"' in template
    assert "isBaseMarketPin" in app_js
    assert "data-base-track" in app_js
    assert "trackFocusedBaseMarket" in app_js
    assert "baseMarketIconMarkup" in app_js
    assert "baseMarketPriceText" in app_js
    assert "base-market-title-line" in app_js
    assert "if (state.mainView === 'lots') {\n    renderLotSubtabs();" in app_js
    assert "state.lotSubtab === 'bases'" in app_js
    assert "refreshBaseMarket(false)" in app_js
    assert "sellerLotsTab: 'Предметы'" in i18n_js
    assert "sellerLotsTitle: 'Предметы'" in i18n_js
    assert "baseTrackSaved: 'Основа добавлена в отслеживание.'" in i18n_js
    assert "baseMarketPricesPending: 'цены ожидают ответа trade2'" in i18n_js


def test_russian_ui_translates_internal_risk_flags() -> None:
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    i18n_js = (root / "app" / "web" / "static" / "i18n.js").read_text(encoding="utf-8")

    assert "riskFlagLabel" in app_js
    assert "executionQualityLabel" in app_js
    assert "item.execution.risk_flags.slice(0, 3).join(', ')" not in app_js
    assert "large_move_low_volume: t('riskLargeMoveLowVolume')" in app_js
    assert "low_volume: t('riskLowVolume')" in app_js
    assert "riskLargeMoveLowVolume: 'сильное движение цены при малом объеме'" in i18n_js
    assert "riskLowVolume: 'малый объем'" in i18n_js


def test_russian_ui_translates_internal_ai_enums() -> None:
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    i18n_js = (root / "app" / "web" / "static" / "i18n.js").read_text(encoding="utf-8")

    assert "riskLevelLabel(summary.overall_risk)" in app_js
    assert "dataQualityLabel(summary.data_quality)" in app_js
    assert "phaseLabel(summary.phase)" in app_js
    assert "confidenceLabel(signal.confidence)" in app_js
    assert "confidenceLabel(forecast.confidence)" in app_js
    assert "dataQualityFull: 'полное'" in i18n_js
    assert "phaseDay27: 'дни 2-7'" in i18n_js
    assert "if (tab === 'ops') loadActiveTrades()" not in app_js


def test_russian_i18n_values_do_not_show_internal_english_terms() -> None:
    i18n_js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "i18n.js").read_text(
        encoding="utf-8"
    )
    russian_block = i18n_js.split("\n  en: {", 1)[0]
    visible_values = "\n".join(part.split("'", 1)[0] for part in russian_block.split(": '")[1:])

    forbidden_fragments = [
        "Email",
        " email",
        "Currency",
        "priced",
        "stackable",
        "pasted",
        "recipe-сигналов",
        "price fixing",
        "rate limit",
        "chat id",
        "bot token",
        "Комиссия/spread",
        "Backend",
        "P/L",
        "JSON-контекст",
        "trade2/exchange",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in visible_values

    assert "Почта подтверждена" in visible_values
    assert "лоты с ценой выкупа" in visible_values
    assert "риск ценовой манипуляции" in visible_values


def test_russian_template_fallback_text_is_readable() -> None:
    template = (Path(__file__).resolve().parents[1] / "app" / "web" / "templates" / "live.html").read_text(
        encoding="utf-8"
    )
    parser = _VisibleTemplateTextParser()
    parser.feed(template)
    visible_values = "\n".join(parser.values)

    forbidden_fragments = [
        "Email",
        "Currency",
        "priced-",
        "build-enabling",
        "price fixing",
        "chat id",
        "Telegram chat",
        "JSON-контекст",
        "SQLite-базе",
        "trader",
        "Rarity: Rare",
        "Chart metric",
        "trade2/exchange",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in visible_values

    assert "Почта" in visible_values
    assert "лоты с ценой выкупа" in visible_values
    assert "структурированный контекст рынка" in visible_values
