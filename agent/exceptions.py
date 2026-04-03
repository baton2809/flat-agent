"""Custom exception hierarchy for FlatAgent."""


class FlatAgentError(Exception):
    """Base exception for all FlatAgent errors."""


class LLMError(FlatAgentError):
    """GigaChat or other LLM call failed."""


class ExternalAPIError(FlatAgentError):
    """External API (CBR, DuckDuckGo) call failed."""


class ValidationError(FlatAgentError):
    """Invalid input parameters provided by the user."""
