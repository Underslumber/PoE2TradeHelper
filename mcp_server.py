import os
import sys
import asyncio
import time
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

import httpx
from app.trade.api_client import PoeTradeClient

# Импортируем FastMCP из mcp.server.fastmcp
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    # Fallback на локальную реализацию, если mcp не установлен
    class FastMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = {}
        
        def tool(self, *args, **kwargs):
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator
        
        def run(self):
            print(f"MCP Server '{self.name}' is running in fallback mode.")
            print("Available tools:", ", ".join(self.tools.keys()))
            print("Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down MCP server...")

# Конфигурация
UA = os.environ.get("USER_AGENT", "poe2-trade-helper/0.1 (contact: set-USER_AGENT-in-env)")
COOL = int(os.environ.get("RATE_COOLDOWN_MS", "250"))
POE_API_BASE = "https://api.pathofexile.com"  # официальный API
TRADE_BASE = "https://www.pathofexile.com/api/trade2"  # веб-API PoE2
TRADE_RU_BASE = "https://ru.pathofexile.com/api/trade2"  # тот же trade2 с русскими терминами

# Настройка логирования
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Создаем экземпляр MCP-сервера
mcp = FastMCP("poe2-trade-helper")


def error_response(error: Exception) -> Dict[str, Any]:
    """Возвращает понятную ошибку без секретов и с реальным HTTP status code, если он есть."""
    status_code = 500
    response = getattr(error, "response", None)
    if response is not None:
        status_code = response.status_code
    elif hasattr(error, "status_code"):
        status_code = error.status_code

    return {"error": str(error), "status_code": status_code}


def log_request(method: str, url: str) -> None:
    """Логирует внешний вызов без тела запроса и без секретов."""
    logger.info("PoE API request: %s %s", method, url)


def auth_headers() -> Dict[str, str]:
    """Создает заголовки для аутентифицированных запросов к API PoE."""
    access_token = os.environ.get("POE_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError("POE_ACCESS_TOKEN is not set in .env")
    return {
        "User-Agent": UA,
        "Authorization": f"Bearer {access_token}",
    }


def ua_headers() -> Dict[str, str]:
    """Создает заголовки с User-Agent для запросов."""
    return {"User-Agent": UA}

# --- ОФИЦИАЛЬНЫЙ API: Currency Exchange (часовые сводки) ---
@mcp.tool()
async def get_currency_exchange(
    realm: str = "poe2",
    hour: Optional[int] = None
) -> Dict[str, Any]:
    """
    Получает часовые сводки обмена валют (исторические; текущий час недоступен).
    
    Параметры:
      realm: 'poe2' | 'xbox' | 'sony'
      hour: unix timestamp, округлённый к часу; если None — первая страница истории
    """
    path = f"/currency-exchange/{realm}" + (f"/{hour}" if hour else "")
    try:
        log_request("GET", f"{POE_API_BASE}{path}")
        async with httpx.AsyncClient(base_url=POE_API_BASE, headers=auth_headers(), timeout=30) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

# --- ОФИЦИАЛЬНЫЙ API: Персонажи (PoE2) ---
@mcp.tool()
async def list_characters(realm: str = "poe2") -> Dict[str, Any]:
    """
    Получает список персонажей аккаунта.
    Требуется OAuth scope: account:characters
    """
    path = f"/character/{'poe2' if realm == 'poe2' else realm}"
    try:
        log_request("GET", f"{POE_API_BASE}{path}")
        async with httpx.AsyncClient(base_url=POE_API_BASE, headers=auth_headers(), timeout=30) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def get_character(name: str, realm: str = "poe2") -> Dict[str, Any]:
    """
    Получает детальную информацию о персонаже по имени.
    """
    path = f"/character/poe2/{name}" if realm == "poe2" else f"/character/{name}"
    try:
        log_request("GET", f"{POE_API_BASE}{path}")
        async with httpx.AsyncClient(base_url=POE_API_BASE, headers=auth_headers(), timeout=30) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

# --- ВЕБ-API ТРЕЙДА (недокументированный): data/search/fetch/exchange ---
@mcp.tool()
async def trade_leagues() -> Dict[str, Any]:
    """Получает список лиг PoE2, доступных на официальном trade2 сайте."""
    try:
        leagues = await PoeTradeClient.get_trade_leagues()
        return {"result": leagues}
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_static_data(locale: str = "en") -> Dict[str, Any]:
    """Получает справочник trade2: валюты, фрагменты, катализаторы и другие exchange-идентификаторы."""
    try:
        en_res, ru_res = await PoeTradeClient.get_trade_static()
        return ru_res if locale.lower().startswith("ru") else en_res
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_search(league: str, query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ищет предметы на торговой площадке PoE2.
    """
    try:
        return await PoeTradeClient.post_search(league, query)
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_fetch(ids: List[str], query_id: str) -> List[Dict[str, Any]]:
    """
    Получает детальную информацию о предметах по их ID.
    """
    try:
        return await PoeTradeClient.fetch_trade_items(ids, query_id)
    except Exception as e:
        return [error_response(e)]

@mcp.tool()
async def trade_exchange(
    league: str, 
    have: List[str], 
    want: List[str], 
    status: str = "online"
) -> Dict[str, Any]:
    """
    Ищет обменные предложения валют.
    """
    try:
        return await PoeTradeClient.post_exchange(league, have, want, status)
    except Exception as e:
        return error_response(e)

if __name__ == "__main__":
    # The MCP stdio transport owns stdout for JSON-RPC framing; any banner
    # output must go to stderr or it corrupts the protocol stream.
    print("Запуск MCP-сервера для PoE2 Trade Helper...", file=sys.stderr)
    print(f"User-Agent: {UA}", file=sys.stderr)
    print("Доступные инструменты:", file=sys.stderr)
    print("- trade_leagues()", file=sys.stderr)
    print("- trade_static_data()", file=sys.stderr)
    print("- get_currency_exchange(realm, hour=None)", file=sys.stderr)
    print("- list_characters(realm='poe2')", file=sys.stderr)
    print("- get_character(name, realm='poe2')", file=sys.stderr)
    print("- trade_search(league, query)", file=sys.stderr)
    print("- trade_fetch(ids, query_id)", file=sys.stderr)
    print("- trade_exchange(league, have, want, status='online')", file=sys.stderr)
    print("\nДля выхода нажмите Ctrl+C", file=sys.stderr)

    # Запускаем MCP-сервер
    mcp.run()
