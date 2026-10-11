"""AutoLab campaign: the six demo scenes as resumable, checkpointed stages (PRD §4, §18).

Every stage is idempotent and its outputs are checkpointed in ``experiment_campaigns``.
Motion commands use deterministic idempotency keys (campaign/stage/scenario/attempt),
so resuming after a crash never repeats an acknowledged move.

The "lab" here is the mock arm + mock camera with a hidden true calibration. When the
real arm is identified, swap the driver/camera in ``Lab``; nothing else changes.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from agents.operator.operator import Operator, latest_twin
from agents.scientist.scientist import Scientist
from agents.scientist.tools import ScientistTools
from evaluation import evaluator
from evaluation.metrics import summarize
from evaluation.twin_eval import heldout_twin_comparison
from robot_gateway.camera import MockCamera
from robot_gateway.driver import MockArmDriver
from robot_gateway.gateway import Gateway
from shared.ids import new_id
from shared.schemas import XY, CalibrationParameters, CampaignStatus, ExperimentCampaign, HarnessVersion, Robot, TwinVersion, utcnow
from shared.store import Store
from shared.telemetry import telemetry
import math
import os

from simulation.world import DEFAULT_TRUTH, make_so101_world_factory, make_world_factory


def world_kind() -> str:
    """"so101" (MuJoCo physics twin of the SO-101) unless forced to the idealized mock."""
    if os.environ.get("AUTOLAB_WORLD", "so101") == "mock":
        return "mock"
    try:
        import mujoco  # noqa: F401

        return "so101"
    except ImportError:
        return "mock"

ROOT = Path(__file__).resolve().parent.parent
SCEN = json.loads((ROOT / "fixtures/scenarios.json").read_text())
BUMP = (2.5, 3.0, 0.6)  # someone knocks the board: +2.5 mm x, +3.0 mm y, +0.6 deg


class CampaignInterrupted(Exception):
    pass


class Lab:
    """The 'physical' world: SO-101 MuJoCo physics (default) or the idealized mock.

    Swap in the LeRobot driver + ChArUco camera for the real arm; nothing else changes.
    """

    def __init__(self, store: Store, bumped: bool, kind: str | None = None) -> None:
        self.store = store
        self.kind = kind or world_kind()
        self.truth = DEFAULT_TRUTH
        self.bumped = bumped
        self.gateway = self._make()

    def _make(self) -> Gateway:
        if self.kind == "so101":
            return make_so101_world_factory(store=self.store, seed=11, board_bump=BUMP if self.bumped else None)()
        cam = MockCamera(self.truth, seed=11)
        if self.bumped:
            cam.nudge_board(*BUMP)
            cam.board_moved = True
        return Gateway(MockArmDriver(latency_s=0.0), cam, robot_id="robot_main", store=self.store, physical_enabled=True)

    def bump_board(self) -> None:
        self.bumped = True
        if self.kind == "so101":
            self.gateway = self._make()  # the board moved under a re-homed arm
        else:
            self.gateway.camera.nudge_board(*BUMP)  # type: ignore[attr-defined]

    def factory(self) -> Callable[[], Gateway]:
        """Fresh gateway in the lab's current physical condition (used for the physical eval stage)."""
        return lambda: self._make()


class Campaign:
    STAGES = ["setup", "baseline", "recalibrate", "verify_calibration", "disturbance", "investigate", "recovered", "meta_improvement", "report"]

    def __init__(self, store: Store, campaign_id: str | None = None, log: Callable[[str], None] = print) -> None:
        self.store = store
        self.log = log
        telemetry.attach_store(store)
        if campaign_id:
            doc = store.get("experiment_campaigns", campaign_id)
            if not doc:
                raise KeyError(campaign_id)
            if doc.get("baseline_version_id") is None:
                self._seed()
                doc["baseline_version_id"] = evaluator.get_active(store).id
            doc.setdefault("checkpoint", {"completed": [], "outputs": {}, "lab": {"bumped": False}})
            self.c = ExperimentCampaign.model_validate({**doc, "status": doc.get("status") if doc.get("status") in {s.value for s in CampaignStatus} else "created"})
        else:
            self._seed()
            self.c = ExperimentCampaign(
                _id=new_id("camp"), objective="Reduce positioning error and improve the harness that produces it",
                baseline_version_id=evaluator.get_active(store).id, scenario_set_id=SCEN["scenario_set_id"],
                budget={"max_physical_moves": 400}, checkpoint={"completed": [], "outputs": {}, "lab": {"bumped": False}},
            )
            store.insert("experiment_campaigns", self.c)
        lab_cp = self.c.checkpoint.get("lab", {})
        self.lab = Lab(store, bumped=lab_cp.get("bumped", False), kind=lab_cp.get("kind"))
        self.scientist = Scientist(ScientistTools(store, review=self._review))
        self.operator = Operator(store, self.lab.gateway, delegate=self._a2a)

    # ---------------------------------------------------------------- wiring
    def _seed(self) -> None:
        s = self.store
        if world_kind() == "so101":
            from simulation.so101.sim import NOMINAL_BOARD

            if not s.get("robots", "robot_so101"):
                s.insert("robots", Robot(_id="robot_so101", name="SO-101 follower arm", manufacturer="TheRobotStudio / Hugging Face",
                                         model="SO-101", control_interface="LeRobot, Feetech STS3215 serial bus", joint_count=6,
                                         asset_uri="simulation/so101/model/so101_new_calib.xml"))
            from dataclasses import asdict

            from robot_gateway.safety import SO101_ENVELOPE

            # Read-only mirror for the dashboard; the gateway enforces its own copy and never reads this.
            s.update("robots", "robot_so101", {"safety_envelope": asdict(SO101_ENVELOPE), "driver": "so101_sim", "is_physical": False})
            if not s.find("twin_versions", {}, limit=1):
                s.insert("twin_versions", TwinVersion(_id="twin_so101_v0", robot_id="robot_so101", backend="mujoco", backend_version="mujoco-3.3.7",
                                                      robot_model="so101", calibration_parameters=NOMINAL_BOARD,
                                                      validation_summary={"note": "tape-measured board placement; official SO-101 MJCF kinematics"}))
        else:
            if not s.get("robots", "robot_main"):
                s.insert("robots", Robot(_id="robot_main", name="AutoLab arm (mock)", control_interface="mock"))
            if not s.find("twin_versions", {}, limit=1):
                s.insert("twin_versions", TwinVersion(_id="twin_v0", robot_id="robot_main", validation_summary={"note": "believed identity calibration"}))
        if not s.find("harness_versions", {"status": "ACTIVE"}, limit=1):
            s.insert("harness_versions", HarnessVersion.model_validate(json.loads((ROOT / "fixtures/harness_v1.json").read_text())))

    def _sim_world_from_evidence(self) -> Callable[[], Gateway]:
        """Evaluator's simulated world: active twin + the disturbance *measured* in visible failures.

        Built from evidence, never from the lab's hidden truth."""
        twin = latest_twin(self.store)
        rows = self.store.find("experiments", {"campaign_id": self.c.id, "twin_version_id": twin.id}, sort=[("started_at", -1)])
        recent = [r for r in rows if r.get("error_xy_mm") and not r["scenario_id"].startswith("pro_")][:6]
        bx = sum(r["error_xy_mm"]["x"] for r in recent) / max(1, len(recent))
        by = sum(r["error_xy_mm"]["y"] for r in recent) / max(1, len(recent))
        cal = twin.calibration_parameters
        # A board shift d (F_base) shows up as board-frame error e = -R^-1 d, so d = -R e.
        th = math.radians(cal.rotation_deg)
        dx = -(math.cos(th) * bx - math.sin(th) * by) * cal.scale
        dy = -(math.sin(th) * bx + math.cos(th) * by) * cal.scale
        sim_truth = cal.model_copy(update={"offset_mm": XY(x=cal.offset_mm.x + dx, y=cal.offset_mm.y + dy), "calibration_version": "sim_from_evidence"})
        if self.lab.kind == "so101":
            # The evaluator's simulated world knows the twin and the measured disturbance, not the servo offsets.
            factory = make_so101_world_factory(board_truth=sim_truth, joint_offsets_deg={}, seed=3, store=self.store)
        else:
            factory = make_world_factory(truth=sim_truth, seed=3, store=self.store)

        def with_flag() -> Gateway:
            gw = factory()
            gw.camera.board_moved = bool(self.lab.bumped)  # type: ignore[attr-defined]
            return gw

        return with_flag

    def _review(self, candidate_id: str):
        return evaluator.evaluate_candidate(candidate_id, latest_twin(self.store), self._sim_world_from_evidence(), self.store,
                                            physical_world=self.lab.factory())

    def _a2a(self, msg: dict) -> dict:
        """Local stand-in for Agent Engine A2A: Operator -> Scientist."""
        return self.scientist.investigate(msg.get("experiment_ids"), focus=msg.get("focus", "task_failures"), campaign_id=self.c.id)

    def _run_targets(self, stage: str, group: str) -> list[dict]:
        out = []
        for i, t in enumerate(SCEN[group]):
            r = self.operator.run_task(t["id"], XY(x=t["x"], y=t["y"]), campaign_id=self.c.id, idem_prefix=f"{self.c.id}:{stage}:{t['id']}", seed=i)
            out.append({"scenario": t["id"], "experiment_id": r.experiment_id, "error_mm": r.error_mm, "success": r.success, "retries": r.retries})
        return out

    def _checkpoint(self, stage: str, output: Any) -> None:
        cp = self.c.checkpoint
        cp["outputs"][stage] = output
        cp["completed"].append(stage)
        cp["lab"] = {"bumped": self.lab.bumped, "kind": self.lab.kind}
        self.store.update("experiment_campaigns", self.c.id, {"checkpoint": cp, "updated_at": utcnow(),
                                                                "completed_trial_ids": [e["experiment_id"] for v in cp["outputs"].values() if isinstance(v, dict) for e in v.get("trials", [])]})

    # ---------------------------------------------------------------- run
    def run(self, stop_after: str | None = None) -> dict:
        self.store.update("experiment_campaigns", self.c.id, {"status": CampaignStatus.RUNNING.value})
        self.store.update("experiment_campaigns", self.c.id, {"pause_requested": False, "resume_requested": False})
        for stage in self.STAGES:
            if stage in self.c.checkpoint["completed"]:
                self.log(f"[skip] {stage} (checkpointed)")
                continue
            doc = self.store.get("experiment_campaigns", self.c.id) or {}
            if doc.get("pause_requested"):  # set from the dashboard; honoured between stages, never mid-motion
                self.store.update("experiment_campaigns", self.c.id, {"status": CampaignStatus.PAUSED.value, "updated_at": utcnow()})
                self.store.audit("campaign_paused", campaign_id=self.c.id, before_stage=stage)
                raise CampaignInterrupted(f"paused by operator before {stage}; resume with --resume {self.c.id}")
            self.log(f"[stage] {stage}")
            out = getattr(self, f"stage_{stage}")()
            self._checkpoint(stage, out)
            if stage == stop_after:
                self.store.update("experiment_campaigns", self.c.id, {"status": CampaignStatus.PAUSED.value})
                raise CampaignInterrupted(f"stopped after {stage}; resume with --resume {self.c.id}")
        self.store.update("experiment_campaigns", self.c.id, {"status": CampaignStatus.COMPLETED.value})
        telemetry.flush()
        return self.c.checkpoint["outputs"]

    # ---------------------------------------------------------------- stages
    def stage_setup(self):
        return {"harness": evaluator.get_active(self.store).id, "twin": latest_twin(self.store).id}

    def stage_baseline(self):
        """Scene 1: the arm misses. Visible calibration + selection targets."""
        trials = self._run_targets("baseline", "calibration") + self._run_targets("baseline", "selection")
        errs = [t["error_mm"] for t in trials if t["error_mm"] is not None]
        self.log(f"  baseline: {sum(t['success'] for t in trials)}/{len(trials)} within tolerance, mean error {sum(errs)/len(errs):.2f} mm")
        return {"trials": trials}

    def stage_recalibrate(self):
        """Scenes 2-3: Scientist fits candidate twins in simulation from the failures."""
        exp_ids = [t["experiment_id"] for t in self.c.checkpoint["outputs"]["baseline"]["trials"]]
        parent = latest_twin(self.store)
        out = self.scientist.recalibrate(parent, exp_ids, campaign_id=self.c.id)
        s = out["summary"]
        self.log(f"  twin {parent.id} -> {out['twin_version_id']}: prediction RMSE {s['prediction_rmse_mm_parent']:.2f} -> {s['prediction_rmse_mm_new']:.2f} mm "
                 f"({s['candidates']} candidates, {s['rejected_inadmissible']} rejected as implausible)")
        return {"parent": parent.id, "twin_version_id": out["twin_version_id"], "summary": s}

    def stage_verify_calibration(self):
        """Scene 4: physical improvement, held-out (evaluator side) and visible."""
        rec = self.c.checkpoint["outputs"]["recalibrate"]
        parent = TwinVersion.model_validate(self.store.get("twin_versions", rec["parent"]))
        new = TwinVersion.model_validate(self.store.get("twin_versions", rec["twin_version_id"]))
        held = heldout_twin_comparison(evaluator.get_active(self.store), parent, new, self.lab.factory(), self.store)
        self.store.update("twin_versions", new.id, {"validation_summary": {**new.validation_summary, "heldout_physical": held}})
        trials = self._run_targets("verify_calibration", "selection")
        self.log(f"  held-out RMSE {held['before']['rmse_mm']:.2f} -> {held['after']['rmse_mm']:.2f} mm "
                 f"({held['rmse_reduction']:+.0%}); success {held['before']['success_rate']:.0%} -> {held['after']['success_rate']:.0%}")
        return {"heldout": held, "trials": trials}

    def stage_disturbance(self):
        """Scene 5a: the board gets bumped; the calibrated twin is now wrong."""
        self.lab.bump_board()
        self.operator.gw = self.lab.gateway
        trials = self._run_targets("disturbance", "selection")
        n_ok = sum(t["success"] for t in trials)
        self.log(f"  after bump: {n_ok}/{len(trials)} within tolerance (retry policy re-sends the same command)")
        return {"trials": trials, "bump": BUMP}

    def stage_investigate(self):
        """Scene 5b: Operator delegates; Scientist proposes competing harness mutations; evaluator decides."""
        failed = [t["experiment_id"] for t in self.c.checkpoint["outputs"]["disturbance"]["trials"]]
        res = self.operator.report_failure(failed)
        self._log_outcomes(res)
        return res

    def _log_outcomes(self, res: dict) -> None:
        for o in res["outcomes"]:
            rs = o.get("reasons") or [""]
            why = rs[-1] if o["decision"] != "approve" else " | ".join(rs)
            self.log(f"  {o.get('mutation_type')}: {o['decision'].upper()} - {why}")

    def stage_recovered(self):
        """Scene 6: new tasks pin the promoted harness."""
        active = evaluator.get_active(self.store)
        trials = self._run_targets("recovered", "selection")
        self.log(f"  harness v{active.version}: {sum(t['success'] for t in trials)}/{len(trials)} within tolerance")
        return {"harness": active.id, "version": active.version, "trials": trials}

    def stage_meta_improvement(self):
        """Stretch: the Scientist improves its own experiment-selection procedure."""
        res = self.scientist.investigate(focus="experiment_policy", campaign_id=self.c.id)
        self._log_outcomes(res)
        return res

    def stage_report(self):
        versions = sorted(self.store.find("harness_versions", {}), key=lambda d: d["version"])
        return {
            "harness_lineage": [{"id": v["_id"], "version": v["version"], "status": v["status"], "parent": v.get("parent_version_id"), "reason": v.get("proposal_reason", "")[:140]} for v in versions],
            "evaluations": [{"candidate": e["candidate_version_id"], "decision": e["decision"], "reasons": e["reasons"]} for e in self.store.find("evaluation_results", {}, sort=[("evaluated_at", 1)])],
            "physical_commands": self.store.count("hardware_commands", {}),
            "traces": self.store.count("agent_traces", {}),
        }
