# Spec: Search / Retrieval

## Обзор

FlatAgent использует **live web search** (DuckDuckGo) вместо RAG с векторным индексом.

**Обоснование:** Данные рынка недвижимости (цены, объявления, новостройки) меняются ежедневно. Статичный индекс устаревал бы быстрее, чем его можно обновлять в PoC.

---

## Архитектура retrieval

```
Запрос пользователя
    │
    ▼
enhance_real_estate_query(query)    ← детерминированная трансформация
    │
    ▼
DuckDuckGo DDGS.text()              ← live web search, max_results=12
    │   └── Retry с timelimit="y" если 0 результатов
    │
    ▼
filter_relevant_results()           ← детерминированная фильтрация
    │   ├── Whitelist known sites
    │   ├── Term score ≥ 2
    │   └── Anti-spam фильтры
    │
    ▼
LLM format_search_results()         ← генерация ответа
    │   ├── System prompt constraints
    │   ├── Validation: len > 50
    │   └── Fallback: шаблонный список
    │
    ▼
+ _build_source_links()             ← ссылки на найденные страницы
+ _build_listing_links()            ← ЦИАН / Авито / ДомКлик с query
```

---

## Query Enhancement

```python
enhance_real_estate_query(query: str) → str
```

| Трансформация | Условие | Пример |
|---|---|---|
| "ЖК" → "жилой комплекс" | `re.sub(r'\bЖК\b', ...)` | "ЖК Символ" → "жилой комплекс Символ" |
| "+ названия список объектов" | Запрос содержит "жк" или "новостройк" без "купить квартиру" | Помогает найти конкретные ЖК |
| "+ недвижимость купить" | Нет real-estate терминов в запросе | Off-topic запросы получают контекст |

---

## Relevance Filtering

### Whitelist сайтов (8 источников)

```python
_RE_SITES = [
    'cian.ru', 'avito.ru', 'domclick.ru', 'realty.yandex.ru',
    'bn.ru', 'realestate.ru', 'sob.ru', 'move.ru',
]
```

### Term scoring (20 терминов)

```python
_REAL_ESTATE_TERMS = [
    'квартир', 'комнат', 'студи', 'апартамент', 'таунхаус', 'коттедж',
    'недвижимость', 'продаж', 'цена', 'млн', 'тыс',
    'жк', 'жилой', 'новостройк', 'вторичк',
    'циан', 'авито', 'домклик',
    'район', 'метро', 'планировк', 'этаж', 'купить',
]
# Порог: ≥ 2 совпадений → relevant
```

### Anti-spam

```python
# Жилищный кодекс (часто путается с аббревиатурой ЖК)
if 'жилищный кодекс' in combined or 'жк рф' in combined:
    continue  # exclude
```

### Graceful degradation

```
Все результаты отфильтрованы
    ↓
fallback 1: real-estate term matching (любой термин из списка)
    ↓
fallback 2: top-3 raw results без фильтрации
```

---

## LLM Formatting

### System prompt constraints

```
- Используй ТОЛЬКО *жирный* (звёздочки) — не используй _подчёркивание_
- Не используй ### заголовки, > цитаты, --- разделители
- Названия ЖК выделяй *жирным*
- ВСЕГДА перечисляй конкретные объекты из результатов
- Не пиши "нет информации" если результаты непустые
- Цены копируй точно с единицами (руб., млн руб., руб/кв.м)
- Игнорируй SEO-мусор
```

### Validation и fallback

```
LLM response
    ├── len > 50 chars → OK, добавить ссылки → ответ
    └── LLMError или len ≤ 50
        → Шаблонный список из raw результатов (top-4)
           + source links + listing platform links
```

### Обязательные ссылки (всегда добавляются)

```python
_LISTING_SITES = [
    ("ЦИАН",    "https://www.cian.ru/cat.php",                "deal_type=sale&..."),
    ("Авито",   "https://www.avito.ru/moskva/kvartiry/prodam", ""),
    ("ДомКлик", "https://domclick.ru/search",                  ""),
]
# URL-encode query → параметр q=
```

---

## CSV Analysis (альтернативный retrieval)

Вместо web search пользователь загружает данные сам — прайс-лист застройщика в CSV.

```
CSV файл (Telegram document)
    │
    ▼
pandas.read_csv() + auto-encoding
    │
    ▼
Column detection (LLM-guided маппинг: площадь, цена)
    │
    ▼
OLS regression: price ~ area (statsmodels)
    │   R², коэффициенты, цена за м²
    │
    ▼
Outlier detection: |residual| > 2σ
    │   Переоцененные и недооцененные лоты
    │
    ▼
Plotly scatter + regression line → kaleido → PNG
    │
    ▼
Telegram: reply_text (аналитика) + reply_photo (график)
```

---

## [Агентский трек] Качество поиска

| Аспект | Реализация | Цель |
|---|---|---|
| Relevance | Whitelist + term score + graceful degradation | ≥80% релевантных в топ-5 |
| Anti-injection | Результаты в user-контексте, не system prompt | Защита от web injection |
| Prompt constraints | Запрет Markdown, требование конкретных объектов | Консистентное форматирование |
| Fallback при пустом LLM | Шаблонный список + ссылки | Всегда полезный ответ |

**Eval план (решение):** `eval/test_search.json` — 5 кейсов для spot-check релевантности:

```json
[
  {"query": "купить квартиру в Москве", "expected_sources_min": 1, "expected_re_terms_min": 2},
  {"query": "новостройки в Мытищах", "expected_sources_min": 1, "expected_re_terms_min": 2},
  {"query": "ЖК Символ цена", "expected_sources_min": 1, "expected_re_terms_min": 2},
  {"query": "жилищный кодекс статья 51", "expected_sources_min": 0, "expected_spam_blocked": true},
  {"query": "вторичное жильё в Подмосковье", "expected_sources_min": 1, "expected_re_terms_min": 2}
]
```

Метрика: % запросов где топ-5 результатов содержат ≥2 real-estate термина. Цель ≥80%.

---

## [Инфраструктурный трек] Надёжность поиска

### DDG Timeout (решение)

```python
# search_tool.py — явный timeout вместо библиотечного default
def _ddg_search(query: str, max_results: int = 12, timelimit=None) -> list:
    try:
        with DDGS(timeout=12) as ddgs:   # явный 12 сек
            results = list(ddgs.text(
                query,
                region="ru-ru",
                safesearch="moderate",
                max_results=max_results,
                timelimit=timelimit,
            ))
        return results
    except Exception as e:
        raise ExternalAPIError(f"DDG search failed: {e}") from e
```

### Circuit Breaker для DDG (решение)

```python
# Singleton circuit breaker (module-level)
_ddg_cb = CircuitBreaker(failure_threshold=3, window_sec=60, recovery_sec=60)

def _ddg_search_safe(query: str, max_results: int = 12) -> list:
    if _ddg_cb.is_open():
        logger.warning("DDG circuit breaker OPEN — skipping search")
        raise ExternalAPIError("DDG circuit breaker open")
    try:
        results = _ddg_search(query, max_results)
        _ddg_cb.record_success()
        return results
    except ExternalAPIError:
        _ddg_cb.record_failure()
        raise
```

| Параметр | Значение |
|---|---|
| DDG timeout | 12 сек (явный) |
| Circuit breaker threshold | 3 ошибки за 60 сек → open |
| Recovery period | 60 сек → half-open → 1 пробный запрос |
| При open | Немедленно `ExternalAPIError` — не ждём timeout |
| Мониторинг | `search_requests_total`, `search_errors_total`, `ddg_cb_state{state}` |
