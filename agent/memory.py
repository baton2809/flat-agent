"""Long-term memory management using SQLite for thread-safe persistence."""

import hashlib
import logging
import re
import sqlite3
import threading
import time
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_settings, get_llm

logger = logging.getLogger(__name__)

_MEMORY_TTL_DAYS = 30

_MEMORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS user_memory (
    user_id    TEXT NOT NULL,
    fact       TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    UNIQUE(user_id, fact)
)
"""

_MEMORY_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_user_memory_user_id ON user_memory(user_id)"
)


class MemoryExtractionFormat(BaseModel):
    """Structure for memory extraction results."""
    there_is_a_fact_to_remember: bool = Field(description="Есть ли факт для запоминания")
    fact_to_remember: str = Field(description="Факт для запоминания", default="")


class LongTermMemory:
    """Thread-safe long-term memory backed by the same SQLite DB as checkpoints."""

    def __init__(self):
        self._db_path = str(get_settings().db_path)
        self._local = threading.local()
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection (thread-local, so thread-safe)."""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _ensure_table(self) -> None:
        conn = self._conn()
        conn.execute(_MEMORY_TABLE_DDL)
        conn.execute(_MEMORY_INDEX_DDL)
        conn.commit()

    def get_user_facts(self, user_id: str) -> list[str]:
        """Return all stored facts for a user."""
        rows = self._conn().execute(
            "SELECT fact FROM user_memory WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r["fact"] for r in rows]

    def add_user_fact(self, user_id: str, fact: str) -> None:
        """Persist a fact; silently ignores duplicates."""
        try:
            self._conn().execute(
                "INSERT OR IGNORE INTO user_memory (user_id, fact) VALUES (?, ?)",
                (user_id, fact),
            )
            self._conn().commit()
            uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
            logger.info("stored fact for user %s: %s", uid_hash, fact)
        except sqlite3.Error as exc:
            uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
            logger.error("failed to store fact for user %s: %s", uid_hash, exc)

    def delete_user_facts(self, user_id: str) -> None:
        """Remove all stored facts for a user (called on /start or /forget)."""
        uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        try:
            self._conn().execute(
                "DELETE FROM user_memory WHERE user_id = ?", (user_id,)
            )
            self._conn().commit()
            logger.info("cleared all facts for user %s", uid_hash)
        except sqlite3.Error as exc:
            logger.error("failed to clear facts for user %s: %s", uid_hash, exc)

    def get_memory_context(self, user_id: str) -> str:
        """Return formatted memory context for injection into LLM prompts."""
        facts = self.get_user_facts(user_id)
        if not facts:
            return ""
        return "Факты о пользователе:\n- " + "\n- ".join(facts)

    def get_user_name(self, user_id: str) -> str | None:
        """Return the stored name of the user, or None if unknown.

        Handles various phrasings GigaChat or regex might store:
        - "Пользователя зовут Алексей"
        - "Пользователь назвал свое имя Алексей"
        - "Пользователь представился как Алексей"
        """
        _name_patterns = (
            r"зовут\s+(\w+)",
            r"имя\s+(\w+)",
            r"представился\s+(?:как\s+)?(\w+)",
            r"назвал[аось]*\s+(?:себя\s+|свое\s+имя\s+|своё\s+имя\s+)?([А-ЯЁ][а-яё]+)",
        )
        for fact in self.get_user_facts(user_id):
            for pattern in _name_patterns:
                m = re.search(pattern, fact, re.IGNORECASE)
                if m:
                    name = m.group(1).strip(".,!?")
                    if len(name) >= 2:
                        return name
        return None

    def extract_and_store_facts(self, user_id: str, user_message: str) -> bool:
        """Extract facts from the user message and persist them.

        Uses LLM as primary extractor; falls back to regex patterns on failure.
        """
        if not user_message.strip():
            return False

        uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        logger.info("memory extraction for user %s: %.50s", uid_hash, user_message)

        prompt = (
            "Определи, содержит ли сообщение пользователя факт, который стоит запомнить "
            "(имя, бюджет, предпочтения, семья, работа, местоположение).\n"
            "Если да - сформулируй его одним предложением в формате "
            "'Пользователь <факт>'.\n"
            "Если нет - ответь 'нет'.\n\n"
            f"Сообщение: {user_message}"
        )

        llm_extracted = False
        try:
            response = get_llm().invoke([
                SystemMessage(content="Ты помощник по извлечению фактов из диалога."),
                HumanMessage(content=prompt),
            ])
            text = response.content.strip()
            if not (text.lower().startswith("нет") or len(text) < 10):
                # Take first non-empty line that mentions the user
                for line in text.splitlines():
                    line = line.strip()
                    if len(line) > 15 and "пользовател" in line.lower():
                        self.add_user_fact(user_id, line)
                        llm_extracted = True
                        break
        except Exception as exc:
            logger.error("llm memory extraction failed for user %s: %s", uid_hash, exc)

        if llm_extracted:
            return True

        # Regex fallback
        fact = self._extract_fact_by_regex(user_message)
        if fact:
            self.add_user_fact(user_id, fact)
            return True
        return False

    def _extract_fact_by_regex(self, message: str) -> Optional[str]:
        """Simple regex-based fact extraction used as a fallback."""
        msg = message.lower()

        # "меня зовут Алексей", "зовут Алексей", "зовут меня Алексей", "мое имя Алексей", "называй меня Алексей"
        for pattern in (
            r"меня зовут\s+(\w+)",
            r"зовут меня\s+(\w+)",        # "Зовут меня Дмитрий"
            r"(?<!\w)зовут\s+(?!меня\b)(\w+)",  # "зовут Алексей" но не "зовут меня"
            r"(?:мое|моё)\s+имя\s+(\w+)",
            r"называй меня\s+(\w+)",
        ):
            m = re.search(pattern, msg)
            if m:
                return f"Пользователя зовут {m.group(1).capitalize()}"

        m = re.search(r"(\d[\d.,]*)\s*(?:млн|миллион)", msg)
        if m:
            return f"Бюджет пользователя: {m.group(0)}"

        if any(w in msg for w in ("семья", "жена", "муж", "дети", "ребёнок", "ребенок")):
            return f"Пользователь упомянул семью: {message[:120]}"

        if any(w in msg for w in ("работаю", "работает")):
            return f"Пользователь упомянул работу: {message[:120]}"

        return None

    def cleanup_stale_facts(self) -> int:
        """Delete memory facts older than _MEMORY_TTL_DAYS days."""
        cutoff = int(time.time()) - _MEMORY_TTL_DAYS * 86400
        cur = self._conn().execute(
            "DELETE FROM user_memory WHERE created_at < ?", (cutoff,)
        )
        self._conn().commit()
        deleted = cur.rowcount
        logger.info("cleanup_stale_facts: removed %d expired facts", deleted)
        return deleted

    def cleanup_old_checkpoints(self, keep_per_thread: int = 5) -> None:
        """Remove old LangGraph checkpoints keeping the latest N per thread.

        Runs VACUUM afterward to reclaim disk space.
        """
        conn = self._conn()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "checkpoints" not in tables:
                return

            conn.execute(
                """
                DELETE FROM checkpoints
                WHERE rowid NOT IN (
                    SELECT rowid FROM (
                        SELECT rowid, ROW_NUMBER() OVER (
                            PARTITION BY thread_id ORDER BY rowid DESC
                        ) AS rn
                        FROM checkpoints
                    ) ranked
                    WHERE rn <= ?
                )
                """,
                (keep_per_thread,),
            )

            if "checkpoint_blobs" in tables:
                conn.execute(
                    """
                    DELETE FROM checkpoint_blobs
                    WHERE (thread_id, checkpoint_ns, channel, version) NOT IN (
                        SELECT thread_id, checkpoint_ns, channel, version
                        FROM checkpoints
                    )
                    """
                )

            if "checkpoint_writes" in tables:
                conn.execute(
                    """
                    DELETE FROM checkpoint_writes
                    WHERE (thread_id, checkpoint_ns, checkpoint_id) NOT IN (
                        SELECT thread_id, checkpoint_ns, checkpoint_id
                        FROM checkpoints
                    )
                    """
                )

            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
            logger.info("checkpoint cleanup complete (keep_per_thread=%d)", keep_per_thread)

        except Exception as exc:
            logger.error("checkpoint cleanup failed: %s", exc)


memory_manager = LongTermMemory()
