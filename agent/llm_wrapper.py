"""Custom LLM wrapper for GigaChat integration."""

import logging
from typing import List, Optional, Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    after_log,
)
from config import get_settings
from agent.circuit_breaker import gigachat_cb, CircuitOpenError

logger = logging.getLogger(__name__)


class GigaChatWrapper(BaseChatModel):
    """Custom wrapper for GigaChat to work with LangChain."""

    client: Optional[GigaChat] = None
    credentials: str
    scope: str
    model: str
    verify_ssl_certs: bool
    temperature: float = 0.7

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        s = get_settings()
        self.credentials = kwargs.get('credentials', s.gigachat_credentials)
        self.scope = kwargs.get('scope', s.gigachat_scope)
        self.model = kwargs.get('model', s.gigachat_model)
        self.verify_ssl_certs = kwargs.get('verify_ssl_certs', s.gigachat_verify_ssl)
        self.temperature = kwargs.get('temperature', 0.7)
        self._init_client()

    def _init_client(self):
        try:
            logger.info("initializing gigachat with scope: %s, model: %s", self.scope, self.model)
            self.client = GigaChat(
                credentials=self.credentials,
                scope=self.scope,
                model=self.model,
                verify_ssl_certs=self.verify_ssl_certs,
            )
            logger.info("gigachat client initialized successfully")
        except Exception as e:
            logger.error("failed to initialize gigachat client: %s", e)
            self.client = None

    @property
    def _llm_type(self) -> str:
        return "gigachat"

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Messages]:
        gigachat_messages = []
        for message in messages:
            if isinstance(message, SystemMessage):
                role = MessagesRole.SYSTEM
            elif isinstance(message, HumanMessage):
                role = MessagesRole.USER
            elif isinstance(message, AIMessage):
                role = MessagesRole.ASSISTANT
            else:
                role = MessagesRole.USER

            gigachat_messages.append(Messages(
                role=role,
                content=message.content,
            ))
        return gigachat_messages

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        after=after_log(logger, logging.WARNING),
        reraise=False,
    )
    def _call_gigachat(self, chat: Chat):
        """Send request to GigaChat with tenacity retry on network errors."""
        return self.client.chat(chat)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        logger.debug("_generate called with %s messages", len(messages))

        if not self.client:
            logger.warning("GigaChat client is None, using fallback")
            return self._generate_fallback(messages)

        # Circuit breaker check
        if gigachat_cb.is_open():
            logger.warning("GigaChat circuit breaker OPEN — using fallback")
            return self._generate_fallback(messages)

        try:
            gigachat_messages = self._convert_messages(messages)
            chat = Chat(
                messages=gigachat_messages,
                temperature=self.temperature,
                model=self.model,
            )

            logger.info(
                "sending request to gigachat: %s messages, model %s",
                len(gigachat_messages),
                self.model,
            )

            response = self._call_gigachat(chat)

            if response is None:
                # tenacity exhausted retries, reraise=False → None returned
                raise ConnectionError("GigaChat unreachable after 3 retries")

            gigachat_cb.record_success()
            logger.info("received response from gigachat")

            message = AIMessage(content=response.choices[0].message.content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        except Exception as e:
            gigachat_cb.record_failure()
            logger.error("error calling gigachat: %s (%s)", e, type(e).__name__)
            if hasattr(e, 'response'):
                logger.error("HTTP Response: %s", e.response)
            logger.info("falling back to predefined responses")
            return self._generate_fallback(messages)

    def _generate_fallback(self, messages: List[BaseMessage]) -> ChatResult:
        """Generate fallback response when GigaChat is not available."""
        logger.warning("using fallback response generation")
        last_user_msg = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content.lower()
                break

        if any(w in last_user_msg for w in ['ипотек', 'кредит', 'ставк', 'mortgage', 'loan']):
            content = "Я могу помочь с расчетом ипотеки. Укажите сумму кредита, процентную ставку и срок в месяцах."
        elif any(w in last_user_msg for w in ['сравни', 'лучше', 'compare', 'versus']):
            content = "Я могу помочь сравнить объекты недвижимости. Опишите объекты, которые хотите сравнить."
        elif any(w in last_user_msg for w in ['найди', 'найти', 'поиск', 'find', 'search']):
            content = "Я помогу найти информацию о недвижимости. Что именно вы ищете?"
        elif any(w in last_user_msg for w in ['студи', 'комнат', 'квартир', 'жк']):
            content = "Могу помочь с поиском квартиры. Уточните параметры: район, бюджет, количество комнат."
        else:
            content = (
                "Я ваш помощник по недвижимости. Могу помочь с:\n"
                "- Расчетом ипотеки\n"
                "- Сравнением объектов\n"
                "- Поиском информации о недвижимости"
            )

        message = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self, schema):
        """Compatibility stub — structured output goes through direct_llm_call.py."""
        logger.warning("with_structured_output is not supported by GigaChatWrapper, returning self")
        return self

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)
