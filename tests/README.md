# FlatAgent Tests

Структура тестов для проекта FlatAgent.

## Структура

```
tests/
    unit/               # юнит-тесты отдельных компонентов
        test_mortgage_calc.py
        test_routing.py
        test_nodes.py
        test_memory.py
        test_mortgage_node.py
        test_mortgage_parsing.py
        test_error_handling.py
        test_gigachat_connection.py
    integration/        # интеграционные тесты
        test_api.py
        test_full_graph.py
        test_bot_scenarios.py
        test_all_scenarios.py
        test_search_live.py
```

## Запуск тестов

Все юнит-тесты (не нужен запущенный сервер):

```bash
pytest tests/unit/
```

Интеграционные тесты (нужен запущенный сервер на localhost:8000):

```bash
pytest tests/integration/test_api.py
pytest tests/integration/test_full_graph.py
```

Живые тесты качества поиска и ответов:

```bash
python tests/integration/test_search_live.py
python tests/integration/test_all_scenarios.py
```

Отдельный файл:

```bash
pytest tests/unit/test_mortgage_calc.py
```

## Типы тестов

### Unit (unit/)

Тестируют отдельные компоненты в изоляции, без запросов к LLM и внешним сервисам:

- роутинг запросов по типу
- расчет ипотеки
- парсинг параметров из текста
- узлы графа с замоканным LLM
- обработка ошибок
- долговременная память пользователя

### Integration (integration/)

Тестируют взаимодействие компонентов, нужен запущенный сервер:

- FastAPI эндпоинты
- LangGraph граф целиком
- сценарии диалогов
- качество поиска и роутинга на реальных запросах

## Добавление нового теста

Создай файл `test_*.py` в нужной папке и добавь в начало:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```

Затем импортируй нужные модули из проекта.

## Требования

- тесты запускаются из корня проекта
- используй относительные импорты через sys.path
- интеграционные тесты требуют запущенный сервер: `bash manage.sh start`
