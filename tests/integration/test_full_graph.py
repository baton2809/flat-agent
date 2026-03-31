"""Test full graph functionality."""

import logging
from langchain_core.messages import HumanMessage
from agent import build_graph

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logging.getLogger('httpx').setLevel(logging.WARNING)

def test_full_graph():
    """Test complete graph workflow."""
    logger = logging.getLogger(__name__)

    try:
        logger.info("Building agent graph...")
        graph = build_graph()
        logger.info("Graph built successfully")

        test_message = "Привет! Помоги с ипотекой на 5 млн рублей"
        user_id = "test_user_456"

        config = {"configurable": {"thread_id": user_id}}

        input_state = {
            "messages": [HumanMessage(content=test_message)],
            "user_id": user_id,
            "route": None
        }

        logger.info(f"Testing with message: {test_message}")
        result = graph.invoke(input_state, config)

        logger.info(f"Final result keys: {result.keys()}")
        logger.info(f"Messages count: {len(result.get('messages', []))}")
        logger.info(f"Route: {result.get('route', 'unknown')}")

        if 'messages' in result:
            for i, msg in enumerate(result['messages']):
                logger.info(f"Message {i}: {type(msg).__name__} - {msg.content[:100]}...")

        return True

    except Exception as e:
        logger.error(f"Graph test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    print("Testing full agent graph...")
    success = test_full_graph()
    print(f"Result: {'success' if success else 'failed'}")
