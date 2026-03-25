# C4 Context Diagram — FlatAgent

Система, пользователь, внешние сервисы и границы.

```mermaid
flowchart LR
    USER["👤 Покупатель квартиры\n───────────────\nТелефон / Telegram App\nПланирует покупку недвижимости"]

    subgraph SYSTEM["  FlatAgent  "]
        FA["🤖 FlatAgent\n───────────────\nAI-агент по недвижимости:\nрасчёт ипотеки · поиск\nсравнение · анализ CSV"]
    end

    subgraph EXT["Внешние сервисы"]
        TG["📱 Telegram\nМессенджер\nWebhook / Polling"]
        GC["🧠 GigaChat API\nLLM от Сбер\nGIGACHAT_API_B2B"]
        CBR["🏦 ЦБ РФ API\nКлючевая ставка\nКурсы USD/EUR/CNY"]
        DDG["🔍 DuckDuckGo\nПоиск объявлений\nбез API-ключа"]
    end

    USER -- "сообщения / CSV" --> TG
    TG -- "webhook / polling" --> FA
    USER -- "POST /chat" --> FA
    FA -- "ответы пользователю" --> TG
    FA -- "роутинг · генерация · извлечение фактов\nHTTPS / OAuth2" --> GC
    FA -- "GET ставка + курсы\nHTTPS XML/HTML" --> CBR
    FA -- "поиск ru-ru\nHTTPS" --> DDG
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
