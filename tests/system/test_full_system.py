"""Test the full FlatAgent system with enhanced routing."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import build_graph
from agent.state import AgentState
from langchain_core.messages import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_full_agent():
    """Test the complete agent with enhanced routing."""
    print("--- full FlatAgent system tests ---")

    try:
        graph = build_graph()
        print("Graph built successfully")
    except Exception as e:
        print(f"Failed to build graph: {e}")
        return

    test_cases = [
        ("Привет!", "chat"),
        ("Хочу взять ипотеку на 5 млн", "mortgage"),
        ("Что лучше - новостройка или вторичка?", "compare"),
        ("Найди мне квартиру в центре Москвы", "search"),
        ("Расскажи про документы для покупки", "chat"),
    ]

    for user_input, expected_route in test_cases:
        print(f"\nTesting: '{user_input}' (expected route: {expected_route})")

        config = {"configurable": {"thread_id": f"test-{hash(user_input) % 1000}"}}

        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "route": "",
            "user_id": "test_user"
        }

        try:
            result = graph.invoke(initial_state, config)

            route = result.get('route', 'unknown')
            route_status = "ok" if route == expected_route else f"wrong (got {route})"
            print(f"   Route: {route} [{route_status}]")

            if result.get('messages'):
                last_message = result['messages'][-1]
                if hasattr(last_message, 'content'):
                    response_preview = last_message.content[:100] + "..." if len(last_message.content) > 100 else last_message.content
                    print(f"   Response: {response_preview}")
                else:
                    print(f"   Response: {str(last_message)[:100]}...")
            else:
                print("   No response generated")

        except Exception as e:
            print(f"   Test failed: {e}")


if __name__ == "__main__":
    test_full_agent()
