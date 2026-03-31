"""Prometheus metrics definitions for FlatAgent.

All metrics are module-level singletons — import and use anywhere.

Usage::

    from agent.metrics import request_total, request_duration, llm_calls_total

    request_total.labels(route="mortgage").inc()
    with request_duration.labels(route="mortgage").time():
        ...
"""

from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# Request metrics
# ---------------------------------------------------------------------------

request_total = Counter(
    "flatagent_request_total",
    "Total requests processed",
    labelnames=["route"],  # mortgage | compare | search | chat
)

request_duration = Histogram(
    "flatagent_request_duration_seconds",
    "End-to-end request latency",
    labelnames=["route"],
    buckets=[0.5, 1, 2, 5, 10, 15, 30],
)

# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------

llm_calls_total = Counter(
    "flatagent_llm_calls_total",
    "GigaChat API calls",
    labelnames=["node", "status"],  # node: router/memory/compare/search/chat; status: ok/error/fallback
)

llm_duration = Histogram(
    "flatagent_llm_duration_seconds",
    "GigaChat call latency",
    labelnames=["node"],
    buckets=[0.5, 1, 2, 5, 10, 30],
)

# ---------------------------------------------------------------------------
# External API metrics
# ---------------------------------------------------------------------------

external_errors = Counter(
    "flatagent_external_api_errors_total",
    "External API failures",
    labelnames=["service"],  # gigachat | cbr | duckduckgo
)

circuit_breaker_open = Gauge(
    "flatagent_circuit_breaker_open",
    "Circuit breaker state (1=open, 0=closed)",
    labelnames=["service"],
)

# ---------------------------------------------------------------------------
# Infrastructure metrics
# ---------------------------------------------------------------------------

fallback_total = Counter(
    "flatagent_fallback_total",
    "Fallback activations",
    labelnames=["type"],  # llm_keyword | regex_memory | template_compare | template_search
)

db_size_bytes = Gauge(
    "flatagent_db_size_bytes",
    "checkpoints.db file size in bytes",
)

memory_facts_total = Gauge(
    "flatagent_memory_facts_total",
    "Total facts stored in user_memory table",
)

rate_limit_hits = Counter(
    "flatagent_rate_limit_hits_total",
    "Rate limit rejections",
    labelnames=["channel"],  # api | telegram
)
