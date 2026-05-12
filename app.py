from flask import Flask, render_template, jsonify
import os
import time
import json
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Tuple
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
import threading
import http.client

# Настройка логирования
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Создаем форматтер
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Обработчик для вывода в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)

# Обработчик для записи в файл лога
file_handler = logging.FileHandler('poe2_trade_helper.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(log_formatter)

# Обработчик для отладочного лога
debug_file_handler = logging.FileHandler('debug.log', encoding='utf-8')
debug_file_handler.setLevel(logging.DEBUG)
debug_file_handler.setFormatter(log_formatter)

# Добавляем обработчики к корневому логгеру
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
root_logger.addHandler(debug_file_handler)

# Настройка логирования для requests и urllib3
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('http.client').setLevel(logging.WARNING)

# Удаляем стандартные обработчики, чтобы избежать дублирования
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Добавляем наши обработчики
logging.root.addHandler(file_handler)
logging.root.addHandler(console_handler)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

app = Flask(__name__)

# Конфигурация
CACHE_DURATION = 300  # 5 минут в секундах
POE_API_URL = "https://poe.ninja/api/data/currencyoverview"
LEAGUE = "Affliction"  # TODO: Обновлять автоматически

# ID валют в официальном API PoE
CURRENCY_IDS = {
    "liquid_ire": "Liquid IRE",
    "liquid_guilt": "Liquid GUILT",
    "liquid_disgust": "Liquid DISGUST",
    "liquid_greed": "Liquid GREED",
    "liquid_paranoia": "Liquid PARANOIA",
    "liquid_envy": "Liquid ENVY",
    "liquid_despair": "Liquid DESPAIR",
    "liquid_fear": "Liquid FEAR",
    "liquid_suffering": "Liquid SUFFERING",
    "liquid_isolation": "Liquid ISOLATION"
}

# Базовая информация о валютах
CURRENCIES = [
    {"id": "liquid_ire", "name_ru": "Жидкий гнев", "name_en": "Liquid Ire"},
    {"id": "liquid_guilt", "name_ru": "Жидкая вина", "name_en": "Liquid Guilt"},
    {"id": "liquid_disgust", "name_ru": "Жидкое отвращение", "name_en": "Liquid Disgust"},
    {"id": "liquid_greed", "name_ru": "Жидкая жадность", "name_en": "Liquid Greed"},
    {"id": "liquid_paranoia", "name_ru": "Жидкая паранойя", "name_en": "Liquid Paranoia"},
    {"id": "liquid_envy", "name_ru": "Жидкая зависть", "name_en": "Liquid Envy"},
    {"id": "liquid_despair", "name_ru": "Жидкое отчаяние", "name_en": "Liquid Despair"},
    {"id": "liquid_fear", "name_ru": "Жидкий страх", "name_en": "Liquid Fear"},
    {"id": "liquid_suffering", "name_ru": "Жидкое страдание", "name_en": "Liquid Suffering"},
    {"id": "liquid_isolation", "name_ru": "Жидкое отчуждение", "name_en": "Liquid Isolation"},
]

# Глобальные переменные
CACHE_FILE = 'Answer_API.txt'
CACHE_DURATION = 300  # 5 минут в секундах

# Глобальное хранилище данных
currency_data = {
    'currencies': [],
    'last_updated': None,
    'next_update': None,
    'league': None,
    'status': 'idle'  # 'idle', 'updating', 'error'
}

def save_to_cache(data):
    """Сохраняет данные в кэш-файл"""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'currencies': data['currencies'],
                'last_updated': data['last_updated'].isoformat() if data['last_updated'] else None,
                'league': data['league']
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"Данные успешно сохранены в кэш: {CACHE_FILE}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении в кэш: {e}")
        return False

def load_from_cache():
    """Загружает данные из кэш-файла"""
    if not os.path.exists(CACHE_FILE):
        logger.info("Кэш-файл не найден")
        return None
        
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Преобразуем строку даты обратно в объект datetime
        if 'last_updated' in data and data['last_updated']:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
            
        logger.info(f"Данные успешно загружены из кэша (обновлено: {data.get('last_updated')})")
        return data
    except Exception as e:
        logger.error(f"Ошибка при загрузке из кэша: {e}")
        return None

def update_currency_data():
    """Обновляет данные о валютах и сохраняет в кэш"""
    global currency_data
    
    if currency_data['status'] == 'updating':
        logger.info("Обновление уже выполняется, пропускаем")
        return
        
    currency_data['status'] = 'updating'
    logger.info("Начато обновление данных о валютах...")
    
    try:
        # Здесь будет код для получения данных с API
        # Пока что используем заглушку
        # TODO: Заменить на реальный запрос к API
        new_data = {
            'currencies': [
                {'name': 'Liquid Ire', 'price': '1.5', 'currency': 'chaos'},
                {'name': 'Liquid Guilt', 'price': '2.0', 'currency': 'chaos'},
                # ... другие валюты
            ],
            'last_updated': datetime.utcnow(),
            'league': '0.3',
            'status': 'idle'
        }
        
        # Обновляем глобальные данные
        currency_data.update({
            'currencies': new_data['currencies'],
            'last_updated': new_data['last_updated'],
            'next_update': datetime.utcnow() + timedelta(seconds=CACHE_DURATION),
            'league': new_data['league'],
            'status': 'idle'
        })
        
        # Сохраняем в кэш
        save_to_cache(currency_data)
        logger.info("Данные о валютах успешно обновлены")
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении данных: {e}")
        currency_data['status'] = 'error'
    
    # Планируем следующее обновление
    schedule_next_update()

def schedule_next_update():
    """Планирует следующее обновление данных"""
    def update_task():
        time.sleep(CACHE_DURATION)
        update_currency_data()
    
    # Запускаем обновление в отдельном потоке
    thread = threading.Thread(target=update_task, daemon=True)
    thread.start()
    
    next_update_time = datetime.utcnow() + timedelta(seconds=CACHE_DURATION)
    currency_data['next_update'] = next_update_time
    logger.info(f"Следующее обновление запланировано на {next_update_time}")

# Загружаем данные из кэша при старте
def init_cache():
    """Инициализирует кэш при старте приложения"""
    cached_data = load_from_cache()
    if cached_data:
        currency_data.update({
            'currencies': cached_data.get('currencies', []),
            'last_updated': cached_data.get('last_updated'),
            'league': cached_data.get('league', '0.3'),
            'status': 'idle'
        })
    
    # Запускаем обновление данных
    update_currency_data()

# Словарь для преобразования ID валют в читаемые имена
CURRENCY_IDS = {
    # Основные валюты
    'chaos': 'Chaos Orb',
    'divine': 'Divine Orb',
    'exalted': 'Exalted Orb',
    'mirror': 'Mirror of Kalandra',
    
    # PoE2 Жидкие эмоции
    'liquid_ire': 'Liquid IRE',
    'liquid_guilt': 'Liquid Guilt',
    'liquid_disgust': 'Liquid Disgust',
    'liquid_greed': 'Liquid Greed',
    'liquid_paranoia': 'Liquid Paranoia',
    'liquid_envy': 'Liquid Envy',
    'liquid_despair': 'Liquid Despair',
    'liquid_fear': 'Liquid Fear',
    'liquid_suffering': 'Liquid Suffering',
    'liquid_isolation': 'Liquid Isolation'
}

# Словарь для отображения русских названий
POE2_CURRENCIES = {
    'liquid_ire': 'Жидкий гнев',
    'liquid_guilt': 'Жидкая вина',
    'liquid_disgust': 'Жидкое отвращение',
    'liquid_greed': 'Жидкая жадность',
    'liquid_paranoia': 'Жидкая паранойя',
    'liquid_envy': 'Жидкая зависть',
    'liquid_despair': 'Жидкое отчаяние',
    'liquid_fear': 'Жидкий страх',
    'liquid_suffering': 'Жидкое страдание',
    'liquid_isolation': 'Жидкое одиночество'
}

# Глобальный кэш для хранения данных о валютах
cache = {
    "data": None,
    "last_updated": None,
    "is_updating": False,
    "next_update": None,
    "league": None
}

# Инициализируем кэш при импорте модуля
init_cache()

def parse_currency_data_from_html(html_content: str) -> Dict[str, Any]:
    """Парсинг данных о курсах валют из HTML файла"""
    from bs4 import BeautifulSoup
    import json
    
    try:
        logger.info("Начинаем парсинг HTML...")
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Находим скрипт с данными
        script_content = None
        for i, script in enumerate(soup.find_all('script')):
            script_text = str(script)
            if 'currencyDetails' in script_text:
                script_content = script_text
                logger.info(f"Найден скрипт с данными (скрипт #{i+1}, длина: {len(script_text)} символов)")
                break
                
        if not script_content:
            logger.error("Не удалось найти данные о валютах в HTML")
            # Логируем первые 1000 символов HTML для отладки
            logger.debug(f"Начало HTML: {html_content[:1000]}...")
            return None
            
        # Извлекаем JSON из скрипта
        start = script_content.find('{')
        end = script_content.rfind('}') + 1
        
        if start == -1 or end == 0:
            logger.error("Не удалось найти JSON в скрипте")
            return None
            
        json_str = script_content[start:end]
        logger.debug(f"Извлечен JSON (первые 200 символов): {json_str[:200]}...")
        
        try:
            data = json.loads(json_str)
            lines_count = len(data.get('lines', []))
            logger.info(f"Успешно загружены данные о {lines_count} валютах")
            
            if lines_count > 0:
                first_currency = data['lines'][0]
                logger.debug(f"Первая валюта: {first_currency.get('currencyTypeName')} = {first_currency.get('chaosEquivalent')}")
                
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка при разборе JSON: {e}")
            logger.debug(f"Проблемный JSON (первые 500 символов): {json_str[:500]}")
            return None
            
    except Exception as e:
        logger.error(f"Критическая ошибка при парсинге HTML: {str(e)}", exc_info=True)
        return None

def fetch_currency_data() -> Dict[str, Any]:
    """Получение данных о курсах валют с официального Trade API Path of Exile"""
    try:
        logger.info("=== НАЧАЛО ЗАПРОСА К API ===")
        
        headers = {
            'User-Agent': 'PoE2TradeHelper/1.0',
            'Accept': 'application/json'
        }
        
        # 1. Получаем список лиг
        leagues_url = "https://api.pathofexile.com/leagues"
        logger.info(f"1. Запрос списка лиг: {leagues_url}")
        
        # Получаем текущую лигу
        response = requests.get(leagues_url, headers=headers, timeout=15)
        response.raise_for_status()
        leagues = response.json()
        
        # Выбираем основную лигу (игнорируем SSF, Hardcore и т.д.)
        main_leagues = [
            league for league in leagues 
            if not league.get('privateLeague') and 
               not any(x in league.get('id', '').lower() for x in ['ssf', 'hardcore', 'ruthless'])
        ]
        
        if not main_leagues:
            logger.error("Не удалось найти основную лигу")
            return None
            
        current_league = main_leagues[0]
        league_id = current_league.get('id')
        logger.info(f"Используем лигу: {current_league.get('name')} (ID: {league_id})")
        
        # 2. Получаем статические данные о валютах
        logger.info("2. Получение статических данных о валютах...")
        try:
            static_data_url = "https://www.pathofexile.com/api/trade/data/static"
            response = requests.get(static_data_url, headers=headers, timeout=15)
            response.raise_for_status()
            static_data = response.json()
            
            # Логируем структуру ответа для отладки
            logger.debug(f"Структура статических данных: {json.dumps(static_data, indent=2)}")
            
            if 'result' not in static_data or not isinstance(static_data['result'], list):
                logger.error("Некорректный формат статических данных")
                return None
            
            # Находим категорию с валютами
            currency_category = None
            for category in static_data['result']:
                if isinstance(category, dict) and category.get('label') == 'Currency':
                    currency_category = category
                    break
            
            if not currency_category:
                logger.error("Не удалось найти категорию валют")
                return None
                
            # Создаем карту валют для быстрого поиска
            currency_map = {}
            for entry in currency_category.get('entries', []):
                if isinstance(entry, dict) and 'name' in entry and 'id' in entry and entry['name']:
                    currency_map[entry['name'].lower()] = entry
                    logger.debug(f"Добавлена валюта: {entry.get('name')} (ID: {entry.get('id')})")
            
            logger.info(f"Загружено {len(currency_map)} валют")
            
            # Логируем первые 10 валют для отладки
            if currency_map:
                logger.debug("Примеры загруженных валют:")
                for i, (name, data) in enumerate(currency_map.items()):
                    if i >= 10:  # Ограничиваем количество логов
                        logger.debug(f"... и еще {len(currency_map) - 10} валют")
                        break
                    logger.debug(f"  - {name}: {data}")
            else:
                logger.warning("Не удалось загрузить валюты. Ответ API:")
                logger.warning(json.dumps(static_data, indent=2, ensure_ascii=False))
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при получении статических данных: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка при разборе JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}", exc_info=True)
            return None
        
        # 3. Ищем Divine Orb как базовую валюту
        divine_orb = currency_map.get('divine orb')
        if not divine_orb:
            logger.error("Не удалось найти Divine Orb в списке валют")
            return None
            
        divine_orb_id = divine_orb['id']
        logger.info(f"Найден Divine Orb: ID={divine_orb_id}")
        
        # 4. Формируем запрос на поиск торговых предложений
        logger.info("4. Поиск торговых предложений...")
        
        # Получаем ID валют, которые мы хотим найти
        target_currencies = [
            'liquid ire', 'liquid guilt', 'liquid disgust', 'liquid greed',
            'liquid paranoia', 'liquid envy', 'liquid despair', 'liquid fear',
            'liquid suffering', 'liquid isolation'
        ]
        
        # Собираем ID только тех валют, которые есть в игре
        currency_ids = []
        for curr_name in target_currencies:
            if curr_name in currency_map:
                currency_ids.append(currency_map[curr_name]['id'])
        
        if not currency_ids:
            logger.error("Не удалось найти ни одной валюты PoE2 в статических данных")
            return None
            
        logger.info(f"Ищем цены для {len(currency_ids)} валют PoE2")
        
        # 5. Формируем запрос к Trade API
        trade_url = f"https://www.pathofexile.com/api/trade/exchange/{league_id}"
        
        # Создаем запрос на обмен валют
        payload = {
            "exchange": {
                "status": {"option": "online"},
                "have": currency_ids,
                "want": [divine_orb_id]
            }
        }
        
        # Добавляем заголовки с User-Agent
        trade_headers = headers.copy()
        trade_headers['Content-Type'] = 'application/json'
        
        # Выполняем запрос
        logger.info(f"Отправка запроса к Trade API: {trade_url}")
        response = requests.post(
            trade_url,
            json=payload,
            headers=trade_headers,
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Ошибка Trade API: {response.status_code} - {response.text}")
            return None
            
        search_result = response.json()
        
        if 'result' not in search_result or not search_result['result']:
            logger.error("Не найдено результатов торговли")
            return None
            
        logger.info(f"Найдено {len(search_result['result'])} предложений")
        
        # 6. Обрабатываем результаты
        result = {
            'lines': [],
            'league': {'name': league_id, 'id': league_id},
            'currencyDetails': [],
            'language': {'t2c': {}}
        }
        
        # Собираем статистику по ценам
        price_stats = {}
        
        # Берем первые 10 предложений для анализа
        offer_ids = search_result['result'][:10]
        
        if offer_ids:
            # Получаем детали предложений
            fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(offer_ids)}?query={search_result.get('id', '')}"
            logger.info(f"Получение деталей {len(offer_ids)} предложений...")
            
            fetch_response = requests.get(fetch_url, headers=headers, timeout=30)
            
            if fetch_response.status_code == 200:
                offers_data = fetch_response.json()
                
                for offer in offers_data.get('result', []):
                    if 'listing' not in offer:
                        continue
                        
                    listing = offer['listing']
                    if 'price' not in listing:
                        continue
                        
                    price = listing['price']
                    if 'exchange' not in price or 'item' not in price:
                        continue
                        
                    have_currency = price['exchange'].get('currency')
                    want_currency = price['item'].get('currency')
                    
                    if not have_currency or want_currency.lower() != 'divine orb':
                        continue
                        
                    try:
                        have_amount = float(price['exchange'].get('amount', 0))
                        want_amount = float(price['item'].get('amount', 0))
                        
                        if have_amount <= 0 or want_amount <= 0:
                            continue
                            
                        if have_currency not in price_stats:
                            price_stats[have_currency] = []
                            
                        # Сохраняем цену (сколько Divine Orb'ов можно получить за 1 единицу валюты)
                        price_stats[have_currency].append(want_amount / have_amount)
                        
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Ошибка при обработке цены: {e}")
                        continue
        
        # 7. Формируем результат
        for currency_id, prices in price_stats.items():
            if not prices:
                continue
                
            # Вычисляем среднюю цену
            avg_price = sum(prices) / len(prices)
            
            # Находим название валюты по ID
            currency_name = next(
                (name for name, data in currency_map.items() 
                 if data['id'] == currency_id),
                currency_id
            )
            
            # Добавляем в результат
            result['lines'].append({
                'currencyTypeName': currency_name,
                'receive': {
                    'value': avg_price,
                    'currency': 'divine'
                },
                'pay': {
                    'value': 1.0,
                    'currency': currency_name
                }
            })
        
        logger.info(f"Обработано {len(result['lines'])} валют")
        return result
        
        try:
            # Логируем детали запроса
            logger.debug(f"Заголовки запроса: {headers}")
            logger.debug(f"Таймаут: 10 сек")
            
            # Выполняем запрос
            start_time = time.time()
            leagues_response = requests.get(
                leagues_url,
                headers=headers,
                timeout=10
            )
            request_time = time.time() - start_time
            
            # Логируем ответ
            logger.info(f"2. Ответ получен за {request_time:.2f} сек")
            logger.info(f"   Статус: {leagues_response.status_code}")
            logger.debug(f"   Заголовки ответа: {dict(leagues_response.headers)}")
            
            if leagues_response.status_code != 200:
                logger.error(f"ОШИБКА: Не удалось получить список лиг. Код: {leagues_response.status_code}")
                logger.error(f"Ответ сервера: {leagues_response.text[:500]}")
                return None
                
            # Парсим JSON
            try:
                leagues = leagues_response.json()
                logger.info(f"3. Успешно получено {len(leagues)} лиг")
                
                if leagues:
                    logger.debug(f"   Пример лиги: ID={leagues[0].get('id')}, Имя={leagues[0].get('name')}")
                else:
                    logger.warning("   Список лиг пуст!")
                    
            except Exception as e:
                logger.error(f"ОШИБКА при разборе JSON с лигами: {e}")
                logger.debug(f"Сырой ответ: {leagues_response.text[:500]}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"ОШИБКА при выполнении запроса к {leagues_url}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            logger.error(f"Сообщение: {str(e)}")
            return None
        
        # 4. Выбираем лигу (игнорируем SSF и другие специальные лиги)
        logger.info("4. Выбор подходящей лиги...")
        current_league = next((league for league in leagues if not league.get('rules')), None)
        
        if not current_league and leagues:  # Если не нашли, берем первую
            current_league = leagues[0]
            logger.warning(f"   Не найдена обычная лига, используем первую из списка: {current_league.get('id')}")
            
        if not current_league:
            logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось определить текущую лигу")
            return None
            
        league_id = current_league['id']
        logger.info(f"   Выбрана лига: {league_id} (ID: {current_league.get('id')})")
        
        # 5. Получаем список всех валют
        logger.info("5. Получение списка валют...")
        static_data_url = "https://www.pathofexile.com/api/trade/data/static"
        
        try:
            logger.debug(f"   Запрос к {static_data_url}")
            start_time = time.time()
            static_response = requests.get(
                static_data_url,
                headers={"User-Agent": "PoE2TradeHelper/1.0"},
                timeout=15
            )
            request_time = time.time() - start_time
            
            logger.info(f"6. Ответ получен за {request_time:.2f} сек, статус: {static_response.status_code}")
            
            if static_response.status_code != 200:
                logger.error(f"   ОШИБКА: Не удалось получить список валют. Код: {static_response.status_code}")
                logger.error(f"   Ответ сервера: {static_response.text[:500]}")
                return None
                
            try:
                static_data = static_response.json()
                logger.info(f"   Успешно получены данные о валютах")
                
                # Проверяем структуру полученных данных
                if 'result' not in static_data:
                    logger.error("   ОШИБКА: В ответе отсутствует ключ 'result'")
                    logger.debug(f"   Полученные данные: {static_data}")
                    return None
                    
            except Exception as e:
                logger.error(f"   ОШИБКА при разборе JSON с валютами: {e}")
                logger.debug(f"   Сырой ответ: {static_response.text[:500]}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ОШИБКА при выполнении запроса к {static_data_url}")
            logger.error(f"   Тип ошибки: {type(e).__name__}")
            logger.error(f"   Сообщение: {str(e)}")
            return None
        
        # 7. Находим ID Divine Orb (валюта, в которой будем показывать цены)
        logger.info("7. Поиск Divine Orb в списке валют...")
        
        # Ищем категорию с валютами
        currency_category = next((c for c in static_data['result'] if c.get('label') == 'Currency'), None)
        
        if not currency_category:
            logger.error("   ОШИБКА: Не найдена категория 'Currency' в статических данных")
            logger.debug(f"   Доступные категории: {[c.get('label', 'N/A') for c in static_data['result']]}")
            return None
            
        entries = currency_category.get('entries', [])
        logger.info(f"   Найдено {len(entries)} валют в категории")
        
        # Ищем Divine Orb
        divine_orb_entry = None
        for entry in entries:
            if isinstance(entry, dict) and entry.get('name') == 'Divine Orb':
                divine_orb_entry = entry
                break
                
        logger.debug(f"   Найденные ключи в записи: {list(entries[0].keys()) if entries else 'Нет записей'}")
        logger.debug(f"   Пример записи: {entries[0] if entries else 'Нет записей'}")
        
        if not divine_orb_entry:
            logger.error("   ОШИБКА: Не удалось найти Divine Orb в списке валют")
            logger.debug(f"   Доступные валюты: {[x['name'] for x in currency_category['entries'][:5]]}...")
            return None
            
        divine_orb_id = divine_orb_entry['id']
        logger.info(f"   Найден Divine Orb: ID={divine_orb_id}")
        
        # 8. Создаем словарь для быстрого поиска валют по имени
        logger.info("8. Создание карты валют...")
        currency_map = {}
        
        for category in static_data['result']:
            if category.get('label') == 'Currency':
                for entry in category.get('entries', []):
                    if isinstance(entry, dict):
                        currency_name = entry.get('name')
                        if currency_name:
                            currency_map[currency_name] = entry
        
        logger.info(f"   Создана карта {len(currency_map)} валют")
        logger.debug(f"   Примеры валют: {list(currency_map.keys())[:5]}...")
        
        # 9. Формируем данные для запроса к Trade API
        logger.info("9. Подготовка данных для Trade API...")
        trade_data = {
            "exchange": {
                "status": {"option": "online"},
                "have": [],  # Сюда добавим ID валют, которые нас интересуют
                "want": [divine_orb_id]  # Хотим получить цены в Divine Orbs
            }
        }
        
        # 10. Добавляем все валюты из нашего списка в запрос
        logger.info("10. Добавление валют в запрос...")
        found_currencies = []
        
        for currency in CURRENCIES:
            currency_name = currency['name_en']
            if currency_name in currency_map:
                currency_id = currency_map[currency_name]['id']
                if currency_id not in trade_data['exchange']['have']:
                    trade_data['exchange']['have'].append(currency_id)
                    found_currencies.append(currency_name)
        
        logger.info(f"   Добавлено {len(found_currencies)} валют в запрос")
        logger.debug(f"   Валюты в запросе: {', '.join(found_currencies[:5])}{'...' if len(found_currencies) > 5 else ''}")
        
        if not trade_data['exchange']['have']:
            logger.error("   ОШИБКА: Не удалось найти ID ни для одной из валют")
            logger.debug(f"   Доступные валюты: {', '.join(list(currency_map.keys())[:5])}...")
            return None
        
        # 11. Отправляем запрос на поиск предложений
        search_url = f"https://www.pathofexile.com/api/trade/exchange/{league_id}"
        logger.info(f"11. Отправка запроса к Trade API: {search_url}")
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'PoE2TradeHelper/1.0',
            'Accept': 'application/json'
        }
        
        try:
            logger.debug(f"   Тело запроса: {json.dumps(trade_data, indent=2, ensure_ascii=False)[:500]}...")
            start_time = time.time()
            
            response = requests.post(
                search_url, 
                json=trade_data, 
                headers=headers, 
                timeout=30
            )
            
            request_time = time.time() - start_time
            logger.info(f"12. Ответ получен за {request_time:.2f} сек, статус: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"   ОШИБКА: Не удалось получить результаты торговли. Код: {response.status_code}")
                logger.error(f"   Ответ сервера: {response.text[:500]}")
                return None
                
            try:
                search_result = response.json()
                logger.info(f"   Успешно получены результаты поиска")
                
                if not search_result.get('result'):
                    logger.error("   ОШИБКА: Пустой результат торговли")
                    logger.debug(f"   Полный ответ: {search_result}")
                    return None
                
                # 13. Получаем ID предложений (берем первые 10 для статистики)
                offer_ids = search_result['result'][:10]
                logger.info(f"13. Получено {len(offer_ids)} предложений из {len(search_result['result'])}")
                
                if not offer_ids:
                    logger.warning("   Нет доступных предложений")
                    return None
                
                # 14. Получаем детали предложений
                fetch_url = f"https://www.pathofexile.com/api/trade/fetch/{','.join(offer_ids)}?query={search_result['id']}"
                logger.info(f"14. Получение деталей предложений: {fetch_url}")
                
                try:
                    fetch_response = requests.get(fetch_url, headers=headers, timeout=30)
                    logger.info(f"15. Ответ получен за {time.time() - start_time - request_time:.2f} сек, статус: {fetch_response.status_code}")
                    
                    if fetch_response.status_code != 200:
                        logger.error(f"   ОШИБКА: Не удалось получить детали предложений. Код: {fetch_response.status_code}")
                        logger.error(f"   Ответ сервера: {fetch_response.text[:500]}")
                        return None
                        
                    try:
                        offers_data = fetch_response.json()
                        logger.info(f"   Успешно получены детали {len(offers_data.get('result', []))} предложений")
                        
                        # 16. Обрабатываем результаты
                        logger.info("16. Обработка результатов...")
                        result = {
                            'lines': [],
                            'league': {'name': league_id, 'id': league_id},
                            'currencyDetails': [],
                            'language': {
                                't2c': {}
                            }
                        }
                        
                        # Собираем статистику по ценам
                        price_stats = {}
                        processed_offers = 0
                        
                        for offer in offers_data.get('result', []):
                            if 'listing' not in offer:
                                continue
                                
                            listing = offer['listing']
                            if 'price' not in listing:
                                continue
                                
                            price = listing['price']
                            if 'exchange' not in price or 'item' not in price:
                                continue
                                
                            have_currency = price['exchange'].get('currency')
                            want_currency = price['item'].get('currency')
                            
                            if not have_currency or want_currency != 'Divine Orb':
                                continue
                                
                            try:
                                have_amount = float(price['exchange'].get('amount', 0))
                                want_amount = float(price['item'].get('amount', 0))
                            except (ValueError, TypeError) as e:
                                logger.warning(f"   Ошибка преобразования суммы: {e}")
                                continue
                            
                            if have_amount <= 0 or want_amount <= 0:
                                continue
                            
                            if have_currency not in price_stats:
                                price_stats[have_currency] = []
                            
                            # Сохраняем цену (сколько Divine Orb'ов можно получить за 1 единицу валюты)
                            price_stats[have_currency].append(want_amount / have_amount)
                            processed_offers += 1
                            
                        logger.info(f"   Обработано {processed_offers} предложений для {len(price_stats)} валют")
                        
                    except Exception as e:
                        logger.error(f"   ОШИБКА при разборе JSON с деталями предложений: {e}")
                        logger.debug(f"   Сырой ответ: {fetch_response.text[:500]}")
                        return None
                        
                except requests.exceptions.RequestException as e:
                    logger.error(f"   ОШИБКА при получении деталей предложений: {e}")
                    return None
                
            except Exception as e:
                logger.error(f"   ОШИБКА при разборе JSON с результатами поиска: {e}")
                logger.debug(f"   Сырой ответ: {response.text[:500]}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ОШИБКА при выполнении запроса к Trade API: {e}")
            return None
        
        # Вычисляем средние цены и формируем результат
        for currency_id, prices in price_stats.items():
            if not prices:
                continue
                
            avg_price = sum(prices) / len(prices)
            currency_name = next(
                (name for name, data in currency_map.items() 
                 if data.get('id') == currency_id),
                currency_id
            )
            
            result['lines'].append({
                'currencyTypeName': currency_name,
                'receive': {'value': avg_price},
                'pay': {'value': 1.0},
                'currencyId': currency_id
            })
            
            # Добавляем информацию о валюте для отображения
            result['currencyDetails'].append({
                'id': currency_id,
                'name': currency_name,
                'tradeId': currency_map.get(currency_name, {}).get('tradeId', currency_name.lower().replace(' ', '-'))
            })
            
            # Добавляем в словарь перевода
            result['language']['t2c'][currency_id] = currency_name
        
        logger.info(f"Обработано {len(result['lines'])} валют")
        return result
        
    except requests.RequestException as e:
        logger.error(f"Ошибка при запросе к API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Код статуса: {e.response.status_code}")
            logger.error(f"Ответ: {e.response.text[:500]}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}", exc_info=True)
        return None

def update_cache():
    """Обновление кэша данных"""
    if cache.get("is_updating"):
        logger.info("Обновление уже выполняется, пропускаем")
        return
    
    logger.info("Начало обновления кэша...")
    cache["is_updating"] = True
    
    try:
        # Получаем данные с API
        data = fetch_currency_data()
        
        if data:
            # Обновляем кэш
            cache["data"] = data
            cache["last_updated"] = datetime.utcnow()
            cache["next_update"] = datetime.utcnow() + timedelta(minutes=5)
            
            # Сохраняем в файл
            save_to_cache({
                'data': data,
                'last_updated': cache["last_updated"],
                'next_update': cache["next_update"]
            })
            
            logger.info(f"Кэш успешно обновлен. Валют: {len(data.get('lines', []))}")
            return True
        else:
            logger.warning("Не удалось получить данные с API")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении кэша: {e}", exc_info=True)
        return False
        
    finally:
        cache["is_updating"] = False
        logger.info("Завершено обновление кэша")

def get_currency_value(currency_id: str):
    """
    Получение стоимости валюты в хаосах из загруженных данных API
    
    Args:
        currency_id: ID валюты из словаря CURRENCY_IDS
        
    Returns:
        float: Стоимость валюты в хаосах или None, если не найдена
    """
    try:
        if not cache.get('data') or not isinstance(cache['data'], dict):
            logger.warning("Кэш данных пуст или имеет неверный формат")
            return None
            
        # Получаем список валют из кэша
        currencies = cache['data'].get('lines', [])
        if not currencies:
            logger.warning("Список валют пуст. Доступные ключи в кэше: " + 
                          ", ".join(str(k) for k in cache['data'].keys()) 
                          if isinstance(cache['data'], dict) else "нет данных")
            return None
            
        # Получаем название валюты по ID
        currency_name = CURRENCY_IDS.get(currency_id, "").lower()
        if not currency_name:
            logger.warning(f"Неизвестный ID валюты: {currency_id}")
            return None
            
        base_currency_name = currency_name.replace("liquid ", "").strip()
        
        # Создаем список для хранения всех вариантов названий валют
        search_terms = {
            'base': [
                currency_name,
                base_currency_name,
                currency_name.replace(" ", ""),  # Без пробелов
                base_currency_name + " orb",     # С пробелом
                "orb of " + base_currency_name,  # С префиксом
                base_currency_name.capitalize(),  # С заглавной буквы
                currency_name.capitalize(),       # С заглавной буквы с Liquid
                "Liquid " + base_currency_name.capitalize(),  # С заглавной Liquid
                base_currency_name.upper(),                    # Верхний регистр
                base_currency_name.replace(" ", "").lower(),  # Без пробелов, нижний регистр
                "orb of " + base_currency_name.capitalize(),   # С префиксом и заглавной
                "orb of " + base_currency_name.lower(),        # С префиксом и нижним регистром
                base_currency_name + "'s orb",                 # С апострофом
                base_currency_name + "'s Orb"                  # С апострофом и заглавной
            ],
            'ire': ["Ire's Orb", "Ire's orb", "Ire Orb", "ire orb"] if "ire" in currency_name else []
        }
        
        # Объединяем все варианты поиска
        all_search_terms = search_terms['base'] + search_terms['ire']
        
        # Добавляем ID валюты в поиск
        all_search_terms.append(currency_id)
        
        # Удаляем дубликаты и пустые строки
        all_search_terms = list({term.lower() for term in all_search_terms if term and str(term).strip()})
        
        logger.debug(f"Поиск валюты: ID={currency_id}, имя='{currency_name}', варианты поиска: {all_search_terms}")
        
        # Ищем валюту по различным вариантам названий
        for currency in currencies:
            if not isinstance(currency, dict):
                continue
                
            currency_name = str(currency.get('currencyTypeName', '')).lower()
            currency_id_str = str(currency.get('id', '')).lower()
            
            # Проверяем все варианты названий для поиска
            for term in all_search_terms:
                term_lower = str(term).lower()
                if (term_lower and 
                    (term_lower in currency_name or 
                     term_lower in currency_id_str or
                     currency_id.lower() in currency_id_str)):
                    
                    chaos_value = currency.get('chaosEquivalent')
                    if chaos_value is not None:
                        logger.info(f"Найдена валюта: {currency_name} = {chaos_value} хаос (по термину: {term})")
                        return float(chaos_value)
        
        # Если не нашли, логируем доступные валюты для отладки
        available_currencies = [
            f"{item.get('currencyTypeName', 'unknown')} (ID: {item.get('id', '?')})" 
            for item in cache["data"].get("lines", [])[:10]  # Ограничиваем количество для лога
        ]
        
        logger.warning(
            f"Валюта не найдена: {currency_name} (ID: {currency_id})\n"
            f"Доступные валюты ({len(available_currencies)}): {', '.join(available_currencies)}"
        )
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка при поиске валюты {currency_id}: {str(e)}", exc_info=True)
        return None

@app.route('/')
def index():
    logger.info("Обработка запроса главной страницы")
    
    # Инициализация переменных по умолчанию
    data = {}
    poe2_currencies = []
    error = None
    
    try:
        # Проверяем, нужно ли обновлять кэш
        if cache.get('data') is None or cache.get('next_update') is None or datetime.utcnow() >= cache.get('next_update', datetime.utcnow()):
            logger.info("Кэш пустой или устарел, запускаем обновление...")
            update_cache()
        
        # Получаем данные из кэша
        data = cache.get('data', {}) if cache.get('data') else {}
        
        # Если данные пустые, пробуем загрузить из файла
        if not data and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"Данные загружены из файла {CACHE_FILE}")
            except Exception as e:
                logger.error(f"Ошибка при загрузке данных из файла: {e}")
                error = f"Ошибка загрузки данных: {str(e)}"
        
        # Получаем список валют PoE2
        poe2_currencies = []
        for cid, name in POE2_CURRENCIES.items():
            try:
                value = get_currency_value(cid)
                poe2_currencies.append({
                    'id': cid,
                    'name': name,
                    'value': value
                })
                logger.debug(f"Валюта {name}: {value}")
            except Exception as e:
                logger.warning(f"Не удалось получить цену для валюты: {name} ({cid})")
                poe2_currencies.append({
                    'id': cid,
                    'name': name,
                    'value': None,
                    'error': str(e)
                })
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
    
    # Сортируем валюты по имени
    poe2_currencies_sorted = sorted(poe2_currencies, key=lambda x: x['name'])
    
    # Получаем временные метки с проверкой на None
    last_updated = cache.get('last_updated')
    next_update = cache.get('next_update')
    
    # Логируем информацию о времени
    logger.info(f"Последнее обновление: {last_updated}")
    logger.info(f"Следующее обновление: {next_update}")
    
    # Подготавливаем данные для отладки
    debug_info = {
        'last_updated': str(last_updated) if last_updated else 'N/A',
        'next_update': str(next_update) if next_update else 'N/A',
        'currencies_loaded': len([c for c in poe2_currencies if c.get('value') is not None]),
        'currencies_failed': len([c for c in poe2_currencies if c.get('value') is None]),
        'cache_has_data': bool(cache.get('data')),
        'error': str(e) if 'e' in locals() and e is not None else None
    }
    
    if app.debug:
        try:
            # Создаем словарь с сериализуемыми данными
            debug_info = {
                'league': str(cache.get('data', {}).get('league', {}).get('name', 'N/A')),
                'cache_available': bool(cache.get('data')),
                'currencies_count': len(cache.get('data', {}).get('lines', [])),
                'cache_keys': list(cache.keys()) if cache else [],
                'last_updated': last_updated.isoformat() if hasattr(last_updated, 'isoformat') else str(last_updated or 'N/A'),
                'next_update': next_update.isoformat() if hasattr(next_update, 'isoformat') else str(next_update or 'N/A'),
                'timestamp': datetime.utcnow().isoformat(),
                'last_updated_type': type(last_updated).__name__ if last_updated is not None else 'None',
                'next_update_type': type(next_update).__name__ if next_update is not None else 'None',
                'api_response': {
                    'league': cache.get('data', {}).get('league', {}).get('name', 'N/A') if cache.get('data') else 'N/A',
                    'currencies': [
                        {
                            'id': curr.get('id'),
                            'name': curr.get('name'),
                            'value': curr.get('value')
                        }
                        for curr in poe2_currencies_sorted
                    ] if poe2_currencies_sorted else []
                }
            }
            
            # Удаляем None значения, чтобы избежать проблем с сериализацией
            debug_info = {k: v for k, v in debug_info.items() if v is not None}
            
        except Exception as e:
            logger.error(f"Ошибка при подготовке отладочной информации: {e}", exc_info=True)
            debug_info = {
                'error': str(e),
                'cache_available': bool(cache.get('data')),
                'last_updated': str(last_updated) if last_updated else 'N/A',
                'next_update': str(next_update) if next_update else 'N/A',
                'timestamp': datetime.utcnow().isoformat()
            }
    
    # Рендерим шаблон с данными
    return render_template(
        'index.html',
        currencies=poe2_currencies_sorted,  # Используем отсортированный список валют
        last_updated=last_updated,
        next_update=next_update,
        status='updating' if cache.get('is_updating') else 'idle',
        league=cache.get('data', {}).get('league', {}).get('name') if cache.get('data') else None,
        debug_info=debug_info
    )

@app.route('/api/update', methods=['POST'])
def update_currency_rates():
    """Ручное обновление курсов валют"""
    if currency_data['status'] == 'updating':
        return jsonify({
            "status": "updating", 
            "message": "Обновление уже выполняется",
            "last_updated": currency_data['last_updated'].isoformat() if currency_data['last_updated'] else None,
            "next_update": currency_data['next_update'].isoformat() if currency_data['next_update'] else None
        })
    
    try:
        # Запускаем обновление в отдельном потоке
        thread = threading.Thread(target=update_currency_data, daemon=True)
        thread.start()
        
        return jsonify({
            "status": "started", 
            "message": "Запущено обновление курсов валют",
            "last_updated": currency_data['last_updated'].isoformat() if currency_data['last_updated'] else None,
            "next_update": currency_data['next_update'].isoformat() if currency_data['next_update'] else None
        })
        
    except Exception as e:
        logger.error(f"Ошибка при запуске обновления: {e}")
        return jsonify({
            "status": "error", 
            "message": f"Не удалось запустить обновление: {str(e)}"
        }), 500

@app.route('/api/status')
def get_status():
    """Получение текущего статуса обновления"""
    return jsonify({
        "status": currency_data['status'],
        "last_updated": currency_data['last_updated'].isoformat() if currency_data['last_updated'] else None,
        "next_update": currency_data['next_update'].isoformat() if currency_data['next_update'] else None,
        "league": currency_data['league'],
        "currencies_count": len(currency_data['currencies'])
    })

@app.route('/api/currencies')
def get_currencies():
    """Получение списка валют"""
    return jsonify({
        "status": "success",
        "data": {
            "currencies": currency_data['currencies'],
            "last_updated": currency_data['last_updated'].isoformat() if currency_data['last_updated'] else None,
            "next_update": currency_data['next_update'].isoformat() if currency_data['next_update'] else None,
            "league": currency_data['league']
        }
    })

def check_poe2_support():
    """Проверяет поддержку PoE2 в различных API"""
    print("\n=== Поиск поддержки PoE2 в различных API ===\n")
    
    headers = {
        'User-Agent': 'PoE2TradeHelper/1.0',
        'Accept': 'application/json'
    }
    
    # 1. Проверяем доступные лиги
    print("1. Проверка доступных лиг...")
    try:
        response = requests.get(
            "https://api.pathofexile.com/leagues",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        leagues = response.json()
        
        # Ищем актуальную лигу (игнорируем SSF, Hardcore и т.д.)
        main_leagues = [
            league for league in leagues 
            if not league.get('privateLeague') and 
               not any(x in league.get('id', '').lower() for x in ['ssf', 'hardcore', 'ruthless'])
        ]
        
        if not main_leagues:
            print("Не удалось найти основную лигу. Доступные лиги:")
            for league in leagues[:10]:
                print(f"- {league.get('name')} (ID: {league.get('id')})")
            return False
            
        # Берем самую свежую лигу
        target_league = main_leagues[0]
        league_id = target_league.get('id')
        league_name = target_league.get('name')
        
        print(f"Используем лигу: {league_name} (ID: {league_id})")
        
        # 2. Проверяем Trade API
        print("\n2. Проверка Trade API...")
        try:
            # Получаем список доступных валют
            response = requests.get(
                "https://www.pathofexile.com/api/trade/data/static",
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            static_data = response.json()
            
            # Ищем категорию с валютами
            currency_category = next(
                (c for c in static_data.get('result', []) 
                 if c.get('label') == 'Currency'), 
                None
            )
            
            if not currency_category:
                print("Не удалось найти категорию валют")
                return False
                
            # Ищем валюты PoE2
            print("\n3. Поиск валют PoE2...")
            poe2_currencies = [
                curr for curr in currency_category.get('entries', [])
                if 'liquid' in curr.get('name', '').lower()
            ]
            
            if poe2_currencies:
                print(f"Найдено {len(poe2_currencies)} валют PoE2:")
                for curr in poe2_currencies[:5]:  # Показываем первые 5
                    print(f"- {curr.get('name')} (ID: {curr.get('id')})")
                if len(poe2_currencies) > 5:
                    print(f"...и еще {len(poe2_currencies) - 5} валют")
                return True
            else:
                print("Валюты PoE2 не найдены. Доступные валюты:")
                for curr in currency_category.get('entries', [])[:10]:
                    print(f"- {curr.get('name')} (ID: {curr.get('id')})")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе к Trade API: {e}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе списка лиг: {e}")
        return False
    
    print("\n=== Проверка завершена ===\n")
    return False

if __name__ == '__main__':
    # Запускаем проверку API при старте
    if not check_poe2_support():
        print("\nНе удалось найти поддержку PoE2 в проверенных API.")
        print("Рекомендации:")
        print("1. Убедитесь, что PoE2 уже запущена и доступна через API")
        print("2. Проверьте название лиги PoE2 и обновите код")
        print("3. Используйте локальный парсер, если API недоступно")
    
    # Запускаем приложение
    # Создаем папку для шаблонов, если её нет
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True)
