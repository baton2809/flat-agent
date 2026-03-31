"""Agent state definition for LangGraph."""

from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Typed state container passed between LangGraph nodes.

    Attributes:
        messages: conversation history with add_messages reducer.
        route: routing decision produced by router_node (mortgage/compare/search/chat).
        user_id: unique user identifier (telegram chat_id).
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    route: str
    user_id: str
