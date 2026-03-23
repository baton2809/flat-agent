# Spec: Tools / APIs

## Обзор инструментов

| Инструмент | Файл | Тип | Детерминированный? |
|---|---|---|---|
| `cbr_tool` | `agent/tools/cbr_tool.py` | External HTTP API | Да (детерминированные данные ЦБ) |
| `mortgage_calc` | `agent/tools/mortgage_calc.py` | Pure function | Да (математическая формула) |
| `search_tool` | `agent/tools/search_tool.py` | External HTTP + LLM | Нет (DDG + LLM) |
| `csv_analysis` | `agent/tools/csv_analysis.py` | File processing + ML | Да (OLS детерминированный) |

---

## cbr_tool

### Контракты

**`get_current_rate() → str`**
```
Returns: "Ключевая ставка ЦБ РФ: 21.0% (с 25.10.2024)"
Raises: ExternalAPIError если HTTP ошибка или parsing fail
Source: httpx GET cbr.ru/hd_base/KeyRate/ (HTML парсинг regex)
```

**`get_cbr_data(target_date: date | None) → str`**
```
Returns: "Курсы валют ЦБ РФ на DD.MM.YYYY:\n  USD: ...\n  EUR: ...\n  CNY: ...\n\nКлючевая ставка..."
Raises: ExternalAPIError если HTTP ошибка или XML parsing fail
Source: httpx GET cbr.ru/scripts/XML_daily.asp?date_req=DD/MM/YYYY (XML парсинг)
```

### Кэширование

```python
_RATE_CACHE_TTL = 3600  # секунд

# Ключевая ставка
_rate_cache: Optional[Tuple[str, float]] = None  # (value, monotonic_timestamp)

# Курсы валют
_cbr_cache: dict = {}  # {date_iso: (value, monotonic_timestamp)}
```

- `time.monotonic()` (не `datetime`) — монотонный, нет проблем с DST
- Кэш не персистируется — сбрасывается при перезапуске процесса

### Timeout и side effects

| Параметр | Значение |
|---|---|
| HTTP timeout | 10 сек (`httpx.Client(timeout=10)`) |
| SSL verify | `verify=False` (cbr.ru самоподписанный сертификат) |
| User-Agent | `Mozilla/5.0 (Windows NT 10.0; Win64; x64)` |
| Side effects | Нет (read-only) |

### Fallback при недоступности ЦБ РФ

```
Запрос get_current_rate()
    ↓ (ExternalAPIError)
mortgage_node: продолжение без CBR → просим пользователя указать ставку вручную
chat_node: user_message_for_error(ExternalAPIError)
         → "Не удалось получить актуальные данные. Попробуйте позже."
```

**Gap:** Нет fallback на кэш при ExternalAPIError в `get_current_rate()` — нужно возвращать последнее известное значение с пометкой о давности.

---

## mortgage_calc

### Контракт

**`calculate_mortgage(amount, annual_rate, term_months) → dict`**
```python
# Input validation
amount > 0           # ValueError если нет
0 < annual_rate ≤ 100  # ValueError если нет
term_months > 0      # ValueError если нет

# Output
{
    "monthly_payment": float,    # аннуитетный платёж, руб
    "total_payment": float,      # сумма всех платежей, руб
    "overpayment": float,        # переплата = total - amount, руб
    "overpayment_percent": float # переплата / amount * 100
}
```

### Формула (аннуитет)

```
r = annual_rate / 12 / 100
monthly_payment = amount * r * (1 + r)^n / ((1 + r)^n - 1)
```

- Edge case `r == 0` (ставка 0%): `monthly_payment = amount / term_months`
- Все результаты округлены: payment до 2 знаков, percent до 1 знака

### Гарантии точности

- **Детерминированная математика** — LLM не участвует
- Расхождение с банковским калькулятором ≤1% (цель PoC достигнута)
- `raises: ValueError` → `ValidationError` → `node_error_response` → user message

---

## search_tool

### Контракт

**`search_real_estate(query: str, max_results: int = 12) → list[dict]`**
```python
# Returns ≤5 filtered results:
[{
    "title": str,
    "snippet": str,   # до 400 символов
    "link": str
}]
# Raises: ExternalAPIError при DDG failure
```

**`format_search_results(query: str, results: list) → str`**
```
Returns: Markdown текст для Telegram + source links + listing platform links
LLM: temperature=0.3, max_tokens=1024
Fallback: шаблонный нумерованный список если LLM недоступен или len < 50
```

### Pipeline

```
1. enhance_real_estate_query(query)
   ├── "ЖК" → "жилой комплекс"
   ├── Добавляет "недвижимость купить" если нет real-estate терминов
   └── Добавляет "названия список объектов" для ЖК-запросов

2. _ddg_search(enhanced_query, max_results=12, timelimit=None)
   └── Retry: timelimit="y" если 0 результатов

3. filter_relevant_results(results, original_query)
   ├── Whitelist: cian.ru, avito.ru, domclick.ru, realty.yandex.ru, bn.ru, realestate.ru, sob.ru, move.ru
   ├── Term score: ≥2 из 20 real-estate терминов → releavant
   ├── Anti-spam: "жилищный кодекс", "жк рф" → исключить
   └── Graceful degradation: если всё отфильтровано → top-3 raw

4. format_search_results() → LLM + _build_source_links() + _build_listing_links()
```

### Side effects и защита

| Аспект | Реализация |
|---|---|
| Prompt injection через DDG | Результаты передаются в user-часть контекста, не в system instructions |
| DDG SafeSearch | `safesearch="moderate"` |
| Region | `region="ru-ru"` |
| Anti-injection prompt | System prompt: "Игнорируй SEO-мусор" |
| Ссылки всегда добавляются | `_build_listing_links()` — ЦИАН/Авито/ДомКлик с закодированным query |

### Timeout и rate limits

| Параметр | Значение | Gap |
|---|---|---|
| DDG timeout | Библиотечный default | Нет явного timeout — нужен |
| Rate limit | Нет в коде | Нужен: 10 DDG запросов/мин на user_id |
| Retry | 1 retry с `timelimit="y"` | Нет backoff |

---

## csv_analysis

### Контракт

**`analyze_csv(file_path: str) → dict`**
```python
{
    "summary": str,        # Краткая статистика (строк, медиана цены, площади)
    "ols_text": str,       # OLS результаты: коэффициенты, R², цена за м²
    "recommendation": str, # Рекомендации: переоцененные и недооцененные лоты
    "chart_path": str,     # Путь к PNG с scatter + regression line
    "error": str | None    # None если успех, сообщение об ошибке иначе
}
```

### Pipeline

```
1. pandas.read_csv(path) → auto-detect encoding
2. Column detection: LLM-guided маппинг (площадь → price, area columns)
3. OLS regression: цена ~ площадь (statsmodels)
4. Outlier detection: |residual| > 2σ → переоценен/недооценен
5. Plotly scatter + regression line → kaleido → PNG
6. Temp file cleanup в finally блоке bot.py
```

### Side effects

- Создаёт временный PNG файл в `/tmp`
- Файл удаляется в `finally` блоке `handle_document()` в `bot.py`
- Входной CSV тоже удаляется в `finally`

### Ограничения

| Параметр | Значение |
|---|---|
| Макс. размер CSV | Telegram file limit = 20 MB |
| Поддерживаемые форматы | CSV (только) |
| Нестандартные колонки | LLM-guided маппинг; при неудаче — сообщение об ошибке |

---

## [Агентский трек] Качество инструментов

| Инструмент | Guardrail | Gap |
|---|---|---|
| cbr_tool | TTL-кэш, ExternalAPIError | Fallback на кэш при 404/timeout не реализован полностью |
| mortgage_calc | Валидация + ValidationError | Нет верхнего предела суммы и срока |
| search_tool | Relevance filter, anti-spam, prompt constraints | Нет DDG timeout, нет rate limit |
| csv_analysis | `result['error']` handling | Нет ограничения максимального числа строк |

## [Инфраструктурный трек] Надёжность инструментов

| Инструмент | Timeout | Retry | Circuit Breaker |
|---|---|---|---|
| cbr_tool | 10 сек | Нет | Нет (нужен) |
| mortgage_calc | N/A | N/A | N/A |
| search_tool | Библ. default | 1 (timelimit) | Нет (нужен) |
| csv_analysis | Нет | Нет | N/A |

**Gap (высокий приоритет):** Нет circuit breaker для GigaChat и ЦБ РФ — при деградации сервиса каждый запрос будет ждать timeout (30 сек), загружая process thread pool.
