"""Atlas Agent Engine entrypoint for the AutoLab Scientist.

Thin LangGraph shell over the tested core in ``agents/scientist``. The LLM decides
which tools to call; every number comes from structured tools, and promotion is
impossible from here: ``submit_candidate_for_review`` only enqueues the candidate
for the local evaluator worker.
"""
from __future__ import annotations

import json
import os

from agent_engine_sdk_langgraph import App
from langchain_anthropic import ChatAnthropic
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.scientist import brain
from agents.scientist.tools import ScientistTools
from evaluation.review_queue import request_review, review_status
from shared.schemas import MutationType, RiskClassification
from shared.store import get_store
from shared.telemetry import telemetry

app = App(app_name="autolab-scientist")
_store = get_store()
telemetry.attach_store(_store)
_tools = ScientistTools(_store, review=lambda cid: None)  # review goes through the queue below

SYSTEM = brain.SYSTEM + """

Workflow: (1) search_prior_experiments and recall_lessons, (2) diagnose_failures, (3) propose 1-3 competing
mutations with propose_harness_mutation, cheapest hypothesis first, (4) submit_candidate_for_review for each,
(5) record what you learned with remember_episode. Report decisions honestly, including rejections."""


@app.tool()
def search_prior_experiments(harness_version_id: str = "", limit: int = 30) -> str:
    """Recent experiments (protected evaluation targets are always excluded). Optionally filter by harness version id."""
    q = {"harness_version_id": harness_version_id} if harness_version_id else {}
    rows = _tools.search_prior_experiments(q, limit=limit)
    keep = ("_id", "scenario_id", "harness_version_id", "twin_version_id", "position_error_mm", "error_xy_mm", "retries",
            "first_attempt_error_mm", "board_moved_detected", "verification_status", "execution_environment")
    return json.dumps([{k: r.get(k) for k in keep} for r in rows], default=str)


@app.tool()
def inspect_active_harness() -> str:
    """The active harness version document."""
    return _tools.active_harness().model_dump_json(by_alias=True)


@app.tool()
def diagnose_failures(experiment_ids: list[str]) -> str:
    """Deterministic statistics over the given experiments: bias vs spread, retry gain, board-moved evidence, ranked hypotheses."""
    rows = [r for r in (_store.get("experiments", i) for i in experiment_ids) if r and not str(r["scenario_id"]).startswith("pro_")]
    return json.dumps(brain.diagnose(rows).to_dict(), default=str)


@app.tool()
def recall_lessons(limit: int = 5) -> str:
    """Past mutation proposals with their decisions (structured), plus related episodic memory."""
    lessons = _tools.lessons(limit)
    try:
        eps = [c.content for c in app.memory.search_episodes(query="harness mutation rejected approved", top_k=3)]
    except Exception:
        eps = []
    return json.dumps({"structured": lessons, "episodes": eps}, default=str)


@app.tool()
def propose_harness_mutation(mutation_json: str) -> str:
    """Create a candidate harness version. ``mutation_json`` must match the ProposedMutation schema:
    {mutation_type: parameter|workflow|memory_policy|experiment_policy, workflow_ops?: [op,...], retry_policy?: {...},
     memory_policy?: {...}, experiment_policy?: {...}, hypothesis, expected_improvement, risk: low|medium|high}."""
    p = brain.ProposedMutation.model_validate_json(mutation_json)
    out = _tools.propose_harness_mutation(MutationType(p.mutation_type), brain.to_patch(p), p.hypothesis, p.expected_improvement, RiskClassification(p.risk))
    return json.dumps(out)


@app.tool()
def submit_candidate_for_review(candidate_id: str) -> str:
    """Queue a PROPOSED candidate for the independent evaluator. You cannot promote it yourself."""
    return json.dumps({"queued": request_review(_store, candidate_id)})


@app.tool()
def get_review_status(candidate_id: str) -> str:
    """Current lifecycle status and the evaluator's decision/reasons for a candidate, if decided."""
    return json.dumps(review_status(_store, candidate_id), default=str)


@app.tool()
def remember_episode(title: str, summary: str) -> str:
    """Save a short episodic memory of this investigation (no raw numbers needed; they live in Atlas)."""
    r = app.memory.save_episode(title=title, content=summary)
    return json.dumps({"saved": bool(getattr(r, "acknowledged", True))})


@app.entrypoint
def build_agent():
    llm = app.llm(ChatAnthropic(model=os.environ.get("AUTOLAB_SCIENTIST_MODEL", "claude-opus-5-5"), max_tokens=16000))
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
