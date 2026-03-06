"""Custom LLM wrapper for GigaChat integration."""

import logging
from typing import List, Optional, Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from config import get_settings

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
                verify_ssl_certs=self.verify_ssl_certs
            )
            logger.info("gigachat client initialized successfully")
        except Exception as e:
            logger.error("failed to initialize gigachat client: %s", e)
            logger.error("credentials length: %s", len(self.credentials) if self.credentials else 0)
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
                content=message.content
            ))
        return gigachat_messages
    
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
        
        try:
            gigachat_messages = self._convert_messages(messages)
            
            chat = Chat(
                messages=gigachat_messages,
                temperature=self.temperature,
                model=self.model
            )
            
            logger.info("sending request to gigachat: %s messages, model %s", len(gigachat_messages), self.model)
            logger.debug("Request messages: %s", [msg.content[:50] + '...' if len(msg.content) > 50 else msg.content for msg in gigachat_messages])
            
            response = self.client.chat(chat)
            
            logger.info("received response from gigachat")
            logger.debug("Response content preview: %s...", response.choices[0].message.content[:100])
            
            message = AIMessage(content=response.choices[0].message.content)
            generation = ChatGeneration(message=message)
            
            return ChatResult(generations=[generation])
            
        except Exception as e:
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
        
        if any(word in last_user_msg for word in ['mortgage', 'loan', 'credit', 'ипотек', 'кредит', 'ставк']):
            content = "Я могу помочь с расчетом ипотеки. Укажите сумму кредита, процентную ставку и срок в месяцах."
        elif any(word in last_user_msg for word in ['compare', 'comparison', 'versus', 'сравни', 'лучше']):
            content = "Я могу помочь сравнить объекты недвижимости. Опишите объекты, которые хотите сравнить."
        elif any(word in last_user_msg for word in ['find', 'search', 'look', 'найди', 'найти', 'поиск']):
            content = "Я помогу найти информацию о недвижимости. Что именно вы ищете?"
        elif any(word in last_user_msg for word in ['студи', 'комнат', 'квартир', 'жк']):
            content = "Могу помочь с поиском квартиры. Уточните параметры: район, бюджет, количество комнат."
        else:
            content = """Я ваш помощник по недвижимости. Могу помочь с:
- Расчетом ипотеки
- Сравнением объектов
- Поиском информации о недвижимости"""
        
        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])
    
    def with_structured_output(self, schema):
        """Compatibility method for structured output - returns self as it's not supported."""
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