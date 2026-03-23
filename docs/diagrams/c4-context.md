# C4 Context Diagram — FlatAgent

Система, пользователь, внешние сервисы и границы.

```mermaid
C4Context
    title FlatAgent — System Context

    Person(user, "Покупатель квартиры", "Физическое лицо, планирующее покупку недвижимости в России")

    System(flatagent, "FlatAgent", "AI-агент для консультаций по недвижимости: расчёт ипотеки, поиск, сравнение вариантов, анализ прайс-листов")

    System_Ext(telegram, "Telegram", "Мессенджер. Канал взаимодействия с пользователем через бота")
    System_Ext(gigachat, "GigaChat API", "LLM от Сбер. Роутинг запросов, генерация ответов, извлечение фактов (GIGACHAT_API_B2B)")
    System_Ext(cbr, "ЦБ РФ API", "Публичный XML/HTML API. Ключевая ставка и курсы валют (USD/EUR/CNY)")
    System_Ext(duckduckgo, "DuckDuckGo Search", "Поисковый движок. Живой поиск объявлений и новостей рынка недвижимости (без API-ключа)")

    Rel(user, telegram, "Пишет сообщения, загружает CSV", "Telegram App")
    Rel(telegram, flatagent, "Webhook / Polling", "HTTPS JSON")
    Rel(user, flatagent, "REST API запросы", "HTTPS JSON (POST /chat)")

    Rel(flatagent, gigachat, "LLM inference: роутинг, сравнение, форматирование, извлечение фактов", "HTTPS / Sber OAuth2")
    Rel(flatagent, cbr, "GET ключевая ставка и курсы валют", "HTTPS XML/HTML")
    Rel(flatagent, duckduckgo, "Поиск объявлений и новостей рынка", "HTTPS")
    Rel(flatagent, telegram, "Отправка ответов пользователю", "Telegram Bot API")
```

## Ключевые границы

| Граница | Описание |
|---|---|
| **В системе** | LangGraph агент, FastAPI, Telegram bot, SQLite, CSV-анализ |
| **Вне системы** | GigaChat (внешний SaaS), ЦБ РФ (государственный API), DuckDuckGo (поисковик), Telegram (мессенджер) |
| **Out-of-scope PoC** | ЦИАН/Авито API, банковские API, ЕГРН, голосовые сообщения |

## Внешние зависимости и их критичность

| Сервис | Критичность | Fallback |
|---|---|---|
| GigaChat API | Высокая | Keyword-based шаблонные ответы |
| ЦБ РФ API | Средняя | TTL-кэш последнего значения (1 час) |
| DuckDuckGo | Средняя | Текстовый fallback с ссылками на ЦИАН/Авито |
| Telegram API | Высокая | Нет (канал доставки) |
| SQLite (local) | Критическая | Нет fallback — мониторинг обязателен |
