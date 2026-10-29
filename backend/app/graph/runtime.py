"""Graph runtime: Postgres checkpointer (needed for HITL interrupt/resume) + compiled graph."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings
from app.graph.build import build_graph
from app.observability import configure

_pool = None
_graph = None


def init_graph():
    global _pool, _graph
    if _graph is not None:
        return _graph
    from langgraph.checkpoint.postgres import PostgresSaver
    _pool = ConnectionPool(conninfo=settings.psycopg_url, max_size=8, open=True,
                           kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0})
    saver = PostgresSaver(_pool)
    saver.setup()
    configure()  # LangSmith observability switches on with the key
    _graph = build_graph(saver)
    return _graph


def get_graph():
    return init_graph()


def close_graph():
    global _pool, _graph
    if _pool:
        _pool.close()
    _pool, _graph = None, None
