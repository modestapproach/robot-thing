"""Atlas Agent Engine entrypoint for the AutoLab Operator.

Runs tasks through the *local* robot gateway (via an authenticated tunnel) under the
harness version pinned at task start, and delegates investigations to the Scientist
over project-scoped A2A. It has no tool that edits configuration.
"""
from __future__ import annotations

import json
import os

from agent_engine_sdk_langgraph import App
from langchain_anthropic import ChatAnthropic
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.operator.operator import Operator
from robot_gateway.client import RemoteGateway
from shared.schemas import XY
from shared.store import get_store
from shared.telemetry import telemetry

app = App(app_name="autolab-operator")
_store = get_store()
telemetry.attach_store(_store)
_op: Operator | None = None


def op() -> Operator:
    global _op
    if _op is None:
        _op = Operator(_store, RemoteGateway())  # type: ignore[arg-type]
    return _op


SYSTEM = """You are the AutoLab Operator. You execute bounded robot tasks using only the approved, active harness.
You cannot change configuration or bypass the gateway; the gateway enforces safety. After failures, delegate an
investigation to the Scientist with delegate_investigation and report its answer verbatim. Never claim success
without a measured error; 'unknown' outcomes stay unknown."""


@app.tool()
def observe_robot() -> str:
    """Robot state and a fresh camera observation in board coordinates."""
    return json.dumps(op().observe_robot(), default=str)


@app.tool()
def get_active_harness() -> str:
    """The active harness version (pinned at the start of each task)."""
    return op().get_active_harness().model_dump_json(by_alias=True)


@app.tool()
def preview_movement(x_mm: float, y_mm: float) -> str:
    """Digital-twin prediction for a board target (simulated, not measured)."""
    return json.dumps(op().preview_movement(XY(x=x_mm, y=y_mm)))


@app.tool()
def run_target_task(scenario_id: str, x_mm: float, y_mm: float) -> str:
    """Execute one task to a board target under the active harness; returns the measured outcome."""
    r = op().run_task(scenario_id, XY(x=x_mm, y=y_mm), idem_prefix=f"ae:{scenario_id}:{os.urandom(3).hex()}")
    return json.dumps({"experiment_id": r.experiment_id, "success": r.success, "error_mm": r.error_mm, "status": r.status, "retries": r.retries, "steps": r.steps})


@app.tool()
def delegate_investigation(experiment_ids: list[str], focus: str = "task_failures") -> str:
    """Ask the Scientist (A2A) to investigate failures. Returns its report."""
    rt = getattr(app, "_runtime", None)
    a2a = getattr(rt, "a2a", None) if rt else None
    if a2a is None:
        return json.dumps({"error": "A2A unavailable in this runtime"})
    agents = a2a.discover_agents(skills=["investigate-failures"], limit=5)
    if not agents:
        return json.dumps({"error": "no scientist agent discovered"})
    resp = a2a.invoke_agent(agent_id=agents[0].agent_id, message=json.dumps({"experiment_ids": experiment_ids, "focus": focus}),
                            skill="investigate-failures", timeout=280)
    return json.dumps({"status": resp.status, "result": getattr(resp, "result", None), "error": getattr(resp, "error", None)}, default=str)


@app.entrypoint
def build_agent():
    llm = app.llm(ChatAnthropic(model=os.environ.get("AUTOLAB_OPERATOR_MODEL", "claude-opus-5-5"), max_tokens=8000))
    tools = app.get_tools()
    model = llm.bind_tools(app.get_tool_schemas())

    def call_model(state: MessagesState):
        msgs = state["messages"]
        if not msgs or getattr(msgs[0], "type", "") != "system":
            msgs = [("system", SYSTEM), *msgs]
        return {"messages": [model.invoke(msgs)]}

    g = StateGraph(MessagesState)
    g.add_node("agent", call_model)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=app.checkpointer())


app.run()
