"""Property comparison node with LLM-enhanced responses."""

import logging
from typing import Dict
from langchain_core.messages import AIMessage, HumanMessage
from agent.state import AgentState
from agent.direct_llm_call import llm_call_direct, create_dialog
from agent.exceptions import LLMError
from agent.error_handler import node_error_response

logger = logging.getLogger(__name__)


def compare_node(state: AgentState) -> Dict:
    """Handle property comparison requests with intelligent LLM analysis."""
    messages = state.get('messages', [])

    last_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    try:
        response = generate_comparison_response(last_message)
    except Exception as e:
        return node_error_response(e, __name__)

    new_message = AIMessage(content=response)
    return {"messages": [new_message]}


def generate_comparison_response(user_query: str) -> str:
    """Generate intelligent comparison using LLM."""

    system_prompt = """Ты эксперт по сравнению недвижимости для Telegram бота. Анализируй запросы на сравнение и давай детальные ответы.

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Используй только **жирный** и *курсив* (Telegram Markdown)
- НЕ используй ### заголовки, > цитаты, --- разделители
- Выделяй важную информацию **жирным**
- Используй простые списки с дефисами

ЗАДАЧА: Сравнить объекты недвижимости или дать рекомендации по выбору.

ТИПЫ СРАВНЕНИЯ:
1. КОНКРЕТНЫЕ ОБЪЕКТЫ (ЖК, квартиры с ценами/площадями)
2. ОБЩИЕ КАТЕГОРИИ (первичка vs вторичка, центр vs окраина)
3. РАЙОНЫ И ЛОКАЦИИ
4. ТИПЫ ЖИЛЬЯ (студия vs однушка, дом vs квартира)

СТРУКТУРА:
**Сравнение вариантов:**

**Вариант 1:**
- Плюсы и характеристики
- Минусы и ограничения

**Вариант 2:**
- Плюсы и характеристики
- Минусы и ограничения

**Рекомендации:**
- Конкретные советы с обоснованием

СТИЛЬ: Конкретный, информативный, только Telegram Markdown. Не менее 500 символов."""

    comparison_prompt = f"""Пользователь просит сравнение: "{user_query}"

Проанализируй запрос и дай детальное сравнение с конкретными рекомендациями:"""

    try:
        dialog = create_dialog(system_prompt, comparison_prompt)
        comparison_text = llm_call_direct(dialog, temperature=0.3)

        if comparison_text and len(comparison_text.strip()) > 100:
            return comparison_text.strip()

        raise LLMError("llm returned insufficient response")

    except LLMError as e:
        logger.warning("llm comparison failed: %s", e)

        # Fallback: keyword-based static comparison
        if any(word in user_query.lower() for word in ['первичка', 'вторичка', 'новостройка', 'готовое']):
            return """**Первичное vs Вторичное жилье**

**Первичка (новостройки):**
- Современная планировка и инфраструктура
- Новые коммуникации и системы
- Возможность покупки на этапе строительства
- *Минусы:* риски недостроя, выше цена за кв.м

**Вторичка (готовое жилье):**
- Можно сразу въехать и оценить состояние
- Сложившаяся инфраструктура района
- Возможность торговаться в цене
- *Минусы:* потребность в ремонте, устаревшие коммуникации

**Рекомендация:** Для инвестиций - первичка в перспективных районах. Для жизни - качественная вторичка в развитом районе."""

        elif any(word in user_query.lower() for word in ['центр', 'спальный', 'район', 'округ']):
            return """**Центр vs Спальные районы**

**Центр города:**
- Развитая транспортная доступность
- Множество учреждений и развлечений
- Высокая ликвидность недвижимости
- Престижный адрес
- *Минусы:* очень высокая стоимость, шум, проблемы с парковкой

**Спальные районы:**
- Более доступная цена
- Тихая, спокойная обстановка
- Больше зелени и свежего воздуха
- Просторные дворы и парковки
- *Минусы:* далеко от работы, меньше транспорта, ограниченная инфраструктура

**Рекомендация:** Центр - для молодых профессионалов и инвесторов. Спальные районы - для семей с детьми."""

        else:
            return """**Для качественного сравнения укажите:**

- **Конкретные объекты** с характеристиками (площадь, цена, район)
- **Тип сравнения** (новостройка vs вторичка, разные районы)
- **Важные критерии** (бюджет, транспорт, инфраструктура)

**Примеры запросов:**
- "Сравни ЖК Северная корона и ЖК Респект"
- "Что лучше: студия в центре или однушка на окраине?"
- "Первичка vs вторичка для инвестиций"

Уточните детали для точного сравнения."""
