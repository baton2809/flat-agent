"""Circuit breaker for external services (GigaChat, DDG, CBR).

State machine: closed → open → half-open → closed.
When open: immediately raises CircuitOpenError instead of waiting for timeout.
"""

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is in the open state."""


class CircuitBreaker:
    """Simple in-process circuit breaker.

    Usage::

        _cb = CircuitBreaker(failure_threshold=5, window_sec=60, recovery_sec=30)

        if _cb.is_open():
            raise CircuitOpenError("service unavailable")
        try:
            result = call_service()
            _cb.record_success()
            return result
        except Exception:
            _cb.record_failure()
            raise
    """

    def __init__(
        self,
        failure_threshold: int,
        window_sec: float,
        recovery_sec: float,
        name: str = "unnamed",
    ) -> None:
        self.name = name
        self.threshold = failure_threshold
        self.window = window_sec
        self.recovery = recovery_sec

        self._failures: deque = deque()
        self._state = "closed"
        self._opened_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True if requests should be blocked."""
        if self._state == "closed":
            return False

        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.recovery:
                self._state = "half-open"
                logger.info("[circuit_breaker] %s → half-open (trying probe)", self.name)
                return False  # allow one probe request
            return True

        # half-open: allow one probe; next call decides
        return False

    def record_success(self) -> None:
        """Call after a successful request."""
        if self._state != "closed":
            logger.info("[circuit_breaker] %s → closed (recovered)", self.name)
        self._failures.clear()
        self._state = "closed"

    def record_failure(self) -> None:
        """Call after a failed request."""
        now = time.monotonic()
        self._failures.append(now)
        # evict failures outside the window
        while self._failures and self._failures[0] < now - self.window:
            self._failures.popleft()

        if self._state == "half-open" or len(self._failures) >= self.threshold:
            self._state = "open"
            self._opened_at = now
            logger.warning(
                "[circuit_breaker] %s → open (%d failures in %.0fs window)",
                self.name,
                len(self._failures),
                self.window,
            )

    @property
    def state(self) -> str:
        return self._state


# ---------------------------------------------------------------------------
# Module-level singletons — one per external service
# ---------------------------------------------------------------------------

gigachat_cb = CircuitBreaker(
    failure_threshold=5,
    window_sec=60,
    recovery_sec=30,
    name="gigachat",
)

cbr_cb = CircuitBreaker(
    failure_threshold=3,
    window_sec=300,
    recovery_sec=120,
    name="cbr",
)

ddg_cb = CircuitBreaker(
    failure_threshold=3,
    window_sec=60,
    recovery_sec=60,
    name="ddg",
)
