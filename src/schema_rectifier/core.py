"""
The purpose of this project is to build a flexible data ingestion pipeline.
The specific task that this system performs is to re-label column names
according to a data dictionary if they don't match expected column names.
"""

from typing import Any
from functools import partial
import logging
import os
import sqlite3

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from schema_rectifier.nodes import (
    gateway_node,
    load,
    single_column_name_mapping,
    single_column_name_mapping_validator,
    write_pending_review,
)
from schema_rectifier.utils import State, Status

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def _initialize_model():
    import os
    return os.environ.get("LLM_API_URL", "http://localhost:11434")  # defaults to local ollama instance

def _get_default_checkpointer():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        connection_kwargs = {
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        }
        # Initialize connection pool
        pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
            conninfo=db_url,
            max_size=20,
            kwargs=connection_kwargs,
        )
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        return checkpointer
    
    # Fallback to local SQLite if no DATABASE_URL is configured
    conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
    return SqliteSaver(conn)

def build_graph(llm_url: str, memory=None):
    if memory is None:
        memory = _get_default_checkpointer()

    builder = StateGraph(State)  # type: ignore
    builder.add_node("gateway", gateway_node)
    builder.add_node(
        "single_column_name_mapping", partial(single_column_name_mapping, llm_url=llm_url)
    )
    builder.add_node(
        "single_column_name_mapping_validator", single_column_name_mapping_validator
    )
    builder.add_node("write_pending_review", write_pending_review)
    # builder.add_node("human_review", human_review)
    builder.add_node("load", load)

    builder.add_edge(START, "gateway")
    builder.add_conditional_edges(
        "gateway",
        lambda state: state.get("status", Status.INVALID),
        {
            Status.VALID: "load", 
            Status.INVALID: "single_column_name_mapping"
        },
    )
    builder.add_conditional_edges(
        "single_column_name_mapping",
        lambda state: state.get("status", Status.INVALID),
        {
            Status.VALID: "single_column_name_mapping_validator",
            Status.RETRY_OUT: "write_pending_review",  # too many retries, ask human with unresolved mappings
            Status.INVALID: "single_column_name_mapping_validator",  # llm failed, validate what we have
        },
    )
    builder.add_conditional_edges(
        "single_column_name_mapping_validator",
        lambda state: state.get("status", Status.INVALID),
        {Status.VALID: "write_pending_review", Status.INVALID: "single_column_name_mapping"},
    )
    builder.add_edge("write_pending_review", "load")
    builder.add_edge("load", END)

    graph = builder.compile(checkpointer=memory, interrupt_before=["load"])
    return graph
