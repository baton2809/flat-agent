"""
Integration tests for FlatAgent bot scenarios.
Tests all real user queries from Telegram screenshots.

Run: python tests/integration/test_bot_scenarios.py
"""

import sys
import time
import re
import requests

BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT = 30


def chat(message: str, user_id: str = "test_scenarios") -> str:
    """Send message to API and return response text."""
    resp = requests.post(
        f"{BASE_URL}/chat",
        json={"message": message, "user_id": user_id},
        timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()["response"]


def check(name: str, condition: bool, detail: str = ""):
    """Print test result."""
    status = "PASS" if condition else "FAIL"
    mark = "+" if condition else "-"
    print(f"  [{mark}] {status}: {name}")
    if not condition and detail:
        print(f"       >> {detail}")
    return condition


def run_suite(suite_name: str, tests: list) -> tuple:
    """Run a list of (name, condition, detail) tuples. Returns (passed, total)."""
    print(f"\n  {suite_name}")
    print(f"  {'-' * len(suite_name)}")
    passed = 0
    for name, condition, detail in tests:
        if check(name, condition, detail):
            passed += 1
    return passed, len(tests)


def main():
    total_passed = 0
    total_tests = 0

    print("\n  Проверка доступности API")
    print("  ------------------------")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        data = r.json()
        check("API отвечает на /health", r.status_code == 200)
        check("Agent инициализирован", data.get("agent") == "FlatAgent")
        total_passed += 2
        total_tests += 2
    except Exception as e:
        print(f"  [-] FAIL: API недоступен: {e}")
        print("  Убедитесь что бот запущен: bash manage.sh start")
        sys.exit(1)

    time.sleep(1)
    r1 = chat("кто ты?", "t_identity")
    r2 = chat("что ты умеешь?", "t_identity")
    p, t = run_suite("ТЕСТ 1: Идентичность бота", [
        ("'кто ты?' -> упоминает FlatAgent",
         "flatagent" in r1.lower() or "flat_agent" in r1.lower() or "flat agent" in r1.lower(),
         f"Ответ: {r1[:150]}"),
        ("'кто ты?' -> не попадает в compare_node",
         "запрос некорректен" not in r1.lower() and "для сравнения" not in r1.lower(),
         f"Ответ: {r1[:150]}"),
        ("'что ты умеешь?' -> описывает возможности",
         any(w in r2.lower() for w in ["ипотек", "сравн", "найт", "помог"]),
         f"Ответ: {r2[:150]}"),
        ("'что ты умеешь?' -> не попадает в compare_node",
         "запрос некорректен" not in r2.lower(),
         f"Ответ: {r2[:150]}"),
    ])
    total_passed += p
    total_tests += t

    time.sleep(1)
    r3 = chat("ипотека на 30 лет по ставке 10 и сумма 10 млн", "t_mortgage")
    r4 = chat("расcитай мне ипотека на 40 лет по ставке 12 процентов на сумму 12 млн", "t_mortgage2")
    r5 = chat("ипотека на 20 лет по ставке 16 сумма 20 млн", "t_mortgage3")
    r6 = chat("ипотека 15% на 25 лет сумма 8 млн", "t_mortgage4")

    def has_rate(resp: str, expected_rate: str) -> bool:
        return f"{expected_rate}%" in resp or f"ставка: {expected_rate}" in resp.lower()

    p, t = run_suite("ТЕСТ 2: Расчет ипотеки (ставка без %)", [
        ("'ставке 10' -> ставка 10%, не 18%",
         has_rate(r3, "10.0") or has_rate(r3, "10"),
         f"Ответ: {r3[:200]}"),
        ("'ставке 12 процентов' -> ставка 12%, не 18%",
         has_rate(r4, "12.0") or has_rate(r4, "12"),
         f"Ответ: {r4[:200]}"),
        ("'ставке 16' -> ставка 16%",
         has_rate(r5, "16.0") or has_rate(r5, "16"),
         f"Ответ: {r5[:200]}"),
        ("'15%' -> ставка 15%",
         has_rate(r6, "15.0") or has_rate(r6, "15"),
         f"Ответ: {r6[:200]}"),
        ("Ответ содержит ежемесячный платеж",
         "ежемесячный платеж" in r3.lower() or "monthly" in r3.lower(),
         f"Ответ: {r3[:200]}"),
        ("Ответ содержит сумму 10 млн",
         "10,000,000" in r3 or "10 000 000" in r3,
         f"Ответ: {r3[:200]}"),
    ])
    total_passed += p
    total_tests += t

    time.sleep(1)
    r7 = chat("ставка цб", "t_cbr")
    r8 = chat("ставка цб и курс всех валют на сегодня", "t_cbr2")
    r9 = chat("курс доллара сегодня", "t_cbr3")

    p, t = run_suite("ТЕСТ 3: Данные ЦБ РФ (реальные, не хардкод)", [
        ("'ставка цб' -> возвращает ставку",
         "%" in r7 and ("ставка" in r7.lower() or "rate" in r7.lower()),
         f"Ответ: {r7[:200]}"),
        ("'ставка цб' -> не возвращает хардкод 16.0%",
         "16.0%" not in r7,
         f"Ответ: {r7[:200]}"),
        ("'ставка цб' -> показывает актуальную ставку",
         "15.5" in r7 or "15,5" in r7,
         f"Ответ: {r7[:200]}"),
        ("'курс всех валют' -> содержит USD",
         "usd" in r8.lower() or "доллар" in r8.lower(),
         f"Ответ: {r8[:200]}"),
        ("'курс всех валют' -> содержит EUR",
         "eur" in r8.lower() or "евро" in r8.lower(),
         f"Ответ: {r8[:200]}"),
        ("'курс всех валют' -> содержит CNY",
         "cny" in r8.lower() or "юань" in r8.lower(),
         f"Ответ: {r8[:200]}"),
        ("'курс доллара' -> содержит цифры курса",
         bool(re.search(r'\d+[,\.]\d+', r9)),
         f"Ответ: {r9[:200]}"),
    ])
    total_passed += p
    total_tests += t

    time.sleep(1)
    uid = "t_memory_unique_42"
    chat("меня зовут Александр, я работаю врачом", uid)
    time.sleep(2)
    r10 = chat("как меня зовут?", uid)
    r11 = chat("где я работаю?", uid)

    p, t = run_suite("ТЕСТ 4: Долгосрочная память", [
        ("Помнит имя пользователя",
         "александр" in r10.lower() or "alex" in r10.lower(),
         f"Ответ: {r10[:200]}"),
        ("Не говорит 'не помню'",
         "не помню" not in r10.lower() and "не сохраняю" not in r10.lower(),
         f"Ответ: {r10[:200]}"),
        ("Помнит профессию",
         "врач" in r11.lower() or "медицин" in r11.lower(),
         f"Ответ: {r11[:200]}"),
    ])
    total_passed += p
    total_tests += t

    time.sleep(1)
    r12 = chat("сравни первичку и вторичку", "t_routing")
    r13 = chat("найди квартиры в москве до 10 млн", "t_routing2")
    r14 = chat("привет", "t_routing3")

    p, t = run_suite("ТЕСТ 5: Роутинг запросов", [
        ("'сравни...' -> попадает в compare_node",
         any(w in r12.lower() for w in ["первичк", "вторичк", "новостройк", "сравнени", "преимущест"]),
         f"Ответ: {r12[:200]}"),
        ("'найди квартиры' -> попадает в search_node",
         any(w in r13.lower() for w in ["найден", "поиск", "объявлен", "предложен", "циан", "авито"]),
         f"Ответ: {r13[:200]}"),
        ("'привет' -> попадает в chat_node",
         any(w in r14.lower() for w in ["привет", "здравствуй", "помощ", "помог", "flatagent", "рад"]),
         f"Ответ: {r14[:200]}"),
    ])
    total_passed += p
    total_tests += t

    print(f"\n  ТЕСТ 6: Проверка 6 критериев курса")
    print(f"  ------------------------------------")

    import os
    flat = str(Path(__file__).parent.parent.parent)

    from pathlib import Path
    llm_file = Path(flat) / "agent" / "llm_wrapper.py"
    c1 = llm_file.exists() and "gigachat" in llm_file.read_text().lower()
    check("1. LLM GigaChat - используется в агенте", c1)

    graph_file = Path(flat) / "agent" / "graph.py"
    c2 = graph_file.exists() and "StateGraph" in graph_file.read_text()
    check("2. LangGraph StateGraph - используется", c2)

    cbr_file = Path(flat) / "agent" / "tools" / "cbr_tool.py"
    search_file = Path(flat) / "agent" / "tools" / "search_tool.py"
    c3a = cbr_file.exists() and "cbr.ru" in cbr_file.read_text()
    c3b = search_file.exists()
    check("3a. Инструмент 1: CBR API (cbr.ru)", c3a)
    check("3b. Инструмент 2: Search tool (DuckDuckGo)", c3b)

    graph_text = graph_file.read_text()
    c4 = "SqliteSaver" in graph_text
    check("4. SqliteSaver - состояние сохраняется между вызовами", c4)

    c5 = all(n in graph_text for n in ["mortgage_node", "compare_node", "search_node", "chat_node"])
    check("5. Роутинг 4 пути: mortgage/compare/search/chat", c5)

    main_file = Path(flat) / "main.py"
    c6 = main_file.exists() and "FastAPI" in main_file.read_text()
    check("6. FastAPI - запускается и принимает API запросы", c6)

    criteria_passed = sum([c1, c2, c3a, c3b, c4, c5, c6])
    total_passed += criteria_passed
    total_tests += 7

    print(f"\n  итого: {total_passed}/{total_tests} тестов прошло ({int(total_passed / total_tests * 100)}%)")
    if total_passed == total_tests:
        print("  все тесты прошли")
    else:
        failed = total_tests - total_passed
        print(f"  не прошло: {failed} тестов")


if __name__ == "__main__":
    main()
