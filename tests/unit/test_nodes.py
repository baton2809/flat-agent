#!/usr/bin/env python3
"""Node integration tests for FlatAgent - runs each node type against real queries."""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, AIMessage
from agent.nodes.search import search_node
from agent.nodes.mortgage import mortgage_node
from agent.nodes.chat import chat_node
from agent.nodes.compare import compare_node
from agent.tools.mortgage_calc import calculate_mortgage


def test_search_node():
    test_cases = [
        "Найди квартиру в Москве до 10 млн",
        "1 комнатная квартира ЖК Респект",
        "Новостройки в Подольске",
        "Квартиры в Купчино до 5 миллионов"
    ]

    for query in test_cases:
        print(f"\nтестируем: {query}")
        try:
            state = {"messages": [HumanMessage(content=query)], "user_id": "test"}
            result = search_node(state)

            if "messages" in result and len(result["messages"]) > 0:
                response = result["messages"][0].content
                print(f"  ответ получен: {len(response)} символов")

                if any(keyword in response.lower() for keyword in ["найден", "результат", "квартир", "цен"]):
                    print("  ok: ответ содержит релевантную информацию")
                else:
                    print("  warn: ответ может быть нерелевантным")
            else:
                print("  fail: пустой ответ")

        except Exception as e:
            print(f"  error: {e}")


def test_mortgage_node():
    test_cases = [
        "Рассчитай ипотеку на 5 млн на 20 лет",
        "Какой платеж по ипотеке 8 млн под 16%?",
        "Ипотечный калькулятор 3 миллиона на 15 лет"
    ]

    for query in test_cases:
        print(f"\nтестируем: {query}")
        try:
            state = {"messages": [HumanMessage(content=query)], "user_id": "test"}
            result = mortgage_node(state)

            if "messages" in result and len(result["messages"]) > 0:
                response = result["messages"][0].content
                print(f"  ответ получен: {len(response)} символов")

                if any(keyword in response.lower() for keyword in ["платеж", "ипотек", "расчет", "рубл"]):
                    print("  ok: ответ содержит ипотечную информацию")
                else:
                    print("  warn: ответ может быть нерелевантным")
            else:
                print("  fail: пустой ответ")

        except Exception as e:
            print(f"  error: {e}")


def test_chat_node():
    test_cases = [
        "Как выбрать квартиру в новостройке?",
        "Что такое эскроу счета?",
        "Какие документы нужны для покупки жилья?",
        "Как проверить застройщика?"
    ]

    for query in test_cases:
        print(f"\nтестируем: {query}")
        try:
            state = {"messages": [HumanMessage(content=query)], "user_id": "test"}
            result = chat_node(state)

            if "messages" in result and len(result["messages"]) > 0:
                response = result["messages"][0].content
                print(f"  ответ получен: {len(response)} символов")

                if any(keyword in response.lower() for keyword in ["рекомендую", "советую", "важно", "необходимо", "стоит"]):
                    print("  ok: ответ содержит консультационную информацию")
                else:
                    print("  warn: ответ может быть нерелевантным")
            else:
                print("  fail: пустой ответ")

        except Exception as e:
            print(f"  error: {e}")


def test_compare_node():
    test_cases = [
        "Сравни ЖК Респект и ЖК Северная корона",
        "Что лучше: первичка или вторичка?",
        "Новостройка или готовое жилье?",
        "Центр города vs спальный район"
    ]

    for query in test_cases:
        print(f"\nтестируем: {query}")
        try:
            state = {"messages": [HumanMessage(content=query)], "user_id": "test"}
            result = compare_node(state)

            if "messages" in result and len(result["messages"]) > 0:
                response = result["messages"][0].content
                print(f"  ответ получен: {len(response)} символов")

                if any(keyword in response.lower() for keyword in ["сравнение", "отличи", "преимущества", "недостатки", "лучше"]):
                    print("  ok: ответ содержит сравнительную информацию")
                else:
                    print("  warn: ответ может быть нерелевантным")
            else:
                print("  fail: пустой ответ")

        except Exception as e:
            print(f"  error: {e}")


def test_mortgage_calculator_directly():
    test_cases = [
        {"amount": 5000000, "rate": 16.0, "years": 20},
        {"amount": 8000000, "rate": 15.5, "years": 25},
        {"amount": 3000000, "rate": 17.0, "years": 15}
    ]

    for case in test_cases:
        print(f"\nтестируем: {case['amount']} руб, {case['rate']}%, {case['years']} лет")
        try:
            term_months = case['years'] * 12
            result = calculate_mortgage(case['amount'], case['rate'], term_months)
            print(f"  ежемесячный платеж: {result['monthly_payment']:,.2f} руб")
            print(f"  общая переплата: {result['overpayment']:,.2f} руб")
            print(f"  процент переплаты: {result['overpayment_percent']:.1f}%")
            print("  ok: расчет выполнен успешно")
        except Exception as e:
            print(f"  error: {e}")


def run_all_node_tests():
    print("комплексное тестирование узлов flatagent")
    print("="*60)

    for fn in [test_search_node, test_mortgage_node, test_chat_node, test_compare_node, test_mortgage_calculator_directly]:
        try:
            fn()
        except Exception as e:
            print(f"error в {fn.__name__}: {e}")

    print("\n" + "="*60)
    print("тестирование завершено")


if __name__ == "__main__":
    run_all_node_tests()
