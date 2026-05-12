import os
import asyncio
import time
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import quote
from dotenv import load_dotenv
import httpx

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

# Загрузка переменных окружения
load_dotenv()

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
    url = f"{TRADE_BASE}/data/leagues"
    try:
        log_request("GET", url)
        async with httpx.AsyncClient(headers=ua_headers(), timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_static_data(locale: str = "en") -> Dict[str, Any]:
    """Получает справочник trade2: валюты, фрагменты, катализаторы и другие exchange-идентификаторы."""
    base = TRADE_RU_BASE if locale.lower().startswith("ru") else TRADE_BASE
    url = f"{base}/data/static"
    try:
        log_request("GET", url)
        async with httpx.AsyncClient(headers=ua_headers(), timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_search(league: str, query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ищет предметы на торговой площадке PoE2.
    
    Параметры:
      league: название лиги (например, 'Affliction')
      query: словарь с параметрами поиска
    """
    url = f"{TRADE_BASE}/search/poe2/{quote(league, safe='')}"
    try:
        log_request("POST", url)
        async with httpx.AsyncClient(headers={"User-Agent": UA, "Content-Type": "application/json"}, timeout=30) as client:
            response = await client.post(url, json={"query": query, "sort": {"price": "asc"}})
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

@mcp.tool()
async def trade_fetch(ids: List[str], query_id: str) -> List[Dict[str, Any]]:
    """
    Получает детальную информацию о предметах по их ID.
    
    Параметры:
      ids: список ID предметов
      query_id: ID запроса из trade_search
    """
    results = []
    try:
        async with httpx.AsyncClient(headers=ua_headers(), timeout=30) as client:
            # Обрабатываем по 20 ID за раз
            for i in range(0, len(ids), 20):
                chunk = ",".join(ids[i:i+20])
                url = f"{TRADE_BASE}/fetch/{chunk}?query={quote(query_id, safe='')}"
                log_request("GET", url)
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                results.extend(data.get("result", []))
                
                # Соблюдаем задержку между запросами
                if i + 20 < len(ids):
                    await asyncio.sleep(COOL / 1000)
        
        return results
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
    
    Параметры:
      league: название лиги
      have: список ID валют, которые есть
      want: список ID валют, которые нужны
      status: статус игроков ('online' или 'any')
    """
    url = f"{TRADE_BASE}/exchange/poe2/{quote(league, safe='')}"
    body = {
        "exchange": {
            "have": have,
            "want": want,
            "status": {"option": status}
        }
    }
    
    try:
        log_request("POST", url)
        async with httpx.AsyncClient(
            headers={"User-Agent": UA, "Content-Type": "application/json"}, 
            timeout=30
        ) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return error_response(e)

if __name__ == "__main__":
    print("Запуск MCP-сервера для PoE2 Trade Helper...")
    print(f"User-Agent: {UA}")
    print("Доступные инструменты:")
    print("- trade_leagues()")
    print("- trade_static_data()")
    print("- get_currency_exchange(realm, hour=None)")
    print("- list_characters(realm='poe2')")
    print("- get_character(name, realm='poe2')")
    print("- trade_search(league, query)")
    print("- trade_fetch(ids, query_id)")
    print("- trade_exchange(league, have, want, status='online')")
    print("\nДля выхода нажмите Ctrl+C")
    
    # Запускаем MCP-сервер
    mcp.run()
