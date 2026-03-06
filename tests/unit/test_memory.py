"""Unit tests for agent/memory.py - LongTermMemory class."""

import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def _make_memory():
    """Create a LongTermMemory instance backed by an in-memory SQLite DB."""
    from agent.memory import LongTermMemory

    mem = LongTermMemory.__new__(LongTermMemory)
    mem._db_path = ":memory:"
    import threading
    mem._local = threading.local()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    mem._local.conn = conn

    mem._ensure_table()
    return mem


def test_get_user_facts_empty():
    mem = _make_memory()
    assert mem.get_user_facts("user1") == []


def test_add_user_fact_stores_fact():
    mem = _make_memory()
    mem.add_user_fact("user1", "Пользователь работает программистом")
    facts = mem.get_user_facts("user1")
    assert len(facts) == 1
    assert "программистом" in facts[0]


def test_add_user_fact_ignores_duplicate():
    mem = _make_memory()
    fact = "Пользователь работает программистом"
    mem.add_user_fact("user1", fact)
    mem.add_user_fact("user1", fact)
    facts = mem.get_user_facts("user1")
    assert len(facts) == 1


def test_add_user_fact_different_users():
    mem = _make_memory()
    mem.add_user_fact("user1", "Факт для пользователя 1")
    mem.add_user_fact("user2", "Факт для пользователя 2")
    assert len(mem.get_user_facts("user1")) == 1
    assert len(mem.get_user_facts("user2")) == 1
    assert mem.get_user_facts("user3") == []


def test_get_memory_context_empty():
    mem = _make_memory()
    ctx = mem.get_memory_context("user1")
    assert ctx == ""


def test_get_memory_context_with_facts():
    mem = _make_memory()
    mem.add_user_fact("user1", "Пользователя зовут Иван")
    mem.add_user_fact("user1", "Бюджет пользователя: 10 млн")
    ctx = mem.get_memory_context("user1")
    assert "Иван" in ctx
    assert "10 млн" in ctx
    assert ctx.startswith("Факты о пользователе:")


def test_extract_and_store_facts_empty_message():
    mem = _make_memory()
    result = mem.extract_and_store_facts("user1", "")
    assert result is False
    result = mem.extract_and_store_facts("user1", "   ")
    assert result is False


def test_regex_fallback_name():
    mem = _make_memory()
    fact = mem._extract_fact_by_regex("меня зовут Алексей")
    assert fact is not None
    assert "Алексей" in fact


def test_regex_fallback_budget():
    mem = _make_memory()
    fact = mem._extract_fact_by_regex("у меня есть 5 млн рублей на квартиру")
    assert fact is not None
    assert "5" in fact


def test_regex_fallback_family():
    mem = _make_memory()
    fact = mem._extract_fact_by_regex("у меня жена и двое детей")
    assert fact is not None
    assert "семью" in fact.lower() or "жена" in fact.lower() or "Пользователь" in fact


def test_regex_fallback_no_match():
    mem = _make_memory()
    fact = mem._extract_fact_by_regex("расскажи про ипотеку")
    assert fact is None


def test_delete_user_facts_removes_all():
    """delete_user_facts clears all facts for a user without affecting other users."""
    mem = _make_memory()
    mem.add_user_fact("user1", "Пользователя зовут Артур")
    mem.add_user_fact("user1", "Бюджет: 5 млн")
    mem.add_user_fact("user2", "Пользователя зовут Мария")

    mem.delete_user_facts("user1")

    assert mem.get_user_facts("user1") == []
    assert mem.get_user_facts("user2") == ["Пользователя зовут Мария"]


def test_delete_user_facts_noop_on_unknown_user():
    """delete_user_facts does not raise when user has no stored facts."""
    mem = _make_memory()
    mem.delete_user_facts("nonexistent_user")
    assert mem.get_user_facts("nonexistent_user") == []


def test_cleanup_old_checkpoints_no_table():
    mem = _make_memory()
    mem.cleanup_old_checkpoints(keep_per_thread=5)


def run_tests():
    tests = [
        test_get_user_facts_empty,
        test_add_user_fact_stores_fact,
        test_add_user_fact_ignores_duplicate,
        test_add_user_fact_different_users,
        test_get_memory_context_empty,
        test_get_memory_context_with_facts,
        test_extract_and_store_facts_empty_message,
        test_regex_fallback_name,
        test_regex_fallback_budget,
        test_regex_fallback_family,
        test_regex_fallback_no_match,
        test_delete_user_facts_removes_all,
        test_delete_user_facts_noop_on_unknown_user,
        test_cleanup_old_checkpoints_no_table,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL {test.__name__}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
