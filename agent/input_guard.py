"""Input validation and prompt injection protection."""

import logging
import re

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 4000

_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+instructions?",
    r"forget\s+(previous|all|above|your)\s+instructions?",
    r"disregard\s+(previous|all|above)\s+instructions?",
    r"you\s+are\s+now\s+(?:a\s+)?(?:an?\s+)?\w+",
    r"act\s+as\s+(?:a\s+)?(?:an?\s+)?\w+\s+(?:without|with\s+no)",
    r"pretend\s+(?:you\s+are|to\s+be)",
    r"игнорируй\s+(?:предыдущие|все|выше)\s+инструкции",
    r"забудь\s+(?:предыдущие|все|свои)\s+инструкции",
    r"ты\s+теперь\s+(?:не|другой|новый)",
    r"system\s*:\s*you",
    r"<\s*system\s*>",
    r"\[INST\]",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def validate_user_message(message: str) -> tuple[bool, str]:
    """Validate a user message for length and prompt injection patterns.

    Returns:
        (True, "") if message is valid.
        (False, reason) if message should be rejected.
    """
    if not message or not message.strip():
        return False, "Сообщение не может быть пустым."
    if len(message) > _MAX_MESSAGE_LEN:
        return False, (
            f"Сообщение слишком длинное ({len(message)} символов). "
            f"Максимум {_MAX_MESSAGE_LEN} символов."
        )
    if _INJECTION_RE.search(message):
        logger.warning("prompt injection attempt detected: %.60s...", message)
        return False, "Сообщение содержит недопустимые инструкции."
    return True, ""
