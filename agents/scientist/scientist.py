"""Scientist agent core (PRD §5.1, §8.4-8.6, §13.2).

Two loops:
- ``recalibrate``: inner loop. Physical evidence -> simulated candidate twins ->
  new twin version (with provenance). Improves the robot model.
- ``investigate``: outer loop. Failures -> diagnosis -> competing harness
  mutations -> independent review. Improves how the robot works and learns.
"""
from __future__ import annotations

from typing import Any

from agents.scientist import brain
from agents.scientist.tools import ScientistTools
from shared.ids import new_id
from shared.schemas import XY, MutationType, RiskClassification, TwinVersion
from shared.telemetry import telemetry


class Scientist:
    def __init__(self, tools: ScientistTools) -> None:
        self.tools = tools

    # ---------------------------------------------------------------- inner loop
    def recalibrate(self, twin: TwinVersion, experiment_ids: list[str], campaign_id: str | None = None) -> dict[str, Any]:
        with telemetry.trace("autolab-scientist", "recalibration", f"refit twin {twin.id} from {len(experiment_ids)} experiments",
                             campaign_id=campaign_id, twin_version_id=twin.id) as t:
            with telemetry.span(t, "memory_retrieval", source="experiments"):
                rows = [self.tools.store.get("experiments", i) for i in experiment_ids]
                rows = [r for r in rows if r and r.get("observed_position_mm") and not str(r["scenario_id"]).startswith("pro_")]
            # Use first-attempt geometry only: commanded with this twin's calibration, no correction applied.
            evidence = [(XY(**r["target_position_mm"]), XY(**r["observed_position_mm"])) for r in rows if r.get("retries", 0) == 0 or r.get("first_attempt_error_mm") == r.get("position_error_mm")]
            evidence = evidence or [(XY(**r["target_position_mm"]), XY(**r["observed_position_mm"])) for r in rows]
            cands = self.tools.calibration_candidates(evidence, twin.calibration_parameters)
            with telemetry.span(t, "simulation_request", candidates=len(cands)):
                res = self.tools.run_simulation_batch(twin, cands, evidence)
            best = next(s for s in res.scores if s["index"] == res.best_index)
            base_score = next((s for s in res.scores if s["index"] == 0), None)
            new_twin = TwinVersion(
                _id=new_id("twin"),
                robot_id=twin.robot_id,
                parent_version_id=twin.id,
                backend=twin.backend,
                backend_version=twin.backend_version,
                robot_model=twin.robot_model,
                calibration_parameters=best["candidate"] | {"calibration_version": new_id("cal")},
                uncertainty_parameters=twin.uncertainty_parameters,
                source_experiment_ids=[r["_id"] for r in rows],
                validation_summary={
                    "batch_id": res.batch_id,
                    "environment": "simulation",
                    "candidates": len(cands),
                    "rejected_inadmissible": len(res.rejected),
                    "prediction_rmse_mm_parent": base_score["prediction_rmse_mm"] if base_score else None,
                    "prediction_rmse_mm_new": best["prediction_rmse_mm"],
                    "ranking": [{"index": s["index"], "rmse": round(s["prediction_rmse_mm"], 3)} for s in res.scores],
                    "rejections": res.rejected,
                },
            )
            self.tools.store.insert("twin_versions", new_twin)
            if base_score and base_score["prediction_rmse_mm"] > 1.0:
                telemetry.signal(t, "twin_prediction_mismatch", parent_rmse_mm=base_score["prediction_rmse_mm"])
            t.output = f"twin {new_twin.id}: prediction RMSE {base_score['prediction_rmse_mm']:.2f} -> {best['prediction_rmse_mm']:.2f} mm"
            t.properties["outcome"] = "twin_updated"
            return {"twin_version_id": new_twin.id, "batch": res, "summary": new_twin.validation_summary}

    # ---------------------------------------------------------------- outer loop
    def investigate(self, experiment_ids: list[str] | None = None, focus: str = "task_failures", campaign_id: str | None = None) -> dict[str, Any]:
        active = self.tools.active_harness()
        with telemetry.trace("autolab-scientist", "investigation", f"focus={focus}", campaign_id=campaign_id, harness_version_id=active.id) as t:
            with telemetry.span(t, "memory_retrieval", source="experiments+lessons"):
                if experiment_ids:
                    rows = [self.tools.store.get("experiments", i) for i in experiment_ids]
                    rows = [r for r in rows if r and not str(r["scenario_id"]).startswith("pro_")]
                else:
                    rows = self.tools.search_prior_experiments({"harness_version_id": active.id}, limit=30)
                lessons = self.tools.lessons()
            diag = brain.diagnose(rows)
            with telemetry.span(t, "reasoning", focus=focus) as sp:
                proposals, engine = brain.propose(diag, active, lessons, focus)
                sp.attrs["engine"] = engine
            t.properties["model"] = engine
            outcomes = []
            for p in proposals.proposals:
                with telemetry.span(t, "mutation_proposal", mutation_type=p.mutation_type):
                    created = self.tools.propose_harness_mutation(
                        MutationType(p.mutation_type), brain.to_patch(p), p.hypothesis, p.expected_improvement, RiskClassification(p.risk)
                    )
                if not created.get("candidate_id"):
                    outcomes.append({**created, "hypothesis": p.hypothesis, "decision": "reject", "reasons": [created["error"]]})
                    telemetry.signal(t, "candidate_rejected", reason=created["error"])
                    continue
                with telemetry.span(t, "promotion_submission", candidate=created["candidate_id"]):
                    review = self.tools.submit_candidate_for_review(created["candidate_id"])
                if review["decision"] != "approve":
                    telemetry.signal(t, "candidate_rejected", candidate=created["candidate_id"], reasons=review["reasons"])
                outcomes.append({**created, "mutation_type": p.mutation_type, "hypothesis": p.hypothesis, **review})
                if review["decision"] == "approve":
                    break  # base changed; remaining proposals would be stale (re-derive next cycle)
            t.output = "; ".join(f"{o.get('mutation_type', '?')}:{o['decision']}" for o in outcomes)
            t.properties["outcome"] = "promoted" if any(o["decision"] == "approve" for o in outcomes) else "no_promotion"
            return {"diagnosis": diag.to_dict(), "reasoning_summary": proposals.reasoning_summary, "engine": engine, "outcomes": outcomes, "trace_id": t.trace_id}
