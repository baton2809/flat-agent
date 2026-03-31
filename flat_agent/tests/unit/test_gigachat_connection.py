"""Test GigaChat connection and functionality."""

import os
import logging
from config import get_llm
from langchain_core.messages import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gigachat_connection():
    """Test GigaChat initialization and basic functionality."""
    try:
        # Test LLM initialization
        llm = get_llm()
        logger.info(f"llm initialized: {type(llm)}")
        logger.info(f"   - credentials length: {len(llm.credentials) if hasattr(llm, 'credentials') and llm.credentials else 0}")
        logger.info(f"   - model: {getattr(llm, 'model', 'Unknown')}")
        logger.info(f"   - client: {type(llm.client) if hasattr(llm, 'client') and llm.client else 'None'}")

        if not hasattr(llm, 'client') or not llm.client:
            logger.error("gigachat client is not initialized")
            return False

        messages = [HumanMessage(content="Привет! Ответь одним словом: Работаю")]
        logger.info("testing llm invoke...")
        response = llm.invoke(messages)

        logger.info(f"response type: {type(response)}")
        if hasattr(response, 'content'):
            logger.info(f"response content: {response.content}")
            if "расчета ипотеки" in response.content or "assistant" in response.content.lower():
                logger.warning("looks like a fallback response, not real gigachat")
                return False
        else:
            logger.info(f"response structure: {response}")

        return True

    except Exception as e:
        logger.error(f"gigachat test failed: {e}")
        logger.error(f"error type: {type(e).__name__}")
        import traceback
        logger.error(f"traceback: {traceback.format_exc()}")
        return False

def test_memory_extraction():
    """Test memory extraction functionality."""
    try:
        from agent.memory import memory_manager
        
        # Test fact extraction
        user_id = "test_user_123"
        test_message = "Меня зовут Александр, я работаю в IT"
        
        result = memory_manager.extract_and_store_facts(user_id, test_message)
        logger.info(f"Fact extraction result: {result}")
        
        facts = memory_manager.get_user_facts(user_id)
        logger.info(f"Stored facts: {facts}")
        
        context = memory_manager.get_memory_context(user_id)
        logger.info(f"Memory context: {context}")
        
        return len(facts) > 0
        
    except Exception as e:
        logger.error(f"Memory test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing GigaChat connection...")
    gigachat_ok = test_gigachat_connection()
    
    print("\nTesting memory extraction...")
    memory_ok = test_memory_extraction()
    
    print(f"\nResults:")
    print(f"GigaChat: {'OK' if gigachat_ok else 'FAILED'}")
    print(f"Memory: {'OK' if memory_ok else 'FAILED'}")