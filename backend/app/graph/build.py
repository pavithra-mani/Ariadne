"""Assemble the LangGraph workflow (Fig. 1): intake -> supervisor -> specialist -> RAG -> risk ->
{supply impact, health/operational impact} -> (recovery pipeline) -> finalize."""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph import nodes, notify, propagate, recovery
from app.graph.state import State


def build_graph(checkpointer=None):
    g = StateGraph(State)
    for name in ("intake", "supervisor", "mulberry_agent", "silkworm_agent", "reeler_agent", "spinner_agent",
                 "rag_node", "risk_node", "supply_impact_node", "health_node", "advisory_node", "finalize"):
        g.add_node(name, getattr(nodes, name))
    g.add_node("stock_monitor_agent", nodes.low_stock_agent)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", lambda s: "finalize" if s.get("clarify") else "supervisor", ["supervisor", "finalize"])
    g.add_conditional_edges("supervisor", nodes.route_after_supervisor,
                            ["mulberry_agent", "silkworm_agent", "reeler_agent", "spinner_agent", "stock_monitor_agent"])
    for agent in ("mulberry_agent", "silkworm_agent", "reeler_agent", "spinner_agent", "stock_monitor_agent"):
        g.add_edge(agent, "rag_node")
    g.add_edge("rag_node", "risk_node")
    g.add_edge("risk_node", "supply_impact_node")
    g.add_edge("risk_node", "health_node")
    g.add_edge(["supply_impact_node", "health_node"], "advisory_node")
    for name in ("inventory_check", "alt_sources", "routing", "propose", "hitl_approval", "deal_rerouting", "notification"):
        g.add_node(name, getattr(recovery, name))
    g.add_node("notify_affected", notify.notify_affected)
    g.add_node("propagate_early", propagate.propagate_early)
    g.add_edge("advisory_node", "notify_affected")
    g.add_edge("notify_affected", "propagate_early")
    g.add_conditional_edges("propagate_early", recovery.recovery_gate, ["inventory_check", "finalize"])
    g.add_edge("inventory_check", "alt_sources")
    g.add_edge("alt_sources", "routing")
    g.add_conditional_edges("routing", recovery.after_routing, ["alt_sources", "propose"])  # bounded retry loop
    g.add_conditional_edges("propose", recovery.after_propose, ["hitl_approval", "notification"])
    g.add_edge("hitl_approval", "deal_rerouting")
    g.add_edge("deal_rerouting", "notification")
    g.add_node("propagate_final", propagate.propagate_final)
    g.add_edge("notification", "propagate_final")
    g.add_edge("propagate_final", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
