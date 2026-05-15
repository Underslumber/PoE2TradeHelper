import asyncio

from app.trade import api_client


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_make_retry_returns_fresh_instance():
    assert api_client._make_retry() is not api_client._make_retry()


def test_poe_trade_client_static_data_is_cached(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, *args, **kwargs):
            calls.append(url)
            if "ru.pathofexile.com" in url:
                return FakeResponse({"result": [{"id": "Currency", "entries": [{"id": "chaos", "text": "Сфера хаоса"}]}]})
            return FakeResponse({"result": [{"id": "Currency", "entries": [{"id": "chaos", "text": "Chaos Orb"}]}]})

    monkeypatch.setattr(api_client, "_trade_static_cache", None)
    monkeypatch.setattr(api_client.httpx, "AsyncClient", FakeAsyncClient)

    first = asyncio.run(api_client.PoeTradeClient.get_trade_static())
    second = asyncio.run(api_client.PoeTradeClient.get_trade_static())

    assert len(calls) == 2
    assert first == second
    assert first[0]["result"][0]["entries"][0]["text"] == "Chaos Orb"
    assert first[1]["result"][0]["entries"][0]["text"] == "Сфера хаоса"
