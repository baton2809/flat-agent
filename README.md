# FlatAgent

Телеграм-бот и REST API для помощи с недвижимостью. Отвечает на вопросы о покупке квартиры, считает ипотеку, ищет объявления, показывает курсы валют и ключевую ставку ЦБ.

## Что умеет

- Рассчитывает ипотеку по сумме, ставке и сроку, подтягивает актуальную ставку ЦБ автоматически
- Ищет объявления о квартирах через интернет (Циан, Авито и другие)
- Анализирует CSV-файлы с данными о недвижимости и строит графики
- Сравнивает варианты квартир между собой
- Отвечает на общие вопросы о рынке, ипотеке, ДДУ и прочем
- Запоминает факты о пользователе между сессиями (имя, бюджет, предпочтения)

## Стек

- Python 3.11+
- FastAPI - REST API сервер
- LangGraph - оркестрация агента в виде графа узлов
- GigaChat (Сбер) - языковая модель
- SQLite - хранение истории диалогов и памяти пользователя
- python-telegram-bot - интеграция с Telegram
- pandas + matplotlib - анализ и визуализация данных

## Структура проекта

```
flat_agent/
    agent/
        nodes/          # узлы графа: router, mortgage, search, compare, chat, memory
        tools/          # инструменты: ЦБ РФ, поиск, ипотечный калькулятор, CSV-анализ
        graph.py        # сборка LangGraph-графа
        memory.py       # долговременная память пользователя
        llm_wrapper.py  # обёртка над GigaChat API
    api/
        routes.py       # FastAPI эндпоинты
    telegram_bot/
        bot.py          # Telegram webhook-бот
    eval/
        run_eval.py     # оценка качества ответов
    tests/
        unit/           # юнит-тесты компонентов
        integration/    # интеграционные тесты API и графа
    config.py           # настройки из переменных окружения
    main.py             # точка входа, запуск сервера
```

## Быстрый старт

**1. Создай файл `.env` в папке `flat_agent/`:**

```
GIGACHAT_CREDENTIALS=<твои креды от GigaChat API>
GIGACHAT_SCOPE=GIGACHAT_API_B2B
TELEGRAM_BOT_TOKEN=<токен бота из BotFather>
WEBHOOK_URL=https://your-domain.com
```

**2. Установи зависимости:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Запусти сервер:**

```bash
cd flat_agent
python main.py
```

Или через скрипт управления из корня проекта:

```bash
bash manage.sh start
```

Сервер поднимается на `http://localhost:8000`.

## API

После запуска доступны два эндпоинта:

**Проверка состояния:**
```
GET /api/v1/health
```

**Отправить сообщение:**
```
POST /api/v1/chat
Content-Type: application/json

{
  "message": "посчитай ипотеку 6 млн на 20 лет",
  "user_id": "user123"
}
```

## Telegram

Бот работает через webhook. После запуска сервера зарегистрируй webhook вручную:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/webhook/telegram"
```

При локальной разработке удобно использовать ngrok для проброса порта.

## Тесты

```bash
# юнит-тесты (без запущенного сервера)
pytest tests/unit/

# интеграционные тесты (нужен запущенный сервер)
pytest tests/integration/

# живые тесты качества поиска и ответов
python tests/integration/test_search_live.py
```
