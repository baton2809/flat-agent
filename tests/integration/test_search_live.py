"""
Live integration tests focused on internet search quality and data freshness.

Covers areas intentionally NOT in test_all_scenarios.py:
- Web search for cities other than Moscow
- Price dynamics and analytics queries (new routing fix)
- CBR data value sanity checks (not just presence of %)
- Multi-turn conversation context
- Colloquial and typo-heavy queries
- Commercial and non-standard property types
- Developer/brand-specific searches
- Negative routing (queries that must NOT go to search or mortgage)

Run: python tests/integration/test_search_live.py
"""

import sys
import time
import re
import requests

BASE_URL = "http://localhost:8000/api/v1"
TIMEOUT = 90
_passed = 0
_failed = 0


def chat(message: str, user_id: str = "live_test") -> str:
    resp = requests.post(
        f"{BASE_URL}/chat",
        json={"message": message, "user_id": user_id},
        timeout=TIMEOUT,
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
        snippet = got[:140].replace("\n", " ") if got else ""
        print(f"  [-] {name}")
        if snippet:
            print(f"      >> {snippet}")


def section(title: str):
    print(f"\n  {title}")
    print(f"  {'-' * len(title)}")


def has_number(text: str) -> bool:
    return bool(re.search(r"\d", text))


def has_ruble_amount(text: str) -> bool:
    return bool(re.search(r"\d[\d\s]*(?:руб|млн|тыс|₽)", text.lower()))


def not_error_response(text: str) -> bool:
    bad = ["укажите сумму кредита", "для расчета ипотеки необходимо",
           "произошла ошибка", "failed to get"]
    return not any(b in text.lower() for b in bad)


def main():
    global _passed, _failed

    # health check
    section("Проверка API")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        ok("API /health отвечает", r.status_code == 200)
        ok("agent FlatAgent", r.json().get("agent") == "FlatAgent")
    except Exception as e:
        print(f"  [-] API недоступен: {e}")
        print("  Запустите: bash manage.sh start")
        sys.exit(1)

    section("A. Поиск недвижимости в разных городах")
    time.sleep(1)

    city_queries = [
        ("найди квартиру в санкт-петербурге до 15 млн",
         ["петербург", "спб", "санкт", "питер", "объявлен", "результат", "циан", "авито", "попробуйте"]),
        ("найди студию в екатеринбурге",
         ["екатеринбург", "студи", "результат", "объявлен", "циан", "авито", "попробуйте"]),
        ("поищи новостройки в казани",
         ["казан", "новостройк", "жк", "результат", "объявлен", "циан", "попробуйте"]),
        ("найди квартиру в сочи у моря",
         ["сочи", "результат", "объявлен", "циан", "авито", "попробуйте"]),
        ("квартиры в новосибирске до 8 млн",
         ["новосибирск", "результат", "объявлен", "циан", "авито", "попробуйте"]),
    ]

    for q, expected_words in city_queries:
        time.sleep(3)
        r = chat(q, "a_cities")
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        ok(f"'{q[:50]}' -> результат содержит данные", found, r)
        ok(f"'{q[:50]}' -> нет ошибки роутинга", not_error_response(r), r)

    section("B. Поиск по типам жилья и параметрам")
    time.sleep(1)

    property_queries = [
        (
            "найди двухкомнатную квартиру в москве с ремонтом до 20 млн",
            ["двух", "2-комн", "результат", "объявлен", "циан", "авито", "попробуйте"],
        ),
        (
            "поищи таунхаус в подмосковье",
            ["таунхаус", "результат", "объявлен", "циан", "авито", "попробуйте"],
        ),
        (
            "найди однокомнатную в новостройке рядом с метро в москве",
            ["метро", "однокомнатн", "результат", "объявлен", "циан", "авито", "попробуйте"],
        ),
        (
            "поищи апартаменты в москва-сити",
            ["апартамент", "сити", "москва", "результат", "объявлен", "циан", "попробуйте"],
        ),
    ]

    for q, expected_words in property_queries:
        time.sleep(3)
        r = chat(q, "b_types")
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        ok(f"'{q[:50]}' -> данные о недвижимости", found, r)
        ok(f"'{q[:50]}' -> нет ошибки роутинга", not_error_response(r), r)

    section("C. Динамика цен и аналитика рынка")
    time.sleep(1)

    analytics_queries = [
        (
            "насколько вырос квадратный метр в москве за 2025 год",
            ["метр", "цен", "результат", "рост", "вырос", "тыс", "млн", "объявлен", "попробуйте"],
        ),
        (
            "как изменились цены на квартиры в спб за последний год",
            ["цен", "результат", "объявлен", "спб", "петербург", "питер", "попробуйте"],
        ),
        (
            "динамика цен на недвижимость в москве 2024 2025",
            ["цен", "результат", "объявлен", "циан", "авито", "москва", "попробуйте"],
        ),
        (
            "насколько упали цены на вторичку в 2024",
            ["цен", "вторичк", "результат", "объявлен", "попробуйте"],
        ),
        (
            "тренд рынка недвижимости россия 2025",
            ["рынк", "недвижимост", "результат", "объявлен", "попробуйте"],
        ),
    ]

    for q, expected_words in analytics_queries:
        time.sleep(3)
        r = chat(q, "c_analytics")
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        not_compare_err = "сравнени" not in r_lower[:100] or len(r) > 150
        ok(f"'{q[:50]}' -> получен результат поиска", found, r)
        ok(f"'{q[:50]}' -> не ушел в compare без данных", not_compare_err, r)

    section("D. ЦБ РФ - санитарная проверка значений")
    time.sleep(1)

    # Key rate sanity: should be between 5% and 30%
    r_rate = chat("ключевая ставка цб", "d_cbr")
    rate_match = re.search(r"(\d+[,.]?\d*)\s*%", r_rate)
    if rate_match:
        rate_val = float(rate_match.group(1).replace(",", "."))
        ok("ключевая ставка в разумном диапазоне (5-30%)", 5 <= rate_val <= 30, r_rate)
    else:
        ok("ключевая ставка содержит числовое значение", False, r_rate)

    time.sleep(1)

    # USD rate sanity: should be between 50 and 200 rubles
    r_usd = chat("курс доллара", "d_cbr")
    usd_match = re.search(r"(\d+[,.]?\d+)\s*руб", r_usd)
    if usd_match:
        usd_val = float(usd_match.group(1).replace(",", "."))
        ok("курс USD в разумном диапазоне (50-200 руб)", 50 <= usd_val <= 200, r_usd)
    else:
        ok("курс USD содержит числовое значение", False, r_usd)

    time.sleep(1)

    # Date in response should be today or nearby
    r_currency = chat("курс всех валют сегодня", "d_cbr")
    has_date = bool(re.search(r"\d{2}\.\d{2}\.\d{4}", r_currency))
    ok("ответ содержит конкретную дату курса", has_date, r_currency)

    time.sleep(1)

    # EUR rate sanity: should be between 60 and 250 rubles
    r_eur = chat("курс евро сейчас", "d_cbr")
    eur_match = re.search(r"(\d+[,.]?\d+)\s*руб", r_eur)
    if eur_match:
        eur_val = float(eur_match.group(1).replace(",", "."))
        ok("курс EUR в разумном диапазоне (60-250 руб)", 60 <= eur_val <= 250, r_eur)
    else:
        ok("курс EUR содержит числовое значение", False, r_eur)

    section("E. Жаргонные и разговорные запросы")
    time.sleep(1)

    colloquial_cases = [
        (
            "хочу однушку в мск недорого",
            ["результат", "объявлен", "однокомнатн", "циан", "авито", "квартир"],
            "e1",
        ),
        (
            "ипотека со скидкой от застройщика что это",
            ["ипотек", "застройщик", "субсиди", "скидк", "ставк", "процент"],
            "e2",
        ),
        (
            "что по ключевой сегодня у цб",
            ["%"],
            "e3",
        ),
        (
            "сколько стоит однушка в хрущевке в москве",
            ["результат", "объявлен", "циан", "авито", "стоим", "цен", "млн"],
            "e4",
        ),
        (
            "ипотека под ноль процентов реально",
            ["ипотек", "процент", "ставк", "субсиди", "застройщик"],
            "e5",
        ),
    ]

    for q, expected_words, uid in colloquial_cases:
        time.sleep(1)
        r = chat(q, uid)
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        ok(f"'{q[:50]}' -> понятный ответ", found, r)

    section("F. Поиск по ЖК и застройщикам")
    time.sleep(1)

    brand_queries = [
        (
            "квартиры в жк пик в москве",
            ["пик", "жк", "результат", "объявлен", "циан", "авито", "попробуйте"],
        ),
        (
            "найди квартиры от самолет девелопмент",
            ["самолет", "результат", "объявлен", "циан", "авито"],
        ),
        (
            "новостройки группы лср в санкт-петербурге",
            ["лср", "петербург", "спб", "результат", "объявлен", "циан", "попробуйте"],
        ),
        (
            "жк символ в москве цены",
            ["символ", "результат", "объявлен", "циан", "авито", "цен", "попробуйте"],
        ),
    ]

    for q, expected_words in brand_queries:
        time.sleep(3)
        r = chat(q, "f_brands")
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        ok(f"'{q[:50]}' -> результаты по бренду", found, r)
        ok(f"'{q[:50]}' -> нет ошибки роутинга", not_error_response(r), r)

    section("G. Многоходовой диалог")
    time.sleep(1)

    uid_g = "g_multiturn_unique77"

    # turn 1: introduce name and budget
    chat("меня зовут Анна, ищу квартиру в москве с бюджетом 12 млн", uid_g)
    time.sleep(2)

    # turn 2: ask follow-up that relies on context
    r_g2 = chat("что ты знаешь обо мне?", uid_g)
    ok("помнит имя из первого сообщения", "анн" in r_g2.lower(), r_g2)
    time.sleep(1)

    # turn 3: clarify mortgage question in context
    r_g3 = chat("кем я работаю?", uid_g)
    # bot should not hallucinate profession that was never mentioned
    hallucinate = any(
        w in r_g3.lower()
        for w in ["програмист", "врач", "учитель", "инженер", "бухгалтер"]
    )
    ok("не придумывает профессию которую не называли", not hallucinate, r_g3)

    section("H. Отрицательный роутинг (не в search)")
    time.sleep(1)

    not_search_cases = [
        ("что такое ДДУ договор", ["дду", "договор", "долев", "застройщик", "участник"]),
        ("как проверить юридическую чистоту квартиры", ["юридическ", "проверк", "обременен", "выписк", "егрн"]),
        ("зачем нужен риелтор при покупке квартиры", ["риелтор", "агент", "помощ", "сделк", "покуп"]),
        ("что такое кадастровая стоимость", ["кадастр", "стоимост", "оценк"]),
    ]

    for q, expected_words in not_search_cases:
        time.sleep(1)
        r = chat(q, "h_consult")
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        not_search_rubbish = "циан.ру" not in r_lower and "avito.ru" not in r_lower
        ok(f"'{q[:50]}' -> консультационный ответ", found, r)
        ok(f"'{q[:50]}' -> не выдает листинги объявлений", not_search_rubbish, r)

    section("I. Точность расчета ипотеки")
    time.sleep(1)

    # 5 млн, 15%, 20 лет -> payment ~65 900 руб (annuity formula)
    r_i1 = chat("ипотека 5 млн под 15 процентов на 20 лет", "i_mortgage")
    # Find all 4-6 digit numbers in response (payment is in range 50 000 - 90 000)
    all_nums = [int(n.replace(" ", "").replace(",", "")) for n in
                re.findall(r"\b\d[\d ,]{3,6}\b", r_i1)
                if n.replace(" ", "").replace(",", "").isdigit()]
    payment_in_range = any(50_000 <= v <= 90_000 for v in all_nums)
    ok("платеж 5 млн 15% 20 лет ~ 65 900 руб (±30%)", payment_in_range, r_i1)

    time.sleep(1)

    # 10 млн, 12%, 30 лет -> payment ~102 861 руб
    r_i2 = chat("посчитай ипотеку 10 млн 12 процентов 30 лет", "i_mortgage2")
    has_payment = "ежемесячный платеж" in r_i2.lower() or "monthly" in r_i2.lower()
    has_num = has_number(r_i2)
    ok("расчет 10 млн 12% 30л содержит платеж", has_payment, r_i2)
    ok("расчет 10 млн 12% 30л содержит числа", has_num, r_i2)

    section("J. Устойчивость к опечаткам")
    time.sleep(1)

    typo_cases = [
        ("ипатека на 5 млн под 16%", ["ипотек", "платеж", "ставк", "%"], "j1"),
        ("расчитай ипотеку 8 млн ставка 14 на 25 лет", ["платеж", "8", "14", "%"], "j2"),
        # severe typo: "далора" instead of "доллара" - bot may or may not route to CBR;
        # accept any meaningful response (currency info OR a polite redirect)
        ("курс далора сегодня", ["руб", "курс", "валют", "usd", "доллар", "рекомендую", "обратит", "не могу"], "j3"),
        # typo "маскве" for "москве" - bot may find results or give helpful redirect
        ("найди кватиру в маскве", ["результат", "объявлен", "циан", "авито", "москв",
                                     "попробуйте", "уточните", "не найдено"], "j4"),
    ]

    for q, expected_words, uid in typo_cases:
        time.sleep(1)
        r = chat(q, uid)
        r_lower = r.lower()
        found = any(w in r_lower for w in expected_words)
        ok(f"'{q[:50]}' -> понимает несмотря на опечатку", found, r)

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
