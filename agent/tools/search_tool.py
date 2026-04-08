"""Web search tool using DuckDuckGo: search, filter and format results."""

import logging
import re
import time
import urllib.parse
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional
from ddgs import DDGS

from agent.exceptions import ExternalAPIError, LLMError
from agent.circuit_breaker import ddg_cb

logger = logging.getLogger(__name__)


_RE_SITES = [
    'cian.ru', 'avito.ru', 'domclick.ru', 'realty.yandex.ru',
    'bn.ru', 'realestate.ru', 'sob.ru', 'move.ru',
]

_REAL_ESTATE_TERMS = [
    'квартир', 'комнат', 'студи', 'апартамент', 'таунхаус', 'коттедж',
    'недвижимость', 'продаж', 'цена', 'млн', 'тыс',
    'жк', 'жилой', 'новостройк', 'вторичк',
    'циан', 'авито', 'домклик',
    'район', 'метро', 'планировк', 'этаж', 'купить',
]

_LISTING_SITES = [
    ("ЦИАН",     "https://www.cian.ru/cat.php",               "deal_type=sale&engine_version=2&offer_type=flat&region=1"),
    ("Авито",    "https://www.avito.ru/moskva/kvartiry/prodam", ""),
    ("ДомКлик", "https://domclick.ru/search",                 ""),
]


# ---------------------------------------------------------------------------
# Per-user DDG rate limiting
# ---------------------------------------------------------------------------

_DDG_RATE_LIMIT = 10
_DDG_RATE_WINDOW = 60.0
_ddg_user_timestamps: dict = defaultdict(deque)


def _ddg_user_rate_limited(user_id: str) -> bool:
    now = time.monotonic()
    dq = _ddg_user_timestamps[user_id]
    while dq and now - dq[0] > _DDG_RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _DDG_RATE_LIMIT:
        return True
    dq.append(now)
    return False


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def enhance_real_estate_query(query: str) -> str:
    """Enhance query for better real estate search results."""
    q_lower = query.lower()

    if re.search(r'\bжк\b|жилой комплекс|новостройк', q_lower):
        if not any(w in q_lower for w in ['название', 'список', 'site:', 'купить квартиру']):
            query += ' названия список объектов'

    query = re.sub(r'\bЖК\b', 'жилой комплекс', query, flags=re.IGNORECASE)

    if not any(kw in query.lower() for kw in _REAL_ESTATE_TERMS):
        query += ' недвижимость купить'

    return query


def filter_relevant_results(results: List[Dict[str, Any]], original_query: str) -> List[Dict[str, Any]]:
    """Filter results by relevance to real estate."""
    if not results:
        return []

    filtered = []
    for result in results:
        title = result.get('title', '').lower()
        snippet = result.get('snippet', '').lower()
        combined = f"{title} {snippet}"

        if 'жилищный кодекс' in combined or 'жк рф' in combined:
            continue

        on_known_site = any(s in result.get('link', '') for s in _RE_SITES)
        score = sum(1 for term in _REAL_ESTATE_TERMS if term in combined)

        if on_known_site or score >= 2:
            filtered.append(result)

    return filtered[:5]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int, timelimit: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run a single DuckDuckGo text search with explicit 12-second timeout."""
    with DDGS(timeout=12) as ddgs:
        raw = list(ddgs.text(
            query,
            region="ru-ru",
            max_results=max_results,
            safesearch="moderate",
            timelimit=timelimit,
        ))
    return [
        {"title": r.get("title", ""), "snippet": r.get("body", ""), "link": r.get("href", "")}
        for r in raw
    ]


def search_real_estate(query: str, max_results: int = 12, user_id: str = "") -> List[Dict[str, Any]]:
    """Perform real estate related web search with enhanced query processing.

    Strategy:
    1. Try enhanced query without timelimit for broad coverage.
    2. If relevance filter removes everything, relax the threshold.
    3. If DuckDuckGo returns empty, retry with time limit (cache warmup).
    """
    if user_id and _ddg_user_rate_limited(user_id):
        logger.warning("DDG rate limit exceeded for user")
        raise ExternalAPIError("Превышен лимит поисковых запросов. Попробуйте позже.")

    # Circuit breaker: fail fast instead of waiting 12s timeout
    if ddg_cb.is_open():
        logger.warning("DDG circuit breaker OPEN — skipping search")
        raise ExternalAPIError("Поиск временно недоступен. Попробуйте позже.")

    original_query = query
    enhanced_query = enhance_real_estate_query(query)

    try:
        logger.debug("searching: %r", enhanced_query)
        results = _ddg_search(enhanced_query, max_results, timelimit=None)

        if not results:
            logger.debug("empty results, retrying with timelimit=y")
            results = _ddg_search(enhanced_query, max_results, timelimit="y")

        if not results:
            ddg_cb.record_success()
            return []

        filtered = filter_relevant_results(results, original_query)

        if not filtered:
            filtered = [r for r in results
                        if any(t in (r.get("title", "") + r.get("snippet", "")).lower()
                               for t in _REAL_ESTATE_TERMS)][:5]

        if not filtered:
            filtered = results[:3]

        ddg_cb.record_success()
        logger.info("search: %s raw -> %s returned", len(results), len(filtered))
        return filtered

    except ExternalAPIError:
        ddg_cb.record_failure()
        raise
    except Exception as e:
        ddg_cb.record_failure()
        logger.error("duckduckgo search error: %s", e)
        raise ExternalAPIError(str(e)) from e


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _build_listing_links(query: str) -> str:
    """Build search links to major listing platforms with encoded query."""
    q = urllib.parse.quote(query)
    lines = []
    for name, base_url, extra_params in _LISTING_SITES:
        params = f"{extra_params}&q={q}" if extra_params else f"q={q}"
        lines.append(f"- [{name}]({base_url}?{params})")
    return "\n".join(lines)


def _build_source_links(results: list) -> str:
    """Build links to actual pages found during search."""
    lines = [
        f"- [{r.get('title', '')[:60].strip()}]({r.get('link', '')})"
        for r in results[:4]
        if r.get("title") and r.get("link")
    ]
    if not lines:
        return ""
    return "*Найдено в сети:*\n" + "\n".join(lines)


def format_search_results(original_query: str, results: list) -> str:
    """Format search results using LLM; always append source and platform links."""
    from agent.direct_llm_call import llm_call_direct, create_dialog  # local import to avoid circular

    system_prompt = """Ты помощник по недвижимости. Отформатируй результаты поиска для Telegram бота.

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Используй ТОЛЬКО *жирный* (звёздочки) - не используй _подчёркивание_
- Не используй ### заголовки, > цитаты, --- разделители
- Названия ЖК выделяй *жирным*: - *Чистое Небо* - от 29 659 руб/кв.м
- Используй простые списки с дефисами

ПРАВИЛА КОНТЕНТА:
1. ВСЕГДА перечисляй конкретные объекты, ЖК или объявления из результатов - даже если информация частичная
2. Не пиши "нет информации" или "ничего не найдено" если результаты поиска непустые - опиши что есть
3. Цены копируй точно как в источнике, всегда добавляй единицы (руб., млн руб., руб/кв.м)
4. Перечисляй названия жилых комплексов (*Символ*, *Событие*), не застройщиков
5. Игнорируй SEO-мусор: "индивидуальная подборка", "нажмите сюда" - это агентские лендинги
6. Формат объекта: - *Название* - район, цена от X, ключевые особенности"""

    results_text = "\n".join([
        f"- {r['title']}\n  {r['snippet'][:400]}\n  {r['link']}"
        for r in results[:5]
    ])

    user_prompt = f"""Запрос пользователя: {original_query}

Результаты поиска:
{results_text}

Отформатируй результаты в полезный ответ. Обязательно перечисли найденные объекты:"""

    source_links = _build_source_links(results)
    listing_links = _build_listing_links(original_query)
    links_block = ""
    if source_links:
        links_block += f"\n\n{source_links}"
    links_block += f"\n\n*Поиск на площадках:*\n{listing_links}"

    try:
        dialog = create_dialog(system_prompt, user_prompt)
        formatted = llm_call_direct(dialog, temperature=0.3)

        if formatted and len(formatted.strip()) > 50:
            return formatted.strip() + links_block

        raise LLMError("llm returned short or empty response")

    except LLMError as e:
        logger.warning("llm result formatting failed: %s", e)
        response = "*Результаты поиска:*\n\n"
        for i, result in enumerate(results[:4], 1):
            response += f"{i}. {result.get('title', 'Без названия')}\n"
            if result.get('snippet'):
                response += f"   {result['snippet'][:200]}\n"
            response += "\n"
        return response + links_block
