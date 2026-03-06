"""Build and compile the LangGraph agent."""

import logging
import sqlite3
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import AgentState
from agent.nodes import (
    router_node,
    mortgage_node,
    compare_node,
    search_node,
    chat_node
)
from agent.nodes.memory_extraction import memory_extraction_node

logger = logging.getLogger(__name__)


def route_decision(state: AgentState) -> str:
    """Determine next node based on routing result."""
    route = state.get("route", "chat")
    logger.info("routing to: %s_node", route)
    return f"{route}_node"


def build_graph(db_path: str = "checkpoints.db"):
    """Build and compile the agent graph with state persistence."""
    logger.info("building agent graph")
    
    graph = StateGraph(AgentState)
    
    graph.add_node("router", router_node)
    graph.add_node("memory_extraction", memory_extraction_node)
    graph.add_node("mortgage_node", mortgage_node)
    graph.add_node("compare_node", compare_node)
    graph.add_node("search_node", search_node)
    graph.add_node("chat_node", chat_node)
    
    graph.set_entry_point("router")
    
    graph.add_conditional_edges(
        "router",
        route_decision,
        {
            "mortgage_node": "memory_extraction",
            "compare_node": "memory_extraction", 
            "search_node": "memory_extraction",
            "chat_node": "memory_extraction",
        }
    )
    
    
    def route_after_memory(state: AgentState) -> str:
        """Dispatch to the correct processing node after memory extraction."""
        route = state.get("route", "chat")
        logger.info("post-memory routing to: %s_node", route)
        return f"{route}_node"
    
    graph.add_conditional_edges(
        "memory_extraction",
        route_after_memory,
        {
            "mortgage_node": "mortgage_node",
            "compare_node": "compare_node",
            "search_node": "search_node", 
            "chat_node": "chat_node",
        }
    )
    
    graph.add_edge("mortgage_node", END)
    graph.add_edge("compare_node", END)
    graph.add_edge("search_node", END)
    graph.add_edge("chat_node", END)
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    checkpointer = SqliteSaver(conn)
    logger.info("compiling graph with sqlite checkpointer at %s", db_path)
    
    compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("graph compiled successfully")
    
    return compiled_graph