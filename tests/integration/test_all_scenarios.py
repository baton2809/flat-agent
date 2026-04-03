"""
Comprehensive integration tests covering all user scenarios from Telegram screenshots.
Tests routing correctness, response content, and edge cases.

Run: python tests/integration/test_all_scenarios.py
"""

import sys
import time
import re
import requests

BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT = 90
_passed = 0
_failed = 0


def chat(message: str, user_id: str = "test_all") -> str:
    """Send message to API and return response text."""
    resp = requests.post(
        f"{BASE_URL}/chat",
        json={"message": message, "user_id": user_id},
        timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()["response"]


def ok(name: str, condition: bool, got: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [+] {name}")
    else:
        _failed += 1
        snippet = got[:120].replace("\n", " ") if got else ""
        print(f"  [-] {name}")
        if snippet:
            print(f"      >> {snippet}")


def section(title: str):
    print(f"\n  {title}")
    print(f"  {'-' * len(title)}")


def main():
    global _passed, _failed

    section("Проверка API")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        data = r.json()
        ok("API /health", r.status_code == 200)
        ok("agent FlatAgent", data.get("agent") == "FlatAgent")
    except Exception as e:
        print(f"  [-] API недоступен: {e}")
        print("  Запустите: bash manage.sh start")
        sys.exit(1)

    section("1. Идентичность бота")
    time.sleep(1)

    r1 = chat("ты кто?", "t1")
    r2 = chat("кто ты?", "t1")
    r3 = chat("что ты умеешь?", "t1")
    r4 = chat("представься", "t1")

    def has_identity(r):
        return "flatagent" in r.lower() or "flat agent" in r.lower() or "flat_agent" in r.lower()

    ok("'ты кто?' -> упоминает FlatAgent", has_identity(r1), r1)
    ok("'ты кто?' -> не попадает в compare", "для сравнения" not in r1.lower() and "запрос некорректен" not in r1.lower(), r1)
    ok("'кто ты?' -> упоминает FlatAgent", has_identity(r2), r2)
    ok("'что ты умеешь?' -> описывает возможности", any(w in r3.lower() for w in ["ипотек", "сравн", "найт", "помог", "недвижимост"]), r3)
    ok("'представься' -> упоминает FlatAgent", has_identity(r4), r4)

    section("2. Расчет ипотеки")
    time.sleep(1)

    cases = [
        ("ипотека на 30 лет по ставке 10 и сумма 10 млн", "10", "t2a"),
        ("расcчитай ипотека на 40 лет по ставке 12 процентов на сумму 12 млн", "12", "t2b"),
        ("ипотека на 20 лет по ставке 16 сумма 20 млн", "16", "t2c"),
        ("ипотека 15% на 25 лет сумма 8 млн", "15", "t2d"),
        ("расчитай мне ипотека при ставке 18 на срок 25 лет сумма 20 млн", "18", "t2e"),
    ]

    for msg, expected_rate, uid in cases:
        r = chat(msg, uid)
        has_rate = f"{expected_rate}.0%" in r or f"{expected_rate}%" in r or f"ставка: {expected_rate}" in r.lower()
        has_payment = "ежемесячный платеж" in r.lower() or "monthly" in r.lower()
        ok(f"ставке {expected_rate} -> рассчитывает с {expected_rate}%", has_rate, r)
        ok(f"ставке {expected_rate} -> содержит ежемесячный платеж", has_payment, r)

    section("3. Ключевая ставка ЦБ РФ")
    time.sleep(1)

    cbr_queries = [
        "ставка цб",
        "ключевая ставка",
        "посмотри какая ключевая ЦБ",
        "какая ключевую ЦБ сейчас",
        "ЦБ ставка сегодня",
        "ставку цб покажи",
        "что сейчас ставка центрального банка",
        "текущая ставка банка России",
    ]

    for q in cbr_queries:
        r = chat(q, "t3")
        has_pct = "%" in r
        not_mortgage_error = "для расчета ипотеки" not in r.lower() and "укажите сумму" not in r.lower()
        ok(f"'{q}' -> возвращает ставку в %", has_pct, r)
        ok(f"'{q}' -> НЕ уходит в mortgage_node", not_mortgage_error, r)

    section("4. Курсы валют ЦБ РФ")
    time.sleep(1)

    currency_queries = [
        ("посмотри какая ключевая ЦБ и курсы валюты на сейчас", ["usd", "eur", "cny", "доллар", "евро", "юань"]),
        ("курс всех валют", ["usd", "eur", "cny", "доллар", "евро", "юань"]),
        ("курс доллара сегодня", ["доллар", "usd", r"\d+[.,]\d+"]),
        ("курс евро сегодня", ["евро", "eur", r"\d+[.,]\d+"]),
        ("какой курс юаня", ["юань", "cny", r"\d+[.,]\d+"]),
    ]

    for q, expected_words in currency_queries:
        r = chat(q, "t4")
        r_lower = r.lower()
        found = any(
            re.search(w, r_lower) if r'\d' in w else w in r_lower
            for w in expected_words
        )
        not_mortgage = "для расчета" not in r_lower and "укажите сумму" not in r_lower
        ok(f"'{q[:45]}' -> содержит данные о валюте", found, r)
        ok(f"'{q[:45]}' -> НЕ уходит в mortgage_node", not_mortgage, r)

    section("5. Долгосрочная память")
    time.sleep(1)

    uid_mem = "t5_memory_unique_99"
    chat("меня зовут Дмитрий, я работаю архитектором", uid_mem)
    time.sleep(2)
    r_name = chat("как меня зовут?", uid_mem)
    r_job = chat("кем я работаю?", uid_mem)
    r_mem = chat("ты меня помнишь?", uid_mem)

    ok("помнит имя после сохранения", "дмитри" in r_name.lower(), r_name)
    ok("не говорит 'не помню'", "не помню" not in r_name.lower() and "не сохраняю" not in r_name.lower(), r_name)
    ok("помнит профессию", "архитект" in r_job.lower(), r_job)
    ok("подтверждает что помнит", any(w in r_mem.lower() for w in ["дмитри", "архитект", "да", "помн"]), r_mem)

    section("6. Поиск недвижимости")
    time.sleep(1)

    search_queries = [
        "найди мне квартиру на вторичном рынке москвы стоимостью до 20 млн",
        "найди однокомнатную квартиру в москве до 8 млн",
        "поищи новостройки в подмосковье",
        "покажи квартиры в химках",
    ]

    for q in search_queries:
        r = chat(q, "t6")
        r_lower = r.lower()
        has_search_content = any(w in r_lower for w in [
            "результат", "поиск", "найден", "объявлен", "предложен",
            "циан", "авито", "домклик", "cian", "avito"
        ])
        not_mortgage = "укажите сумму кредита" not in r_lower
        ok(f"'{q[:45]}' -> поиск выполнен", has_search_content, r)
        ok(f"'{q[:45]}' -> не уходит в mortgage", not_mortgage, r)

    section("7. Сравнение объектов")
    time.sleep(1)

    compare_queries = [
        "сравни первичку и вторичку",
        "что лучше: новостройка или вторичный рынок?",
        "сравни ипотеку 10 млн под 12% и 8 млн под 15%",
    ]

    for q in compare_queries:
        r = chat(q, "t7")
        has_compare = any(w in r.lower() for w in [
            "первичк", "вторичк", "преимущест", "сравнени", "новостройк", "плюс", "минус"
        ])
        ok(f"'{q[:50]}' -> даёт сравнение", has_compare, r)

    section("8. Граничные случаи")
    time.sleep(1)

    edge_cases = [
        ("привет", "приветствие", lambda r: any(w in r.lower() for w in ["привет", "здравствуй", "рад", "помог", "flatagent"])),
        ("стоит ли сейчас покупать квартиру", "консультация", lambda r: len(r) > 50 and "для расчета ипотеки необходимо" not in r.lower()),
        ("какие документы нужны для покупки", "консультация", lambda r: any(w in r.lower() for w in ["документ", "паспорт", "договор", "выписк"])),
        ("что такое эскроу счет", "консультация", lambda r: "эскроу" in r.lower() or "счет" in r.lower()),
    ]

    for msg, intent, check_fn in edge_cases:
        r = chat(msg, "t8")
        ok(f"'{msg[:45]}' -> {intent}", check_fn(r), r)

    total = _passed + _failed
    pct = int(_passed / total * 100) if total > 0 else 0
    print(f"\n  итого: {_passed}/{total} тестов прошло ({pct}%)")

    if _failed == 0:
        print("  все тесты прошли")
    else:
        print(f"  провалилось: {_failed} тестов")
        sys.exit(1)


if __name__ == "__main__":
    main()
